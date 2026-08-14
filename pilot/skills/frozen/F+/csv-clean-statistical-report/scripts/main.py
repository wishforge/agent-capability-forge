#!/usr/bin/env python3
"""Clean an order/sales CSV and write a statistical report."""

import csv
import os
import sys
from datetime import datetime

COLUMNS = ['id', 'customer', 'date', 'category', 'amount']

DATE_FORMATS = (
    '%Y-%m-%d',
    '%Y/%m/%d',
    '%Y.%m.%d',
    '%m/%d/%Y',
    '%m-%d-%Y',
    '%d/%m/%Y',
    '%d-%m-%Y',
    '%d.%m.%Y',
    '%b %d, %Y',
    '%B %d, %Y',
    '%d %b %Y',
    '%d %B %Y',
)


def parse_date(value):
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def parse_amount(value):
    text = value.strip().replace(',', '')
    try:
        return float(text)
    except ValueError:
        return 0.0


def id_key(value):
    try:
        return (0, int(value), '')
    except ValueError:
        return (1, 0, value)


def cell(row, index):
    return row[index].strip() if index is not None and index < len(row) else ''


def main():
    if len(sys.argv) != 3:
        print('usage: python main.py <input.csv> <outdir>', file=sys.stderr)
        return 2

    input_path, outdir = sys.argv[1], sys.argv[2]

    with open(input_path, newline='', encoding='utf-8-sig') as handle:
        rows = list(csv.reader(handle))

    if not rows:
        records = []
    else:
        header = [name.strip().lower() for name in rows[0]]
        if any(name in header for name in COLUMNS):
            data = rows[1:]
        else:
            header = COLUMNS
            data = rows
        index = {name: header.index(name) for name in COLUMNS if name in header}

        seen = set()
        records = []
        for row in data:
            key = tuple(row)
            if key in seen:
                continue
            seen.add(key)

            record = {name: cell(row, index.get(name)) for name in COLUMNS}
            if not record['id'] or not record['customer'] or not record['category']:
                continue
            record['date'] = parse_date(record['date'])
            if record['date'] is None:
                continue
            record['amount'] = parse_amount(record['amount'])
            records.append(record)

    records.sort(key=lambda r: id_key(r['id']))
    total_rows = len(records)
    total_amount = sum(r['amount'] for r in records)
    unique_customers = len({r['customer'] for r in records})
    mean_amount = total_amount / total_rows if total_rows else 0.0

    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'report.md'), 'w', encoding='utf-8') as report:
        report.write(f'total_rows: {total_rows}\n')
        report.write(f'total_amount: {total_amount:.2f}\n')
        report.write(f'unique_customers: {unique_customers}\n')
        report.write(f'mean_amount: {mean_amount:.2f}\n')

    print(f'report.md written with {total_rows} rows')
    return 0


if __name__ == '__main__':
    sys.exit(main())
