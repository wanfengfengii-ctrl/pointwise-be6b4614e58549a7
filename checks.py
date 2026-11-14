import argparse
from collections import Counter
from copy import deepcopy
import json

from probe import run_case
from samples import CASES
from source_manifest import verify_sources

def triples(result):
    return Counter((row["left_id"], row["right_id"], row["key"]) for row in result["rows"])

def normal():
    verify_sources()
    result = run_case(CASES["normal"])
    assert result["error"] is None, result
    assert result["warnings"] == [], result
    assert result["dtypes"]["key"] == "int64", result
    assert triples(result) == Counter([("L1", None, 1), ("L2", "R2", 2), ("L3", "R3", 3)]), result
    repeated = run_case(CASES["duplicates"])
    assert repeated["error"] is None, repeated
    assert triples(repeated) == Counter([("L0", "R0", 7), ("L1", "R0", 7)]), repeated
    invalid = deepcopy(CASES["duplicates"])
    invalid["validate"] = "one_to_one"
    rejected = run_case(invalid)
    assert rejected["error"] and rejected["error"]["type"] == "MergeError", rejected
    nullable = run_case(CASES["nullable"])
    assert nullable["error"] is None, nullable
    assert triples(nullable) == Counter([("LN", "RN", None), ("L1", "R1", 1)]), nullable
    print(json.dumps({"normal": result, "duplicates": repeated,
                      "duplicate_rejected": rejected, "nullable": nullable},
                     ensure_ascii=False, indent=2, allow_nan=False))
    print("NORMAL_REGRESSION_OK")

def incident():
    result = run_case(CASES["incident"])
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    expected = Counter([("L0", "R0", 9007199254740992), ("L1", "R1", 9007199254740993)])
    if result["error"] is not None or triples(result) != expected:
        raise AssertionError("MERGE_IDENTITY_MISMATCH: unique integer identities were not preserved")
    print("INCIDENT_IDENTITY_OK")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["normal", "incident"])
    args = parser.parse_args()
    if args.command == "normal":
        normal()
    else:
        incident()
