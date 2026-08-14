---
name: csv-clean-statistical-report
description: Cleans a CSV of transaction records (deduplicate rows, drop rows missing id/customer/category or an unparseable date, fill missing amounts with 0, sort by id) and writes a statistical report.md.
---

# CSV Clean + Statistical Report

Use this skill when a task asks you to read a CSV with columns `id`, `customer`, `date`, `category`, and `amount`, clean it, and write a `report.md` containing `total_rows`, `total_amount`, `unique_customers`, and `mean_amount`.

## Cleaning rules

The script in `scripts/main.py` applies these rules in order:

1. Remove exact duplicate rows (identical values in every column), keeping the first occurrence.
2. Drop rows where `id`, `customer`, or `category` is empty or whitespace-only.
3. Fill missing or non-numeric `amount` values with `0`.
4. Normalize `date` values to `YYYY-MM-DD`; drop rows whose date cannot be parsed.
5. Sort rows by `id` ascending (numeric when possible).

## Usage

Run the script with the input CSV path and the output directory:

```bash
python scripts/main.py path/to/input.csv path/to/output
```

The script writes `report.md` into the output directory with exactly these four lines (floats formatted with 2 decimals):

```text
total_rows: 9
total_amount: 83.00
unique_customers: 8
mean_amount: 9.22
```

It also prints the report to stdout. Verify `report.md` exists and contains exactly those four lines before finishing.
