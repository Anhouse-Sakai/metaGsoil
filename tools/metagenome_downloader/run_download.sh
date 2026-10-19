#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTDIR="${1:-$PWD/metagenome_downloads}"
JOBS="${JOBS:-4}"
CONNECTIONS="${CONNECTIONS:-4}"
THREADS="${THREADS:-16}"
ORGANIZE_MODE="${ORGANIZE_MODE:-symlink}"
MANIFEST="${MANIFEST:-$SCRIPT_DIR/download_manifest_target.tsv}"
VERIFY_MD5="${VERIFY_MD5:-1}"
DRY_RUN="${DRY_RUN:-0}"

choose_resolved_file() {
  if [[ -n "${RESOLVED_FILES:-}" ]]; then
    [[ -f "$RESOLVED_FILES" ]] && printf '%s\n' "$RESOLVED_FILES"
    return 0
  fi

  local candidates=(
    "$SCRIPT_DIR/logs/resolved_files_MAG.tsv"
    "$SCRIPT_DIR/logs/resolved_files.tsv"
    "$OUTDIR/logs/resolved_files_MAG.tsv"
    "$OUTDIR/logs/resolved_files.tsv"
    "$SCRIPT_DIR/../data/logs/resolved_files_MAG.tsv"
    "$SCRIPT_DIR/../data/logs/resolved_files.tsv"
  )

  local path
  for path in "${candidates[@]}"; do
    if [[ -f "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
}

RESOLVED_TSV="$(choose_resolved_file || true)"

if [[ -n "$RESOLVED_TSV" ]]; then
  echo "Using resolved file list: $RESOLVED_TSV"
  mkdir -p "$OUTDIR/logs"
  ARIA2_INPUT="$OUTDIR/logs/aria2_input_from_resolved.txt"

  python3 - "$RESOLVED_TSV" "$ARIA2_INPUT" "$VERIFY_MD5" <<'PY'
import csv
import sys
from pathlib import Path

resolved_tsv = Path(sys.argv[1])
aria2_input = Path(sys.argv[2])
verify_md5 = sys.argv[3] not in {"0", "false", "False", "no", "NO"}

pending = 0
skipped = 0
with resolved_tsv.open("r", encoding="utf-8-sig", newline="") as source_fh, aria2_input.open(
    "w", encoding="utf-8"
) as target_fh:
    reader = csv.DictReader(source_fh, delimiter="\t")
    required = {"url", "target"}
    missing = required.difference(reader.fieldnames or [])
    if missing:
        raise SystemExit(f"Resolved TSV missing columns: {', '.join(sorted(missing))}")

    for row in reader:
        url = (row.get("url") or "").strip()
        target = Path((row.get("target") or "").strip())
        if not url or not str(target):
            continue

        expected = 0
        try:
            expected = int((row.get("expected_bytes") or "0").strip() or "0")
        except ValueError:
            expected = 0

        if target.exists() and (not expected or target.stat().st_size == expected):
            skipped += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        pending += 1
        target_fh.write(url + "\n")
        target_fh.write(f"  dir={target.parent}\n")
        target_fh.write(f"  out={target.name}\n")
        target_fh.write("  continue=true\n")
        target_fh.write("  auto-file-renaming=false\n")
        target_fh.write("  allow-overwrite=true\n")
        md5 = (row.get("md5") or "").strip()
        if verify_md5 and md5:
            target_fh.write(f"  checksum=md5={md5}\n")

print(f"Prepared aria2 input: {aria2_input}")
print(f"Pending files: {pending}")
print(f"Already present with expected size: {skipped}")
PY

  if [[ ! -s "$ARIA2_INPUT" ]]; then
    echo "No pending files to download."
    exit 0
  fi

  if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
    echo "DRY_RUN enabled; not starting aria2c."
    exit 0
  fi

  ARIA2_BIN="$(command -v aria2c || true)"
  if [[ -n "$ARIA2_BIN" && "$ARIA2_BIN" != /snap/bin/aria2c ]]; then
    aria2c \
      --input-file="$ARIA2_INPUT" \
      --max-concurrent-downloads="$JOBS" \
      --split="$CONNECTIONS" \
      --max-connection-per-server="$CONNECTIONS" \
      --min-split-size=64M \
      --continue=true \
      --file-allocation=none \
      --retry-wait=10 \
      --max-tries=0 \
      --timeout=120 \
      --connect-timeout=30 \
      --summary-interval=60 \
      --console-log-level=notice
    exit $?
  fi

  if [[ "$ARIA2_BIN" == /snap/bin/aria2c ]]; then
    echo "Skipping snap aria2c because it cannot write to /mnt/sakai on this server."
  else
    echo "aria2c not found; using curl/wget fallback."
  fi

  python3 - "$RESOLVED_TSV" "$JOBS" <<'PYDL'
import csv
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

resolved_tsv = Path(sys.argv[1])
jobs = max(1, int(sys.argv[2]))
curl = shutil.which("curl")
wget = shutil.which("wget")
if not curl and not wget:
    raise SystemExit("Neither curl nor wget is available")

items = []
with resolved_tsv.open("r", encoding="utf-8-sig", newline="") as fh:
    reader = csv.DictReader(fh, delimiter="\t")
    for row in reader:
        url = (row.get("url") or "").strip()
        target = Path((row.get("target") or "").strip())
        if not url or not str(target):
            continue
        expected = 0
        try:
            expected = int((row.get("expected_bytes") or "0").strip() or "0")
        except ValueError:
            expected = 0
        if target.exists() and (not expected or target.stat().st_size == expected):
            continue
        items.append((url, target))

print(f"curl/wget pending files: {len(items)}", flush=True)


def download(item):
    url, target = item
    target.parent.mkdir(parents=True, exist_ok=True)
    if curl:
        cmd = [curl, "--fail", "--location", "--continue-at", "-", "--retry", "8", "--retry-all-errors", "--connect-timeout", "30", "--output", str(target), url]
    else:
        cmd = [wget, "--continue", "--tries=0", "--timeout=120", "--output-document", str(target), url]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return False, url, result.stderr[-1000:]
    return True, url, "downloaded"

failures = 0
completed = 0
with ThreadPoolExecutor(max_workers=jobs) as executor:
    futures = [executor.submit(download, item) for item in items]
    for future in as_completed(futures):
        ok, url, message = future.result()
        completed += 1
        if ok:
            print(f"[{completed}/{len(items)}] OK {url}", flush=True)
        else:
            failures += 1
            print(f"[{completed}/{len(items)}] FAILED {url}: {message}", flush=True)

raise SystemExit(1 if failures else 0)
PYDL

  exit $?
fi

echo "No resolved file list found; falling back to legacy manifest workflow."
python3 "$SCRIPT_DIR/download_all_metagenomes.py" \
  --manifest "$MANIFEST" \
  --outdir "$OUTDIR" \
  --mode all \
  --jobs "$JOBS" \
  --connections "$CONNECTIONS" \
  --threads "$THREADS" \
  --yes

python3 "$SCRIPT_DIR/organize_by_article.py" \
  --manifest "$MANIFEST" \
  --outdir "$OUTDIR" \
  --mode "$ORGANIZE_MODE"
