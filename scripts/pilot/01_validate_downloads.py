#!/usr/bin/env python3
"""Audit pilot downloads against the downloader's resolved ENA manifests.

Outputs are deterministic TSV files under metadata/qc.  A non-zero exit means
at least one requested file is absent, has the wrong size/MD5, is not a valid
gzip stream, or is not structurally FASTQ-like.
"""
from __future__ import annotations

import os
import argparse
import csv
import gzip
import hashlib
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BATCHES = {
    "core_a_rice": "raw_data/16S/core_a_rice",
    "technical_amplicon": "raw_data/16S/technical_amplicon",
    "mag_technical": "raw_data/shotgun/mag_technical",
}


def md5sum(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fastq_sample(path: Path, max_reads: int) -> dict[str, str]:
    reads = bases = qchars = 0
    qsum = 0
    min_len: int | None = None
    max_len = 0
    status = "pass"
    reason = ""
    try:
        with gzip.open(path, "rt", encoding="ascii", errors="strict") as handle:
            while reads < max_reads:
                header = handle.readline()
                if not header:
                    break
                seq = handle.readline().rstrip("\n\r")
                plus = handle.readline()
                qual = handle.readline().rstrip("\n\r")
                if not header.startswith("@") or not plus.startswith("+") or len(seq) != len(qual):
                    status, reason = "fail", "invalid FASTQ four-line record"
                    break
                length = len(seq)
                reads += 1
                bases += length
                min_len = length if min_len is None else min(min_len, length)
                max_len = max(max_len, length)
                qsum += sum(ord(char) - 33 for char in qual)
                qchars += len(qual)
    except Exception as exc:  # recorded as data-quality evidence, not hidden
        status, reason = "fail", f"gzip/FASTQ read error: {type(exc).__name__}: {exc}"
    return {
        "sampled_reads": str(reads),
        "sampled_bases": str(bases),
        "mean_read_length": f"{bases / reads:.2f}" if reads else "",
        "min_read_length": str(min_len) if min_len is not None else "",
        "max_read_length": str(max_len) if reads else "",
        "mean_phred": f"{qsum / qchars:.2f}" if qchars else "",
        "fastq_sample_status": status,
        "fastq_sample_reason": reason,
    }


def audit_one(batch: str, row: dict[str, str], max_reads: int) -> dict[str, str]:
    target = Path(row["target"])
    expected_size = int(row.get("expected_bytes") or 0)
    observed_size = target.stat().st_size if target.exists() else 0
    size_status = "pass" if target.exists() and (not expected_size or observed_size == expected_size) else "fail"
    observed_md5 = md5sum(target) if target.exists() else ""
    expected_md5 = (row.get("md5") or "").lower()
    md5_status = "pass" if target.exists() and (not expected_md5 or observed_md5.lower() == expected_md5) else "fail"
    fq = fastq_sample(target, max_reads) if target.exists() else {
        "sampled_reads": "", "sampled_bases": "", "mean_read_length": "",
        "min_read_length": "", "max_read_length": "", "mean_phred": "",
        "fastq_sample_status": "fail", "fastq_sample_reason": "missing file",
    }
    overall = "pass" if size_status == md5_status == fq["fastq_sample_status"] == "pass" else "fail"
    return {
        "batch": batch,
        "run_accession": row.get("run_accession", ""),
        "library_layout": row.get("library_layout", ""),
        "url": row.get("url", ""),
        "target": str(target),
        "expected_bytes": str(expected_size or ""),
        "observed_bytes": str(observed_size),
        "size_status": size_status,
        "expected_md5": expected_md5,
        "observed_md5": observed_md5,
        "md5_status": md5_status,
        **fq,
        "overall_status": overall,
    }


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("LITTLEDREAM_ROOT", ".")))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sample-reads", type=int, default=40000)
    parser.add_argument("--batch", choices=sorted(BATCHES), action="append",
                        help="Audit only the named batch; repeatable. Default: all batches.")
    args = parser.parse_args()
    root = args.root.resolve()

    jobs: list[tuple[str, dict[str, str]]] = []
    selected_batches = args.batch or list(BATCHES)
    for batch in selected_batches:
        relative = BATCHES[batch]
        manifest = root / relative / "logs" / "resolved_files.tsv"
        if not manifest.exists():
            jobs.append((batch, {"target": str(manifest), "run_accession": "MANIFEST_MISSING"}))
            continue
        with manifest.open(encoding="utf-8", newline="") as handle:
            jobs.extend((batch, row) for row in csv.DictReader(handle, delimiter="\t"))

    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(audit_one, batch, row, args.sample_reads) for batch, row in jobs]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: (row["batch"], row["run_accession"], row["target"]))
    write_tsv(root / "metadata" / "qc" / "download_integrity_and_fastq_qc.tsv", results)

    summary: list[dict[str, str]] = []
    for batch in selected_batches:
        subset = [row for row in results if row["batch"] == batch]
        passed = sum(row["overall_status"] == "pass" for row in subset)
        summary.append({
            "batch": batch,
            "requested_files": str(len(subset)),
            "passed_files": str(passed),
            "failed_files": str(len(subset) - passed),
            "observed_bytes": str(sum(int(row["observed_bytes"] or 0) for row in subset)),
            "status": "pass" if subset and passed == len(subset) else "fail",
        })
    write_tsv(root / "metadata" / "qc" / "download_qc_summary.tsv", summary)
    return 0 if results and all(row["overall_status"] == "pass" for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
