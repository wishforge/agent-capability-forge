# Clean an order/sales CSV and write a Markdown statistical report.

import csv
import os
import sys
from datetime import datetime

COLUMNS = ('id', 'customer', 'date', 'category', 'amount')

DATE_FORMATS = (
    '%Y-%m-%d',
    '%Y/%m/%d',
    '%Y.%m.%d',
    '%m/%d/%Y',
    '%m-%d-%Y',
    '%d/%m/%Y',
    '%d-%m-%Y',
    '%d.%m.%Y',
)


def cell(row, index):
    if index is None or index >= len(row):
        return ''
    return row[index].strip()


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
        return (0, int(value))
    except ValueError:
        return (1, value)


def load_records(input_path):
    with open(input_path, newline='', encoding='utf-8-sig') as handle:
        rows = list(csv.reader(handle))

    if not rows:
        return []

    header = [name.strip().lower() for name in rows[0]]
    if any(name in header for name in COLUMNS):
        data_rows = rows[1:]
        index = {name: header.index(name) for name in COLUMNS if name in header}
    else:
        data_rows = rows
        index = {name: position for position, name in enumerate(COLUMNS)}

    seen = set()
    records = []
    for row in data_rows:
        if tuple(row) in seen:
            continue
        seen.add(tuple(row))

        values = {name: cell(row, index.get(name)) for name in COLUMNS}
        if not values['id'] or not values['customer'] or not values['category']:
            continue

        normalized_date = parse_date(values['date'])
        if normalized_date is None:
            continue

        records.append({
            'id': values['id'],
            'customer': values['customer'],
            'date': normalized_date,
            'category': values['category'],
            'amount': parse_amount(values['amount']),
        })

    records.sort(key=lambda record: id_key(record['id']))
    return records


def main():
    if len(sys.argv) != 3:
        print('usage: python main.py <input.csv> <outdir>', file=sys.stderr)
        return 2

    input_path = sys.argv[1]
    outdir = sys.argv[2]

    records = load_records(input_path)

    total_rows = len(records)
    total_amount = sum(record['amount'] for record in records)
    unique_customers = len({record['customer'] for record in records})
    mean_amount = total_amount / total_rows if total_rows else 0.0

    os.makedirs(outdir, exist_ok=True)
    report_path = os.path.join(outdir, 'report.md')
    with open(report_path, 'w', encoding='utf-8') as handle:
        handle.write('total_rows: {}\n'.format(total_rows))
        handle.write('total_amount: {:.2f}\n'.format(total_amount))
        handle.write('unique_customers: {}\n'.format(unique_customers))
        handle.write('mean_amount: {:.2f}\n'.format(mean_amount))

    print('wrote report.md with {} rows'.format(total_rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
