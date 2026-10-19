#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

TSV = Path('/mnt/sakai/paperdata/data/logs/resolved_files_MAG.tsv')

def human(value: int) -> str:
    amount = float(value)
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']:
        if amount < 1024 or unit == 'PiB':
            return f'{amount:.2f} {unit}' if unit != 'B' else f'{int(amount)} {unit}'
        amount /= 1024

records = 0
complete = 0
partial = 0
missing = 0
expected_total = 0
observed_total = 0
with TSV.open('r', encoding='utf-8-sig', newline='') as fh:
    for row in csv.DictReader(fh, delimiter='\t'):
        records += 1
        target = Path(row.get('target') or '')
        try:
            expected = int((row.get('expected_bytes') or '0').strip() or '0')
        except ValueError:
            expected = 0
        expected_total += expected
        if not target.exists():
            missing += 1
            continue
        observed = target.stat().st_size
        observed_total += observed
        if expected and observed >= expected:
            complete += 1
        else:
            partial += 1

print(f'Total records: {records}')
print(f'Complete files: {complete}')
print(f'Partial files: {partial}')
print(f'Missing files: {missing}')
print(f'Observed bytes: {human(observed_total)}')
print(f'Expected bytes: {human(expected_total)}')
if expected_total:
    print(f'Progress by bytes: {observed_total / expected_total * 100:.2f}%')
