import asyncio
import sqlite3
from pathlib import Path

import pytest

from database.db import Database


ROOT = Path(__file__).resolve().parents[1]


def make_database(tmp_path: Path) -> Database:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ciphers.json").write_text(
        (ROOT / "data" / "ciphers.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return Database(str(data_dir / "bot.db"))


def test_cipher_event_initializes_additional_default_teams(tmp_path):
    async def scenario():
        db = make_database(tmp_path)
        await db.init()
        teams = await db.ensure_cipher_event(8099)

        assert len(teams) == 13
        assert {team["name"] for team in teams} >= {"Team Mavericks", "The Way Makers"}
        assert await db.link_cipher_team_channel(8099, "Team Mavericks", 15001)
        assert await db.link_cipher_team_channel(8099, "The Way Makers", 15002)
        for channel_id, name in ((15001, "Team Mavericks"), (15002, "The Way Makers")):
            mapped = await db.find_cipher_team_by_context(8099, channel_id=channel_id)
            assert mapped and mapped["name"] == name
        with sqlite3.connect(db.db_path) as conn:
            for team in teams:
                assert conn.execute(
                    "SELECT COUNT(*) FROM cipher_team_queue WHERE team_id = ?",
                    (team["id"],),
                ).fetchone()[0] == 16
            conn.execute(
                """
                UPDATE cipher_teams
                SET score = 234, channel_id = 1234, role_id = 5678
                WHERE guild_id = ? AND name = 'Inovexa'
                """,
                (8099,),
            )

        teams_after_repeat = await db.ensure_cipher_event(8099)
        assert len(teams_after_repeat) == 13
        existing = next(team for team in teams_after_repeat if team["name"] == "Inovexa")
        assert (existing["score"], existing["channel_id"], existing["role_id"]) == (234, 1234, 5678)

    asyncio.run(scenario())


async def assign_question(db: Database, guild_id: int):
    teams = await db.ensure_cipher_event(guild_id)
    question = await db.assign_random_cipher(teams[0]["id"])
    assert question is not None
    return teams, question


def test_fourth_wrong_answer_exhausts_without_pass_effects(tmp_path):
    async def scenario():
        db = make_database(tmp_path)
        await db.init()
        teams, question = await assign_question(db, 8100)
        team = teams[0]

        for attempt in range(4):
            result = await db.submit_cipher_answer(
                8100, team["id"], question["id"], 1, "incorrect",
                False, question["points"], submission_id=f"exhaust-{attempt}",
            )
            assert result["accepted"]

        assert result["score"] == 52
        assert result["exhausted"] and result["attempt_number"] == 4
        assert await db.get_active_cipher(team["id"]) is None
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT status FROM cipher_team_queue WHERE team_id = ? AND question_id = ?",
                (team["id"], question["id"]),
            ).fetchone()[0] == "EXHAUSTED"
            assert conn.execute(
                "SELECT COUNT(*) FROM cipher_team_queue WHERE team_id = ? AND status IN ('PASSED', 'BURNED')",
                (team["id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT score FROM cipher_teams WHERE id = ?",
                (teams[1]["id"],),
            ).fetchone()[0] == 100

    asyncio.run(scenario())


@pytest.mark.parametrize(("starting_score", "expected_score"), [(12, 0), (6, -6)])
def test_wrong_answer_disqualifies_at_or_below_zero(tmp_path, starting_score, expected_score):
    async def scenario():
        db = make_database(tmp_path)
        await db.init()
        teams, question = await assign_question(db, 8101)
        team = teams[0]
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE cipher_teams SET score = ? WHERE id = ?", (starting_score, team["id"]))

        result = await db.submit_cipher_answer(
            8101, team["id"], question["id"], 1, "incorrect",
            False, question["points"], submission_id=f"score-{starting_score}",
        )
        assert result["score"] == expected_score and result["is_disqualified"]
        assert await db.get_active_cipher(team["id"]) is None
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT status FROM cipher_team_queue WHERE team_id = ? AND question_id = ?",
                (team["id"], question["id"]),
            ).fetchone()[0] == "INTERRUPTED"

    asyncio.run(scenario())


def test_explicit_pass_bonus_only_reaches_eligible_opponents(tmp_path):
    async def scenario():
        db = make_database(tmp_path)
        await db.init()
        teams, question = await assign_question(db, 8102)
        passing_team = teams[0]
        disqualified = [teams[1], teams[2]]
        with sqlite3.connect(db.db_path) as conn:
            conn.executemany(
                "UPDATE cipher_teams SET score = 0, is_disqualified = 1 WHERE id = ?",
                [(team["id"],) for team in disqualified],
            )

        result = await db.pass_cipher_question(8102, passing_team["id"], 1)
        assert result and result["passed_question"]["id"] == question["id"]
        assert result["burned_question"] and result["burned_question"]["id"] != question["id"]
        board = await db.get_cipher_leaderboard(8102)
        by_id = {team["id"]: team for team in board}
        assert all(by_id[team["id"]]["score"] == 0 for team in disqualified)
        assert all(by_id[team["id"]]["is_disqualified"] for team in disqualified)
        eligible = [team for team in teams[1:] if team["id"] not in {t["id"] for t in disqualified}]
        assert len(eligible) == len(teams) - 3
        assert all(by_id[team["id"]]["score"] == 120 for team in eligible)

    asyncio.run(scenario())
