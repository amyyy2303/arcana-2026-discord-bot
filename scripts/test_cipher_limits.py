import asyncio
import ast
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import database.db as db_module
from database.db import Database
from utils.security import verify_answer


async def run_tests():
    print("=== TESTING ARCANA ATTEMPT LIMITS AND DISQUALIFICATION ===")
    with tempfile.TemporaryDirectory(prefix="arcana-tests-") as temp_dir:
        data_dir = Path(temp_dir) / "data"
        data_dir.mkdir()
        (data_dir / "ciphers.json").write_text(
            (ROOT / "data" / "ciphers.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        db = Database(str(data_dir / "bot.db"))
        await db.init()

        questions = json.loads((ROOT / "data" / "ciphers.json").read_text(encoding="utf-8"))
        assert len(questions) == 16
        assert {q["difficulty"].lower(): q["points"] for q in questions} == {
            "easy": 150,
            "medium": 250,
            "hard": 400,
        }
        for question in questions:
            assert (ROOT / "data" / "ciphers" / question["image_filename"]).is_file()
        assert all((ROOT / "data" / "ciphers" / f"{qid}.png").is_file() for qid in range(1, 17))
        print("PASS official 16-question bank, point values, and all 16 images")

        async def new_team(guild_id):
            teams = await db.ensure_cipher_event(guild_id)
            assert len(teams) == 13
            team = teams[0]
            question = await db.assign_random_cipher(team["id"])
            assert question
            return team, question

        # Verify each wrong answer deducts exactly 12 and decrements the remaining limit.
        team, question = await new_team(9001)
        for attempt, remaining in enumerate((3, 2, 1), start=1):
            result = await db.submit_cipher_answer(
                9001, team["id"], question["id"], 1, "incorrect",
                False, question["points"], submission_id=f"first-three-{attempt}",
            )
            assert result["accepted"] and result["score"] == 100 - 12 * attempt
            assert result["attempt_number"] == attempt
            assert result["failed_attempts"] == attempt
            assert result["attempts_remaining"] == remaining
            active = await db.get_active_cipher(team["id"])
            assert active and active["active_attempts"] == attempt
        print("PASS first, second, and third wrong answer: -12 each; 3, 2, and 1 remain")

        # Fourth wrong answer permanently exhausts the question without pass effects.
        fourth = await db.submit_cipher_answer(
            9001, team["id"], question["id"], 1, "incorrect",
            False, question["points"], submission_id="first-three-4",
        )
        assert fourth["accepted"] and fourth["score"] == 52 and fourth["exhausted"]
        assert fourth["attempt_number"] == 4 and fourth["attempts_remaining"] == 0
        assert await db.get_active_cipher(team["id"]) is None
        with sqlite3.connect(db.db_path) as conn:
            status = conn.execute(
                "SELECT status FROM cipher_team_queue WHERE team_id = ? AND question_id = ?",
                (team["id"], question["id"]),
            ).fetchone()[0]
        assert status == "EXHAUSTED"
        next_question = await db.assign_random_cipher(team["id"])
        assert next_question and next_question["id"] != question["id"]
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT status FROM cipher_team_queue WHERE team_id = ? AND question_id = ?",
                (team["id"], question["id"]),
            ).fetchone()[0] == "EXHAUSTED"
            assert conn.execute(
                "SELECT score FROM cipher_teams WHERE id != ? AND guild_id = ? ORDER BY id LIMIT 1",
                (team["id"], 9001),
            ).fetchone()[0] == 100
        print("PASS fourth wrong answer exhausts question, clears active state, and grants no pass bonus/burn")

        # Correct answers on attempts one, two, and three award the question value once.
        for guild_id, prior_wrong in ((9010, 0), (9011, 1), (9012, 2)):
            correct_team, correct_question = await new_team(guild_id)
            for attempt in range(prior_wrong):
                failed = await db.submit_cipher_answer(
                    guild_id, correct_team["id"], correct_question["id"], 1,
                    "incorrect", False, correct_question["points"],
                    submission_id=f"correct-{guild_id}-wrong-{attempt}",
                )
                assert failed["accepted"]
            assert verify_answer(correct_question["answer"], correct_question)
            solved = await db.submit_cipher_answer(
                guild_id, correct_team["id"], correct_question["id"], 1,
                correct_question["answer"], True, correct_question["points"],
                submission_id=f"correct-{guild_id}",
            )
            assert solved["accepted"] and solved["attempt_number"] == prior_wrong + 1
            assert solved["score"] == 100 - prior_wrong * 12 + correct_question["points"]
            assert await db.get_active_cipher(correct_team["id"]) is None
            assert solved["active_attempts"] == 0
            with sqlite3.connect(db.db_path) as conn:
                assert conn.execute(
                    "SELECT status FROM cipher_team_queue WHERE team_id = ? AND question_id = ?",
                    (correct_team["id"], correct_question["id"]),
                ).fetchone()[0] == "SOLVED"
        print("PASS correct answers on attempts one, two, and three award configured points once")

        # Four wrong answers disqualify at a zero score, and the exact score-12 edge disqualifies immediately.
        dq_team, dq_question = await new_team(9020)
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE cipher_teams SET score = 48 WHERE id = ?", (dq_team["id"],))
        for attempt in range(4):
            result = await db.submit_cipher_answer(
                9020, dq_team["id"], dq_question["id"], 2, "incorrect",
                False, dq_question["points"], submission_id=f"dq-four-{attempt}",
            )
        assert result["score"] == 0 and result["is_disqualified"] and result["exhausted"]
        assert await db.get_active_cipher(dq_team["id"]) is None

        zero_team, zero_question = await new_team(9021)
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE cipher_teams SET score = 12 WHERE id = ?", (zero_team["id"],))
        zero_result = await db.submit_cipher_answer(
            9021, zero_team["id"], zero_question["id"], 2, "incorrect",
            False, zero_question["points"], submission_id="score-twelve",
        )
        assert zero_result["score"] == 0 and zero_result["is_disqualified"]
        with sqlite3.connect(db.db_path) as conn:
            interrupted = conn.execute(
                "SELECT status FROM cipher_team_queue WHERE team_id = ? AND question_id = ?",
                (zero_team["id"], zero_question["id"]),
            ).fetchone()[0]
        assert interrupted == "INTERRUPTED"
        assert await db.assign_random_cipher(zero_team["id"]) is None
        after_disqualification = await db.submit_cipher_answer(
            9021, zero_team["id"], zero_question["id"], 2, "correct",
            True, zero_question["points"], submission_id="after-disqualification",
        )
        assert after_disqualification["accepted"] is False
        assert await db.pass_cipher_question(9021, zero_team["id"], 2) is None
        print("PASS four-failure and score-12 disqualification; disqualified teams cannot draw, answer, or pass")

        negative_team, negative_question = await new_team(9022)
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE cipher_teams SET score = 6 WHERE id = ?", (negative_team["id"],))
        negative_result = await db.submit_cipher_answer(
            9022, negative_team["id"], negative_question["id"], 2, "incorrect",
            False, negative_question["points"], submission_id="score-below-zero",
        )
        assert negative_result["score"] == -6 and negative_result["is_disqualified"]
        assert await db.get_active_cipher(negative_team["id"]) is None
        print("PASS score below zero disqualifies immediately and interrupts the active question")

        # Explicit pass alone receives the collateral burn and +20 to each opponent.
        pass_team, pass_question = await new_team(9030)
        with sqlite3.connect(db.db_path) as conn:
            opponents = conn.execute(
                "SELECT id FROM cipher_teams WHERE guild_id = ? AND id != ? ORDER BY id LIMIT 2",
                (9030, pass_team["id"]),
            ).fetchall()
            disqualified_opponents = [row[0] for row in opponents]
            conn.executemany(
                "UPDATE cipher_teams SET score = 0, is_disqualified = 1 WHERE id = ?",
                [(team_id,) for team_id in disqualified_opponents],
            )
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            guarded = db._apply_score_delta(conn.cursor(), disqualified_opponents[0], 20)
            assert guarded["score"] == 0 and guarded["is_disqualified"]
            conn.commit()
        passed = await db.pass_cipher_question(9030, pass_team["id"], 3, opposition_bonus=20)
        assert passed and passed["passed_question"]["id"] == pass_question["id"]
        assert passed["burned_question"] and passed["burned_question"]["id"] != pass_question["id"]
        assert await db.get_active_cipher(pass_team["id"]) is None
        pass_board = await db.get_cipher_leaderboard(9030)
        assert len(pass_board) == 13
        disqualified_board = [t for t in pass_board if t["id"] in disqualified_opponents]
        eligible_board = [t for t in pass_board if t["id"] not in [pass_team["id"], *disqualified_opponents]]
        assert all(t["score"] == 0 and t["is_disqualified"] for t in disqualified_board)
        assert all(t["score"] == 120 and not t["is_disqualified"] for t in eligible_board)
        assert len(eligible_board) == 10
        print("PASS explicit pass burns one question, rewards ten eligible opponents, and excludes two disqualified teams")

        # Restart preserves active attempt count, score, question state, and disqualification status.
        restart_team, restart_question = await new_team(9040)
        for attempt in range(2):
            await db.submit_cipher_answer(
                9040, restart_team["id"], restart_question["id"], 4, "incorrect",
                False, restart_question["points"], submission_id=f"restart-{attempt}",
            )
        reopened_db = Database(str(data_dir / "bot.db"))
        await reopened_db.init()
        resumed = await reopened_db.get_active_cipher(restart_team["id"])
        resumed_team = await reopened_db.get_cipher_team(9040, restart_team["id"])
        assert resumed and resumed["active_attempts"] == 2 and resumed["failed_attempts"] == 2
        assert resumed_team["score"] == 76
        assert resumed_team["is_disqualified"] == 0
        print("PASS restart preserves attempt count, score, active question, and status")

        # A repeated concurrent invocation with one Discord submission ID can only apply once.
        concurrent_team, concurrent_question = await new_team(9050)
        async def duplicate_submission():
            return await reopened_db.submit_cipher_answer(
                9050, concurrent_team["id"], concurrent_question["id"], 5,
                "incorrect", False, concurrent_question["points"],
                submission_id="duplicate-message-id",
            )
        results = await asyncio.gather(duplicate_submission(), duplicate_submission())
        assert sum(result["accepted"] for result in results) == 1
        assert sum(result["duplicate"] for result in results) == 1
        concurrent_row = await reopened_db.get_cipher_team(9050, concurrent_team["id"])
        assert concurrent_row["score"] == 88 and concurrent_row["active_attempts"] == 1
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM cipher_logs WHERE submission_id = ?",
                ("duplicate-message-id",),
            ).fetchone()[0] == 1
        print("PASS concurrent duplicate submission deducts once and records one answer event")

        reset_team, reset_question = await new_team(9055)
        await db.submit_cipher_answer(
            9055, reset_team["id"], reset_question["id"], 6, "incorrect",
            False, reset_question["points"], submission_id="reset-before",
        )
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE cipher_teams SET score = 0, is_disqualified = 1 WHERE id = ?", (reset_team["id"],))
        reset_rows = await db.reset_cipher_event(9055, reset_score=100)
        assert len(reset_rows) == 13 and all(row["score"] == 100 for row in reset_rows)
        assert all(not row["is_disqualified"] and row["active_question_id"] is None for row in reset_rows)
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM cipher_team_queue WHERE team_id = ? AND status = 'AVAILABLE' AND attempts = 0",
                (reset_team["id"],),
            ).fetchone()[0] == 16
        print("PASS existing admin reset still restores scores, statuses, attempts, and all 16 questions")

        # Leaderboard reports every required status and queue count.
        board = await reopened_db.get_cipher_leaderboard(9001)
        leader = next(item for item in board if item["id"] == team["id"])
        assert leader["score"] == 52 and leader["active_question_id"] is not None
        assert leader["exhausted_count"] == 1 and leader["available_count"] == 14
        disqualified_board = await reopened_db.get_cipher_leaderboard(9021)
        disqualified_entry = next(item for item in disqualified_board if item["id"] == zero_team["id"])
        assert disqualified_entry["is_disqualified"] and disqualified_entry["score"] == 0
        assert disqualified_entry["active_question_id"] is None
        assert all({"solved_count", "passed_count", "burned_count", "exhausted_count", "available_count"} <= item.keys()
                   for item in board)
        print("PASS leaderboard reports score, disqualification, active question, and queue totals")

        # Validate the existing command decorators without requiring Discord at test time.
        def command_names(path, namespace):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if (
                        isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr == "command"
                        and isinstance(dec.func.value, ast.Name)
                        and dec.func.value.id == namespace
                    ):
                        if dec.func.attr == "command":
                            name = next(
                                (kw.value.value for kw in dec.keywords
                                 if kw.arg == "name" and isinstance(kw.value, ast.Constant)),
                                None,
                            )
                            if name:
                                names.add(name)
            return names

        general_slash = command_names(ROOT / "cogs" / "general.py", "app_commands")
        cipher_slash = command_names(ROOT / "cogs" / "cipher_event.py", "app_commands")
        cipher_prefix = command_names(ROOT / "cogs" / "cipher_event.py", "commands")
        assert {"hello", "ping"} <= general_slash
        assert {"cipher", "answer", "pass"} <= cipher_slash
        assert {"cipher", "answer", "pass"} <= cipher_prefix
        print("PASS /hello, /ping, and existing prefix/slash cipher command definitions remain present")

        # Migrate a copy of the pre-attempt schema without changing its event rows or mappings.
        legacy_dir = Path(temp_dir) / "legacy-data"
        legacy_dir.mkdir()
        (legacy_dir / "ciphers.json").write_text(
            (ROOT / "data" / "ciphers.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        legacy_path = legacy_dir / "bot.db"
        with sqlite3.connect(legacy_path) as legacy:
            legacy.executescript(
                """
                CREATE TABLE cipher_teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    channel_id INTEGER DEFAULT NULL,
                    role_id INTEGER DEFAULT NULL,
                    score INTEGER NOT NULL DEFAULT 100,
                    active_question_id INTEGER DEFAULT NULL,
                    is_finished BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, name COLLATE NOCASE)
                );
                CREATE TABLE cipher_team_queue (
                    team_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (team_id, question_id)
                );
                CREATE TABLE cipher_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    question_id INTEGER DEFAULT NULL,
                    details TEXT DEFAULT '',
                    points_delta INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE cipher_config (
                    guild_id INTEGER PRIMARY KEY,
                    admin_channel_id INTEGER DEFAULT NULL,
                    leaderboard_message_id INTEGER DEFAULT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    start_points INTEGER DEFAULT 100
                );
                INSERT INTO cipher_teams
                    (id, guild_id, name, channel_id, role_id, score, active_question_id)
                VALUES (77, 9060, 'Inovexa', 7001, 8001, 64, 1);
                INSERT INTO cipher_teams
                    (id, guild_id, name, score, active_question_id)
                VALUES (78, 9060, 'Cartels', 0, 2);
                INSERT INTO cipher_team_queue (team_id, question_id)
                VALUES (77, 1), (78, 2);
                INSERT INTO cipher_logs (guild_id, team_id, user_id, action, question_id, details)
                VALUES (9060, 77, 9, 'ANSWER_WRONG', 1, 'Failed attempt (old-one)');
                INSERT INTO cipher_logs (guild_id, team_id, user_id, action, question_id, details)
                VALUES (9060, 77, 9, 'ANSWER_WRONG', 1, 'Failed attempt (old-two)');
                INSERT INTO cipher_logs (guild_id, team_id, user_id, action, details)
                VALUES (9060, 77, 9, 'LEGACY_EVENT', 'preserve this history');
                INSERT INTO cipher_config
                    (guild_id, admin_channel_id, leaderboard_message_id, is_active, start_points)
                VALUES (9060, 6001, 6002, 1, 100);
                """
            )

        legacy_db = Database(str(legacy_path))
        await legacy_db.init()
        legacy_teams = await legacy_db.ensure_cipher_event(9060)
        assert len(legacy_teams) == 13
        migrated_team = await legacy_db.get_cipher_team(9060, 77)
        assert migrated_team["score"] == 64
        assert migrated_team["channel_id"] == 7001 and migrated_team["role_id"] == 8001
        assert migrated_team["active_attempts"] == 2
        zero_legacy_team = await legacy_db.get_cipher_team(9060, 78)
        assert zero_legacy_team["is_disqualified"] and zero_legacy_team["score"] == 0
        assert zero_legacy_team["active_question_id"] is None
        migrated_active = await legacy_db.get_active_cipher(77)
        assert migrated_active and migrated_active["id"] == 1
        assert migrated_active["active_attempts"] == 2
        assert migrated_active["failed_attempts"] == 2
        assert await legacy_db.get_cipher_config(9060) == {
            "guild_id": 9060,
            "admin_channel_id": 6001,
            "leaderboard_message_id": 6002,
            "is_active": 1,
            "start_points": 100,
        }
        migrated_wrong = await legacy_db.submit_cipher_answer(
            9060, 77, 1, 9, "incorrect", False, 150, submission_id="legacy-migrated-answer",
        )
        assert migrated_wrong["score"] == 52 and migrated_wrong["failed_attempts"] == 3
        with sqlite3.connect(legacy_path) as legacy:
            assert legacy.execute(
                "SELECT action, details FROM cipher_logs WHERE action = 'LEGACY_EVENT'"
            ).fetchone() == ("LEGACY_EVENT", "preserve this history")
            assert legacy.execute(
                "SELECT status, attempts FROM cipher_team_queue WHERE team_id = 77 AND question_id = 1"
            ).fetchone() == ("ACTIVE", 3)
            assert legacy.execute(
                "SELECT status FROM cipher_team_queue WHERE team_id = 78 AND question_id = 2"
            ).fetchone()[0] == "INTERRUPTED"
            assert legacy.execute(
                "SELECT COUNT(*) FROM cipher_logs WHERE team_id = 77"
            ).fetchone()[0] == 4
            assert legacy.execute(
                "SELECT admin_channel_id, leaderboard_message_id FROM cipher_config WHERE guild_id = 9060"
            ).fetchone() == (6001, 6002)
        print("PASS additive migration infers legacy attempts and preserves team, event, and admin configuration data")

        # Existing queue statuses on the production-era schema are left intact by additive migration.
        status_path = legacy_dir / "status-preservation.db"
        with sqlite3.connect(status_path) as legacy:
            legacy.executescript(
                """
                CREATE TABLE cipher_teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    channel_id INTEGER DEFAULT NULL,
                    role_id INTEGER DEFAULT NULL,
                    score INTEGER NOT NULL DEFAULT 100,
                    active_question_id INTEGER DEFAULT NULL,
                    is_finished BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, name COLLATE NOCASE)
                );
                CREATE TABLE cipher_team_queue (
                    team_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'AVAILABLE',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (team_id, question_id)
                );
                CREATE TABLE cipher_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    question_id INTEGER DEFAULT NULL,
                    details TEXT DEFAULT '',
                    points_delta INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE cipher_questions (
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
                INSERT INTO cipher_teams
                    (id, guild_id, name, score, active_question_id)
                VALUES (88, 9070, 'Cartels', 76, 1);
                INSERT INTO cipher_team_queue (team_id, question_id, status)
                VALUES (88, 1, 'ACTIVE'), (88, 2, 'PASSED'), (88, 3, 'BURNED'), (88, 13, 'EXHAUSTED');
                INSERT INTO cipher_logs (guild_id, team_id, user_id, action, question_id)
                VALUES (9070, 88, 10, 'ANSWER_WRONG', 1),
                       (9070, 88, 10, 'ANSWER_WRONG', 1);
                INSERT INTO cipher_questions
                    (id, title, category, difficulty, points, ciphertext, answer, answer_hashes, hint, image_filename)
                VALUES (
                    13, 'Persisted Q13', 'Legacy category', 'hard', 400, 'stored ciphertext',
                    'stored answer', '[\"persisted-hash\",\"legacy-alias-hash\"]',
                    'stored hint', 'persisted-q13.png'
                );
                """
            )
        status_db = Database(str(status_path))
        original_aiosqlite_setting = db_module.HAS_AIOSQLITE
        db_module.HAS_AIOSQLITE = False
        try:
            await status_db.init()
        finally:
            db_module.HAS_AIOSQLITE = original_aiosqlite_setting
        with sqlite3.connect(status_path) as legacy:
            saved_statuses = legacy.execute(
                "SELECT question_id, status FROM cipher_team_queue WHERE team_id = 88 ORDER BY question_id"
            ).fetchall()
            assert saved_statuses == [
                (1, "ACTIVE"), (2, "PASSED"), (3, "BURNED"), (13, "EXHAUSTED")
            ]
            assert legacy.execute(
                "SELECT active_attempts FROM cipher_teams WHERE id = 88"
            ).fetchone()[0] == 2
            assert legacy.execute(
                """
                SELECT title, category, difficulty, points, ciphertext, answer,
                       answer_hashes, hint, image_filename
                FROM cipher_questions WHERE id = 13
                """
            ).fetchone() == (
                "Persisted Q13", "Legacy category", "hard", 400, "stored ciphertext",
                "stored answer", '["persisted-hash","legacy-alias-hash"]',
                "stored hint", "persisted-q13.png",
            )
        print("PASS migration preserves existing queue states/question data and recovers attempts")

    print("ALL ARCANA LIMIT AND DISQUALIFICATION TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_tests())
