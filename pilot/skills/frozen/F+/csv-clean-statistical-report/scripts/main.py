#!/usr/bin/env python3
"""Clean a CSV of transaction records and write a statistical report.

Usage:
    python main.py <input.csv> <output_directory>
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = ('id', 'customer', 'date', 'category', 'amount')
DATE_FORMATS = ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d')
NEWLINE = chr(10)


def normalize_date(raw):
    value = (raw or '').strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return None


def parse_amount(raw):
    value = (raw or '').strip()
    if value == '':
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def id_sort_key(raw):
    value = raw.strip()
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def main():
    if len(sys.argv) != 3:
        print('usage: python main.py <input.csv> <output_directory>', file=sys.stderr)
        return 2
    input_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            print('error: input CSV has no header row', file=sys.stderr)
            return 2
        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing:
            print('error: missing required columns: ' + ', '.join(missing), file=sys.stderr)
            return 2
        records = list(reader)

    seen = set()
    cleaned = []
    for record in records:
        key = tuple(record.get(col, '') for col in reader.fieldnames)
        if key in seen:
            continue
        seen.add(key)

        if any(not (record.get(col) or '').strip() for col in ('id', 'customer', 'category')):
            continue

        normalized_date = normalize_date(record.get('date'))
        if normalized_date is None:
            continue

        cleaned.append({
            'id': record['id'].strip(),
            'customer': record['customer'].strip(),
            'date': normalized_date,
            'category': record['category'].strip(),
            'amount': parse_amount(record.get('amount')),
        })

    cleaned.sort(key=lambda row: id_sort_key(row['id']))

    total_rows = len(cleaned)
    total_amount = sum(row['amount'] for row in cleaned)
    unique_customers = len({row['customer'] for row in cleaned})
    mean_amount = total_amount / total_rows if total_rows else 0.0

    report = NEWLINE.join([
        'total_rows: {}'.format(total_rows),
        'total_amount: {:.2f}'.format(total_amount),
        'unique_customers: {}'.format(unique_customers),
        'mean_amount: {:.2f}'.format(mean_amount),
    ]) + NEWLINE

    (output_dir / 'report.md').write_text(report, encoding='utf-8')
    print(report, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
