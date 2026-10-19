#!/usr/bin/env python3
"""Add locked subgroup fields to the article master table without inventing values."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


SUBGROUP_FIELDS = [
    "latitude_band",
    "elevation_m",
    "soil_type_reported",
    "soil_classification_system",
    "soil_type_harmonized",
    "climate_type_reported",
    "koppen_geiger_class",
    "climate_zone_harmonized",
    "mean_annual_temperature_C",
    "mean_annual_precipitation_mm",
    "aridity_index",
    "irrigation_regime",
    "subgroup_covariate_status",
]


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--site-covariates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    headers, candidates = read_tsv(args.candidate)
    _, sites = read_tsv(args.site_covariates)
    site_by_study = {row["study_id"]: row for row in sites}

    for field in SUBGROUP_FIELDS:
        if field not in headers:
            insert_at = headers.index("longitude") + 1 + sum(
                prior in headers for prior in SUBGROUP_FIELDS[: SUBGROUP_FIELDS.index(field)]
            )
            headers.insert(insert_at, field)

    for candidate in candidates:
        site = site_by_study.get(candidate.get("study_id", ""), {})
        for field in SUBGROUP_FIELDS:
            if candidate.get(field, ""):
                continue
            source_field = "covariate_verification_status" if field == "subgroup_covariate_status" else field
            candidate[field] = site.get(source_field, "")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
