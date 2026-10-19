#!/usr/bin/env python3
"""Join CheckM2 quality predictions into the final MAG trait table."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    report = root / "tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered/checkm2/quality_report.tsv"
    traits_path = root / "tmp/result/tables/mag_traits.tsv"
    quality_rows = read_tsv(report)
    traits = read_tsv(traits_path)
    quality = {}
    for row in quality_rows:
        name = row.get("Name", row.get("name", ""))
        quality[name] = row
        for suffix in (".fa", ".fna", ".fasta", ".gz"):
            if name.endswith(suffix):
                quality[name[: -len(suffix)]] = row
    for trait in traits:
        row = quality.get(trait.get("mag_id", ""), {})
        completeness = row.get("Completeness", row.get("completeness", ""))
        contamination = row.get("Contamination", row.get("contamination", ""))
        trait["completeness"] = completeness
        trait["contamination"] = contamination
        try:
            comp, contam = float(completeness), float(contamination)
            if comp >= 90 and contam <= 5:
                trait["quality_status"] = "high_quality_by_completeness_contamination_only"
            elif comp >= 50 and contam <= 10:
                trait["quality_status"] = "medium_quality"
            else:
                trait["quality_status"] = "low_quality"
        except ValueError:
            trait["quality_status"] = "CheckM2_value_missing"
        trait["checkm2_version"] = "1.1.0"
        trait["checkm2_database_doi"] = "10.5281/zenodo.14897628"
    headers = list(traits[0]) if traits else ["status"]
    with traits_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
        writer.writeheader(); writer.writerows(traits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
