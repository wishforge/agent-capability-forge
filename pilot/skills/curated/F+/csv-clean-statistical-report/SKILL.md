---
name: csv-clean-statistical-report
description: Clean an order/sales CSV (remove exact duplicate rows, drop rows missing id/customer/category, fill missing amounts with 0, normalize dates to YYYY-MM-DD, sort by id ascending) and write a statistical report with total rows, total amount, unique customers, and mean amount. Use when a task asks for CSV cleaning plus these statistics.
---

# CSV Clean + Statistical Report

This task family takes a CSV with columns `id,customer,date,category,amount` and produces a cleaned CSV plus a four-line Markdown report.

## Stable contract

Input: `data/input.csv` with header `id,customer,date,category,amount` (UTF-8, with or without BOM).

Cleaning rules, applied in this order:

1. Remove exact duplicate rows (identical across all columns).
2. Drop rows where `id`, `customer`, or `category` is empty or missing.
3. Fill missing `amount` values with 0.
4. Normalize `date` values to `YYYY-MM-DD`; drop rows whose date cannot be parsed.
5. Sort remaining rows by `id` ascending.

Output:

- `data/cleaned.csv` — cleaned rows with the same five columns and header.
- `report.md` — exactly these four lines, numeric values with 2 decimals:

  ```
  total_rows: <int>
  total_amount: <number>
  unique_customers: <int>
  mean_amount: <number>
  ```

`total_rows` is the number of cleaned rows, `total_amount` is the sum of all amounts, `unique_customers` is the number of distinct customer values, and `mean_amount` is `total_amount / total_rows` (0 when there are no rows).

## Procedure

1. Run the provided script: `python scripts/main.py data/input.csv .`
2. Verify `data/cleaned.csv` exists with the cleaned rows.
3. Verify `report.md` contains exactly the four required lines in the required format.
4. Finish only after both outputs are verified.
