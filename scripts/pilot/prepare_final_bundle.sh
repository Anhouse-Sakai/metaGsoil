#!/usr/bin/env bash
# Build a small final-delivery archive. Raw reads, reference databases,
# alignments and assembly intermediates are deliberately excluded.
set -euo pipefail

ROOT="${LITTLEDREAM_ROOT:-$PWD}"
RESULT="$ROOT/tmp/result"
OUT="$RESULT/littledream_pilot_final_delivery.tar.gz"
STAGE="$ROOT/tmp/final_delivery_stage_20260814"

cleanup_stage() {
  local expected resolved
  expected="$(realpath -m "$ROOT/tmp/final_delivery_stage_20260814")"
  resolved="$(realpath -m "$STAGE")"
  if [[ "$resolved" != "$expected" || "$resolved" == "$ROOT" || "$resolved" == "$ROOT/tmp" ]]; then
    echo "Unsafe stage path: $resolved" >&2
    exit 90
  fi
  [[ ! -e "$resolved" ]] || rm -rf -- "$resolved"
}
trap cleanup_stage EXIT
cleanup_stage
mkdir -p "$STAGE"

copy_relative_find() {
  local base="$1"
  shift
  (
    cd "$base"
    find . "$@" -exec cp -L --parents --target-directory="$STAGE" {} +
  )
}

# Structured metadata, including the user-facing article-list alias.
copy_relative_find "$ROOT" -maxdepth 3 -path './metadata/*' \( -type f -o -type l \) \
  \( -name '*.tsv' -o -name '*.json' -o -name '*.md' \)

# Canonical final tables and reports.
copy_relative_find "$ROOT" -maxdepth 4 -path './tmp/result/tables/*' -type f -name '*.tsv'
copy_relative_find "$ROOT" -maxdepth 4 -path './tmp/result/reports/*' -type f -name '*.md'
copy_relative_find "$ROOT" -maxdepth 2 -path './tmp/raw_data_inventory.tsv' -type f
copy_relative_find "$ROOT" -maxdepth 3 -path './results/feasibility/*.md' -type f

# Final figures only from the canonical visualization tree, not duplicated Step archives.
FIGDIR="$(find "$RESULT" -type f -name 'Figure_1_N_rate_vs_relative_yield.pdf' \
  -path '*/可视化result/*' -printf '%h\n' | head -n 1)"
[[ -n "$FIGDIR" && -d "$FIGDIR" ]] || { echo 'Canonical final figure directory missing' >&2; exit 91; }
(
  cd "$ROOT"
  find "${FIGDIR#$ROOT/}" -maxdepth 1 -type f \
    \( -name '*.pdf' -o -name '*.svg' -o -name '*.png' \) \
    -exec cp -L --parents --target-directory="$STAGE" {} +
)

# Formal workbook: exact ending excludes the older stage workbook.
mapfile -t workbooks < <(find "$RESULT" -maxdepth 1 -type f \
  -name '*Pilot*全部文章与数据审计总表.xlsx' | sort)
[[ "${#workbooks[@]}" -eq 1 ]] || { echo "Expected one formal workbook, got ${#workbooks[@]}" >&2; exit 92; }
mkdir -p "$STAGE/workbook"
cp -L "${workbooks[0]}" "$STAGE/workbook/"

# Requested Step1-Step6 organization, containing only small outputs/scripts.
mkdir -p "$STAGE/step_archives"
mapfile -t steps < <(find "$RESULT" -maxdepth 1 -type d -name 'Step[1-6]*' | sort)
[[ "${#steps[@]}" -eq 6 ]] || { echo "Expected six Step directories, got ${#steps[@]}" >&2; exit 93; }
for step in "${steps[@]}"; do
  cp -a "$step" "$STAGE/step_archives/"
done

# Dynamic records and every runnable Pilot script used in the handoff.
copy_relative_find "$ROOT" -maxdepth 1 -type f -name '*.md'
copy_relative_find "$ROOT" -maxdepth 2 -path './tmp/*.md' -type f
copy_relative_find "$ROOT" -maxdepth 3 -path './tmp/result/*.md' -type f
copy_relative_find "$ROOT" -maxdepth 3 -path './scripts/pilot/*' -type f \
  \( -name '*.py' -o -name '*.R' -o -name '*.sh' \)
copy_relative_find "$ROOT" -maxdepth 4 -path './tools/metagenome_downloader/*' -type f \
  \( -name '*.py' -o -name '*.sh' -o -name '*.md' -o -name '*.tsv' -o -name '*.json' \)

mkdir -p "$STAGE/qa_logs"
for log in \
  "$ROOT/download_logs/analysis/final_figure_render.log" \
  "$ROOT/download_logs/analysis/final_pdf_fonts.log"; do
  [[ ! -f "$log" ]] || cp -L "$log" "$STAGE/qa_logs/"
done

# Hard exclusion guard for large biological data and intermediate formats.
mapfile -t forbidden < <(find "$STAGE" -type f \( \
  -name '*.fastq' -o -name '*.fastq.gz' -o -name '*.fq' -o -name '*.fq.gz' \
  -o -name '*.bam' -o -name '*.sam' -o -name '*.cram' \
  -o -name '*.fa' -o -name '*.fasta' -o -name '*.fna' -o -name '*.faa' \
  -o -name '*.h5' -o -name '*.hmm' -o -name '*.bt2' -o -name '*.bt2l' \))
[[ "${#forbidden[@]}" -eq 0 ]] || { printf 'Forbidden bundle file: %s\n' "${forbidden[@]}" >&2; exit 94; }

python3 - "$STAGE" <<'PY'
from pathlib import Path
import hashlib
import json
import sys

root = Path(sys.argv[1])
rows = []
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    data = path.read_bytes()
    rows.append({
        "path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })
(root / "BUNDLE_MANIFEST.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
)
PY

tar -C "$STAGE" -czf "$OUT" .
sha256sum "$OUT" > "$OUT.sha256"
echo "bundle=$OUT"
echo "files=$(find "$STAGE" -type f | wc -l)"
wc -c "$OUT"
cat "$OUT.sha256"
