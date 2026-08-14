#!/usr/bin/env python3
"""Curated F+ method: clean an order/sales CSV and write cleaned.csv + report.md."""

import csv
import sys
from pathlib import Path

COLUMNS = ("id", "customer", "date", "category", "amount")


def clean_rows(rows):
    seen = set()
    cleaned = []
    for row in rows:
        key = tuple(sorted(row.items()))
        if key in seen:
            continue
        seen.add(key)
        if not (row["id"].strip() and row["customer"].strip() and row["category"].strip()):
            continue
        try:
            row["date"] = "-".join(
                "{:02d}".format(int(part)) for part in row["date"].replace("/", "-").split("-")
            )
        except (ValueError, TypeError):
            continue
        row["amount"] = row["amount"].strip() or "0"
        cleaned.append(row)
    cleaned.sort(key=lambda row: int(row["id"]))
    return cleaned


def main(argv):
    if len(argv) != 3:
        print("usage: python main.py <input.csv> <outdir>", file=sys.stderr)
        return 2
    input_path, outdir = Path(argv[1]), Path(argv[2])
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        cleaned = clean_rows(csv.DictReader(handle))

    amounts = [float(row["amount"]) for row in cleaned]
    stats = {
        "total_rows": len(cleaned),
        "total_amount": round(sum(amounts), 2),
        "unique_customers": len({row["customer"] for row in cleaned}),
        "mean_amount": round(sum(amounts) / len(amounts), 2) if cleaned else 0.0,
    }

    (outdir / "data").mkdir(parents=True, exist_ok=True)
    with (outdir / "data" / "cleaned.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(cleaned)
    with (outdir / "report.md").open("w", encoding="utf-8") as handle:
        handle.write("total_rows: {}\n".format(stats["total_rows"]))
        handle.write("total_amount: {:.2f}\n".format(stats["total_amount"]))
        handle.write("unique_customers: {}\n".format(stats["unique_customers"]))
        handle.write("mean_amount: {:.2f}\n".format(stats["mean_amount"]))
    print("wrote cleaned.csv and report.md with {} rows".format(stats["total_rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
