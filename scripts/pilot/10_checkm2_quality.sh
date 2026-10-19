#!/usr/bin/env bash
# Prepare the official CheckM2 v1.1.0 database while MAG assembly runs, then
# assess dereplicated bins when they become available.
set -euo pipefail

ROOT="${1:-${LITTLEDREAM_ROOT:-$PWD}}"
THREADS="${2:-16}"
MM="$ROOT/必要软件/micromamba/bin/micromamba"
ENV="$ROOT/必要软件/checkm2_env"
DBROOT="$ROOT/reference_databases/checkm2"
DBTAR="$DBROOT/checkm2_database.tar.gz"
DB="$DBROOT/CheckM2_database/uniref100.KO.1.dmnd"
BASE="$ROOT/tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered"
BINS="$BASE/drep/dereplicated_genomes"
OUT="$BASE/checkm2"
LOG="$ROOT/download_logs/analysis/checkm2_prepare_and_quality.log"
mkdir -p "$DBROOT" "$ROOT/download_logs/analysis" "$BASE"
exec > >(tee -a "$LOG") 2>&1
# The server user's ~/.local Python packages include NumPy 2.x.  CheckM2's
# TensorFlow 2.17 binary is built against NumPy 1.x, so user-site leakage can
# override the environment's pinned NumPy 1.26 and crash at import time.
export PYTHONNOUSERSITE=1
# CheckM2 launches DIAMOND by command name.  Invoking checkm2 through its
# absolute path is not enough: the environment bin directory must also be on
# PATH for the subprocess lookup.
export PATH="$ENV/bin:$ROOT/必要软件/pilot_env/bin:$PATH"

echo "[$(date -Is)] CheckM2 preparation started"
if [[ ! -x "$ENV/bin/checkm2" ]]; then
  "$MM" create -y -p "$ENV" -c conda-forge -c bioconda checkm2=1.1.0
fi
"$ENV/bin/checkm2" --version

if [[ ! -s "$DB" ]]; then
  curl --fail --location --continue-at - --retry 8 --retry-all-errors \
    -o "$DBTAR" "https://zenodo.org/api/records/14897628/files/checkm2_database.tar.gz/content"
  printf '07c10655620843b517d0df0c160d911f  %s\n' "$DBTAR" | md5sum -c -
  tar -xzf "$DBTAR" -C "$DBROOT"
fi
[[ -s "$DB" ]] || { echo "CheckM2 database missing after extraction" >&2; exit 2; }
printf 'version\t1.1.0\ndatabase_doi\t10.5281/zenodo.14897628\ndatabase_md5\t07c10655620843b517d0df0c160d911f\ndatabase_path\t%s\n' "$DB" \
  > "$ROOT/metadata/checkm2_database_audit.tsv"

for _ in {1..720}; do
  if [[ -d "$BINS" ]] && find "$BINS" -maxdepth 1 -type f -name '*.fa*' -print -quit | grep -q .; then
    break
  fi
  if [[ -f "$BASE/MAG_TECHNICAL_STATUS.tsv" ]] && grep -q 'no_bins_recovered' "$BASE/MAG_TECHNICAL_STATUS.tsv"; then
    printf 'status\tno_bins_recovered\n' > "$BASE/CHECKM2_STATUS.tsv"
    echo "[$(date -Is)] No bins recovered; explicit terminal state recorded"
    exit 0
  fi
  sleep 30
done
[[ -d "$BINS" ]] && find "$BINS" -maxdepth 1 -type f -name '*.fa*' -print -quit | grep -q . || {
  printf 'status\ttimeout_waiting_for_bins\n' > "$BASE/CHECKM2_STATUS.tsv"
  exit 4
}

OUT_TMP="$(realpath -m "$OUT.tmp")"
EXPECTED_TMP="$(realpath -m "$BASE/checkm2.tmp")"
if [[ "$OUT_TMP" != "$EXPECTED_TMP" || "$OUT_TMP" == "$BASE" ]]; then
  echo "Refusing to clean unexpected CheckM2 temporary path: $OUT_TMP" >&2
  exit 5
fi
rm -rf -- "$OUT_TMP"
"$ENV/bin/checkm2" predict --threads "$THREADS" --input "$BINS" \
  --output-directory "$OUT_TMP" -x fa --database_path "$DB"
if [[ -e "$OUT" ]]; then
  mv "$OUT" "$BASE/checkm2_pre_recovery_$(date +%Y%m%dT%H%M%S)"
fi
mv "$OUT_TMP" "$OUT"
"$ROOT/必要软件/pilot_env/bin/python" "$ROOT/scripts/pilot/10_parse_checkm2.py" --root "$ROOT"
printf 'status\tpass\ncheckm2_version\t1.1.0\ndatabase_doi\t10.5281/zenodo.14897628\n' > "$BASE/CHECKM2_STATUS.tsv"
echo "[$(date -Is)] CheckM2 quality assessment completed"
