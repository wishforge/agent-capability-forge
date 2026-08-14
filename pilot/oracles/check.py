#!/usr/bin/env python3
"""M3 - deterministic F+ oracle: check.py <fixture_dir> <output_dir>.

PASS iff report.md contains total_rows/total_amount/unique_customers/mean_amount
exactly matching fixture expected.json (floats rounded to 2 decimals).
"""

import json
import re
import sys

KEYS = ["total_rows", "total_amount", "unique_customers", "mean_amount"]
INT_KEYS = {"total_rows", "unique_customers"}


def main() -> int:
    fixture_dir, output_dir = sys.argv[1], sys.argv[2]
    expected = json.load(open(f"{fixture_dir}/expected.json"))
    report = open(f"{output_dir}/report.md", encoding="utf-8").read()
    found = {}
    for line in report.splitlines():
        m = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.+?)\s*$", line)
        if m:
            found[m.group(1)] = m.group(2).strip()
    problems = []
    for key in KEYS:
        if key not in found:
            problems.append(f"missing {key}")
            continue
        try:
            if key in INT_KEYS:
                ok = int(found[key]) == int(expected[key])
            else:
                ok = abs(round(float(found[key]), 2) - round(float(expected[key]), 2)) < 1e-9
        except ValueError:
            ok = False
        if not ok:
            problems.append(f"{key}: expected {expected[key]}, got {found[key]}")
    if problems:
        print("FAIL " + "; ".join(problems))
        return 1
    print("PASS " + " ".join(f"{k}={expected[k]}" for k in KEYS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
