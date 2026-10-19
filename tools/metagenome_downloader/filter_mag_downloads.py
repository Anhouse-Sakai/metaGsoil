#!/usr/bin/env python3
"""Filter resolved download files to MAG-relevant sequence archives.

This script does not resolve DOI/accessions and does not contact remote services.
It only reads an existing resolved_files.tsv and writes resolved_files_MAG.tsv.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEFAULT_INPUT = Path("logs/resolved_files.tsv")
FALLBACK_INPUT = Path("../data/logs/resolved_files.tsv")

KEEP_EXTENSIONS = (
    ".fastq.gz",
    ".fastq",
    ".fq.gz",
    ".fq",
    ".sra",
    ".fasta",
    ".fa",
    ".tar.gz",
    ".zip",
)

DROP_EXTENSIONS = (
    ".chrlist",
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".png",
    ".jpeg",
    ".jpg",
    ".svg",
    ".gif",
    ".html",
    ".htm",
)

DROP_KEYWORD_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:"
    r"supplement|supplementary|figure|fig|table|image|readme|"
    r"protocol|manual|poster|slides|presentation"
    r")(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


def resolve_default_input(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_INPUT and FALLBACK_INPUT.exists():
        return FALLBACK_INPUT
    return path


def normalize_name(value: str) -> str:
    value = unquote(value or "")
    if "://" in value:
        split = urlsplit(value)
        value = split.path or value
    else:
        value = value.split("?", 1)[0].split("#", 1)[0]
    return value.lower()


def searchable_text(row: dict[str, str]) -> str:
    parts = [row.get("url", ""), row.get("target", "")]
    normalized = []
    for part in parts:
        text = normalize_name(part)
        basename = os.path.basename(text)
        normalized.extend([text, basename])
    return " ".join(normalized)


def has_extension(row: dict[str, str], extensions: tuple[str, ...]) -> bool:
    for field in ("url", "target"):
        name = normalize_name(row.get(field, ""))
        if any(name.endswith(ext) for ext in extensions):
            return True
    return False


def expected_bytes(row: dict[str, str]) -> int:
    value = (row.get("expected_bytes") or "").strip()
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def keep_row(row: dict[str, str]) -> tuple[bool, str]:
    source = (row.get("source") or "").strip()
    if source == "ENA:fastq_ftp":
        return True, "keep_ena_fastq_ftp"

    text = searchable_text(row)
    if DROP_KEYWORD_RE.search(text):
        return False, "drop_supplement_or_nondata_keyword"

    if has_extension(row, DROP_EXTENSIONS):
        return False, "drop_non_sequence_extension"

    if has_extension(row, KEEP_EXTENSIONS):
        return True, "keep_sequence_or_archive_extension"

    return False, "drop_unknown_or_non_sequence_extension"


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} PiB"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter resolved_files.tsv to MAG-relevant downloads without re-resolving accessions."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Input resolved TSV. Defaults to logs/resolved_files.tsv; falls back to ../data/logs/resolved_files.tsv when run from the bundle.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output filtered TSV. Defaults to resolved_files_MAG.tsv next to the input file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = resolve_default_input(args.input)
    output_path = args.output or input_path.with_name("resolved_files_MAG.tsv")

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    original = 0
    kept = 0
    removed = 0
    kept_bytes = 0
    removal_reasons: dict[str, int] = {}

    with input_path.open("r", encoding="utf-8-sig", newline="") as source_fh, output_path.open(
        "w", encoding="utf-8", newline=""
    ) as target_fh:
        reader = csv.DictReader(source_fh, delimiter="\t")
        if not reader.fieldnames:
            raise SystemExit(f"Input file has no header: {input_path}")
        writer = csv.DictWriter(target_fh, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()

        for row in reader:
            original += 1
            keep, reason = keep_row(row)
            if keep:
                kept += 1
                kept_bytes += expected_bytes(row)
                writer.writerow(row)
            else:
                removed += 1
                removal_reasons[reason] = removal_reasons.get(reason, 0) + 1

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Original files: {original}")
    print(f"Kept: {kept}")
    print(f"Removed: {removed}")
    print(f"Estimated size kept: {human_bytes(kept_bytes)}")
    if removal_reasons:
        print("Removal reasons:")
        for reason, count in sorted(removal_reasons.items()):
            print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
