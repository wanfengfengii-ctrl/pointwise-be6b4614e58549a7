"""Small inputs; no general reference matcher or review conclusions."""
CASES = {
    "normal": {
        "left": {"dtype": "int64", "rows": [["L1", 1], ["L2", 2], ["L3", 3]]},
        "right": {"dtype": "uint64", "rows": [["R3", 3], ["R2", 2], ["R4", 4]]},
        "how": "left", "partition": False, "validate": "one_to_one"
    },
    "incident": {
        "left": {"dtype": "int64",
                 "rows": [["L0", 9007199254740992], ["L1", 9007199254740993]]},
        "right": {"dtype": "uint64",
                  "rows": [["R1", 9007199254740993], ["R0", 9007199254740992]]},
        "how": "inner", "partition": False, "validate": "one_to_one"
    },
    "duplicates": {
        "left": {"dtype": "int64", "rows": [["L0", 7], ["L1", 7]]},
        "right": {"dtype": "uint64", "rows": [["R0", 7]]},
        "how": "inner", "partition": False, "validate": None
    },
    "nullable": {
        "left": {"dtype": "Int64", "rows": [["LN", None], ["L1", 1]]},
        "right": {"dtype": "UInt64", "rows": [["RN", None], ["R1", 1]]},
        "how": "inner", "partition": False, "validate": "one_to_one"
    }
}
