#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
from collections import defaultdict
from pathlib import Path

KO_GROUP = {
    "K02588": ("nitrogen_fixation", "nifH"),
    "K10944": ("nitrification", "amoA/pmoA"),
    "K10535": ("nitrification", "hao"),
    "K00370": ("nitrate_reduction", "narG"),
    "K02567": ("nitrate_reduction", "napA"),
    "K00368": ("denitrification", "nirK"),
    "K15864": ("denitrification", "nirS"),
    "K04561": ("denitrification", "norB"),
    "K00376": ("denitrification", "nosZ"),
    "K00362": ("assimilatory_nitrate_reduction", "nirB"),
    "K00363": ("assimilatory_nitrate_reduction", "nirD"),
    "K00372": ("assimilatory_nitrate_reduction", "nasA"),
    "K01915": ("ammonium_assimilation", "glnA"),
    "K00260": ("ammonium_assimilation", "gdhA"),
}
N_RATE = {"SRR11128411": 0, "SRR11128414": 60, "SRR11128415": 120}


def open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--analysis-dir", required=True)
    p.add_argument("--ko-list", type=Path, required=True)
    p.add_argument("--kofam-dir", type=Path, required=True)
    a = p.parse_args(); root = a.root.resolve(); base = root / a.analysis_dir

    thresholds = {}
    with open_text(a.ko_list) as h:
        reader = csv.DictReader(h, delimiter="\t")
        for row in reader:
            ko = row.get("knum", "")
            if ko in KO_GROUP and row.get("threshold") not in (None, "", "-"):
                thresholds[ko] = (float(row["threshold"]), row.get("score_type", "full"))

    if set(thresholds) != set(KO_GROUP):
        missing = sorted(set(KO_GROUP) - set(thresholds))
        raise SystemExit(f"Missing KOfam thresholds for targeted KOs: {missing}")

    # hmmsearch target names are the FASTA record identifiers emitted by
    # Prodigal (for example k141_429732_164).  The GFF `ID=349_164` attribute
    # is an unrelated internal identifier and cannot be used for the join.
    # Parse the Prodigal protein headers directly; their `# start # end #`
    # fields also provide the coding-sequence length in base pairs.
    gene_contig = {}; gene_len = {}
    with (a.kofam_dir / "proteins.faa").open() as h:
        for line in h:
            if not line.startswith(">"):
                continue
            fields = [part.strip() for part in line[1:].rstrip().split("#")]
            gene = fields[0].split()[0]
            if len(fields) < 3:
                raise SystemExit(f"Unrecognized Prodigal protein header: {line.rstrip()}")
            start, end = int(fields[1]), int(fields[2])
            if "_" not in gene:
                raise SystemExit(f"Cannot derive contig from Prodigal gene identifier: {gene}")
            gene_contig[gene] = gene.rsplit("_", 1)[0]
            gene_len[gene] = abs(end - start) + 1

    hits = []
    for ko, (threshold, score_type) in thresholds.items():
        with (a.kofam_dir / "tblout" / f"{ko}.tbl").open() as h:
            for line in h:
                if line.startswith("#") or not line.strip(): continue
                f = line.split(maxsplit=18)
                gene = f[0]; full_score = float(f[5]); domain_score = float(f[8])
                score = full_score if score_type == "full" else domain_score
                if score >= threshold and gene in gene_contig:
                    hits.append((gene, ko, score, threshold, gene_contig[gene], gene_len[gene]))
    best = {}
    for hit in hits:
        gene, ko, score, threshold, contig, length = hit
        normalized = score / threshold
        if gene not in best or normalized > best[gene][0]: best[gene] = (normalized, hit)
    hit_rows = []
    contig_function = defaultdict(list)
    for _, hit in best.values():
        gene, ko, score, threshold, contig, length = hit
        group, symbol = KO_GROUP[ko]
        hit_rows.append({"gene_id": gene, "contig": contig, "gene_length_bp": length,
                         "KO": ko, "gene_symbol": symbol, "function_group": group,
                         "score": score, "KOfam_threshold": threshold})
        contig_function[contig].append((group, length))

    depth = base / "contig_depth.txt"
    raw = defaultdict(float)
    with depth.open() as h:
        reader = csv.DictReader(h, delimiter="\t")
        sample_cols = [
            x for x in (reader.fieldnames or [])
            if any(run in x for run in N_RATE) and not x.endswith("-var")
        ]
        if len(sample_cols) != len(N_RATE):
            raise SystemExit(
                f"Expected one depth column for each of {len(N_RATE)} runs; found {sample_cols}"
            )
        for row in reader:
            funcs = contig_function.get(row["contigName"], [])
            for sample in sample_cols:
                run = next((r for r in N_RATE if r in sample), sample)
                for group, gene_bp in funcs: raw[(run, group)] += float(row[sample]) * gene_bp
    rows = []
    function_groups = sorted(set(KO_GROUP[k][0] for k in KO_GROUP))
    for run in sorted(N_RATE):
        denom = sum(value for (r, _), value in raw.items() if r == run)
        for group in function_groups:
            value = raw.get((run, group), 0.0)
            rows.append({"study_id": "MAIZE_ENEBE_2020", "run_accession": run,
                         "N_rate": N_RATE.get(run, ""), "function_group": group,
                         "depth_x_gene_bp": value, "relative_abundance": value / denom if denom else 0,
                         "replicate_n": 1, "confounded": "yes",
                         "screening_status": "qualified_hits_present" if hit_rows else "no_qualified_hits",
                         "interpretation": "technical only; targeted KOfam hits; no causal inference"})
    expected_function_rows = len(N_RATE) * len(function_groups)
    if len(rows) != expected_function_rows:
        raise SystemExit(
            f"Incomplete Run-by-function grid: observed {len(rows)}, expected {expected_function_rows}"
        )
    out = root / "tmp" / "result" / "tables"; out.mkdir(parents=True, exist_ok=True)
    outputs = [
        (out / "kofam_nitrogen_gene_hits.tsv", hit_rows,
         ["gene_id", "contig", "gene_length_bp", "KO", "gene_symbol", "function_group",
          "score", "KOfam_threshold"]),
        (out / "shotgun_function.tsv", rows,
         ["study_id", "run_accession", "N_rate", "function_group", "depth_x_gene_bp",
          "relative_abundance", "replicate_n", "confounded", "screening_status", "interpretation"]),
    ]
    for path, data, empty_headers in outputs:
        headers = list(data[0]) if data else empty_headers
        with path.open("w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, headers, delimiter="\t"); w.writeheader(); w.writerows(data)
    return 0


if __name__ == "__main__": raise SystemExit(main())
