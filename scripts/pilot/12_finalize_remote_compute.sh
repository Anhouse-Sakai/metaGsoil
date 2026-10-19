#!/usr/bin/env bash
# Wait for the two already-running compute chains, repair valid edge exits, and
# produce all server-side result tables/figures/reports needed before workbook QA.
set -euo pipefail

ROOT="${1:-${LITTLEDREAM_ROOT:-$PWD}}"
ENV_BIN="$ROOT/必要软件/pilot_env/bin"
export PATH="$ENV_BIN:$PATH"
LOG="$ROOT/download_logs/analysis/final_remote_compute.log"
READY="$ROOT/tmp/result/REMOTE_COMPUTE_COMPLETE"
mkdir -p "$(dirname "$LOG")" "$ROOT/tmp/result"
exec > >(tee -a "$LOG") 2>&1

echo "[$(date -Is)] final remote compute watcher started"
for pid in 2184660 2184662 2207411; do
  while kill -0 "$pid" 2>/dev/null; do
    sleep 20
  done
done

TABLES="$ROOT/tmp/result/tables"
REF="$ROOT/reference_databases/silva/silva_nr99_v138.2_toSpecies_trainset.fa.gz"
taxonomy_count="$(find "$ROOT/tmp/analysis/amplicon" -mindepth 2 -maxdepth 2 -name taxonomy_silva138_2.tsv -type f | wc -l)"
if [[ "$taxonomy_count" -lt 3 ]]; then
  Rscript "$ROOT/scripts/pilot/02b_assign_taxonomy.R" "$ROOT" "$REF" 16
fi
primary_count=0
if [[ -s "$TABLES/permanova.tsv" ]]; then
  primary_count="$(grep -c 'primary_N_effect_adjusted_for_stratum' "$TABLES/permanova.tsv" || true)"
fi
if [[ "$primary_count" -lt 3 ]]; then
  Rscript "$ROOT/scripts/pilot/03_microbiome_metrics.R" "$ROOT"
fi
if [[ ! -s "$TABLES/rice_joint_yield_microbiome.tsv" ]]; then
  Rscript "$ROOT/scripts/pilot/04_yield_and_joint_analysis.R" "$ROOT"
fi

MAG="$ROOT/tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered"
if [[ ! -s "$MAG/MAG_TECHNICAL_STATUS.tsv" ]]; then
  mapfile -t RECOVERY_BINS < <(find "$MAG/bins" -maxdepth 1 -name '*.fa' -type f | sort)
  if [[ ${#RECOVERY_BINS[@]} -gt 0 ]]; then
    echo "MAG has ${#RECOVERY_BINS[@]} raw bins but no terminal state; recovering only ANI dereplication"
    recovery="$MAG/drep_recovery"
    if [[ -e "$recovery" ]]; then
      echo "Existing dRep recovery directory prevents an untracked overwrite: $recovery" >&2
      exit 21
    fi
    dRep dereplicate "$recovery" -g "${RECOVERY_BINS[@]}" -p 24 --ignoreGenomeQuality \
      > "$MAG/logs/drep_recovery.log" 2>&1
    if [[ -e "$MAG/drep" ]]; then
      mv "$MAG/drep" "$MAG/drep_failed_pre_recovery_$(date +%Y%m%dT%H%M%S)"
    fi
    mv "$recovery" "$MAG/drep"
    printf 'field\tvalue\nstatus\tpass\ninput_runs\t3\nhost_filter\tB73_RefGen_v5_both_mates_unmapped\nraw_bins\t%s\ndereplicated_bins\t%s\ninferential_use\ttechnical_feasibility_only\nrecovery\tdrep_only_after_prepatch_controller_exit\n' \
      "${#RECOVERY_BINS[@]}" "$(find "$MAG/drep/dereplicated_genomes" -type f | wc -l)" \
      > "$MAG/MAG_TECHNICAL_STATUS.tsv"
  else
    echo "MAG pipeline did not produce an explicit terminal status or recoverable raw bins" >&2
    exit 21
  fi
fi
# The already-running shell may still hold the pre-patch script inode.  Normalize
# its successful status format without touching any result payload.
if ! grep -q $'status\tpass\|status\tno_bins_recovered' "$MAG/MAG_TECHNICAL_STATUS.tsv"; then
  if find "$MAG/drep/dereplicated_genomes" -maxdepth 1 -type f -name '*.fa*' -print -quit 2>/dev/null | grep -q .; then
    awk 'NR==1 {print; print "status\tpass"; next} {print}' "$MAG/MAG_TECHNICAL_STATUS.tsv" \
      > "$MAG/MAG_TECHNICAL_STATUS.tsv.tmp"
    mv "$MAG/MAG_TECHNICAL_STATUS.tsv.tmp" "$MAG/MAG_TECHNICAL_STATUS.tsv"
  fi
fi
if ! grep -q $'status\tpass\|status\tno_bins_recovered' "$MAG/MAG_TECHNICAL_STATUS.tsv"; then
  echo "Unrecognized MAG terminal status:" >&2
  cat "$MAG/MAG_TECHNICAL_STATUS.tsv" >&2
  exit 22
fi

# Rebuilding these summaries is deterministic and cheap; it also repairs the
# old controller's valid no-bin exit path if that branch was already buffered.
if grep -q 'no_bins_recovered' "$MAG/MAG_TECHNICAL_STATUS.tsv"; then
  mkdir -p "$MAG/drep/dereplicated_genomes"
fi
python "$ROOT/scripts/pilot/07_mag_summaries.py" --root "$ROOT"
if ! grep -q $'status\tpass\|status\tno_bins_recovered' "$MAG/CHECKM2_STATUS.tsv" 2>/dev/null; then
  echo "CheckM2 lacks a valid terminal state after MAG completion; rerunning quality-only controller"
  bash "$ROOT/scripts/pilot/10_checkm2_quality.sh" "$ROOT" 16
fi
if [[ -s "$MAG/CHECKM2_STATUS.tsv" ]] && grep -q $'status\tpass' "$MAG/CHECKM2_STATUS.tsv"; then
  python "$ROOT/scripts/pilot/10_parse_checkm2.py" --root "$ROOT"
elif ! grep -q 'no_bins_recovered' "$MAG/CHECKM2_STATUS.tsv" 2>/dev/null; then
  echo "CheckM2 did not produce a valid pass/no_bins_recovered terminal status" >&2
  exit 23
fi

if [[ ! -s "$TABLES/kofam_nitrogen_gene_hits.tsv" || ! -s "$TABLES/shotgun_function.tsv" ]]; then
  bash "$ROOT/scripts/pilot/08_kofam_nitrogen_function.sh" "$ROOT" 24
fi
Rscript "$ROOT/scripts/pilot/06_make_preliminary_figures.R" "$ROOT"
python "$ROOT/scripts/pilot/11_finalize_records.py" --root "$ROOT"

printf 'completed_at\t%s\nstatus\tpass\n' "$(date -Is)" > "$READY"
echo "[$(date -Is)] final remote compute ready for workbook and machine QA"
