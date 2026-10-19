#!/usr/bin/env python3
"""Build auditable MAG trait and per-run abundance tables from shared bins."""
from __future__ import annotations

import os
import argparse
import csv
from collections import defaultdict
from pathlib import Path


N_RATE = {"SRR11128411": 0, "SRR11128414": 60, "SRR11128415": 120}


def fasta_records(path: Path):
    name = None
    chunks: list[str] = []
    with path.open(encoding="ascii") as handle:
        for line in handle:
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(chunks)
                name = line[1:].split()[0]
                chunks = []
            else:
                chunks.append(line.strip().upper())
    if name is not None:
        yield name, "".join(chunks)


def n50(lengths: list[int]) -> int:
    target = sum(lengths) / 2
    cumulative = 0
    for length in sorted(lengths, reverse=True):
        cumulative += length
        if cumulative >= target:
            return length
    return 0


def write_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("LITTLEDREAM_ROOT", ".")))
    parser.add_argument("--analysis-dir", default="tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered")
    args = parser.parse_args()
    root = args.root.resolve(); base = root / args.analysis_dir
    genomes = base / "drep" / "dereplicated_genomes"
    if not genomes.exists():
        raise SystemExit(f"Missing dereplicated genomes: {genomes}")

    contig_to_mag: dict[str, str] = {}
    traits: list[dict] = []
    for fasta in sorted(genomes.glob("*.fa*")):
        records = list(fasta_records(fasta)); lengths = [len(seq) for _, seq in records]
        sequence = "".join(seq for _, seq in records)
        mag_id = fasta.stem
        for contig, _ in records: contig_to_mag[contig] = mag_id
        traits.append({
            "study_id": "MAIZE_ENEBE_2020", "mag_id": mag_id,
            "genome_size_bp": len(sequence), "contig_count": len(records), "N50_bp": n50(lengths),
            "gc_fraction": (sequence.count("G") + sequence.count("C")) / len(sequence) if sequence else 0,
            "completeness": "", "contamination": "",
            "quality_status": "pending_CheckM2",
            "interpretation": "technical only; n=1 and NPK-confounded",
        })

    depth_path = base / "contig_depth.txt"
    with depth_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        headers = reader.fieldnames or []
        # jgi_summarize_bam_contig_depths derives sample names from the BAM
        # basename and strips the .bam suffix (for example
        # SRR11128411.sorted).  Exclude the paired variance columns.
        sample_cols = [
            h for h in headers
            if any(run in h for run in N_RATE) and not h.endswith("-var")
        ]
        if len(sample_cols) != len(N_RATE):
            raise SystemExit(
                f"Expected one depth column for each of {len(N_RATE)} runs; found {sample_cols}"
            )
        weighted = defaultdict(float); bp = defaultdict(int)
        for row in reader:
            mag = contig_to_mag.get(row["contigName"])
            if not mag: continue
            length = int(float(row["contigLen"]))
            for sample in sample_cols:
                weighted[(mag, sample)] += float(row[sample]) * length
                bp[(mag, sample)] += length

    run_depths = defaultdict(dict)
    for (mag, sample), total in weighted.items():
        run = next((run for run in N_RATE if run in sample), sample)
        run_depths[run][mag] = total / bp[(mag, sample)] if bp[(mag, sample)] else 0
    abundance: list[dict] = []
    for run, values in sorted(run_depths.items()):
        denom = sum(values.values())
        for mag, depth in sorted(values.items()):
            abundance.append({
                "study_id": "MAIZE_ENEBE_2020", "run_accession": run,
                "N_rate": N_RATE.get(run, ""), "mag_id": mag,
                "length_weighted_depth": depth,
                "relative_abundance": depth / denom if denom else 0,
                "detected_depth_ge_0_1": "yes" if depth >= 0.1 else "no",
                "interpretation": "technical only; one run per NPK treatment",
            })
    expected_pairs = len(N_RATE) * len(traits)
    if traits and len(abundance) != expected_pairs:
        raise SystemExit(
            f"Incomplete Run-by-MAG abundance grid: observed {len(abundance)}, expected {expected_pairs}"
        )
    out = root / "tmp" / "result" / "tables"
    write_tsv(out / "mag_traits.tsv", traits)
    write_tsv(out / "mag_abundance.tsv", abundance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
