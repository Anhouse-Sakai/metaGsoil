#!/usr/bin/env bash
# Targeted KOfam screen of N-cycle/assimilation genes on the shared coassembly.
# This is a technical function layer only because n=1 and NPK are confounded.
set -euo pipefail

ROOT="${1:-${LITTLEDREAM_ROOT:-$PWD}}"
THREADS="${2:-24}"
ENV_BIN="$ROOT/必要软件/pilot_env/bin"
export PATH="$ENV_BIN:$PATH"
BASE="$ROOT/tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered"
REF="$ROOT/reference_databases/kofam"
OUT="$BASE/kofam_nitrogen"
mkdir -p "$REF" "$OUT/tblout" "$BASE/logs"

PROFILES="$REF/profiles.tar.gz"
KOLIST="$REF/ko_list.gz"
[[ -s "$PROFILES" ]] || curl --fail --location --continue-at - --retry 8 --retry-all-errors \
  -o "$PROFILES" https://www.genome.jp/ftp/db/kofam/profiles.tar.gz
[[ -s "$KOLIST" ]] || curl --fail --location --continue-at - --retry 8 --retry-all-errors \
  -o "$KOLIST" https://www.genome.jp/ftp/db/kofam/ko_list.gz
gzip -t "$KOLIST"; tar -tzf "$PROFILES" >/dev/null

KOS=(K02588 K10944 K10535 K00370 K02567 K00368 K15864 K04561 K00376 K00362 K00363 K00372 K01915 K00260)
for ko in "${KOS[@]}"; do
  [[ -s "$REF/profiles/$ko.hmm" ]] || tar -xzf "$PROFILES" -C "$REF" "profiles/$ko.hmm"
done

CONTIGS="$BASE/coassembly/final.contigs.fa"
[[ -s "$CONTIGS" ]] || { echo "Missing host-filtered coassembly" >&2; exit 2; }
if [[ ! -s "$OUT/proteins.faa" || ! -s "$OUT/genes.gff" ]]; then
  prodigal -i "$CONTIGS" -a "$OUT/proteins.faa" -d "$OUT/genes.fna" \
    -o "$OUT/genes.gff" -f gff -p meta > "$BASE/logs/prodigal.log" 2>&1
fi
for ko in "${KOS[@]}"; do
  hmmsearch --cpu "$THREADS" --noali --tblout "$OUT/tblout/$ko.tbl" \
    "$REF/profiles/$ko.hmm" "$OUT/proteins.faa" > "$OUT/tblout/$ko.log"
done
python "$ROOT/scripts/pilot/08_parse_kofam_functions.py" \
  --root "$ROOT" --analysis-dir "tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered" \
  --ko-list "$KOLIST" --kofam-dir "$OUT"
