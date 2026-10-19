#!/usr/bin/env python3
"""Correct discovery-stage audit labels for the four processed Pilot studies.

Only audit-status/evidence fields are changed.  Eligibility, treatment, Run,
and analytical fields are preserved exactly.  The Chinese alias is rewritten
from the canonical table so the two article-list files remain byte-identical.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


AUDITED = {
    "RICE_DONG_2021": "PRJNA725973",
    "MAIZE_MENG_2024": "PRJNA1142092",
    "WHEAT_MA_2025": "PRJNA638680",
    "MAIZE_ENEBE_2020": "PRJNA607213",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-dir", type=Path, required=True)
    args = parser.parse_args()
    metadata = args.metadata_dir.resolve()
    canonical = metadata / "candidate_studies.tsv"
    alias = metadata / "全部文章信息总表.tsv"
    if not canonical.is_file():
        raise SystemExit(f"Missing canonical article table: {canonical}")

    with canonical.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    required = {"study_id", "download_eligible", "full_text_status", "supplement_status", "evidence_sources"}
    missing = required - set(headers)
    if missing:
        raise SystemExit(f"Missing fields: {sorted(missing)}")
    if len(rows) != 28 or len({row["study_id"] for row in rows}) != 28:
        raise SystemExit("Refusing to edit: expected 28 unique article rows")

    found: set[str] = set()
    for row in rows:
        study = row["study_id"]
        if study not in AUDITED:
            continue
        if row.get("download_eligible") != "yes":
            raise SystemExit(f"Audited study is not download-eligible: {study}")
        found.add(study)
        row["full_text_status"] = "pilot_eligibility_audited"
        row["supplement_status"] = "pilot_mapping_evidence_audited"
        project = AUDITED[study]
        sources = [item for item in row.get("evidence_sources", "").split(";") if item]
        for source in [f"https://www.ncbi.nlm.nih.gov/bioproject/{project}", "metadata/accession_audit.tsv"]:
            if source not in sources:
                sources.append(source)
        row["evidence_sources"] = ";".join(sources)
    if found != set(AUDITED):
        raise SystemExit(f"Missing audited studies: {sorted(set(AUDITED) - found)}")

    for path in [canonical, alias]:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    jif_headers = [
        "study_id", "journal", "publication_year", "JIF", "JIF_year", "JIF_source",
        "IF_gt_8", "verification_status", "verification_date", "source_url", "notes",
    ]
    jif_rows = []
    for row in rows:
        jif_rows.append({
            "study_id": row["study_id"],
            "journal": row.get("journal", ""),
            "publication_year": row.get("publication_year", ""),
            "JIF": "JIF_unverified",
            "JIF_year": "",
            "JIF_source": "No authenticated Clarivate JCR access in pilot environment",
            "IF_gt_8": "JIF_unverified",
            "verification_status": "not_verified_no_authenticated_JCR_access",
            "verification_date": "2026-08-13",
            "source_url": "",
            "notes": "Do not guess or substitute third-party estimates; IF>8 sensitivity analysis is unavailable.",
        })
    jif_path = metadata / "jif_verification.tsv"
    with jif_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=jif_headers, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(jif_rows)
    print(f"updated={len(found)} rows={len(rows)} alias_synchronized=yes jif_audit_rows={len(jif_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
