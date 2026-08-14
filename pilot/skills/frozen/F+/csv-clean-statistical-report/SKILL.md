---
name: csv-clean-statistical-report
description: Clean an order/sales CSV (dedupe, drop incomplete rows, fill missing amounts, normalize dates, sort by id) and generate a Markdown statistical report. Use when a task asks for CSV cleaning plus total rows, total amount, unique customers, and mean amount.
---

# CSV Clean + Statistical Report

Use `scripts/main.py` to do the whole job:

```
python scripts/main.py <input.csv> <outdir>
```

The script removes exact duplicate rows, drops rows missing id/customer/category, fills missing amount values with 0, normalizes dates to YYYY-MM-DD (dropping unparseable dates), sorts by id ascending, and writes `report.md` into the output directory.

`report.md` contains exactly these four lines, with floats formatted to 2 decimals:

```
total_rows: <int>
total_amount: <number>
unique_customers: <int>
mean_amount: <number>
```

Run the script, then verify `report.md` matches the required format before finishing.
