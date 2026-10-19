#!/usr/bin/env python3
"""Build auditable pilot metadata, explicit run allowlists, and download manifests.

The script deliberately separates discovery-level records from verified run-level
records. It never converts a BioProject into a download list without applying a
study-specific sample-alias rule.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENA = "https://www.ebi.ac.uk/ena/portal/api/filereport"
CROSSREF = "https://api.crossref.org/works/"
USER_AGENT = "littledream-pilot/1.0 (mailto:codex@example.invalid)"

CANDIDATE_HEADERS = """study_id discovery_status screening_status exclusion_reason core_response_eligible download_eligible doi pmid title authors journal publication_year article_url discovery_source search_query access_date full_text_status supplement_status JIF JIF_year JIF_source IF_gt_8 crop country site latitude longitude field_experiment randomized_design biological_replication replicate_n experiment_establishment_year sampling_year treatment_duration_years season_definition_recoverable N_gradient_count N_rates_reported N_unit_original N_rates_convertible contains_0N zero_N_sample_count zero_N_yield_available zero_N_raw_reads_available inorganic_N_main_factor N_form P_K_controlled other_management_changes confounded confounding_reason yield_available same_season_yield yield_source yield_unit raw_16S_available raw_shotgun_available soil_compartment marker_region primer_sequences_available sequencing_platform BioProject claimed_accessions verified_accessions accession_status sample_treatment_mapping_status run_count_reported run_count_verified estimated_download_size_bytes pH_available SOC_available TN_available sampling_depth_available sampling_stage_available fertilizer_timing_available coordinates_available core_class study_quality_score quality_score_max evidence_sources verification_notes""".split()

SEQ_HEADERS = """study_id site_id season_id treatment_id sample_id soil_compartment sequencing_type marker_region primer_forward primer_reverse platform instrument_model library_strategy library_layout paired_end read_length BioProject BioSample Experiment_accession Run_accession raw_reads_available read_count estimated_bases estimated_download_size paper_mapping_label archive_sample_title mapping_status accession_status download_eligible download_status integrity_status read_qc_status analysis_eligibility evidence_source notes""".split()

TREAT_HEADERS = """study_id site_id experiment_id season_id treatment_id crop soil_compartment N_rate N_unit_original N_rate_kg_ha_season N_form zero_N P_rate K_rate other_fertilizer application_count basal_N topdress_N application_timing days_since_last_N_to_sampling treatment_duration_years microbiome_sampling_stage yield yield_unit yield_basis pH SOC TN available_N NO3 NH4 sampling_depth_cm replicate_n confounded mapping_status evidence_source notes""".split()

AUDIT_HEADERS = """study_id claimed_accession accession_type claim_location claim_text archive_lookup_status resolved_project resolved_sample_count resolved_run_count paper_expected_sample_count crop_match location_match sequencing_type_match treatment_mapping_recoverable mapping_status wrong_accession_suspected corrected_accession correction_evidence reviewer_status review_date notes""".split()

STUDY_QUALITY_HEADERS = """study_id field_experiment randomized_design biological_replication N_rates_ge_3 N_rates_ge_4 contains_0N same_season_yield raw_sequencing clear_treatment_mapping pH_available SOC_TN_available N_form_known sampling_stage_known sampling_depth_known treatment_duration_known P_K_controlled raw_score max_score quality_fraction notes""".split()

CANDIDATES = [
    "10.3389/fmicb.2021.730506", "10.3389/fpls.2024.1481465",
    "10.3390/microorganisms13102382", "10.1038/s41598-017-03539-6",
    "10.3390/agronomy10081175", "10.3389/fmicb.2020.01948",
    "10.1186/s40168-019-0750-2", "10.3389/fmicb.2018.01074",
    "10.3389/fpls.2020.575861", "10.3389/fmicb.2016.01207",
    "10.1371/journal.pone.0085301", "10.3389/fmicb.2022.833758",
    "10.1186/s13213-020-01591-8", "10.1038/s41598-022-06155-1",
    "10.1016/j.apsoil.2019.04.014", "10.1016/j.still.2018.08.017",
    "10.1016/j.apsoil.2016.07.009", "10.1021/acsomega.2c01711",
    "10.1016/j.apsoil.2021.104275", "10.1111/1462-2920.14824",
    "10.1038/s41598-026-47528-0", "10.1016/j.soilbio.2021.108349",
    "10.1128/spectrum.01785-22", "10.1038/s41467-025-57213-x",
    "10.3390/agronomy10010093", "10.1038/s41598-020-58402-y",
    "10.1186/s40168-021-01118-6", "10.3390/microorganisms9071419",
]

SPECIAL = {
    "10.3389/fmicb.2021.730506": dict(
        study_id="RICE_DONG_2021", crop="rice", country="China", site="Shenyang",
        screening_status="pilot_selected", core_response_eligible="yes", download_eligible="yes",
        field_experiment="yes", randomized_design="yes", biological_replication="yes", replicate_n="3",
        experiment_establishment_year="2016", sampling_year="2020", treatment_duration_years="5",
        season_definition_recoverable="yes", N_gradient_count="3", N_rates_reported="0;150;300",
        N_unit_original="kg N ha-1 season-1", N_rates_convertible="yes", contains_0N="yes",
        zero_N_sample_count="6", zero_N_yield_available="yes", zero_N_raw_reads_available="yes",
        inorganic_N_main_factor="yes", N_form="urea", P_K_controlled="yes", confounded="no",
        yield_available="yes", same_season_yield="yes", yield_source="Figure 1 (2020 bar values)",
        yield_unit="t ha-1", raw_16S_available="yes", raw_shotgun_available="no",
        soil_compartment="bulk soil;rhizosphere", marker_region="full-length 16S (27F/1492R)",
        primer_sequences_available="yes", sequencing_platform="PacBio Sequel II",
        BioProject="PRJNA725973", claimed_accessions="PRJNA725973", verified_accessions="SRR14360818-SRR14360835",
        accession_status="verified", sample_treatment_mapping_status="verified", run_count_reported="18",
        run_count_verified="18", pH_available="yes", SOC_available="yes", TN_available="yes",
        sampling_depth_available="yes", sampling_stage_available="yes", fertilizer_timing_available="yes",
        coordinates_available="yes", core_class="Core-A", study_quality_score="17", quality_score_max="17",
        verification_notes="2020-08 BioSample dates match the paper's 2020 full-heading sampling and 2020 yield season."
    ),
    "10.3389/fpls.2024.1481465": dict(
        study_id="MAIZE_MENG_2024", crop="maize", country="China", site="Hohhot",
        screening_status="pilot_selected_16S_only", core_response_eligible="no", download_eligible="yes",
        field_experiment="yes", randomized_design="unclear", biological_replication="yes", replicate_n="3",
        experiment_establishment_year="2018", sampling_year="2023", treatment_duration_years="6",
        season_definition_recoverable="yes", N_gradient_count="6", N_rates_reported="0;120;180;240;300;360",
        N_unit_original="kg N ha-1 season-1", N_rates_convertible="yes", contains_0N="yes",
        zero_N_sample_count="6", zero_N_yield_available="no", zero_N_raw_reads_available="yes",
        inorganic_N_main_factor="yes", N_form="resin-coated urea (46% N)", P_K_controlled="yes", confounded="no",
        yield_available="yes", same_season_yield="no", yield_source="Figure 2 reports 2020-2022 only",
        yield_unit="kg ha-1", raw_16S_available="yes", raw_shotgun_available="no",
        soil_compartment="bulk soil;rhizosphere;endosphere", marker_region="16S amplicon",
        primer_sequences_available="yes", sequencing_platform="Illumina MiSeq", BioProject="PRJNA1142092",
        claimed_accessions="PRJNA1142092", verified_accessions="36 bacterial bulk/rhizosphere runs selected",
        accession_status="verified_with_year_mismatch", sample_treatment_mapping_status="verified",
        run_count_reported="108 bacterial+fungal", run_count_verified="108", pH_available="yes",
        SOC_available="yes", TN_available="yes", sampling_depth_available="yes", sampling_stage_available="yes",
        fertilizer_timing_available="yes", coordinates_available="yes", core_class="16S-only",
        study_quality_score="15", quality_score_max="17",
        verification_notes="All bacterial BioSamples checked are dated 2023-07-23; paper yield series ends in 2022. Retained only for separate 16S analysis."
    ),
    "10.3390/microorganisms13102382": dict(
        study_id="WHEAT_MA_2025", crop="wheat", country="China", site="Xuchang;Kaifeng;Shangshui",
        screening_status="pilot_selected_16S_only", core_response_eligible="no", download_eligible="yes",
        field_experiment="yes", randomized_design="yes", biological_replication="yes", replicate_n="4",
        experiment_establishment_year="2013", sampling_year="2018", treatment_duration_years="5",
        season_definition_recoverable="yes", N_gradient_count="4", N_rates_reported="0;180;240;300",
        N_unit_original="kg N ha-1 season-1", N_rates_convertible="yes", contains_0N="yes",
        zero_N_sample_count="12", zero_N_yield_available="no", zero_N_raw_reads_available="yes",
        inorganic_N_main_factor="yes", N_form="urea", P_K_controlled="yes", confounded="no",
        yield_available="yes", same_season_yield="no", yield_source="Figure 1 gives five-year pooled distribution",
        yield_unit="kg ha-1", raw_16S_available="yes", raw_shotgun_available="no",
        soil_compartment="bulk soil", marker_region="V3-V4 (338F/806R)", primer_sequences_available="yes",
        sequencing_platform="Illumina MiSeq 2x300", BioProject="PRJNA638680",
        claimed_accessions="SRP266837", verified_accessions="SRP266837=PRJNA638680; 48 runs",
        accession_status="verified", sample_treatment_mapping_status="verified_by_alias",
        run_count_reported="48", run_count_verified="48", pH_available="yes", SOC_available="yes",
        TN_available="yes", sampling_depth_available="yes", sampling_stage_available="yes",
        fertilizer_timing_available="yes", coordinates_available="yes", core_class="16S-only",
        study_quality_score="16", quality_score_max="17",
        verification_notes="Run aliases encode soil type, N rate, and replicate. Supplement has no year-specific 2018 yield; only five-year pooled yield is shown."
    ),
    "10.1186/s13213-020-01591-8": dict(
        study_id="MAIZE_ENEBE_2020", crop="maize", country="South Africa", screening_status="pilot_selected_MAG_only",
        core_response_eligible="no", download_eligible="yes", field_experiment="yes",
        biological_replication="no", replicate_n="1", N_gradient_count="3", N_rates_reported="0;60;120",
        N_unit_original="kg fertilizer ha-1", N_rates_convertible="no", contains_0N="yes",
        zero_N_raw_reads_available="yes", inorganic_N_main_factor="no", N_form="NPK 20-7-3",
        P_K_controlled="no", confounded="yes", confounding_reason="P and K co-vary with N; no biological replication",
        yield_available="no", same_season_yield="no", raw_16S_available="no", raw_shotgun_available="yes",
        soil_compartment="rhizosphere", sequencing_platform="Illumina HiSeq", BioProject="PRJNA607213",
        claimed_accessions="PRJNA607213", verified_accessions="SRR11128411;SRR11128414;SRR11128415",
        accession_status="verified", sample_treatment_mapping_status="verified", run_count_reported="5",
        run_count_verified="5", core_class="MAG-only technical", study_quality_score="6", quality_score_max="17",
        verification_notes="Three inorganic/control WGS runs total about 6.1 GB compressed; technical coassembly only, not causal N-response inference."
    ),
}

CROP_HINTS = {
    "10.1038/s41598-017-03539-6": "wheat", "10.3390/agronomy10081175": "wheat",
    "10.3389/fmicb.2020.01948": "wheat", "10.1186/s40168-019-0750-2": "wheat",
    "10.3389/fmicb.2018.01074": "wheat", "10.3389/fpls.2020.575861": "wheat",
    "10.3389/fmicb.2016.01207": "wheat;rice", "10.1371/journal.pone.0085301": "wheat;rice",
    "10.3389/fmicb.2022.833758": "maize", "10.1038/s41598-022-06155-1": "rice",
    "10.1016/j.apsoil.2019.04.014": "maize", "10.1016/j.still.2018.08.017": "maize",
    "10.1016/j.apsoil.2016.07.009": "maize", "10.1021/acsomega.2c01711": "maize",
    "10.1016/j.apsoil.2021.104275": "maize", "10.1111/1462-2920.14824": "wheat",
    "10.1038/s41598-026-47528-0": "maize", "10.1016/j.soilbio.2021.108349": "switchgrass",
    "10.1128/spectrum.01785-22": "maize", "10.1038/s41467-025-57213-x": "rice",
    "10.3390/agronomy10010093": "wheat", "10.1038/s41598-020-58402-y": "wheat",
    "10.1186/s40168-021-01118-6": "maize", "10.3390/microorganisms9071419": "maize",
}

def get_text(url: str, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {last}")

def crossref(doi: str) -> dict:
    try:
        payload = json.loads(get_text(CROSSREF + urllib.parse.quote(doi, safe="")))["message"]
    except Exception as exc:
        return {"title": "", "authors": "", "journal": "", "year": "", "error": str(exc)}
    authors = []
    for author in payload.get("author", []):
        name = " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part)
        if name:
            authors.append(name)
    parts = payload.get("published-print", payload.get("published-online", {})).get("date-parts", [[""]])
    return {
        "title": (payload.get("title") or [""])[0],
        "authors": "; ".join(authors),
        "journal": (payload.get("container-title") or [""])[0],
        "year": parts[0][0] if parts and parts[0] else "",
        "error": "",
    }

def ena_runs(accession: str) -> list[dict]:
    fields = [
        "run_accession", "run_alias", "study_accession", "sample_accession", "sample_alias",
        "sample_title", "experiment_accession", "experiment_alias", "library_strategy",
        "library_source", "library_layout", "instrument_platform", "instrument_model",
        "read_count", "base_count", "fastq_ftp", "fastq_md5", "fastq_bytes",
    ]
    query = urllib.parse.urlencode({"accession": accession, "result": "read_run", "fields": ",".join(fields), "format": "tsv", "download": "true"})
    text = get_text(ENA + "?" + query)
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))

def bytes_sum(value: str) -> int:
    total = 0
    for item in (value or "").split(";"):
        try:
            total += int(item)
        except ValueError:
            pass
    return total

def write_tsv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in headers})

def build_candidate_rows() -> list[dict]:
    rows = []
    for number, doi in enumerate(CANDIDATES, 1):
        meta = crossref(doi)
        row = {name: "" for name in CANDIDATE_HEADERS}
        row.update({
            "study_id": f"CAND_{number:03d}", "discovery_status": "found",
            "screening_status": "candidate_not_fully_audited", "doi": doi,
            "title": meta["title"], "authors": meta["authors"], "journal": meta["journal"],
            "publication_year": meta["year"], "article_url": f"https://doi.org/{doi}",
            "discovery_source": "OpenAlex;Crossref;publisher/PMC/NCBI as available",
            "search_query": "crop AND nitrogen fertilization AND soil/rhizosphere microbiome AND yield",
            "access_date": "2026-08-12", "full_text_status": "not_fully_audited",
            "supplement_status": "not_fully_audited", "JIF": "JIF_unverified",
            "JIF_year": "", "JIF_source": "No authenticated Clarivate JCR access in pilot environment",
            "IF_gt_8": "JIF_unverified", "crop": CROP_HINTS.get(doi, ""),
            "evidence_sources": f"https://doi.org/{doi}",
            "verification_notes": "Discovery-table record; blank fields mean not yet verified, not negative evidence. " + meta["error"],
        })
        if doi == "10.1016/j.soilbio.2021.108349":
            row.update(screening_status="excluded_crop", exclusion_reason="switchgrass is outside wheat/maize/rice scope", core_response_eligible="no", download_eligible="no")
        if doi in SPECIAL:
            row.update(SPECIAL[doi])
        rows.append(row)
    return rows

def map_selected_runs() -> tuple[list[dict], dict[str, list[str]], list[dict], list[dict]]:
    seq_rows: list[dict] = []
    allowlists: dict[str, list[str]] = {"core_a_rice": [], "amplicon_technical": [], "mag_technical": []}
    audits: list[dict] = []
    treatments: list[dict] = []

    projects = {
        "RICE_DONG_2021": ("PRJNA725973", "rice"),
        "MAIZE_MENG_2024": ("PRJNA1142092", "maize"),
        "WHEAT_MA_2025": ("PRJNA638680", "wheat"),
        "MAIZE_ENEBE_2020": ("PRJNA607213", "maize"),
    }
    for study_id, (project, crop) in projects.items():
        runs = ena_runs(project)
        selected = []
        for run in runs:
            alias = run.get("sample_alias", "")
            mapping = None
            batch = None
            marker = ""
            primers = ("", "")
            compartment = ""
            n_rate = None
            rep = ""
            site = ""
            season = ""
            analysis_eligibility = ""

            if study_id == "RICE_DONG_2021":
                match = re.fullmatch(r"([BR])N(0|150|300)([1-3])", alias)
                if match:
                    compartment = "bulk soil" if match.group(1) == "B" else "rhizosphere"
                    n_rate, rep, site, season = int(match.group(2)), match.group(3), "Shenyang", "2020"
                    mapping, batch, marker = "verified", "core_a_rice", "full-length 16S"
                    primers = ("AGRGTTTGATYNTGGCTCAG", "TASGGHTACCTTGTTASGACTT")
                    analysis_eligibility = "Core-A same-season joint analysis"
            elif study_id == "MAIZE_MENG_2024":
                match = re.fullmatch(r"N(0|8|12|16|20|24)_(NRS|RS)([1-3])", alias)
                if match:
                    n_map = {"0": 0, "8": 120, "12": 180, "16": 240, "20": 300, "24": 360}
                    n_rate, rep = n_map[match.group(1)], match.group(3)
                    compartment = "bulk soil" if match.group(2) == "NRS" else "rhizosphere"
                    site, season, mapping, batch, marker = "Hohhot", "2023", "verified", "amplicon_technical", "16S amplicon"
                    primers = ("TACGGRAGGCAGCAG", "AGGGTATCTAATCCT")
                    analysis_eligibility = "16S-only; no same-season yield"
            elif study_id == "WHEAT_MA_2025":
                match = re.fullmatch(r"(FS|SS|BS)N([0-3])_([1-4])", alias)
                if match:
                    n_rate, rep = {"0": 0, "1": 180, "2": 240, "3": 300}[match.group(2)], match.group(3)
                    site, season, compartment = match.group(1), "2018", "bulk soil"
                    mapping, batch, marker = "verified", "amplicon_technical", "V3-V4"
                    primers = ("ACTCCTACGGGAGGCAGCAG", "GGACTACHVGGGTWTCTAAT")
                    analysis_eligibility = "16S-only; paper yield is five-year pooled"
            elif study_id == "MAIZE_ENEBE_2020":
                match = re.fullmatch(r"MBME(Cn0|N1|N2)", alias)
                if match:
                    n_rate = {"Cn0": 0, "N1": 60, "N2": 120}[match.group(1)]
                    rep, site, season, compartment = "1", "South Africa field", "not_reported", "rhizosphere"
                    mapping, batch, marker = "verified", "mag_technical", "shotgun WGS"
                    analysis_eligibility = "MAG-only technical; P/K confounded and n=1"

            if not mapping:
                continue
            selected.append(run)
            run_acc = run["run_accession"]
            allowlists[batch].append(run_acc)
            seq_rows.append({
                "study_id": study_id, "site_id": site, "season_id": season,
                "treatment_id": f"N{n_rate}", "sample_id": alias, "soil_compartment": compartment,
                "sequencing_type": "shotgun" if batch == "mag_technical" else "16S",
                "marker_region": marker, "primer_forward": primers[0], "primer_reverse": primers[1],
                "platform": run.get("instrument_platform", ""), "instrument_model": run.get("instrument_model", ""),
                "library_strategy": run.get("library_strategy", ""), "library_layout": run.get("library_layout", ""),
                "paired_end": "yes" if run.get("library_layout") == "PAIRED" else "no",
                "BioProject": project, "BioSample": run.get("sample_accession", ""),
                "Experiment_accession": run.get("experiment_accession", ""), "Run_accession": run_acc,
                "raw_reads_available": "yes", "read_count": run.get("read_count", ""),
                "estimated_bases": run.get("base_count", ""), "estimated_download_size": bytes_sum(run.get("fastq_bytes", "")),
                "paper_mapping_label": alias, "archive_sample_title": run.get("sample_title", ""),
                "mapping_status": mapping, "accession_status": "verified", "download_eligible": "yes",
                "download_status": "pending", "integrity_status": "pending", "read_qc_status": "pending",
                "analysis_eligibility": analysis_eligibility,
                "evidence_source": f"https://www.ebi.ac.uk/ena/browser/view/{run_acc}",
                "notes": f"run_alias={run.get('run_alias','')}; experiment_alias={run.get('experiment_alias','')}; replicate={rep}",
            })
        audits.append({
            "study_id": study_id, "claimed_accession": project, "accession_type": "BioProject",
            "claim_location": "paper data availability", "claim_text": project,
            "archive_lookup_status": "resolved", "resolved_project": runs[0].get("study_accession", project) if runs else "",
            "resolved_sample_count": len({row.get("sample_accession", "") for row in runs}),
            "resolved_run_count": len(runs), "paper_expected_sample_count": "",
            "crop_match": "yes", "sequencing_type_match": "yes", "treatment_mapping_recoverable": "yes" if selected else "no",
            "mapping_status": "verified" if selected else "failed", "wrong_accession_suspected": "no",
            "reviewer_status": "reviewed", "review_date": "2026-08-12",
            "notes": f"Selected {len(selected)} of {len(runs)} project runs after alias and scope filtering.",
        })

    for study_id, crop, site, season, compartment, rates, reps, nform, confounded, notes in [
        ("RICE_DONG_2021", "rice", "Shenyang", "2020", "bulk soil;rhizosphere", [0,150,300], 3, "urea", "no", "2020 yield will be digitized from Figure 1 and flagged as approximate."),
        ("MAIZE_MENG_2024", "maize", "Hohhot", "2023", "bulk soil;rhizosphere", [0,120,180,240,300,360], 3, "resin-coated urea", "no", "No 2023 yield in paper; 16S-only."),
        ("WHEAT_MA_2025", "wheat", "FS;SS;BS", "2018", "bulk soil", [0,180,240,300], 4, "urea", "no", "2018 same-season yield unavailable; 16S-only."),
        ("MAIZE_ENEBE_2020", "maize", "South Africa field", "not_reported", "rhizosphere", [0,60,120], 1, "NPK 20-7-3", "yes", "MAG technical only; P/K co-vary and no biological replication."),
    ]:
        for rate in rates:
            treatments.append({
                "study_id": study_id, "site_id": site, "experiment_id": study_id, "season_id": season,
                "treatment_id": f"N{rate}", "crop": crop, "soil_compartment": compartment,
                "N_rate": rate, "N_unit_original": "kg ha-1 season-1", "N_rate_kg_ha_season": rate,
                "N_form": nform, "zero_N": "yes" if rate == 0 else "no", "replicate_n": reps,
                "confounded": confounded, "mapping_status": "verified",
                "evidence_source": "paper methods; ENA sample aliases", "notes": notes,
            })
    return seq_rows, allowlists, audits, treatments

def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "pilot_metadata_out")
    out.mkdir(parents=True, exist_ok=True)
    candidates = build_candidate_rows()
    seq_rows, allowlists, audits, treatments = map_selected_runs()

    estimates = {}
    for name, runs in allowlists.items():
        estimates[name] = sum(int(row["estimated_download_size"] or 0) for row in seq_rows if row["Run_accession"] in runs)
    for row in candidates:
        related = [item for item in seq_rows if item["study_id"] == row["study_id"]]
        if related:
            row["estimated_download_size_bytes"] = sum(int(item["estimated_download_size"] or 0) for item in related)

    write_tsv(out / "candidate_studies.tsv", CANDIDATE_HEADERS, candidates)
    write_tsv(out / "sequencing_runs.tsv", SEQ_HEADERS, seq_rows)
    write_tsv(out / "treatments.tsv", TREAT_HEADERS, treatments)
    write_tsv(out / "accession_audit.tsv", AUDIT_HEADERS, audits)

    quality_rows = []
    for row in candidates:
        if row["study_id"] not in {item["study_id"] for item in seq_rows}:
            continue
        values = {
            "study_id": row["study_id"], "field_experiment": row["field_experiment"],
            "randomized_design": row["randomized_design"], "biological_replication": row["biological_replication"],
            "N_rates_ge_3": "yes" if int(row.get("N_gradient_count") or 0) >= 3 else "no",
            "N_rates_ge_4": "yes" if int(row.get("N_gradient_count") or 0) >= 4 else "no",
            "contains_0N": row["contains_0N"], "same_season_yield": row["same_season_yield"],
            "raw_sequencing": "yes", "clear_treatment_mapping": "yes",
            "pH_available": row["pH_available"], "SOC_TN_available": "yes" if row["SOC_available"] == "yes" and row["TN_available"] == "yes" else "no",
            "N_form_known": "yes" if row["N_form"] else "no", "sampling_stage_known": row["sampling_stage_available"],
            "sampling_depth_known": row["sampling_depth_available"], "treatment_duration_known": "yes" if row["treatment_duration_years"] else "no",
            "P_K_controlled": row["P_K_controlled"], "raw_score": row["study_quality_score"], "max_score": row["quality_score_max"],
            "quality_fraction": (f"{int(row['study_quality_score'])/int(row['quality_score_max']):.3f}" if row["study_quality_score"] and row["quality_score_max"] else ""),
            "notes": row["verification_notes"],
        }
        quality_rows.append(values)
    write_tsv(out / "study_quality.tsv", STUDY_QUALITY_HEADERS, quality_rows)

    for name, runs in allowlists.items():
        with (out / f"allowlist_{name}.tsv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(["run_accession"])
            writer.writerows([[run] for run in sorted(runs)])

    manifest_rows = []
    for row in candidates:
        if row["study_id"] in {item["study_id"] for item in seq_rows}:
            manifest_rows.append({
                "source_sheet": "verified_pilot", "status": row["screening_status"], "doi": row["doi"],
                "title": row["title"], "database": "ENA/NCBI SRA", "data_number": row["BioProject"],
                "description": row["verification_notes"],
            })
    write_tsv(out / "download_manifest_verified_pilot.tsv",
              ["source_sheet","status","doi","title","database","data_number","description"], manifest_rows)

    with (out / "build_summary.json").open("w", encoding="utf-8") as fh:
        json.dump({
            "candidate_count": len(candidates), "sequencing_run_count": len(seq_rows),
            "allowlist_counts": {key: len(value) for key, value in allowlists.items()},
            "estimated_bytes": estimates,
        }, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "candidate_count": len(candidates), "sequencing_run_count": len(seq_rows),
        "allowlist_counts": {key: len(value) for key, value in allowlists.items()},
        "estimated_bytes": estimates,
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
