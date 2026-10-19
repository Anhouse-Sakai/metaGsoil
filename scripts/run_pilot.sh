#!/usr/bin/env bash
# 按顺序跑完整 Pilot。需先准备好 raw_data/ 与 reference_databases/(见 README)。
# 用法: LITTLEDREAM_ROOT=/path/to/project bash scripts/run_pilot.sh [threads]
set -euo pipefail
ROOT="${LITTLEDREAM_ROOT:-$PWD}"; T="${1:-16}"; S="$ROOT/scripts/pilot"
SILVA=reference_databases/silva/silva_nr99_v138.2_toSpecies_trainset.fa.gz
python "$S/00_merge_site_covariates.py"
python "$S/01_validate_downloads.py" --root "$ROOT" --workers 8
Rscript "$S/02_amplicon_dada2.R" "$ROOT" "$T"
Rscript "$S/02b_assign_taxonomy.R" "$ROOT" "$SILVA" "$T"
Rscript "$S/03_microbiome_metrics.R" "$ROOT"
Rscript "$S/04_yield_and_joint_analysis.R" "$ROOT"
bash "$S/05a_maize_host_depletion.sh" "$ROOT" "$T"
bash "$S/05b_mag_pipeline_host_filtered.sh" "$ROOT" "$T"
bash "$S/10_checkm2_quality.sh" "$ROOT" "$T"   # 需 checkm2 环境
bash "$S/08_kofam_nitrogen_function.sh" "$ROOT" "$T"
Rscript "$S/06_make_preliminary_figures.R" "$ROOT"
python "$S/11_finalize_records.py" --root "$ROOT"
python "$S/09_finalize_and_validate.py" --root "$ROOT"
