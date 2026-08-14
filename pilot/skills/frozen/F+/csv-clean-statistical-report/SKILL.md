---
name: csv-clean-statistical-report
description: Clean an order/sales CSV (remove exact duplicates, drop rows missing id/customer/category, fill missing amounts with 0, normalize dates to YYYY-MM-DD, sort by id) and write a Markdown statistical report with total rows, total amount, unique customers, and mean amount. Use when a task asks for CSV cleaning plus these statistics.
---

# CSV Clean + Statistical Report

Run the provided script to clean the CSV and generate the report:

```bash
python scripts/main.py <input.csv> <outdir>
```

The script:

1. Removes exact duplicate rows.
2. Drops rows where id, customer, or category is empty or missing.
3. Fills missing amount values with 0.
4. Normalizes dates to YYYY-MM-DD and drops rows with unparseable dates.
5. Sorts rows by id ascending.

It writes `report.md` into `<outdir>` with exactly these four lines, with numeric values formatted to 2 decimals:

```
total_rows: <int>
total_amount: <number>
unique_customers: <int>
mean_amount: <number>
```

Run the script, then verify `report.md` matches the required format before finishing.
