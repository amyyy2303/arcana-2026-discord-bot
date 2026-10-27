import os
import sqlite3
import asyncio
import json
import random
import re
import hashlib
from typing import Optional, List, Dict, Any

try:
    import aiosqlite
    HAS_AIOSQLITE = True
except ImportError:
    HAS_AIOSQLITE = False


class Database:
    def __init__(self, db_path: str = "data/bot.db"):
        self.db_path = db_path
        self._ensure_dir()

    def _ensure_dir(self):
        dirname = os.path.dirname(self.db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

    async def init(self):
        """Initialize database tables."""
        schema = """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            leader_id INTEGER NOT NULL,
            role_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, name COLLATE NOCASE)
        );

        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE,
            UNIQUE(team_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tags TEXT DEFAULT '',
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_teams_guild ON teams(guild_id);
        CREATE INDEX IF NOT EXISTS idx_links_guild ON links(guild_id);
        CREATE INDEX IF NOT EXISTS idx_links_category ON links(guild_id, category);

        -- Cipher Event Tables
        CREATE TABLE IF NOT EXISTS cipher_teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            channel_id INTEGER DEFAULT NULL,
            role_id INTEGER DEFAULT NULL,
            score INTEGER NOT NULL DEFAULT 100,
            active_question_id INTEGER DEFAULT NULL,
            active_attempts INTEGER NOT NULL DEFAULT 0,
            is_disqualified BOOLEAN NOT NULL DEFAULT 0,
            is_finished BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, name COLLATE NOCASE)
        );

        CREATE TABLE IF NOT EXISTS cipher_questions (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT DEFAULT '',
            difficulty TEXT NOT NULL,
            points INTEGER NOT NULL,
            ciphertext TEXT DEFAULT '',
            answer TEXT NOT NULL,
            answer_hashes TEXT DEFAULT '[]',
            hint TEXT DEFAULT '',
            image_filename TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cipher_team_queue (
            team_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'AVAILABLE',
            attempts INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (team_id, question_id),
            FOREIGN KEY (team_id) REFERENCES cipher_teams (id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES cipher_questions (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cipher_config (
            guild_id INTEGER PRIMARY KEY,
            admin_channel_id INTEGER DEFAULT NULL,
            leaderboard_message_id INTEGER DEFAULT NULL,
            is_active BOOLEAN DEFAULT 1,
            start_points INTEGER DEFAULT 100
        );

        CREATE TABLE IF NOT EXISTS cipher_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            question_id INTEGER DEFAULT NULL,
            details TEXT DEFAULT '',
            points_delta INTEGER DEFAULT 0,
            submission_id TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_cipher_teams_guild ON cipher_teams(guild_id);
        CREATE INDEX IF NOT EXISTS idx_cipher_queue_team ON cipher_team_queue(team_id);
        """
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(schema)
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    async with db.execute("PRAGMA table_info(cipher_teams);") as cur:
                        team_cols = {r[1] for r in await cur.fetchall()}
                    if "is_disqualified" not in team_cols:
                        await db.execute(
                            "ALTER TABLE cipher_teams ADD COLUMN is_disqualified BOOLEAN NOT NULL DEFAULT 0;"
                        )
                    if "active_attempts" not in team_cols:
                        await db.execute(
                            "ALTER TABLE cipher_teams ADD COLUMN active_attempts INTEGER NOT NULL DEFAULT 0;"
                        )
                    if "is_finished" not in team_cols:
                        await db.execute(
                            "ALTER TABLE cipher_teams ADD COLUMN is_finished BOOLEAN NOT NULL DEFAULT 0;"
                        )

                    async with db.execute("PRAGMA table_info(cipher_team_queue);") as cur:
                        queue_cols = {r[1] for r in await cur.fetchall()}
                    if "status" not in queue_cols:
                        await db.execute(
                            "ALTER TABLE cipher_team_queue ADD COLUMN status TEXT NOT NULL DEFAULT 'AVAILABLE';"
                        )
                        await db.execute(
                            """
                            UPDATE cipher_team_queue
                            SET status = 'ACTIVE'
                            WHERE EXISTS (
                                SELECT 1 FROM cipher_teams t
                                WHERE t.id = cipher_team_queue.team_id
                                  AND t.active_question_id = cipher_team_queue.question_id
                            )
                            """
                        )
                    if "attempts" not in queue_cols:
                        await db.execute(
                            "ALTER TABLE cipher_team_queue ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;"
                        )
                        await db.execute(
                            """
                            UPDATE cipher_team_queue
                            SET attempts = (
                                SELECT COUNT(*) FROM cipher_logs l
                                WHERE l.team_id = cipher_team_queue.team_id
                                  AND l.question_id = cipher_team_queue.question_id
                                  AND l.action IN ('ANSWER_WRONG', 'ANSWER_EXHAUSTED')
                            )
                            WHERE EXISTS (
                                SELECT 1 FROM cipher_logs l
                                WHERE l.team_id = cipher_team_queue.team_id
                                  AND l.question_id = cipher_team_queue.question_id
                                  AND l.action IN ('ANSWER_WRONG', 'ANSWER_EXHAUSTED')
                            )
                            """
                        )

                    async with db.execute("PRAGMA table_info(cipher_logs);") as cur:
                        log_cols = {r[1] for r in await cur.fetchall()}
                    if "submission_id" not in log_cols:
                        await db.execute(
                            "ALTER TABLE cipher_logs ADD COLUMN submission_id TEXT DEFAULT NULL;"
                        )
                    await db.execute(
                        """
                        UPDATE cipher_teams
                        SET active_attempts = COALESCE((
                            SELECT queue.attempts FROM cipher_team_queue queue
                            WHERE queue.team_id = cipher_teams.id
                              AND queue.question_id = cipher_teams.active_question_id
                              AND queue.status = 'ACTIVE'
                        ), 0)
                        WHERE active_question_id IS NOT NULL
                        """
                    )
                    await db.execute(
                        """
                        UPDATE cipher_team_queue
                        SET status = 'INTERRUPTED', updated_at = CURRENT_TIMESTAMP
                        WHERE status = 'ACTIVE'
                          AND EXISTS (
                              SELECT 1 FROM cipher_teams t
                              WHERE t.id = cipher_team_queue.team_id AND t.score <= 0
                          )
                        """
                    )
                    await db.execute(
                        """
                        UPDATE cipher_teams
                        SET is_disqualified = 1, active_question_id = NULL, active_attempts = 0
                        WHERE score <= 0
                        """
                    )
                    await db.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cipher_logs_submission "
                        "ON cipher_logs(submission_id) WHERE submission_id IS NOT NULL;"
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        else:
            def _sync_init():
                with sqlite3.connect(self.db_path) as conn:
                    conn.executescript(schema)
                    cur = conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        team_cols = {r[1] for r in cur.execute("PRAGMA table_info(cipher_teams);").fetchall()}
                        if "is_disqualified" not in team_cols:
                            cur.execute(
                                "ALTER TABLE cipher_teams ADD COLUMN is_disqualified BOOLEAN NOT NULL DEFAULT 0;"
                            )
                        if "active_attempts" not in team_cols:
                            cur.execute(
                                "ALTER TABLE cipher_teams ADD COLUMN active_attempts INTEGER NOT NULL DEFAULT 0;"
                            )
                        if "is_finished" not in team_cols:
                            cur.execute(
                                "ALTER TABLE cipher_teams ADD COLUMN is_finished BOOLEAN NOT NULL DEFAULT 0;"
                            )

                        queue_cols = {r[1] for r in cur.execute("PRAGMA table_info(cipher_team_queue);").fetchall()}
                        if "status" not in queue_cols:
                            cur.execute(
                                "ALTER TABLE cipher_team_queue ADD COLUMN status TEXT NOT NULL DEFAULT 'AVAILABLE';"
                            )
                            cur.execute(
                                """
                                UPDATE cipher_team_queue
                                SET status = 'ACTIVE'
                                WHERE EXISTS (
                                    SELECT 1 FROM cipher_teams t
                                    WHERE t.id = cipher_team_queue.team_id
                                      AND t.active_question_id = cipher_team_queue.question_id
                                )
                                """
                            )
                        if "attempts" not in queue_cols:
                            cur.execute(
                                "ALTER TABLE cipher_team_queue ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;"
                            )
                            cur.execute(
                                """
                                UPDATE cipher_team_queue
                                SET attempts = (
                                    SELECT COUNT(*) FROM cipher_logs l
                                    WHERE l.team_id = cipher_team_queue.team_id
                                      AND l.question_id = cipher_team_queue.question_id
                                      AND l.action IN ('ANSWER_WRONG', 'ANSWER_EXHAUSTED')
                                )
                                WHERE EXISTS (
                                    SELECT 1 FROM cipher_logs l
                                    WHERE l.team_id = cipher_team_queue.team_id
                                      AND l.question_id = cipher_team_queue.question_id
                                      AND l.action IN ('ANSWER_WRONG', 'ANSWER_EXHAUSTED')
                                )
                                """
                            )

                        log_cols = {r[1] for r in cur.execute("PRAGMA table_info(cipher_logs);").fetchall()}
                        if "submission_id" not in log_cols:
                            cur.execute(
                                "ALTER TABLE cipher_logs ADD COLUMN submission_id TEXT DEFAULT NULL;"
                            )
                        cur.execute(
                            """
                            UPDATE cipher_teams
                            SET active_attempts = COALESCE((
                                SELECT queue.attempts FROM cipher_team_queue queue
                                WHERE queue.team_id = cipher_teams.id
                                  AND queue.question_id = cipher_teams.active_question_id
                                  AND queue.status = 'ACTIVE'
                            ), 0)
                            WHERE active_question_id IS NOT NULL
                            """
                        )
                        cur.execute(
                            """
                            UPDATE cipher_team_queue
                            SET status = 'INTERRUPTED', updated_at = CURRENT_TIMESTAMP
                            WHERE status = 'ACTIVE'
                              AND EXISTS (
                                  SELECT 1 FROM cipher_teams t
                                  WHERE t.id = cipher_team_queue.team_id AND t.score <= 0
                              )
                            """
                        )
                        cur.execute(
                            """
                            UPDATE cipher_teams
                            SET is_disqualified = 1, active_question_id = NULL, active_attempts = 0
                            WHERE score <= 0
                            """
                        )
                        cur.execute(
                            "CREATE UNIQUE INDEX IF NOT EXISTS idx_cipher_logs_submission "
                            "ON cipher_logs(submission_id) WHERE submission_id IS NOT NULL;"
                        )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
            await asyncio.to_thread(_sync_init)

        # Seed questions into cipher_questions
        await self.seed_cipher_questions()

    # ---------------- TEAM OPERATIONS ---------------- #

    async def create_team(
        self, guild_id: int, name: str, description: str, leader_id: int, role_id: Optional[int] = None
    ) -> Optional[int]:
        """Creates a team and adds the leader as the first member. Returns team ID or None if name exists."""
        def _sync_create():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        INSERT INTO teams (guild_id, name, description, leader_id, role_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (guild_id, name.strip(), description.strip(), leader_id, role_id),
                    )
                    team_id = cur.lastrowid
                    cur.execute(
                        """
                        INSERT INTO team_members (team_id, user_id)
                        VALUES (?, ?)
                        """,
                        (team_id, leader_id),
                    )
                    conn.commit()
                    return team_id
                except sqlite3.IntegrityError:
                    return None

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON;")
                try:
                    cursor = await db.execute(
                        """
                        INSERT INTO teams (guild_id, name, description, leader_id, role_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (guild_id, name.strip(), description.strip(), leader_id, role_id),
                    )
                    team_id = cursor.lastrowid
                    await db.execute(
                        """
                        INSERT INTO team_members (team_id, user_id)
                        VALUES (?, ?)
                        """,
                        (team_id, leader_id),
                    )
                    await db.commit()
                    return team_id
                except aiosqlite.IntegrityError:
                    return None
        return await asyncio.to_thread(_sync_create)

    async def get_team(self, guild_id: int, name: str) -> Optional[Dict[str, Any]]:
        """Fetch team by guild ID and team name (case-insensitive)."""
        query = "SELECT id, guild_id, name, description, leader_id, role_id, created_at FROM teams WHERE guild_id = ? AND name = ? COLLATE NOCASE"
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (guild_id, name.strip())) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        else:
            def _sync_get():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, (guild_id, name.strip()))
                    row = cur.fetchone()
                    return dict(row) if row else None
            return await asyncio.to_thread(_sync_get)

    async def list_teams(self, guild_id: int) -> List[Dict[str, Any]]:
        """List all teams for a guild with member counts."""
        query = """
            SELECT t.id, t.guild_id, t.name, t.description, t.leader_id, t.role_id, t.created_at,
                   COUNT(m.id) as member_count
            FROM teams t
            LEFT JOIN team_members m ON t.id = m.team_id
            WHERE t.guild_id = ?
            GROUP BY t.id
            ORDER BY t.name COLLATE NOCASE ASC
        """
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (guild_id,)) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(r) for r in rows]
        else:
            def _sync_list():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, (guild_id,))
                    return [dict(r) for r in cur.fetchall()]
            return await asyncio.to_thread(_sync_list)

    async def delete_team(self, guild_id: int, name: str) -> Optional[Dict[str, Any]]:
        """Deletes a team and returns the team data if deleted, or None."""
        team = await self.get_team(guild_id, name)
        if not team:
            return None

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON;")
                await db.execute("DELETE FROM teams WHERE id = ?", (team["id"],))
                await db.commit()
                return team
        else:
            def _sync_del():
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("PRAGMA foreign_keys = ON;")
                    conn.execute("DELETE FROM teams WHERE id = ?", (team["id"],))
                    conn.commit()
                    return team
            return await asyncio.to_thread(_sync_del)

    async def add_team_member(self, team_id: int, user_id: int) -> bool:
        """Adds a member to a team. Returns True if added, False if already a member."""
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                try:
                    await db.execute(
                        "INSERT INTO team_members (team_id, user_id) VALUES (?, ?)",
                        (team_id, user_id),
                    )
                    await db.commit()
                    return True
                except aiosqlite.IntegrityError:
                    return False
        else:
            def _sync_add():
                with sqlite3.connect(self.db_path) as conn:
                    try:
                        conn.execute(
                            "INSERT INTO team_members (team_id, user_id) VALUES (?, ?)",
                            (team_id, user_id),
                        )
                        conn.commit()
                        return True
                    except sqlite3.IntegrityError:
                        return False
            return await asyncio.to_thread(_sync_add)

    async def remove_team_member(self, team_id: int, user_id: int) -> bool:
        """Removes a member from a team. Returns True if removed, False otherwise."""
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(
                    "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
                    (team_id, user_id),
                )
                await db.commit()
                return cur.rowcount > 0
        else:
            def _sync_remove():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
                        (team_id, user_id),
                    )
                    conn.commit()
                    return cur.rowcount > 0
            return await asyncio.to_thread(_sync_remove)

    async def get_team_members(self, team_id: int) -> List[int]:
        """Returns list of user IDs for a given team."""
        query = "SELECT user_id FROM team_members WHERE team_id = ? ORDER BY id ASC"
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, (team_id,)) as cursor:
                    rows = await cursor.fetchall()
                    return [r[0] for r in rows]
        else:
            def _sync_members():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(query, (team_id,))
                    return [r[0] for r in cur.fetchall()]
            return await asyncio.to_thread(_sync_members)

    async def is_team_member(self, team_id: int, user_id: int) -> bool:
        """Checks if a user is in a team."""
        query = "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?"
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(query, (team_id, user_id)) as cursor:
                    row = await cursor.fetchone()
                    return row is not None
        else:
            def _sync_is():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(query, (team_id, user_id))
                    return cur.fetchone() is not None
            return await asyncio.to_thread(_sync_is)

    # ---------------- LINK OPERATIONS ---------------- #

    async def add_link(
        self,
        guild_id: int,
        user_id: int,
        url: str,
        title: str,
        category: str = "general",
        tags: str = "",
        description: str = "",
    ) -> int:
        """Adds a new link and returns its ID."""
        category = category.strip().lower() if category else "general"
        tags = ",".join(t.strip().lower() for t in tags.split(",") if t.strip()) if tags else ""
        query = """
            INSERT INTO links (guild_id, user_id, url, title, category, tags, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (guild_id, user_id, url.strip(), title.strip(), category, tags, description.strip())

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(query, params)
                await db.commit()
                return cur.lastrowid
        else:
            def _sync_add():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(query, params)
                    conn.commit()
                    return cur.lastrowid
            return await asyncio.to_thread(_sync_add)

    async def get_link(self, link_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        """Gets a link by ID within a guild."""
        query = "SELECT * FROM links WHERE id = ? AND guild_id = ?"
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (link_id, guild_id)) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        else:
            def _sync_get():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, (link_id, guild_id))
                    row = cur.fetchone()
                    return dict(row) if row else None
            return await asyncio.to_thread(_sync_get)

    async def search_links(
        self, guild_id: int, query: str = "", category: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search links by query (matches title, tags, description, url) and optional category filter."""
        conditions = ["guild_id = ?"]
        params: List[Any] = [guild_id]

        if category:
            conditions.append("category = ? COLLATE NOCASE")
            params.append(category.strip().lower())

        if query:
            search_param = f"%{query.strip()}%"
            conditions.append("(title LIKE ? OR tags LIKE ? OR description LIKE ? OR url LIKE ?)")
            params.extend([search_param, search_param, search_param, search_param])

        where_clause = " AND ".join(conditions)
        sql = f"SELECT * FROM links WHERE {where_clause} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql, tuple(params)) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(r) for r in rows]
        else:
            def _sync_search():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(sql, tuple(params))
                    return [dict(r) for r in cur.fetchall()]
            return await asyncio.to_thread(_sync_search)

    async def list_categories(self, guild_id: int) -> List[Dict[str, Any]]:
        """Returns distinct categories and count of links in each."""
        query = """
            SELECT category, COUNT(id) as count
            FROM links
            WHERE guild_id = ?
            GROUP BY category
            ORDER BY count DESC, category ASC
        """
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (guild_id,)) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(r) for r in rows]
        else:
            def _sync_cats():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, (guild_id,))
                    return [dict(r) for r in cur.fetchall()]
            return await asyncio.to_thread(_sync_cats)

    async def update_link(
        self,
        link_id: int,
        guild_id: int,
        title: Optional[str] = None,
        url: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Updates link fields."""
        fields = []
        params = []
        if title is not None:
            fields.append("title = ?")
            params.append(title.strip())
        if url is not None:
            fields.append("url = ?")
            params.append(url.strip())
        if category is not None:
            fields.append("category = ?")
            params.append(category.strip().lower())
        if tags is not None:
            formatted_tags = ",".join(t.strip().lower() for t in tags.split(",") if t.strip())
            fields.append("tags = ?")
            params.append(formatted_tags)
        if description is not None:
            fields.append("description = ?")
            params.append(description.strip())

        if not fields:
            return False

        params.extend([link_id, guild_id])
        sql = f"UPDATE links SET {', '.join(fields)} WHERE id = ? AND guild_id = ?"

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(sql, tuple(params))
                await db.commit()
                return cur.rowcount > 0
        else:
            def _sync_update():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(sql, tuple(params))
                    conn.commit()
                    return cur.rowcount > 0
            return await asyncio.to_thread(_sync_update)

    async def delete_link(self, link_id: int, guild_id: int) -> bool:
        """Deletes a link by ID within a guild."""
        query = "DELETE FROM links WHERE id = ? AND guild_id = ?"
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(query, (link_id, guild_id))
                await db.commit()
                return cur.rowcount > 0
        else:
            def _sync_del():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(query, (link_id, guild_id))
                    conn.commit()
                    return cur.rowcount > 0
            return await asyncio.to_thread(_sync_del)

    # ---------------- CIPHER EVENT OPERATIONS ---------------- #

    DEFAULT_CIPHER_TEAMS = [
        "Team Mavericks",
        "The Way Makers",
        "Naam m kya rkha h",
        "Inovexa",
        "Crazy crew",
        "Mast orbitors",
        "Oops",
        "Minty jamuns",
        "The Decoders Triad",
        "Hidden hunters",
        "Cartels",
        "Anushka Pal",
        "test",
    ]

    async def seed_cipher_questions(self):
        """Seed 16 cipher questions into cipher_questions table."""
        json_path = os.path.join(os.path.dirname(self.db_path), "ciphers.json")
        ciphers = []
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    ciphers = json.load(f)
            except Exception:
                ciphers = []

        if not ciphers:
            # Fallback inline questions if ciphers.json is not yet created
            ciphers = [
                {"id": 1, "title": "Caesar's March", "category": "Caesar Cipher", "difficulty": "easy", "points": 150, "ciphertext": "KHOOR ZRUOG", "answer": "hello world", "hint": "Shift -3", "image_filename": "cipher_1.png"},
                {"id": 2, "title": "Mirror Reflection", "category": "Reverse Cipher", "difficulty": "easy", "points": 150, "ciphertext": "NOITPECREP", "answer": "perception", "hint": "Reverse", "image_filename": "cipher_2.png"},
                {"id": 3, "title": "Telegraph Lines", "category": "Morse Code", "difficulty": "easy", "points": 150, "ciphertext": "-.-. .. .--. .... . .-.", "answer": "cipher", "hint": "Morse", "image_filename": "cipher_3.png"},
                {"id": 4, "title": "Atbash Inversion", "category": "Atbash Cipher", "difficulty": "easy", "points": 150, "ciphertext": "JFXMGFN", "answer": "quantum", "hint": "Atbash", "image_filename": "cipher_4.png"},
                {"id": 5, "title": "Alphanumeric Index", "category": "A1Z26 Cipher", "difficulty": "easy", "points": 150, "ciphertext": "19-5-3-18-5-20", "answer": "secret", "hint": "A1Z26", "image_filename": "cipher_5.png"},
                {"id": 6, "title": "Binary Logic", "category": "Binary ASCII", "difficulty": "medium", "points": 250, "ciphertext": "01000101 01001110 01001001 01000111 01001101 01000001", "answer": "enigma", "hint": "Binary", "image_filename": "cipher_6.png"},
                {"id": 7, "title": "Hexadecimal Payload", "category": "Hex to ASCII", "difficulty": "medium", "points": 250, "ciphertext": "43 72 79 70 74 6f", "answer": "crypto", "hint": "Hex", "image_filename": "cipher_7.png"},
                {"id": 8, "title": "Radix-64 Transmission", "category": "Base64 Encoding", "difficulty": "medium", "points": 250, "ciphertext": "U3VwZXJTZWNyZXQ=", "answer": "supersecret", "hint": "Base64", "image_filename": "cipher_8.png"},
                {"id": 9, "title": "Halfway Rotation", "category": "ROT13", "difficulty": "medium", "points": 250, "ciphertext": "SNVEARFF", "answer": "fairness", "hint": "ROT13", "image_filename": "cipher_9.png"},
                {"id": 10, "title": "Polyalphabetic Tableau", "category": "Vigenère Cipher", "difficulty": "medium", "points": 250, "ciphertext": "Key: BOT | Ciphertext: TSZJFS", "answer": "solver", "hint": "Vigenere", "image_filename": "cipher_10.png"},
                {"id": 11, "title": "Geometric Grid", "category": "Polybius Square", "difficulty": "medium", "points": 250, "ciphertext": "32 11 44 42 24 53", "answer": "matrix", "hint": "Polybius", "image_filename": "cipher_11.png"},
                {"id": 12, "title": "Zig-Zag Defense", "category": "Rail Fence Cipher", "difficulty": "hard", "points": 400, "ciphertext": "3 Rails | Ciphertext: DNLEFEWLEDTA", "answer": "defendthewall", "hint": "Rail Fence", "image_filename": "cipher_12.png"},
                {"id": 13, "title": "Biliteral Ghost", "category": "Bacon's Cipher", "difficulty": "hard", "points": 400, "ciphertext": "ABBBA AABBA AAAAA ABBAA BAABA ABBAB ABBAA", "answer": "phantom", "hint": "Bacon", "image_filename": "cipher_13.png"},
                {"id": 14, "title": "Singularity Column", "category": "Columnar Transposition", "difficulty": "hard", "points": 400, "ciphertext": "Key: 3142 | Ciphertext: LOBAHLCKE", "answer": "blackhole", "hint": "Columnar", "image_filename": "cipher_14.png"},
                {"id": 15, "title": "Double Enigma Crypt", "category": "Nested Cipher", "difficulty": "hard", "points": 400, "ciphertext": "Step 1: Caesar -1 -> Step 2: Base64 decode 'a3J5cHRvcw=='", "answer": "kryptos", "hint": "Nested", "image_filename": "cipher_15.png"},
                {"id": 16, "title": "The Eternal Tail", "category": "Master Anagram & Shift", "difficulty": "hard", "points": 400, "ciphertext": "Anagram of 'SOROBURO' after ROT-0: Ancient serpent of eternity", "answer": "ouroboros", "hint": "Ouroboros", "image_filename": "cipher_16.png"},
            ]

        def _calc_hashes(item):
            raws = [item["answer"]] + item.get("aliases", [])
            hashes = set()
            for r in raws:
                cleaned = re.sub(r"[^a-zA-Z0-9]", "", r).lower()
                if cleaned:
                    hashes.add(hashlib.sha256(cleaned.encode("utf-8")).hexdigest())
            return json.dumps(list(hashes))

        def _sync_seed():
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                # Ensure answer_hashes column exists
                try:
                    cur.execute("ALTER TABLE cipher_questions ADD COLUMN answer_hashes TEXT DEFAULT '[]'")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass

                for c in ciphers:
                    hashes_json = _calc_hashes(c)
                    cur.execute(
                        """
                        INSERT INTO cipher_questions (id, title, category, difficulty, points, ciphertext, answer, answer_hashes, hint, image_filename)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (c["id"], c["title"], c.get("category", ""), c["difficulty"].lower(), c["points"], c.get("ciphertext", ""), c["answer"].strip().lower(), hashes_json, c.get("hint", ""), c.get("image_filename", f"{c['id']}.png"))
                    )
                conn.commit()

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                try:
                    await db.execute("ALTER TABLE cipher_questions ADD COLUMN answer_hashes TEXT DEFAULT '[]'")
                    await db.commit()
                except Exception:
                    pass

                for c in ciphers:
                    hashes_json = _calc_hashes(c)
                    await db.execute(
                        """
                        INSERT INTO cipher_questions (id, title, category, difficulty, points, ciphertext, answer, answer_hashes, hint, image_filename)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO NOTHING
                        """,
                        (c["id"], c["title"], c.get("category", ""), c["difficulty"].lower(), c["points"], c.get("ciphertext", ""), c["answer"].strip().lower(), hashes_json, c.get("hint", ""), c.get("image_filename", f"{c['id']}.png"))
                    )
                await db.commit()
        else:
            await asyncio.to_thread(_sync_seed)

    async def ensure_cipher_event(self, guild_id: int) -> List[Dict[str, Any]]:
        """Ensures all default competition teams exist and their question queues are initialized."""
        def _sync_ensure():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # Ensure each default team exists
                for team_name in self.DEFAULT_CIPHER_TEAMS:
                    cur.execute(
                        """
                        INSERT INTO cipher_teams (guild_id, name, score)
                        VALUES (?, ?, 100)
                        ON CONFLICT(guild_id, name COLLATE NOCASE) DO NOTHING
                        """,
                        (guild_id, team_name.strip()),
                    )
                conn.commit()

                # Get all teams for guild
                cur.execute("SELECT * FROM cipher_teams WHERE guild_id = ?", (guild_id,))
                teams = [dict(r) for r in cur.fetchall()]

                # Get all question IDs
                cur.execute("SELECT id FROM cipher_questions ORDER BY id ASC")
                q_ids = [r["id"] for r in cur.fetchall()]

                # Populate queues for each team
                for t in teams:
                    for qid in q_ids:
                        cur.execute(
                            """
                            INSERT INTO cipher_team_queue (team_id, question_id, status)
                            VALUES (?, ?, 'AVAILABLE')
                            ON CONFLICT(team_id, question_id) DO NOTHING
                            """,
                            (t["id"], qid),
                        )
                conn.commit()
                return teams

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                for team_name in self.DEFAULT_CIPHER_TEAMS:
                    await db.execute(
                        """
                        INSERT INTO cipher_teams (guild_id, name, score)
                        VALUES (?, ?, 100)
                        ON CONFLICT(guild_id, name COLLATE NOCASE) DO NOTHING
                        """,
                        (guild_id, team_name.strip()),
                    )
                await db.commit()

                async with db.execute("SELECT * FROM cipher_teams WHERE guild_id = ?", (guild_id,)) as cur:
                    teams = [dict(r) for r in await cur.fetchall()]

                async with db.execute("SELECT id FROM cipher_questions ORDER BY id ASC") as cur:
                    q_ids = [r["id"] for r in await cur.fetchall()]

                for t in teams:
                    for qid in q_ids:
                        await db.execute(
                            """
                            INSERT INTO cipher_team_queue (team_id, question_id, status)
                            VALUES (?, ?, 'AVAILABLE')
                            ON CONFLICT(team_id, question_id) DO NOTHING
                            """,
                            (t["id"], qid),
                        )
                await db.commit()
                return teams
        else:
            return await asyncio.to_thread(_sync_ensure)

    async def get_cipher_team(self, guild_id: int, team_id_or_name: Any) -> Optional[Dict[str, Any]]:
        """Fetch team by ID or Name."""
        if isinstance(team_id_or_name, int):
            query = "SELECT * FROM cipher_teams WHERE guild_id = ? AND id = ?"
            params = (guild_id, team_id_or_name)
        else:
            query = "SELECT * FROM cipher_teams WHERE guild_id = ? AND name = ? COLLATE NOCASE"
            params = (guild_id, str(team_id_or_name).strip())

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, params) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None
        else:
            def _sync():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, params)
                    row = cur.fetchone()
                    return dict(row) if row else None
            return await asyncio.to_thread(_sync)

    async def find_cipher_team_by_context(
        self, guild_id: int, channel_id: int, role_ids: Optional[List[int]] = None, channel_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the corresponding cipher team by:
        1. Exact channel_id match
        2. Channel name matching normalized team name
        3. User roles matching team role_id or team name
        """
        await self.ensure_cipher_event(guild_id)

        def _normalize(s: str) -> str:
            return re.sub(r"[^a-zA-Z0-9]", "", s).lower()

        clean_chan_name = _normalize(channel_name) if channel_name else ""

        def _sync_find():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM cipher_teams WHERE guild_id = ?", (guild_id,))
                teams = [dict(r) for r in cur.fetchall()]

                # 1. Exact channel_id match
                for t in teams:
                    if t["channel_id"] and t["channel_id"] == channel_id:
                        return t

                # 2. Normalized channel name match
                if clean_chan_name:
                    for t in teams:
                        if _normalize(t["name"]) == clean_chan_name:
                            return t

                # 3. Role ID match
                if role_ids:
                    for t in teams:
                        if t["role_id"] and t["role_id"] in role_ids:
                            return t

                return None

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM cipher_teams WHERE guild_id = ?", (guild_id,)) as cur:
                    teams = [dict(r) for r in await cur.fetchall()]

                for t in teams:
                    if t["channel_id"] and t["channel_id"] == channel_id:
                        return t

                if clean_chan_name:
                    for t in teams:
                        if _normalize(t["name"]) == clean_chan_name:
                            return t

                if role_ids:
                    for t in teams:
                        if t["role_id"] and t["role_id"] in role_ids:
                            return t

                return None
        else:
            return await asyncio.to_thread(_sync_find)

    async def get_active_cipher(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Fetch the current active cipher for a team."""
        query = """
            SELECT q.*, queue.attempts AS failed_attempts, t.active_attempts
            FROM cipher_questions q
            JOIN cipher_teams t ON t.active_question_id = q.id
            JOIN cipher_team_queue queue ON queue.team_id = t.id
                AND queue.question_id = q.id AND queue.status = 'ACTIVE'
            WHERE t.id = ?
        """
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (team_id,)) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None
        else:
            def _sync():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, (team_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            return await asyncio.to_thread(_sync)

    async def assign_random_cipher(self, team_id: int) -> Optional[Dict[str, Any]]:
        """
        Randomly assigns an available cipher from the team's queue.
        Marks it 'ACTIVE' and updates team's active_question_id atomically.
        """
        def _sync_assign():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
                team = cur.fetchone()
                if not team or team["is_disqualified"] or team["score"] <= 0 or team["active_question_id"]:
                    conn.rollback()
                    return None
                cur.execute(
                    """
                    SELECT q.* FROM cipher_questions q
                    JOIN cipher_team_queue queue ON queue.question_id = q.id
                    WHERE queue.team_id = ? AND queue.status = 'AVAILABLE'
                    """,
                    (team_id,),
                )
                available = [dict(r) for r in cur.fetchall()]
                if not available:
                    cur.execute("UPDATE cipher_teams SET is_finished = 1 WHERE id = ?", (team_id,))
                    conn.commit()
                    return None

                chosen = random.choice(available)
                cur.execute(
                    "UPDATE cipher_teams SET active_question_id = ?, active_attempts = 0, is_finished = 0 WHERE id = ?",
                    (chosen["id"], team_id),
                )
                cur.execute(
                    "UPDATE cipher_team_queue SET status = 'ACTIVE', attempts = 0, updated_at = CURRENT_TIMESTAMP WHERE team_id = ? AND question_id = ? AND status = 'AVAILABLE'",
                    (team_id, chosen["id"]),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
                chosen["failed_attempts"] = 0
                chosen["active_attempts"] = 0
                return chosen

        return await asyncio.to_thread(_sync_assign)

    @staticmethod
    def _apply_score_delta(
        cur: sqlite3.Cursor,
        team_id: int,
        delta: int,
        allow_disqualified: bool = False,
    ) -> Dict[str, Any]:
        """Atomically adjust an eligible team's score and enforce disqualification."""
        cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Cipher team {team_id} does not exist")
        team = dict(row)
        if not allow_disqualified and (team["is_disqualified"] or team["score"] <= 0):
            if team["score"] <= 0 and not team["is_disqualified"]:
                if team["active_question_id"] is not None:
                    cur.execute(
                        """
                        UPDATE cipher_team_queue
                        SET status = 'INTERRUPTED', updated_at = CURRENT_TIMESTAMP
                        WHERE team_id = ? AND question_id = ? AND status = 'ACTIVE'
                        """,
                        (team_id, team["active_question_id"]),
                    )
                cur.execute(
                    """
                    UPDATE cipher_teams
                    SET is_disqualified = 1, active_question_id = NULL, active_attempts = 0
                    WHERE id = ?
                    """,
                    (team_id,),
                )
                cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
                team = dict(cur.fetchone())
            return team

        cur.execute(
            "UPDATE cipher_teams SET score = score + ? WHERE id = ?",
            (delta, team_id),
        )
        cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
        team = dict(cur.fetchone())
        if team["score"] <= 0:
            if team["active_question_id"] is not None:
                cur.execute(
                    """
                    UPDATE cipher_team_queue
                    SET status = 'INTERRUPTED', updated_at = CURRENT_TIMESTAMP
                    WHERE team_id = ? AND question_id = ? AND status = 'ACTIVE'
                    """,
                    (team_id, team["active_question_id"]),
                )
            cur.execute(
                """
                UPDATE cipher_teams
                SET is_disqualified = 1, active_question_id = NULL, active_attempts = 0
                WHERE id = ?
                """,
                (team_id,),
            )
            cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
            team = dict(cur.fetchone())
        return team

    async def submit_cipher_answer(
        self,
        guild_id: int,
        team_id: int,
        question_id: int,
        user_id: int,
        submitted_answer: str,
        is_correct: bool,
        points_reward: int,
        submission_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically apply one answer, its attempt count, score, and question transition."""
        def _sync_submit():
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                if submission_id is not None:
                    cur.execute("SELECT 1 FROM cipher_logs WHERE submission_id = ?", (submission_id,))
                    if cur.fetchone():
                        cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
                        team = dict(cur.fetchone())
                        conn.rollback()
                        return {
                            **team, "accepted": False, "duplicate": True,
                            "attempt_number": team["active_attempts"], "attempts_remaining": max(0, 4 - team["active_attempts"]),
                            "exhausted": False,
                        }

                cur.execute(
                    """
                    SELECT t.*, queue.status AS queue_status, queue.attempts AS failed_attempts
                    FROM cipher_teams t
                    JOIN cipher_team_queue queue ON queue.team_id = t.id AND queue.question_id = ?
                    WHERE t.id = ? AND t.guild_id = ?
                    """,
                    (question_id, team_id, guild_id),
                )
                state = cur.fetchone()
                if (
                    not state
                    or state["is_disqualified"]
                    or state["score"] <= 0
                    or state["active_question_id"] != question_id
                    or state["queue_status"] != "ACTIVE"
                    or state["active_attempts"] >= 4
                ):
                    if state and state["score"] <= 0 and not state["is_disqualified"]:
                        self._apply_score_delta(cur, team_id, 0)
                    cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
                    current_team = cur.fetchone()
                    team = dict(current_team) if current_team else {}
                    if state and state["score"] <= 0 and not state["is_disqualified"]:
                        conn.commit()
                        team["is_disqualified"] = 1
                    else:
                        conn.rollback()
                    return {
                        **team, "accepted": False, "duplicate": False,
                        "attempt_number": 0, "attempts_remaining": 0, "exhausted": False,
                    }

                attempt_number = state["active_attempts"] + 1
                failed_attempts = state["failed_attempts"]
                delta = points_reward if is_correct else -12
                exhausted = False

                if is_correct:
                    cur.execute(
                        """
                        UPDATE cipher_team_queue SET status = 'SOLVED', updated_at = CURRENT_TIMESTAMP
                        WHERE team_id = ? AND question_id = ? AND status = 'ACTIVE'
                        """,
                        (team_id, question_id),
                    )
                    cur.execute(
                        "UPDATE cipher_teams SET active_question_id = NULL, active_attempts = 0 WHERE id = ?",
                        (team_id,),
                    )
                else:
                    failed_attempts += 1
                    exhausted = failed_attempts >= 4
                    cur.execute(
                        """
                        UPDATE cipher_team_queue SET attempts = ?, status = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE team_id = ? AND question_id = ? AND status = 'ACTIVE'
                        """,
                        (failed_attempts, "EXHAUSTED" if exhausted else "ACTIVE", team_id, question_id),
                    )
                    if exhausted:
                        cur.execute(
                            "UPDATE cipher_teams SET active_question_id = NULL, active_attempts = 0 WHERE id = ?",
                            (team_id,),
                        )
                    else:
                        cur.execute(
                            "UPDATE cipher_teams SET active_attempts = ? WHERE id = ?",
                            (attempt_number, team_id),
                        )

                updated_team = self._apply_score_delta(cur, team_id, delta)

                cur.execute(
                    "SELECT COUNT(*) AS remaining FROM cipher_team_queue WHERE team_id = ? AND status = 'AVAILABLE'",
                    (team_id,),
                )
                if cur.fetchone()["remaining"] == 0 and not updated_team["is_disqualified"]:
                    cur.execute("UPDATE cipher_teams SET is_finished = 1 WHERE id = ?", (team_id,))

                clean_guess = re.sub(r"[^a-zA-Z0-9]", "", submitted_answer).lower()
                guess_fp = hashlib.sha256(clean_guess.encode("utf-8")).hexdigest()[:16]
                action = "ANSWER_CORRECT" if is_correct else ("ANSWER_EXHAUSTED" if exhausted else "ANSWER_WRONG")
                log_details = f"Verified ({guess_fp})" if is_correct else f"Failed attempt {failed_attempts} ({guess_fp})"
                cur.execute(
                    """
                    INSERT INTO cipher_logs
                        (guild_id, team_id, user_id, action, question_id, details, points_delta, submission_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (guild_id, team_id, user_id, action, question_id, log_details, delta, submission_id),
                )
                conn.commit()
                return {
                    **updated_team,
                    "accepted": True,
                    "duplicate": False,
                    "attempt_number": attempt_number,
                    "failed_attempts": failed_attempts,
                    "attempts_remaining": max(0, 4 - failed_attempts),
                    "exhausted": exhausted,
                }

        return await asyncio.to_thread(_sync_submit)

    async def pass_cipher_question(
        self,
        guild_id: int,
        team_id: int,
        user_id: int,
        opposition_bonus: int = 20,
    ) -> Dict[str, Any]:
        """Atomically pass the active question and award opponents their pass bonus."""
        def _sync_pass():
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    "SELECT * FROM cipher_teams WHERE id = ? AND guild_id = ?",
                    (team_id, guild_id),
                )
                team_row = cur.fetchone()
                if (
                    not team_row
                    or team_row["is_disqualified"]
                    or team_row["score"] <= 0
                    or not team_row["active_question_id"]
                ):
                    conn.rollback()
                    return None
                team = dict(team_row)
                active_qid = team["active_question_id"]

                cur.execute(
                    """
                    SELECT q.* FROM cipher_questions q
                    JOIN cipher_team_queue queue ON queue.question_id = q.id
                    WHERE q.id = ? AND queue.team_id = ? AND queue.status = 'ACTIVE'
                    """,
                    (active_qid, team_id),
                )
                passed_row = cur.fetchone()
                if not passed_row:
                    conn.rollback()
                    return None
                passed_q = dict(passed_row)

                cur.execute(
                    """
                    UPDATE cipher_team_queue SET status = 'PASSED', updated_at = CURRENT_TIMESTAMP
                    WHERE team_id = ? AND question_id = ? AND status = 'ACTIVE'
                    """,
                    (team_id, active_qid),
                )

                cur.execute(
                    """
                    SELECT q.* FROM cipher_questions q
                    JOIN cipher_team_queue queue ON queue.question_id = q.id
                    WHERE queue.team_id = ? AND queue.status = 'AVAILABLE' AND q.id != ?
                    """,
                    (team_id, active_qid),
                )
                available = [dict(r) for r in cur.fetchall()]
                burned_q = None
                if available:
                    burned_q = random.choice(available)
                    cur.execute(
                        "UPDATE cipher_team_queue SET status = 'BURNED', updated_at = CURRENT_TIMESTAMP WHERE team_id = ? AND question_id = ?",
                        (team_id, burned_q["id"]),
                    )

                cur.execute(
                    "UPDATE cipher_teams SET active_question_id = NULL, active_attempts = 0 WHERE id = ?",
                    (team_id,),
                )

                cur.execute(
                    "SELECT COUNT(*) as rem FROM cipher_team_queue WHERE team_id = ? AND status = 'AVAILABLE'",
                    (team_id,),
                )
                if cur.fetchone()["rem"] == 0:
                    cur.execute("UPDATE cipher_teams SET is_finished = 1 WHERE id = ?", (team_id,))

                cur.execute(
                    """
                    SELECT id FROM cipher_teams
                    WHERE guild_id = ? AND id != ?
                      AND is_disqualified = 0 AND score > 0
                    ORDER BY id
                    """,
                    (guild_id, team_id),
                )
                for (opponent_id,) in cur.fetchall():
                    self._apply_score_delta(cur, opponent_id, opposition_bonus)

                details = f"Passed Q#{passed_q['id']}" + (f", Burned Q#{burned_q['id']}" if burned_q else "")
                cur.execute(
                    """
                    INSERT INTO cipher_logs (guild_id, team_id, user_id, action, question_id, details, points_delta)
                    VALUES (?, ?, ?, 'PASS', ?, ?, 0)
                    """,
                    (guild_id, team_id, user_id, passed_q["id"], details),
                )
                conn.commit()

                cur.execute("SELECT * FROM cipher_teams WHERE id = ?", (team_id,))
                updated_team = dict(cur.fetchone())
                return {
                    "passed_question": passed_q,
                    "burned_question": burned_q,
                    "team": updated_team,
                    "opposition_bonus": opposition_bonus,
                }

        return await asyncio.to_thread(_sync_pass)

    async def reset_cipher_event(self, guild_id: int, reset_score: int = 100) -> List[Dict[str, Any]]:
        """
        Resets the entire cipher event for guild:
        - All teams reset to reset_score (100)
        - active_question_id cleared
        - is_finished cleared
        - All 16 questions in queue set to 'AVAILABLE'
        - Logs reset
        """
        await self.ensure_cipher_event(guild_id)

        def _sync_reset():
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("SELECT id, score FROM cipher_teams WHERE guild_id = ?", (guild_id,))
                for team_id, old_score in cur.fetchall():
                    self._apply_score_delta(
                        cur,
                        team_id,
                        reset_score - old_score,
                        allow_disqualified=True,
                    )
                cur.execute(
                    """
                    UPDATE cipher_teams
                    SET active_question_id = NULL, active_attempts = 0,
                        is_disqualified = ?, is_finished = 0
                    WHERE guild_id = ?
                    """,
                    (int(reset_score <= 0), guild_id),
                )
                cur.execute(
                    """
                    UPDATE cipher_team_queue
                    SET status = 'AVAILABLE', attempts = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE team_id IN (SELECT id FROM cipher_teams WHERE guild_id = ?)
                    """,
                    (guild_id,),
                )
                cur.execute(
                    """
                    INSERT INTO cipher_logs (guild_id, team_id, user_id, action, details, points_delta)
                    VALUES (?, 0, 0, 'RESET', ?, 0)
                    """,
                    (guild_id, f"Full reset to {reset_score} points"),
                )
                conn.commit()

                cur.execute("SELECT * FROM cipher_teams WHERE guild_id = ? ORDER BY name ASC", (guild_id,))
                return [dict(r) for r in cur.fetchall()]
        return await asyncio.to_thread(_sync_reset)

    async def get_cipher_leaderboard(self, guild_id: int) -> List[Dict[str, Any]]:
        """
        Fetches the complete real-time leaderboard for the guild.
        Returns teams sorted by score DESC, with solved, passed, burned, remaining counts and active question.
        """
        await self.ensure_cipher_event(guild_id)

        def _sync_lb():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT t.*, q.title as active_q_title, q.difficulty as active_q_diff, q.points as active_q_points
                    FROM cipher_teams t
                    LEFT JOIN cipher_questions q ON t.active_question_id = q.id
                    WHERE t.guild_id = ?
                    ORDER BY t.score DESC, t.name ASC
                    """,
                    (guild_id,),
                )
                teams = [dict(r) for r in cur.fetchall()]

                for t in teams:
                    cur.execute(
                        """
                        SELECT status, COUNT(*) as count
                        FROM cipher_team_queue
                        WHERE team_id = ?
                        GROUP BY status
                        """,
                        (t["id"],),
                    )
                    counts = {r["status"]: r["count"] for r in cur.fetchall()}
                    t["solved_count"] = counts.get("SOLVED", 0)
                    t["passed_count"] = counts.get("PASSED", 0)
                    t["burned_count"] = counts.get("BURNED", 0)
                    t["exhausted_count"] = counts.get("EXHAUSTED", 0)
                    t["available_count"] = counts.get("AVAILABLE", 0)
                    t["active_count"] = counts.get("ACTIVE", 0)
                return teams

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT t.*, q.title as active_q_title, q.difficulty as active_q_diff, q.points as active_q_points
                    FROM cipher_teams t
                    LEFT JOIN cipher_questions q ON t.active_question_id = q.id
                    WHERE t.guild_id = ?
                    ORDER BY t.score DESC, t.name ASC
                    """,
                    (guild_id,),
                ) as cur:
                    teams = [dict(r) for r in await cur.fetchall()]

                for t in teams:
                    async with db.execute(
                        """
                        SELECT status, COUNT(*) as count
                        FROM cipher_team_queue
                        WHERE team_id = ?
                        GROUP BY status
                        """,
                        (t["id"],),
                    ) as cur:
                        counts = {r["status"]: r["count"] for r in await cur.fetchall()}
                        t["solved_count"] = counts.get("SOLVED", 0)
                        t["passed_count"] = counts.get("PASSED", 0)
                        t["burned_count"] = counts.get("BURNED", 0)
                        t["exhausted_count"] = counts.get("EXHAUSTED", 0)
                        t["available_count"] = counts.get("AVAILABLE", 0)
                        t["active_count"] = counts.get("ACTIVE", 0)
                return teams
        else:
            return await asyncio.to_thread(_sync_lb)

    async def link_cipher_team_channel(
        self, guild_id: int, team_name: str, channel_id: int, role_id: Optional[int] = None
    ) -> bool:
        """Links a team to a Discord channel (and optional role)."""
        query = "UPDATE cipher_teams SET channel_id = ?, role_id = COALESCE(?, role_id) WHERE guild_id = ? AND name = ? COLLATE NOCASE"
        params = (channel_id, role_id, guild_id, team_name.strip())

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(query, params)
                await db.commit()
                return cur.rowcount > 0
        else:
            def _sync():
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute(query, params)
                    conn.commit()
                    return cur.rowcount > 0
            return await asyncio.to_thread(_sync)

    async def get_cipher_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Fetch cipher event configuration for guild."""
        query = "SELECT * FROM cipher_config WHERE guild_id = ?"
        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (guild_id,)) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None
        else:
            def _sync():
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(query, (guild_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            return await asyncio.to_thread(_sync)

    async def set_cipher_config(
        self, guild_id: int, admin_channel_id: Optional[int] = None, leaderboard_message_id: Optional[int] = None
    ):
        """Set or update cipher config (admin room and leaderboard message ID)."""
        def _sync_cfg():
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO cipher_config (guild_id, admin_channel_id, leaderboard_message_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET
                        admin_channel_id = COALESCE(excluded.admin_channel_id, cipher_config.admin_channel_id),
                        leaderboard_message_id = COALESCE(excluded.leaderboard_message_id, cipher_config.leaderboard_message_id)
                    """,
                    (guild_id, admin_channel_id, leaderboard_message_id),
                )
                conn.commit()

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO cipher_config (guild_id, admin_channel_id, leaderboard_message_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET
                        admin_channel_id = COALESCE(excluded.admin_channel_id, cipher_config.admin_channel_id),
                        leaderboard_message_id = COALESCE(excluded.leaderboard_message_id, cipher_config.leaderboard_message_id)
                    """,
                    (guild_id, admin_channel_id, leaderboard_message_id),
                )
                await db.commit()
        else:
            await asyncio.to_thread(_sync_cfg)


_db_instance: Optional[Database] = None


def get_db(db_path: str = "data/bot.db") -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path=db_path)
    return _db_instance
