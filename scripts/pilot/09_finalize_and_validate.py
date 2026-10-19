#!/usr/bin/env python3
"""Collect final Pilot tables, update run-level states, and emit auditable QA.

This script never edits raw FASTQ files or the hand-curated source metadata.
It writes final joined copies under tmp/result/tables and exits non-zero when a
required deliverable is missing or internally inconsistent.
"""
from __future__ import annotations

import os
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Iterable


EXPECTED_STUDIES = {
    "RICE_DONG_2021": 18,
    "MAIZE_MENG_2024": 36,
    "WHEAT_MA_2025": 48,
}
EXPECTED_QC_FILES = 192
EXPECTED_RUNS = 105
ARTICLE_SCHEMA_FIELDS = [
    "study_id", "doi", "title", "authors", "journal", "publication_year",
    "JIF", "JIF_year", "JIF_source", "IF_gt_8", "crop", "country", "site",
    "latitude", "longitude", "latitude_band", "elevation_m", "soil_type_reported",
    "soil_classification_system", "soil_type_harmonized", "climate_type_reported",
    "koppen_geiger_class", "climate_zone_harmonized", "mean_annual_temperature_C",
    "mean_annual_precipitation_mm", "aridity_index", "irrigation_regime",
    "subgroup_covariate_status", "field_experiment", "N_gradient_count", "contains_0N",
    "yield_available", "raw_16S_available", "raw_shotgun_available", "soil_compartment",
    "treatment_duration_years", "confounded", "core_class", "screening_status",
    "download_eligible", "evidence_sources", "verification_notes",
]
SITE_SCHEMA_FIELDS = [
    "study_id", "site_id", "country", "crop", "latitude", "longitude", "latitude_band",
    "elevation_m", "soil_type_reported", "soil_classification_system",
    "soil_type_harmonized", "pH", "SOC", "TN", "climate_type_reported",
    "koppen_geiger_class", "climate_zone_harmonized", "mean_annual_temperature_C",
    "mean_annual_precipitation_mm", "aridity_index", "irrigation_regime",
    "covariate_verification_status", "evidence_source", "notes",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_headers(path: Path) -> list[str]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t").fieldnames or [])


def read_key_value_tsv(path: Path) -> dict[str, str]:
    """Read two-column vertical audit/status files with or without a header."""
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.reader(handle, delimiter="\t") if len(row) >= 2]
    if rows and rows[0][0].lower() in {"field", "key"}:
        rows = rows[1:]
    return {row[0]: row[1] for row in rows}


def write_tsv(path: Path, rows: Iterable[dict[str, object]], headers: list[str] | None = None) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if headers is None:
        headers = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def status_row(check: str, observed: object, expected: object, passed: bool, evidence: Path, note: str = "") -> dict[str, object]:
    return {
        "check": check,
        "observed": observed,
        "expected": expected,
        "status": "pass" if passed else "fail",
        "evidence": str(evidence),
        "note": note,
    }


def as_float(value: str | None) -> float:
    try:
        return float(value or "")
    except ValueError:
        return float("nan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("LITTLEDREAM_ROOT", ".")))
    args = parser.parse_args()
    root = args.root.resolve()
    tables = root / "tmp" / "result" / "tables"
    figures = root / "tmp" / "result" / "\u53ef\u89c6\u5316result"
    checks: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []

    articles_path = root / "metadata" / "candidate_studies.tsv"
    articles = read_tsv(articles_path)
    article_headers = read_headers(articles_path)
    missing_article_schema = sorted(set(ARTICLE_SCHEMA_FIELDS) - set(article_headers))
    checks.append(status_row(
        "candidate_article_locked_schema", ";".join(missing_article_schema) or "complete",
        "complete", not missing_article_schema, articles_path,
        "Includes article identity, evidence, Core eligibility, and locked soil/climate/geographic subgroup fields.",
    ))
    required_article_fields = [
        "study_id", "doi", "title", "authors", "journal", "publication_year",
        "article_url", "discovery_source", "access_date", "crop", "screening_status",
    ]
    missing_core_fields = sum(
        not str(row.get(field, "")).strip() for row in articles for field in required_article_fields
    )
    duplicate_study_ids = len(articles) - len({row.get("study_id", "") for row in articles})
    duplicate_dois = len(articles) - len({row.get("doi", "").lower() for row in articles})
    checks.append(status_row("candidate_article_count", len(articles), 28, len(articles) == 28, articles_path))
    checks.append(status_row("candidate_article_required_field_missing_cells", missing_core_fields, 0,
                             missing_core_fields == 0, articles_path))
    checks.append(status_row("candidate_article_duplicate_study_ids", duplicate_study_ids, 0,
                             duplicate_study_ids == 0, articles_path))
    checks.append(status_row("candidate_article_duplicate_dois", duplicate_dois, 0,
                             duplicate_dois == 0, articles_path))
    selected = [row for row in articles if row.get("download_eligible") == "yes"]
    selected_fields = ["BioProject", "verified_accessions", "sample_treatment_mapping_status", "evidence_sources"]
    selected_missing = sum(not str(row.get(field, "")).strip() for row in selected for field in selected_fields)
    checks.append(status_row("deep_audited_download_study_count", len(selected), 4, len(selected) == 4, articles_path))
    checks.append(status_row("deep_audited_required_field_missing_cells", selected_missing, 0,
                             selected_missing == 0, articles_path))

    site_path = root / "metadata" / "site_covariates.tsv"
    site_rows = read_tsv(site_path)
    site_headers = read_headers(site_path)
    missing_site_schema = sorted(set(SITE_SCHEMA_FIELDS) - set(site_headers))
    checks.append(status_row("site_covariate_row_count", len(site_rows), 4,
                             len(site_rows) == 4, site_path))
    checks.append(status_row(
        "site_covariate_locked_schema", ";".join(missing_site_schema) or "complete",
        "complete", not missing_site_schema, site_path,
        "Blank subgroup values are allowed only when verification status and evidence source are explicit.",
    ))
    site_status_missing = sum(
        not row.get("covariate_verification_status", "").strip()
        or not row.get("evidence_source", "").strip() for row in site_rows
    )
    checks.append(status_row("site_covariate_status_or_source_missing", site_status_missing, 0,
                             site_status_missing == 0, site_path))

    treatment_path = root / "metadata" / "treatments.tsv"
    treatments = read_tsv(treatment_path)
    checks.append(status_row("treatment_row_count", len(treatments), 16,
                             len(treatments) == 16, treatment_path))
    treatment_keys = {(row.get("study_id", ""), row.get("treatment_id", "")) for row in treatments}
    checks.append(status_row("treatment_unique_study_treatment_keys", len(treatment_keys), len(treatments),
                             len(treatment_keys) == len(treatments), treatment_path))
    accession_path = root / "metadata" / "accession_audit.tsv"
    checks.append(status_row("deep_accession_audit_study_count", len(read_tsv(accession_path)), 4,
                             len(read_tsv(accession_path)) == 4, accession_path))
    jif_path = root / "metadata" / "jif_verification.tsv"
    checks.append(status_row("JIF_audit_row_count", len(read_tsv(jif_path)), 28,
                             len(read_tsv(jif_path)) == 28, jif_path,
                             "All rows remain JIF_unverified without authenticated Clarivate JCR access."))

    runs_path = root / "metadata" / "sequencing_runs.tsv"
    runs = read_tsv(runs_path)
    unique_runs = {row.get("Run_accession", "") for row in runs if row.get("Run_accession")}
    checks.append(status_row("sequencing_run_count", len(unique_runs), EXPECTED_RUNS,
                             len(unique_runs) == EXPECTED_RUNS, runs_path))
    required_run_fields = [
        "study_id", "site_id", "season_id", "treatment_id", "sample_id", "soil_compartment",
        "sequencing_type", "platform", "BioProject", "BioSample", "Run_accession",
        "mapping_status", "accession_status", "download_eligible", "evidence_source",
    ]
    run_required_missing = sum(
        not str(row.get(field, "")).strip() for row in runs for field in required_run_fields
    )
    checks.append(status_row("sequencing_run_required_field_missing_cells", run_required_missing, 0,
                             run_required_missing == 0, runs_path))
    orphan_runs = [
        row.get("Run_accession", "") for row in runs
        if (row.get("study_id", ""), row.get("treatment_id", "")) not in treatment_keys
    ]
    checks.append(status_row("sequencing_run_orphan_treatment_links", len(orphan_runs), 0,
                             not orphan_runs, runs_path,
                             ";".join(orphan_runs[:10])))

    qc_path = root / "metadata" / "qc" / "download_integrity_and_fastq_qc.tsv"
    qc = read_tsv(qc_path)
    qc_pass = [row for row in qc if row.get("overall_status") == "pass"]
    checks.append(status_row("downloaded_fastq_file_count", len(qc), EXPECTED_QC_FILES,
                             len(qc) == EXPECTED_QC_FILES, qc_path))
    checks.append(status_row("downloaded_fastq_all_integrity_pass", len(qc_pass), EXPECTED_QC_FILES,
                             len(qc_pass) == EXPECTED_QC_FILES, qc_path))
    qc_by_run: dict[str, list[dict[str, str]]] = {}
    for row in qc:
        qc_by_run.setdefault(row.get("run_accession", ""), []).append(row)
    checks.append(status_row("download_qc_run_coverage", len(qc_by_run), EXPECTED_RUNS,
                             len(qc_by_run) == EXPECTED_RUNS, qc_path))
    batch_counts = Counter(row.get("batch", "") for row in qc)
    for batch, expected in {"core_a_rice": 18, "technical_amplicon": 168, "mag_technical": 6}.items():
        checks.append(status_row(f"qc_file_count_{batch}", batch_counts.get(batch, 0), expected,
                                 batch_counts.get(batch, 0) == expected, qc_path))

    # Generate the large-file inventory directly from the independently verified
    # FASTQ audit and the locked run metadata.  This records the sole physical
    # copy instead of duplicating multi-GB raw data into tmp.
    runs_by_accession = {row.get("Run_accession", ""): row for row in runs}
    inventory_path = root / "tmp" / "raw_data_inventory.tsv"
    inventory_rows: list[dict[str, object]] = []
    for file_row in qc:
        run_accession = file_row.get("run_accession", "")
        run_row = runs_by_accession.get(run_accession, {})
        inventory_rows.append({
            "study_id": run_row.get("study_id", ""),
            "run_accession": run_accession,
            "treatment_id": run_row.get("treatment_id", ""),
            "sample_id": run_row.get("sample_id", ""),
            "data_type": run_row.get("sequencing_type", ""),
            "file_path": file_row.get("target", ""),
            "size_bytes": file_row.get("observed_bytes", ""),
            "expected_md5": file_row.get("expected_md5", ""),
            "observed_md5": file_row.get("observed_md5", ""),
            "integrity_status": file_row.get("overall_status", ""),
            "single_physical_copy": "yes",
            "batch": file_row.get("batch", ""),
            "evidence_source": str(qc_path),
        })
    write_tsv(inventory_path, inventory_rows)
    inventory = read_tsv(inventory_path)
    inventory_runs = {row.get("run_accession", "") for row in inventory if row.get("run_accession")}
    checks.append(status_row("raw_data_inventory_run_coverage", len(inventory_runs), EXPECTED_RUNS,
                             len(inventory_runs) == EXPECTED_RUNS, inventory_path,
                             "Large raw data are single-copy and tracked by path/checksum rather than duplicated into tmp."))

    tracking_all: list[dict[str, object]] = []
    tracking_by_sample: dict[tuple[str, str], dict[str, object]] = {}
    for study, expected in EXPECTED_STUDIES.items():
        study_dir = root / "tmp" / "analysis" / "amplicon" / study
        status_path = study_dir / "STATUS"
        status = status_path.read_text(encoding="utf-8").splitlines()[0].strip() if status_path.is_file() else "missing"
        checks.append(status_row(f"dada2_status_{study}", status, "pass", status == "pass", status_path))
        rows = read_tsv(study_dir / "read_tracking.tsv")
        checks.append(status_row(f"dada2_sample_count_{study}", len(rows), expected,
                                 len(rows) == expected, study_dir / "read_tracking.tsv"))
        for row in rows:
            input_reads = as_float(row.get("input"))
            nonchim = as_float(row.get("nonchim"))
            retention = nonchim / input_reads if input_reads > 0 else float("nan")
            item: dict[str, object] = {
                "study_id": study,
                **row,
                "read_retention_fraction": retention,
                "read_qc_status": "pass" if nonchim >= 1000 and retention >= 0.10 else "caution_low_retention_or_depth",
            }
            tracking_all.append(item)
            tracking_by_sample[(study, row.get("sample_id", ""))] = item
    write_tsv(tables / "dada2_tracking_all.tsv", tracking_all)

    final_runs: list[dict[str, object]] = []
    for row in runs:
        run = row.get("Run_accession", "")
        file_rows = qc_by_run.get(run, [])
        all_file_pass = bool(file_rows) and all(x.get("overall_status") == "pass" for x in file_rows)
        row = dict(row)
        row["download_status"] = "downloaded_verified" if all_file_pass else "missing_or_failed"
        row["integrity_status"] = "pass" if all_file_pass else "fail"
        if row.get("sequencing_type") == "16S":
            track = tracking_by_sample.get((row.get("study_id", ""), row.get("sample_id", "")))
            row["read_qc_status"] = str(track.get("read_qc_status")) if track else "missing_dada2_tracking"
            row["analysis_status"] = "dada2_pass" if track else "analysis_missing"
        else:
            fastp = root / "tmp" / "analysis" / "mag" / "MAIZE_ENEBE_2020" / "fastp" / f"{run}.json"
            if fastp.is_file():
                payload = json.loads(fastp.read_text(encoding="utf-8"))
                before = payload.get("summary", {}).get("before_filtering", {}).get("total_reads", 0)
                after = payload.get("summary", {}).get("after_filtering", {}).get("total_reads", 0)
                row["read_qc_status"] = "pass" if before and after / before >= 0.80 else "caution_fastp_retention_lt_0.80"
                row["analysis_status"] = "fastp_pass" if before and after else "analysis_missing"
            else:
                row["read_qc_status"] = "missing_fastp_report"
                row["analysis_status"] = "analysis_missing"
        final_runs.append(row)
    run_headers = list(runs[0]) if runs else []
    for field in ["download_status", "integrity_status", "read_qc_status", "analysis_status"]:
        if field not in run_headers:
            run_headers.append(field)
    write_tsv(tables / "sequencing_runs_final.tsv", final_runs, run_headers)
    checks.append(status_row("final_run_join_count", len(final_runs), EXPECTED_RUNS,
                             len(final_runs) == EXPECTED_RUNS, tables / "sequencing_runs_final.tsv"))

    required_tables = [
        "taxonomy_filter_summary.tsv", "taxonomic_composition.tsv", "alpha_diversity.tsv",
        "bray_pcoa.tsv", "zeroN_departure.tsv", "raup_crick_zeroN.tsv", "permanova.tsv",
        "permdisp.tsv", "rice_2020_yield_summary.tsv", "rice_2020_yield_curve.tsv",
    ]
    for name in required_tables:
        path = tables / name
        checks.append(status_row(f"required_table_{name}", path.stat().st_size if path.is_file() else 0,
                                 ">0 bytes", path.is_file() and path.stat().st_size > 0, path))

    taxonomy_path = tables / "taxonomy_filter_summary.tsv"
    taxonomy_rows = read_tsv(taxonomy_path)
    taxonomy_studies = {row.get("study_id", "") for row in taxonomy_rows if row.get("study_id")}
    checks.append(status_row("taxonomy_summary_study_coverage", len(taxonomy_studies), 3,
                             taxonomy_studies == set(EXPECTED_STUDIES), taxonomy_path))
    taxonomy_zero_retained = []
    for row in taxonomy_rows:
        retained_asv = as_float(row.get("retained_asv"))
        retained_reads = as_float(row.get("retained_reads"))
        if (not math.isfinite(retained_asv) or not math.isfinite(retained_reads)
                or retained_asv <= 0 or retained_reads <= 0):
            taxonomy_zero_retained.append(row.get("study_id", ""))
    checks.append(status_row("taxonomy_nonzero_retained_ASVs_and_reads", len(taxonomy_zero_retained), 0,
                             not taxonomy_zero_retained, taxonomy_path,
                             ";".join(taxonomy_zero_retained)))

    composition_path = tables / "taxonomic_composition.tsv"
    composition_rows = read_tsv(composition_path)
    composition_sums: dict[tuple[str, str], float] = {}
    for row in composition_rows:
        key = (row.get("study_id", ""), row.get("sample_id", ""))
        composition_sums[key] = composition_sums.get(key, 0.0) + as_float(row.get("relative_abundance"))
    bad_composition_closure = [
        "||".join(key) for key, value in composition_sums.items()
        if not (0.999999 <= value <= 1.000001)
    ]
    checks.append(status_row("taxonomic_composition_sample_coverage", len(composition_sums), 102,
                             len(composition_sums) == 102, composition_path,
                             "Taxonomy filtering must not silently drop a sample."))
    checks.append(status_row("taxonomic_composition_relative_abundance_closure",
                             len(bad_composition_closure), 0, not bad_composition_closure,
                             composition_path, ";".join(bad_composition_closure[:10])))

    alpha_path = tables / "alpha_diversity.tsv"
    alpha_rows = read_tsv(alpha_path)
    alpha_counts = Counter(row.get("study_id", "") for row in alpha_rows)
    for study, expected in EXPECTED_STUDIES.items():
        checks.append(status_row(f"alpha_sample_count_{study}", alpha_counts.get(study, 0), expected,
                                 alpha_counts.get(study, 0) == expected, alpha_path,
                                 "No sample may disappear after taxonomy filtering without an explicit failure."))

    permanova_path = tables / "permanova.tsv"
    permanova_rows = read_tsv(permanova_path)
    primary_permanova_studies = {
        row.get("study_id", "") for row in permanova_rows
        if row.get("analysis_set") == "all_samples"
        and row.get("model_role") == "primary_N_effect_adjusted_for_stratum"
        and row.get("term") == "N_factor"
    }
    permanova_errors = [row for row in permanova_rows if row.get("term") == "ERROR"]
    checks.append(status_row("permanova_primary_N_study_coverage", len(primary_permanova_studies), 3,
                             primary_permanova_studies == set(EXPECTED_STUDIES), permanova_path,
                             "Primary N effects are separate from direct N-by-stratum interaction rows."))
    checks.append(status_row("permanova_error_rows", len(permanova_errors), 0,
                             not permanova_errors, permanova_path))

    permdisp_path = tables / "permdisp.tsv"
    permdisp_rows = read_tsv(permdisp_path)
    primary_permdisp_studies = {
        row.get("study_id", "") for row in permdisp_rows
        if row.get("analysis_set") == "all_samples"
        and row.get("model_role") == "overall_N_dispersion"
        and row.get("stratum_id") == "all"
    }
    checks.append(status_row("permdisp_overall_N_study_coverage", len(primary_permdisp_studies), 3,
                             primary_permdisp_studies == set(EXPECTED_STUDIES), permdisp_path,
                             "Subgroup and QC-sensitivity dispersion rows are retained alongside the overall diagnostic."))

    joint_path = tables / "rice_joint_yield_microbiome.tsv"
    joint_rows = read_tsv(joint_path)
    joint_rates = {row.get("N_rate", "") for row in joint_rows}
    checks.append(status_row("rice_joint_same_season_rows", len(joint_rows), 6,
                             len(joint_rows) == 6 and joint_rates == {"0", "150", "300"}, joint_path))

    host_summary = root / "tmp" / "analysis" / "mag" / "MAIZE_ENEBE_2020" / "host_depleted" / "host_depletion_summary.tsv"
    host_rows = read_tsv(host_summary)
    checks.append(status_row("host_depletion_run_count", len(host_rows), 3, len(host_rows) == 3, host_summary))
    mag_base = root / "tmp" / "analysis" / "mag" / "MAIZE_ENEBE_2020_host_filtered"
    mag_status = mag_base / "MAG_TECHNICAL_STATUS.tsv"
    checks.append(status_row("formal_host_filtered_mag_status", mag_status.stat().st_size if mag_status.is_file() else 0,
                             ">0 bytes", mag_status.is_file() and mag_status.stat().st_size > 0, mag_status))
    for name in ["mag_traits.tsv", "mag_abundance.tsv", "kofam_nitrogen_gene_hits.tsv", "shotgun_function.tsv"]:
        path = tables / name
        # Empty hit tables are scientifically valid, but the file and header must exist.
        checks.append(status_row(f"mag_table_{name}", path.stat().st_size if path.is_file() else 0,
                                 ">0 bytes", path.is_file() and path.stat().st_size > 0, path))

    mag_state = read_key_value_tsv(mag_status)
    no_bins = mag_state.get("status") == "no_bins_recovered"
    checkm2_status_path = mag_base / "CHECKM2_STATUS.tsv"
    checkm2_state = read_key_value_tsv(checkm2_status_path)
    expected_checkm2_status = "no_bins_recovered" if no_bins else "pass"
    checks.append(status_row(
        "checkm2_explicit_final_status", checkm2_state.get("status", "missing"),
        expected_checkm2_status, checkm2_state.get("status") == expected_checkm2_status,
        checkm2_status_path,
        "No-bin runs are valid only when explicit; recovered bins require a CheckM2 pass.",
    ))
    checkm2_audit = root / "metadata" / "checkm2_database_audit.tsv"
    audit_state = read_key_value_tsv(checkm2_audit)
    audit_ok = no_bins or (
        audit_state.get("version") == "1.1.0"
        and audit_state.get("database_doi") == "10.5281/zenodo.14897628"
        and bool(audit_state.get("database_md5"))
    )
    checks.append(status_row(
        "checkm2_database_audit",
        "no_bins_not_applicable" if no_bins else audit_state.get("database_doi", "missing"),
        "no_bins_not_applicable or 10.5281/zenodo.14897628", audit_ok, checkm2_audit,
    ))
    if not no_bins:
        mag_traits = read_tsv(tables / "mag_traits.tsv")
        mag_abundance = read_tsv(tables / "mag_abundance.tsv")
        quality_rows = [
            row for row in mag_traits
            if row.get("quality_status") not in {"", "pending_CheckM2", "CheckM2_value_missing"}
        ]
        checks.append(status_row(
            "checkm2_quality_joined_to_all_mags", len(quality_rows), len(mag_traits),
            bool(mag_traits) and len(quality_rows) == len(mag_traits), tables / "mag_traits.tsv",
        ))
        trait_ids = {row.get("mag_id", "") for row in mag_traits if row.get("mag_id")}
        abundance_ids = {row.get("mag_id", "") for row in mag_abundance if row.get("mag_id")}
        abundance_runs = {row.get("run_accession", "") for row in mag_abundance if row.get("run_accession")}
        expected_abundance_rows = len(trait_ids) * 3
        checks.append(status_row(
            "mag_abundance_complete_run_by_mag_grid", len(mag_abundance), expected_abundance_rows,
            bool(trait_ids) and len(mag_abundance) == expected_abundance_rows
            and abundance_ids == trait_ids and len(abundance_runs) == 3,
            tables / "mag_abundance.tsv",
            f"runs={sorted(abundance_runs)}; trait_MAGs={len(trait_ids)}; abundance_MAGs={len(abundance_ids)}",
        ))

    required_figures = [
        "Figure_1_N_rate_vs_relative_yield.png",
        "Figure_2_N_rate_vs_microbiome_departure.png",
        "Figure_3_N_rate_vs_community_assembly.png",
        "Figure_4_N_rate_vs_shotgun_function.png",
        "Figure_5_N_rate_vs_MAG_trait_abundance.png",
    ]
    for name in required_figures:
        stem = Path(name).stem
        for suffix in [".png", ".pdf", ".svg"]:
            expected_name = stem + suffix
            matches = list(figures.rglob(expected_name)) if figures.exists() else []
            size = sum(p.stat().st_size for p in matches)
            checks.append(status_row(
                f"required_figure_{expected_name}", size, ">0 bytes",
                bool(matches) and size > 0, matches[0] if matches else figures / expected_name,
                "Each diagnostic figure is delivered as 600-dpi PNG plus PDF and editable SVG.",
            ))

    report_paths = {
        "full_problem_report": root / "tmp" / "result" / "全过程疑似问题与报错报告.md",
        "expansion_decision_report": root / "tmp" / "result" / "项目可行性与扩展决策报告.md",
        "goalmode_feasibility_report": root / "results" / "feasibility" / "feasibility_report.md",
        "small_dataset_report": root / "tmp" / "result" / "reports" / "小数据集分析报告.md",
        "analysis_design_report": root / "tmp" / "result" / "reports" / "实验设计_全样本到亚组分析框架.md",
        "reproducibility_handoff": root / "tmp" / "result" / "reports" / "交付清单与复现说明.md",
    }
    for key, path in report_paths.items():
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        checks.append(status_row(f"report_{key}", len(content.encode("utf-8")), ">0 bytes",
                                 bool(content.strip()), path))
        checks.append(status_row(f"report_{key}_placeholder_tokens", content.count("FINAL_"), 0,
                                 "FINAL_" not in content, path))

    decision_path = report_paths["expansion_decision_report"]
    decision_text = decision_path.read_text(encoding="utf-8") if decision_path.is_file() else ""
    decision_lines = [
        line[2:].strip() for line in decision_text.splitlines()
        if line in {"# GO", "# GO_WITH_MODIFICATIONS", "# NO_GO"}
    ]
    checks.append(status_row("single_final_GO_decision", ";".join(decision_lines) or "missing",
                             "exactly one of GO/GO_WITH_MODIFICATIONS/NO_GO", len(decision_lines) == 1,
                             decision_path))

    issue_path = root / "metadata" / "issue_log.tsv"
    issue_rows = read_tsv(issue_path)
    in_progress_issues = [row.get("issue_id", "") for row in issue_rows if row.get("status") == "in_progress"]
    checks.append(status_row("issue_log_minimum_coverage", len(issue_rows), ">=20",
                             len(issue_rows) >= 20, issue_path))
    checks.append(status_row("issue_log_in_progress_rows", len(in_progress_issues), 0,
                             not in_progress_issues, issue_path, ";".join(in_progress_issues)))

    record_paths = {
        "current_work_record": root / "当前目录工作记录.md",
        "experiment_record": root / "实验记录.md",
        "result_workflow": root / "tmp" / "result" / "result_workflow.md",
        "minimal_workflow": root / "tmp" / "最简工作流.md",
    }
    stale_markers = ["当前尚无实际分析结果", "尚未执行数据过滤", "尚未下载FASTQ"]
    for key, path in record_paths.items():
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        stale = [marker for marker in stale_markers if marker in content]
        checks.append(status_row(f"record_{key}", len(content.encode("utf-8")), ">0 bytes",
                                 bool(content.strip()) and not stale, path, ";".join(stale)))
    malformed_root_records = [path.name for path in root.glob("*.md") if "?" in path.name]
    checks.append(status_row("malformed_question_mark_record_names", len(malformed_root_records), 0,
                             not malformed_root_records, root, ";".join(malformed_root_records)))

    # The user requested the small, reproducible outputs to be organized by
    # numbered analytical step while explicitly exempting multi-GB raw data
    # from the copy-on-work convention.
    step_names = [
        "Step1文献与数据审计",
        "Step2原始数据质控",
        "Step3微生物扩增子分析",
        "Step4产量与联合响应分析",
        "Step5Shotgun与MAG技术试验",
        "Step6综合报告与交付QA",
    ]
    for step_name in step_names:
        step_path = root / "tmp" / "result" / step_name
        step_files = [path for path in step_path.rglob("*") if path.is_file()] if step_path.is_dir() else []
        checks.append(status_row(
            f"result_archive_{step_name}", len(step_files), ">=1 file",
            bool(step_files), step_path,
            "Step archive contains only small results/scripts/reports; raw/reference/assembly data remain single-copy.",
        ))
    result_raw_like = [
        str(path) for path in (root / "tmp" / "result").rglob("*")
        if path.is_file() and path.suffix.lower() in {".fastq", ".fq", ".bam", ".sam"}
    ]
    checks.append(status_row(
        "result_archive_excludes_large_raw_alignment_files", len(result_raw_like), 0,
        not result_raw_like, root / "tmp" / "result", ";".join(result_raw_like[:10]),
    ))

    workbook_path = root / "tmp" / "result" / "全球农田氮肥_产量_微生物组_Pilot_全部文章与数据审计总表.xlsx"
    workbook_present = workbook_path.is_file() and workbook_path.stat().st_size > 0
    checks.append(status_row("final_audit_workbook", "present" if workbook_present else "missing",
                             "present", workbook_present,
                             workbook_path))

    changelog_path = root / "tools" / "metagenome_downloader" / "PROJECT_CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    checks.append(status_row("downloader_change_log", len(changelog_text.encode("utf-8")), ">0 bytes",
                             bool(changelog_text.strip()) and "allowlist" in changelog_text.lower(),
                             changelog_path, "Downloader fixes and tests must remain auditable."))

    for key, value in [
        ("candidate_articles", len(articles)),
        ("deep_audited_studies", 4),
        ("core_A_studies", 1),
        ("core_B_studies", 0),
        ("core_AB_studies", 0),
        ("sequencing_runs", len(unique_runs)),
        ("fastq_files_integrity_pass", len(qc_pass)),
        ("dada2_samples", len(tracking_all)),
        ("wheat_low_retention_samples", sum(x.get("read_qc_status") != "pass" and x.get("study_id") == "WHEAT_MA_2025" for x in tracking_all)),
    ]:
        summary.append({"metric": key, "value": value})
    write_tsv(tables / "pipeline_summary.tsv", summary)
    write_tsv(tables / "final_output_validation.tsv", checks)

    # Keep the Step6 evidence copy byte-equivalent to the validation just
    # emitted here, rather than the previous finalizer pass.
    step6_tables = (
        root / "tmp" / "result" / "Step6综合报告与交付QA"
        / "1.报告图件与机器校验"
    )
    if step6_tables.is_dir():
        write_tsv(step6_tables / "pipeline_summary.tsv", summary)
        write_tsv(step6_tables / "final_output_validation.tsv", checks)

    failures = [row for row in checks if row["status"] == "fail"]
    print(json.dumps({"checks": len(checks), "failures": len(failures), "failed_checks": [x["check"] for x in failures]}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
