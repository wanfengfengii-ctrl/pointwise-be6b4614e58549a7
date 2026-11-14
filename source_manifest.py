"""Fingerprint and read the actual upstream Python sources."""
import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path

import numpy
import pandas

MODULES = {
    "pandas.core.frame": "9b813159606b62af03bfe76a7089da282d2d6091f308cf2f4d90dd0661a01105",
    "pandas.core.reshape.merge": "2b7d736ab73adc8d5c125ef84d23cf213acb7697155409693ac94fd9d4cb614a",
    "pandas.core.indexes.base": "2d50f8000608294d074d8bf14a9cdc489f4bdd32ba5b81f233bcd00c44c3ff24",
    "pandas.core.dtypes.cast": "3e3ef65923fed1cb9da69247af98a2dff03f4b84e033478029e055f1c8bff377",
    "pandas.core.dtypes.dtypes": "c373fa029841a5315406a7592e9277eb3887db761d306307d2bef92ac4ce6d8b",
    "pandas.core.arrays.numeric": "955a52a6c1bfebacf640c1e084246861e7fa755249fd06407fdbe4a4b309a242"
}
SYMBOLS = {
    "pandas.core.frame": ["DataFrame.merge"],
    "pandas.core.reshape.merge": [
        "merge", "_MergeOperation.__init__", "_MergeOperation._get_join_info",
        "_MergeOperation._maybe_coerce_merge_keys",
        "_MergeOperation._validate_validate_kwd", "_MergeOperation._maybe_add_join_keys",
        "get_join_indexers", "get_join_indexers_non_unique", "_factorize_keys",
        "_convert_arrays_and_get_rizer_klass"
    ],
    "pandas.core.indexes.base": ["Index.join", "Index._find_common_type_compat"],
    "pandas.core.dtypes.cast": ["find_common_type"],
    "pandas.core.dtypes.dtypes": ["BaseMaskedDtype._get_common_dtype"]
}

def verify_sources():
    assert pandas.__version__ == "2.2.2", pandas.__version__
    assert numpy.__version__ == "1.26.4", numpy.__version__
    for name, expected in MODULES.items():
        path = Path(importlib.import_module(name).__file__)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (name, expected, actual)

def manifest():
    verify_sources()
    symbols = []
    for module_name, names in SYMBOLS.items():
        for name in names:
            obj = importlib.import_module(module_name)
            for part in name.split("."):
                obj = getattr(obj, part)
            lines, start = inspect.getsourcelines(obj)
            symbols.append({"module": module_name, "symbol": name, "line": start,
                            "end_line": start + len(lines) - 1})
    return {
        "repo": "https://github.com/pandas-dev/pandas/tree/v2.2.2",
        "versions": {"pandas": pandas.__version__, "numpy": numpy.__version__},
        "modules": {name: {"path": importlib.import_module(name).__file__, "sha256": value}
                    for name, value in MODULES.items()},
        "symbols": symbols
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", choices=sorted(MODULES))
    args = parser.parse_args()
    if args.module:
        verify_sources()
        path = Path(importlib.import_module(args.module).__file__)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            print(str(number) + ": " + line)
    else:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
