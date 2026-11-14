"""Observe public DataFrame.merge; never compute expected matches."""
import argparse
from copy import deepcopy
import json
import warnings

import numpy as np
import pandas as pd

from samples import CASES
from source_manifest import verify_sources

DTYPES = {"int64", "uint64", "Int64", "UInt64"}

def check_spec(spec):
    if not isinstance(spec, dict) or set(spec) != {"left", "right", "how", "partition", "validate"}:
        raise ValueError("spec fields: left, right, how, partition, validate")
    if spec["how"] not in ("inner", "left") or type(spec["partition"]) is not bool:
        raise ValueError("invalid how or partition")
    if spec["validate"] not in (None, "one_to_one"):
        raise ValueError("validate must be null or one_to_one")
    for side in ("left", "right"):
        table = spec[side]
        if not isinstance(table, dict) or set(table) != {"dtype", "rows"}:
            raise ValueError("table fields: dtype, rows")
        dtype, rows = table["dtype"], table["rows"]
        if dtype not in DTYPES or not isinstance(rows, list):
            raise ValueError("invalid dtype or rows")
        seen = set()
        lo, hi = (0, 2**64 - 1) if dtype.lower() == "uint64" else (-2**63, 2**63 - 1)
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError("each row is [id, key]")
            identity, key = row
            if not isinstance(identity, str) or not identity or identity in seen:
                raise ValueError("row IDs must be nonempty and unique per side")
            seen.add(identity)
            if key is None:
                if dtype not in ("Int64", "UInt64"):
                    raise ValueError("null requires a nullable dtype")
            elif type(key) is not int or not lo <= key <= hi:
                raise ValueError("key is outside its declared integer dtype")

def scalar(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value

def frame(table, identity_column, partition):
    rows = table["rows"]
    result = pd.DataFrame({
        identity_column: pd.Series([r[0] for r in rows], dtype=object),
        "key": pd.Series([r[1] for r in rows], dtype=table["dtype"])
    })
    if partition:
        result["part"] = pd.Series([7] * len(rows), dtype="int64")
    return result

def run_case(spec):
    check_spec(spec)
    verify_sources()
    spec = deepcopy(spec)
    left = frame(spec["left"], "left_id", spec["partition"])
    right = frame(spec["right"], "right_id", spec["partition"])
    observation = {
        "spec": spec,
        "versions": {"pandas": pd.__version__, "numpy": np.__version__},
        "inputs": {side: {"dtype": str(table["key"].dtype),
                          "keys": [scalar(x) for x in table["key"].array]}
                   for side, table in (("left", left), ("right", right))},
        "rows": [], "dtypes": {}, "warnings": [], "error": None
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = left.merge(right, on=["key", "part"] if spec["partition"] else ["key"],
                                how=spec["how"], sort=False, validate=spec["validate"])
            observation["dtypes"] = {name: str(dtype) for name, dtype in result.dtypes.items()}
            columns = list(result.columns)
            # Read each column separately: iterrows/to_numpy can coerce mixed integers.
            arrays = [result[name].array for name in columns]
            observation["rows"] = [
                {name: scalar(value) for name, value in zip(columns, row)}
                for row in zip(*arrays)
            ]
        except Exception as exc:
            observation["error"] = {"type": type(exc).__name__, "message": str(exc)}
        observation["warnings"] = [
            {"type": type(item.message).__name__, "message": str(item.message)} for item in caught
        ]
    return observation

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", nargs="?", choices=sorted(CASES))
    parser.add_argument("--spec")
    args = parser.parse_args()
    if bool(args.case) == bool(args.spec):
        parser.error("choose a sample or --spec FILE")
    if args.spec:
        with open(args.spec, encoding="utf-8") as stream:
            spec = json.load(stream)
    else:
        spec = CASES[args.case]
    print(json.dumps(run_case(spec), ensure_ascii=False, indent=2, allow_nan=False))

if __name__ == "__main__":
    main()
