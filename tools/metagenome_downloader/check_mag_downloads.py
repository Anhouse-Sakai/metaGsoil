#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

TSV = Path('/mnt/sakai/paperdata/data/logs/resolved_files_MAG.tsv')
REPORT = Path('/mnt/sakai/paperdata/data/logs/mag_download_check.tsv')
SUMMARY = Path('/mnt/sakai/paperdata/data/logs/mag_download_check_summary.txt')


def md5sum(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open('rb') as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


total = 0
ok = 0
missing = 0
size_mismatch = 0
md5_mismatch = 0
unknown = 0
expected_total = 0
observed_total = 0

REPORT.parent.mkdir(parents=True, exist_ok=True)
with TSV.open('r', encoding='utf-8-sig', newline='') as source_fh, REPORT.open('w', encoding='utf-8', newline='') as report_fh:
    reader = csv.DictReader(source_fh, delimiter='\t')
    fields = ['status', 'reason', 'target', 'expected_bytes', 'observed_bytes', 'url']
    writer = csv.DictWriter(report_fh, fieldnames=fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()

    for row in reader:
        total += 1
        target = Path(row.get('target') or '')
        expected = 0
        try:
            expected = int((row.get('expected_bytes') or '0').strip() or '0')
        except ValueError:
            expected = 0
        expected_total += expected

        status = 'ok'
        reason = ''
        observed = 0
        if not target.exists():
            status = 'missing'
            reason = 'target does not exist'
            missing += 1
        else:
            observed = target.stat().st_size
            observed_total += observed
            if expected and observed != expected:
                status = 'size_mismatch'
                reason = f'{observed} != {expected}'
                size_mismatch += 1
            elif row.get('md5'):
                observed_md5 = md5sum(target)
                if observed_md5.lower() != row['md5'].lower():
                    status = 'md5_mismatch'
                    reason = f'{observed_md5} != {row["md5"]}'
                    md5_mismatch += 1
                else:
                    ok += 1
            else:
                ok += 1
                if not expected:
                    unknown += 1

        writer.writerow({
            'status': status,
            'reason': reason,
            'target': str(target),
            'expected_bytes': expected,
            'observed_bytes': observed,
            'url': row.get('url', ''),
        })

summary = (
    f'Total MAG records: {total}\n'
    f'OK: {ok}\n'
    f'Missing: {missing}\n'
    f'Size mismatch: {size_mismatch}\n'
    f'MD5 mismatch: {md5_mismatch}\n'
    f'OK with unknown expected size: {unknown}\n'
    f'Expected bytes: {expected_total}\n'
    f'Observed bytes: {observed_total}\n'
    f'Report: {REPORT}\n'
)
SUMMARY.write_text(summary, encoding='utf-8')
print(summary, end='')
raise SystemExit(0 if missing == size_mismatch == md5_mismatch == 0 else 1)
