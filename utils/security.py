import re
import json
import hashlib
from typing import Optional, Dict, Any, List


def normalize_answer(text: str) -> str:
    """Strip all non-alphanumeric characters and lowercase for fair comparison."""
    if not text:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()


def hash_answer(text: str) -> str:
    """Cryptographically hash normalized answer using SHA-256."""
    cleaned = normalize_answer(text)
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def compute_answer_hashes(answer: str, aliases: Optional[List[str]] = None) -> List[str]:
    """Generates a list of unique SHA-256 hashes for the primary answer and aliases."""
    raws = [answer] + (aliases or [])
    hashes = set()
    for r in raws:
        h = hash_answer(r)
        if h:
            hashes.add(h)
    return list(hashes)


def verify_answer(user_input: str, question: Dict[str, Any]) -> bool:
    """Securely verifies user answer against precomputed SHA-256 hashes."""
    if not user_input:
        return False
    user_hash = hash_answer(user_input)

    stored_hashes = []
    if question.get("answer_hashes"):
        try:
            stored_hashes = json.loads(question["answer_hashes"])
        except Exception:
            stored_hashes = []

    if not stored_hashes and question.get("answer"):
        stored_hashes = [hash_answer(question["answer"])]

    return user_hash in stored_hashes
