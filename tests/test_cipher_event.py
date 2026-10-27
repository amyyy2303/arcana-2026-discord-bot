import asyncio

from scripts.test_encryption_and_hiding import test_encryption_and_hiding as run_encryption_tests
from scripts.test_cipher_limits import run_tests


def test_cipher_event_regressions():
    """Run isolated coverage for attempts, scoring, queue transitions, persistence, and commands."""
    asyncio.run(run_tests())


def test_official_answers_and_registered_aliases():
    """Verify the current ARCANA data without changing accepted answer behavior."""
    asyncio.run(run_encryption_tests())
