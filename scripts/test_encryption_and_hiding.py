import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.security import hash_answer, verify_answer


async def test_encryption_and_hiding():
    print("=== TESTING ENCRYPTION, HASHING & SPOILER HIDING ===")

    with (ROOT / "data" / "ciphers.json").open("r", encoding="utf-8") as f:
        ciphers = json.load(f)

    assert len(ciphers) == 16, "Must be 16 ciphers"
    print("✔ Loaded all 16 official questions from data/ciphers.json")

    for cipher in ciphers:
        q_record = {
            "id": cipher["id"],
            "answer": cipher["answer"],
            "answer_hashes": json.dumps([
                hash_answer(cipher["answer"]),
                *[hash_answer(alias) for alias in cipher.get("aliases", [])],
            ]),
        }
        assert verify_answer(cipher["answer"], q_record), (
            f"Failed to verify primary answer for Q#{cipher['id']}: {cipher['answer']}"
        )
        assert verify_answer(cipher["answer"].upper(), q_record), (
            f"Failed uppercase match for Q#{cipher['id']}"
        )
        for alias in cipher.get("aliases", []):
            assert verify_answer(alias, q_record), (
                f"Failed alias match for Q#{cipher['id']}: {alias}"
            )
        assert not verify_answer("bogus_random_guess_12345", q_record), (
            f"False positive on Q#{cipher['id']}"
        )

    print("✔ SHA-256 answer verification passed for all 16 questions and registered aliases")

    q3 = next(cipher for cipher in ciphers if cipher["id"] == 3)
    q3_record = {"answer_hashes": json.dumps([hash_answer(q3["answer"])])}
    assert verify_answer("Neymar Jr", q3_record)
    assert verify_answer("NEYMAR JR.", q3_record)
    assert not verify_answer("neymar", q3_record)
    print("✔ Q3 accepts normalized official answer and rejects unregistered alias")

    q5 = next(cipher for cipher in ciphers if cipher["id"] == 5)
    q5_record = {"answer_hashes": json.dumps([hash_answer(q5["answer"])])}
    assert verify_answer("the ghost of sparta kratos", q5_record)
    assert not verify_answer("kratos", q5_record)
    print("✔ Q5 accepts normalized official answer and rejects unregistered alias")

    q12 = next(cipher for cipher in ciphers if cipher["id"] == 12)
    q12_record = {"answer_hashes": json.dumps([hash_answer(q12["answer"])])}
    assert verify_answer("vscode", q12_record)
    assert verify_answer("vs code", q12_record)
    print("✔ Q12 answer punctuation and spacing normalize consistently")

    q13 = next(cipher for cipher in ciphers if cipher["id"] == 13)
    q13_record = {"answer_hashes": json.dumps([hash_answer(q13["answer"])])}
    assert verify_answer("model training", q13_record)
    assert verify_answer("MODEL TRAINING", q13_record)
    assert not verify_answer("machine learning", q13_record)
    print("✔ Q13 accepts official answer and rejects unregistered alternate")
    print("\n🎉 ENCRYPTION, HASHING & SPOILER HIDING VALIDATION COMPLETE!")


if __name__ == "__main__":
    asyncio.run(test_encryption_and_hiding())
