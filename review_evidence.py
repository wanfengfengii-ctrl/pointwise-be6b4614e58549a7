"""Re-runnable evidence for the pandas 2.2.2 integer-identity merge review.

Commands (always through the pinned workspace runner):
    python3 bootstrap.py review_evidence.py run
    python3 bootstrap.py review_evidence.py verify
    python3 bootstrap.py review_evidence.py demo

`expected()` is independent: it uses only the input rows, Python integers and
the contract's null rule.  It never calls pandas/NumPy matching, dtype
resolution, or factorisation, and it never reads the observed result.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import io
import json
from pathlib import Path
import sys

from probe import run_case
from samples import CASES
from source_manifest import MODULES, verify_sources

ROOT = Path(__file__).resolve().parent
EVIDENCE_PATH = ROOT / "evidence.json"
REVIEW_PATH = ROOT / "REVIEW.md"
DOC_PATH = ROOT / "docs" / "integer-merge.md"
PINNED = {"pandas": "2.2.2", "numpy": "1.26.4"}
REPO = "https://github.com/pandas-dev/pandas/tree/v2.2.2"

# Exact "## " headings expected in REVIEW.md; every case points at one.
REPORT_REFS = [
    "RE-1：正常回归与观察基线",
    "RE-2：重排单因对照",
    "RE-3：固定分区键单因对照",
    "RE-4：大整数边界与误配",
    "RE-5：缺失值与可空表示",
    "RE-6：真重复与重复次数",
    "RE-7：负数与无符号上界",
    "RE-8：左连接保留与组合",
]

# Source citations; verify() re-reads the installed module and checks that
# `snippet` really occurs in the cited range.
SOURCE_REFS = {
    "frame_merge": {
        "module": "pandas.core.frame", "line": 10815, "end_line": 10846,
        "snippet": "def merge(",
    },
    "merge_entry": {
        "module": "pandas.core.reshape.merge", "line": 137, "end_line": 184,
        "snippet": "op = _MergeOperation(",
    },
    "coerce_keys": {
        "module": "pandas.core.reshape.merge", "line": 1364, "end_line": 1552,
        "snippet": "def _maybe_coerce_merge_keys(self) -> None:",
    },
    "coerce_infer_continue": {
        "module": "pandas.core.reshape.merge", "line": 1474, "end_line": 1478,
        "snippet": "lib.infer_dtype(lk, skipna=False)",
    },
    "get_join_indexers": {
        "module": "pandas.core.reshape.merge", "line": 1692, "end_line": 1767,
        "snippet": "def get_join_indexers(",
    },
    "multi_key_factorize": {
        "module": "pandas.core.reshape.merge", "line": 1734, "end_line": 1744,
        "snippet": "_factorize_keys(left_keys[n], right_keys[n], sort=sort)",
    },
    "path_selection": {
        "module": "pandas.core.reshape.merge", "line": 1749, "end_line": 1761,
        "snippet": "get_join_indexers_non_unique(",
    },
    "factorize_keys": {
        "module": "pandas.core.reshape.merge", "line": 2398, "end_line": 2585,
        "snippet": "def _factorize_keys(",
    },
    "rizer_dtype": {
        "module": "pandas.core.reshape.merge", "line": 2588, "end_line": 2622,
        "snippet": "find_common_type([lk.dtype, rk.dtype])",
    },
    "validate_kwd": {
        "module": "pandas.core.reshape.merge", "line": 1633, "end_line": 1689,
        "snippet": "MultiIndex.from_arrays(self.left_join_keys).is_unique",
    },
    "add_join_keys": {
        "module": "pandas.core.reshape.merge", "line": 1003, "end_line": 1117,
        "snippet": "result_dtype = find_common_type([lvals.dtype, rvals.dtype])",
    },
    "find_common_type": {
        "module": "pandas.core.dtypes.cast", "line": 1433, "end_line": 1485,
        "snippet": "return np_find_common_type(*types)",
    },
    "np_result_type": {
        "module": "pandas.core.dtypes.cast", "line": 1392, "end_line": 1410,
        "snippet": "common_dtype = np.result_type(*dtypes)",
    },
    "index_join": {
        "module": "pandas.core.indexes.base", "line": 4628, "end_line": 4632,
        "snippet": "self._find_common_type_compat(other)",
    },
    "index_compat": {
        "module": "pandas.core.indexes.base", "line": 6371, "end_line": 6392,
        "snippet": "self.dtype == \"uint64\"",
    },
    "masked_common": {
        "module": "pandas.core.dtypes.dtypes", "line": 1590, "end_line": 1607,
        "snippet": "def _get_common_dtype(",
    },
}

A = 2 ** 53
B = A + 1
INT64_MAX = 2 ** 63 - 1
UINT64_MAX = 2 ** 64 - 1


def _spec(left_dtype, left_rows, right_dtype, right_rows,
          how="inner", partition=False, validate=None):
    return {
        "left": {"dtype": left_dtype, "rows": left_rows},
        "right": {"dtype": right_dtype, "rows": right_rows},
        "how": how,
        "partition": partition,
        "validate": validate,
    }


# Single-factor controls.  Every case changes one factor against a control
# named in `control_of`.
CASES_EVIDENCE = [
    {
        "id": "C01_normal", "report_ref": REPORT_REFS[0], "control_of": None,
        "factor": "基准：小整数、int64/uint64、left、one_to_one",
        "spec": deepcopy(CASES["normal"]),
    },
    {
        "id": "C02_empty_left", "report_ref": REPORT_REFS[0], "control_of": None,
        "factor": "空左表，可空类型 inner",
        "spec": _spec("Int64", [], "UInt64", [["R0", A]], validate="one_to_one"),
    },
    {
        "id": "C03_empty_right_left", "report_ref": REPORT_REFS[0], "control_of": None,
        "factor": "空右表，可空类型 left，左侧保留",
        "spec": _spec("UInt64", [["L0", UINT64_MAX]], "Int64", [], how="left",
                      validate="one_to_one"),
    },
    {
        "id": "C04_incident", "report_ref": REPORT_REFS[3], "control_of": "C05",
        "factor": "公开事故：2^53/2^53+1，右表降序",
        "spec": deepcopy(CASES["incident"]),
    },
    {
        "id": "C05_incident_right_asc", "report_ref": REPORT_REFS[1], "control_of": None,
        "factor": "与 C04 同值同侧，仅右表改为升序",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "uint64", [["R0", A], ["R1", B]], validate="one_to_one"),
    },
    {
        "id": "C06_same_dtype_reordered", "report_ref": REPORT_REFS[1], "control_of": None,
        "factor": "同 dtype int64，右表降序",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "int64", [["R1", B], ["R0", A]], validate="one_to_one"),
    },
    {
        "id": "C07_partition_asc", "report_ref": REPORT_REFS[2], "control_of": "C05",
        "factor": "C05 加固定 part=7",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "uint64", [["R0", A], ["R1", B]],
                      partition=True, validate="one_to_one"),
    },
    {
        "id": "C08_partition_int64_control", "report_ref": REPORT_REFS[2], "control_of": None,
        "factor": "同 dtype int64，加固定 part=7",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "int64", [["R0", A], ["R1", B]],
                      partition=True, validate="one_to_one"),
    },
    {
        "id": "C09_safe_range_unsorted", "report_ref": REPORT_REFS[3], "control_of": None,
        "factor": "安全整数边界 2^53-1 / 2^53，右表降序",
        "spec": _spec("int64", [["L0", A - 1], ["L1", A]],
                      "uint64", [["R1", A], ["R0", A - 1]]),
    },
    {
        "id": "C10_boundary_false_match", "report_ref": REPORT_REFS[3], "control_of": "C09",
        "factor": "2^53 与 2^53-1 之间出现 2^53+1，右表降序",
        "spec": _spec("int64", [["L0", A]],
                      "uint64", [["R1", B], ["R0", A - 1]]),
    },
    {
        "id": "C11_int64_max_collision", "report_ref": REPORT_REFS[3], "control_of": None,
        "factor": "int64 上界与 uint64 2^63/2^63+1，右表降序",
        "spec": _spec("int64", [["L0", INT64_MAX]],
                      "uint64", [["R1", 2 ** 63 + 1], ["R0", 2 ** 63]]),
    },
    {
        "id": "C12_power_of_two_exact", "report_ref": REPORT_REFS[3], "control_of": None,
        "factor": "大但精确可表示的 2^60/2^61，混合 dtype，右表降序",
        "spec": _spec("int64", [["L0", 2 ** 60], ["L1", 2 ** 61]],
                      "uint64", [["R1", 2 ** 61], ["R0", 2 ** 60]]),
    },
    {
        "id": "C13_validate_not_protective", "report_ref": REPORT_REFS[3], "control_of": "C05",
        "factor": "左右键各唯一，one_to_one，可空 UInt64 右表",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "UInt64", [["R0", A]], validate="one_to_one"),
    },
    {
        "id": "C14_nullable_small", "report_ref": REPORT_REFS[4], "control_of": None,
        "factor": "可空 Int64/UInt64，小整数加空键",
        "spec": _spec("Int64", [["LN", None], ["L0", 1], ["L1", 2]],
                      "UInt64", [["RN", None], ["R0", 1], ["R1", 2]],
                      validate="one_to_one"),
    },
    {
        "id": "C15_nullable_large_desc", "report_ref": REPORT_REFS[4], "control_of": "C14",
        "factor": "C14 换为大整数，右表降序（值域与顺序）",
        "spec": _spec("Int64", [["L0", A], ["L1", B]],
                      "UInt64", [["R1", B], ["R0", A]], validate="one_to_one"),
    },
    {
        "id": "C16_nullable_partition", "report_ref": REPORT_REFS[4], "control_of": "C15",
        "factor": "C15 改为升序并加固定 part=7",
        "spec": _spec("Int64", [["L0", A], ["L1", B]],
                      "UInt64", [["R0", A], ["R1", B]],
                      partition=True, validate="one_to_one"),
    },
    {
        "id": "C17_null_no_false_match", "report_ref": REPORT_REFS[4], "control_of": None,
        "factor": "空键只与空键匹配，可空类型",
        "spec": _spec("Int64", [["LN", None], ["L0", 1]],
                      "UInt64", [["RV", 2], ["RN", None]]),
    },
    {
        "id": "C18_null_duplicate_validate", "report_ref": REPORT_REFS[4], "control_of": None,
        "factor": "同侧两个空键 + one_to_one",
        "spec": _spec("Int64", [["N1", None], ["N2", None]],
                      "UInt64", [["R0", None]], validate="one_to_one"),
    },
    {
        "id": "C19_duplicates_small", "report_ref": REPORT_REFS[5], "control_of": None,
        "factor": "小整数真重复，不校验唯一性",
        "spec": deepcopy(CASES["duplicates"]),
    },
    {
        "id": "C20_duplicates_small_validate", "report_ref": REPORT_REFS[5], "control_of": "C19",
        "factor": "C19 改为 one_to_one",
        "spec": {**deepcopy(CASES["duplicates"]), "validate": "one_to_one"},
    },
    {
        "id": "C21_duplicates_large_mixed", "report_ref": REPORT_REFS[5], "control_of": "C19",
        "factor": "C19 换大整数与 int64/uint64 混用，升序",
        "spec": _spec("int64", [["L0", A], ["L1", A], ["L2", B]],
                      "uint64", [["R0", A], ["R1", B], ["R2", B]]),
    },
    {
        "id": "C22_duplicates_large_same_dtype", "report_ref": REPORT_REFS[5], "control_of": "C21",
        "factor": "C21 改为同 dtype int64",
        "spec": _spec("int64", [["L0", A], ["L1", A], ["L2", B]],
                      "int64", [["R0", A], ["R1", B], ["R2", B]]),
    },
    {
        "id": "C23_negative_mixed", "report_ref": REPORT_REFS[6], "control_of": None,
        "factor": "负 int64 与 uint64 上界、0，右表降序",
        "spec": _spec("int64", [["L0", -1], ["L1", 0]],
                      "uint64", [["R0", UINT64_MAX], ["R1", 0]]),
    },
    {
        "id": "C24_uint64_top_same_dtype", "report_ref": REPORT_REFS[6], "control_of": None,
        "factor": "uint64 上界同 dtype 匹配",
        "spec": _spec("uint64", [["L0", UINT64_MAX]],
                      "uint64", [["R0", UINT64_MAX]], validate="one_to_one"),
    },
    {
        "id": "C25_uint64_vs_signed_no_wrap", "report_ref": REPORT_REFS[6], "control_of": None,
        "factor": "uint64 上界对 int64 上界，不应回绕",
        "spec": _spec("uint64", [["L0", UINT64_MAX]],
                      "int64", [["R0", INT64_MAX]]),
    },
    {
        "id": "C26_signed_min_same_dtype", "report_ref": REPORT_REFS[6], "control_of": None,
        "factor": "int64 下界同 dtype 匹配",
        "spec": _spec("int64", [["L0", -(2 ** 63)]],
                      "int64", [["R0", -(2 ** 63)]], validate="one_to_one"),
    },
    {
        "id": "C27_left_join_ordered", "report_ref": REPORT_REFS[7], "control_of": None,
        "factor": "left 未匹配左行保留，升序，无分区",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "uint64", [["R0", A]], how="left", validate="one_to_one"),
    },
    {
        "id": "C28_left_join_partition_misattach", "report_ref": REPORT_REFS[7], "control_of": "C27",
        "factor": "C27 加固定 part=7",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "uint64", [["R0", A]], how="left", partition=True,
                      validate="one_to_one"),
    },
    {
        "id": "C29_nullable_asc_no_partition", "report_ref": REPORT_REFS[4], "control_of": "C05",
        "factor": "C05 改为可空 Int64/UInt64，两侧升序",
        "spec": _spec("Int64", [["L0", A], ["L1", B]],
                      "UInt64", [["R0", A], ["R1", B]], validate="one_to_one"),
    },
    {
        "id": "C30_left_join_right_desc", "report_ref": REPORT_REFS[7], "control_of": "C27",
        "factor": "C27 仅把右表改为降序",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "uint64", [["R1", B], ["R0", A]], how="left",
                      validate="one_to_one"),
    },
    {
        "id": "C31_same_signedness_partition", "report_ref": REPORT_REFS[2],
        "control_of": "C08",
        "factor": "C08 把右表改为可空同符号 Int64，加固定 part=7",
        "spec": _spec("int64", [["L0", A], ["L1", B]],
                      "Int64", [["R0", A], ["R1", B]],
                      partition=True, validate="one_to_one"),
    },
    {
        "id": "C32_same_signedness_duplicates", "report_ref": REPORT_REFS[5],
        "control_of": "C22",
        "factor": "C22 把右表改为可空同符号 Int64，右表降序",
        "spec": _spec("int64", [["L0", A], ["L1", A], ["L2", B]],
                      "Int64", [["R1", B], ["R0", A]], validate="one_to_one"),
    },
]


# ---------------------------------------------------------------------------
# Independent expectation: inputs + Python ints + the contract's null rule.
# ---------------------------------------------------------------------------

def _match(left_key, right_key):
    if left_key is None or right_key is None:
        return left_key is None and right_key is None
    return int(left_key) == int(right_key)  # Python ints, exact


def _duplicate_side(table):
    keys = [row[1] for row in table["rows"]]
    return any(count > 1 for count in Counter(keys).values())


def expected(spec):
    """Return {"kind": "rows", "rows": [...]} or {"kind": "error", ...}."""
    if spec["validate"] == "one_to_one":
        for side in ("left", "right"):
            if _duplicate_side(spec[side]):
                return {"kind": "error", "error_type": "MergeError",
                        "reason": f"duplicate exact key on {side}"}
    part = 7 if spec["partition"] else None
    rows = []
    matched_left = set()
    for left_id, left_key in spec["left"]["rows"]:
        for right_id, right_key in spec["right"]["rows"]:
            if _match(left_key, right_key):
                row = {"left_id": left_id, "right_id": right_id, "key": left_key}
                if part is not None:
                    row["part"] = part
                rows.append(row)
                matched_left.add(left_id)
    if spec["how"] == "left":
        for left_id, left_key in spec["left"]["rows"]:
            if left_id not in matched_left:
                row = {"left_id": left_id, "right_id": None, "key": left_key}
                if part is not None:
                    row["part"] = part
                rows.append(row)
    return {"kind": "rows", "rows": rows}


def _identity(row, partition):
    return (row["left_id"], row["right_id"], row["key"],
            row.get("part") if partition else None)


def compare(spec, observation):
    exp = expected(spec)
    partition = spec["partition"]
    if exp["kind"] == "error":
        error = observation["error"]
        if error is None:
            return False, ["expected MergeError, observation succeeded with "
                           f"{len(observation['rows'])} rows"]
        if error["type"] != exp["error_type"]:
            return False, [f"expected {exp['error_type']}, observed {error['type']}: "
                           f"{error['message']}"]
        return True, []
    if observation["error"] is not None:
        return False, [f"expected rows, observed {observation['error']['type']}: "
                       f"{observation['error']['message']}"]
    want = Counter(_identity(row, partition) for row in exp["rows"])
    got = Counter(_identity(row, partition) for row in observation["rows"])
    if want == got:
        return True, []
    return False, [
        f"missing expected rows: {sorted(want - got)}",
        f"unexpected observed rows: {sorted(got - want)}",
    ]


# ---------------------------------------------------------------------------
# Evidence assembly and verification helpers
# ---------------------------------------------------------------------------

def _heading_exists(review_text, ref):
    return any(line.strip() == f"## {ref}" for line in review_text.splitlines())


def _source_check(refs):
    problems = []
    for name, ref in refs.items():
        path = Path(importlib.import_module(ref["module"]).__file__)
        lines = path.read_text(encoding="utf-8").splitlines()
        if not 1 <= ref["line"] <= len(lines):
            problems.append(f"{name}: line {ref['line']} outside file")
            continue
        window = lines[ref["line"] - 1:ref["end_line"]]
        if not any(ref["snippet"] in line for line in window):
            problems.append(f"{name}: snippet not found in "
                            f"{ref['module']}:{ref['line']}-{ref['end_line']}")
    return problems


def _run_normal_regression():
    import checks
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        checks.normal()
    text = buffer.getvalue()
    return "NORMAL_REGRESSION_OK" in text, text


def command_run():
    verify_sources()
    cases = []
    for case in CASES_EVIDENCE:
        observation = run_case(deepcopy(case["spec"]))
        exp = expected(case["spec"])
        ok, differences = compare(case["spec"], observation)
        cases.append({**case, "observation": observation,
                      "expected": exp, "match": ok, "differences": differences})
    evidence = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": "CONTRACT.md",
        "repo": REPO,
        "versions": {name: importlib.import_module(
            "pandas" if name == "pandas" else "numpy").__version__ for name in PINNED},
        "source_hashes": dict(MODULES),
        "source_refs": SOURCE_REFS,
        "report_refs": REPORT_REFS,
        "cases": cases,
        "summary": {
            "cases": len(cases),
            "match": sum(case["match"] for case in cases),
            "mismatch": sum(not case["match"] for case in cases),
        },
    }
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(f"wrote {EVIDENCE_PATH.name}: {evidence['summary']['cases']} cases, "
          f"{evidence['summary']['match']} match, "
          f"{evidence['summary']['mismatch']} mismatch")
    for case in cases:
        if not case["match"]:
            print(f"  MISMATCH {case['id']} ({case['report_ref']}): "
                  + " | ".join(case["differences"]))
    return 0


def command_verify():
    problems = []
    verify_sources()

    if not EVIDENCE_PATH.exists():
        print("evidence.json missing; run: python3 bootstrap.py review_evidence.py run")
        return 1
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    if evidence.get("schema") != 1:
        problems.append("unexpected evidence schema")
    if evidence.get("versions") != PINNED:
        problems.append(f"versions {evidence.get('versions')} != {PINNED}")
    if evidence.get("source_hashes") != MODULES:
        problems.append("source hashes differ from source_manifest.py")
    problems.extend(_source_check(evidence.get("source_refs", {})))
    if evidence.get("report_refs") != REPORT_REFS:
        problems.append("report refs differ from this script")

    review = REVIEW_PATH.read_text(encoding="utf-8") if REVIEW_PATH.exists() else ""
    if not review:
        problems.append("REVIEW.md missing")
    for ref in REPORT_REFS:
        if not _heading_exists(review, ref):
            problems.append(f"REVIEW.md missing heading: ## {ref}")
    for marker in ("源码链路", "根因", "发布意见", "调用方规避"):
        if marker not in review:
            problems.append(f"REVIEW.md missing section marker: {marker}")

    doc = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
    if not doc:
        problems.append("docs/integer-merge.md missing")
    for marker in ("当前实际行为", "调用方规避", "库内最小修复建议", "发布检查"):
        if marker not in doc:
            problems.append(f"docs/integer-merge.md missing section marker: {marker}")
    for bad_claim in ("仅调整来源行顺序不影响匹配身份",
                      "键列仍显示整数时不必追踪",
                      "可用于完整整数范围"):
        if bad_claim in doc:
            problems.append(f"docs/integer-merge.md still asserts: {bad_claim}")

    saved_cases = {case["id"]: case for case in evidence.get("cases", [])}
    if set(saved_cases) != {case["id"] for case in CASES_EVIDENCE}:
        problems.append("saved case ids differ from current case list")

    replayed_mismatch = 0
    for case in CASES_EVIDENCE:
        saved = saved_cases.get(case["id"])
        if saved is None:
            continue
        spec = deepcopy(case["spec"])
        observation = run_case(spec)
        if observation != saved["observation"]:
            problems.append(f"{case['id']}: observation changed since run")
        if saved.get("spec") != spec:
            problems.append(f"{case['id']}: saved spec differs")
        if saved.get("report_ref") not in REPORT_REFS:
            problems.append(f"{case['id']}: unknown report ref {saved.get('report_ref')}")
        if saved.get("report_ref") not in review:
            problems.append(f"{case['id']}: report ref not mentioned in REVIEW.md")
        ok, differences = compare(spec, observation)
        if not ok:
            replayed_mismatch += 1
        # The saved verdict must still describe this replay.
        if saved.get("match") != ok:
            problems.append(f"{case['id']}: saved verdict no longer matches replay")
        if saved.get("differences") != differences:
            problems.append(f"{case['id']}: saved differences changed")
        if saved.get("expected") != expected(spec):
            problems.append(f"{case['id']}: independent expectation changed")

    normal_ok, normal_output = _run_normal_regression()
    if not normal_ok:
        problems.append("normal regression did not print NORMAL_REGRESSION_OK")

    if problems:
        print("EVIDENCE_VERIFY_FAILED")
        for item in problems:
            print(" - " + item)
        return 1
    print(f"EVIDENCE_VERIFY_OK: {len(CASES_EVIDENCE)} cases replayed, "
          f"{replayed_mismatch} identity mismatches reproduce, "
          f"normal regression passes, report refs and source lines resolve")
    return 0


def command_demo():
    normal_spec = deepcopy(CASES["normal"])
    normal_observation = run_case(normal_spec)
    normal_ok, normal_diffs = compare(normal_spec, normal_observation)
    print("== normal sample: real merge output ==")
    for row in normal_observation["rows"]:
        print(f"  left={row['left_id']!r} right={row['right_id']!r} key={row['key']!r}")
    print(f"  expected-match={normal_ok}")
    for item in normal_diffs:
        print("  diff: " + item)

    incident_spec = deepcopy(CASES["incident"])
    incident_observation = run_case(incident_spec)
    incident_ok, incident_diffs = compare(incident_spec, incident_observation)
    print("== incident sample: real merge output ==")
    for row in incident_observation["rows"]:
        print(f"  left={row['left_id']!r} right={row['right_id']!r} key={row['key']!r}")
    print("  independent expectation (exact integer identity):")
    for row in expected(incident_spec)["rows"]:
        print(f"  left={row['left_id']!r} right={row['right_id']!r} key={row['key']!r}")
    print(f"  expected-match={incident_ok}")
    for item in incident_diffs:
        print("  diff: " + item)
    right_ids = Counter(row["right_id"] for row in incident_observation["rows"])
    print("  observed right_id multiplicity:", dict(right_ids))
    print("  each left identity attached to every right identity whose float64 "
          "image collides; distinct keys were not preserved")

    if normal_ok and not incident_ok:
        print("DEMO_DEFECT_REPRODUCED")
        return 0
    print("DEMO_UNEXPECTED_STATE")
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "verify", "demo"])
    args = parser.parse_args()
    handler = {"run": command_run, "verify": command_verify, "demo": command_demo}
    return handler[args.command]()


if __name__ == "__main__":
    sys.exit(main())
