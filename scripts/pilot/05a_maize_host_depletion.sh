#!/usr/bin/env bash
# Remove reads for which both mates are not confidently non-host, using the
# B73 RefGen_v5 nuclear + organellar reference before the formal MAG assembly.
set -euo pipefail

ROOT="${1:-${LITTLEDREAM_ROOT:-$PWD}}"
THREADS="${2:-24}"
ENV_BIN="$ROOT/必要软件/pilot_env/bin"
export PATH="$ENV_BIN:$PATH"
OUT="$ROOT/tmp/analysis/mag/MAIZE_ENEBE_2020"
REFDIR="$ROOT/reference_databases/maize_B73_RefGen_v5"
DEP="$OUT/host_depleted"
mkdir -p "$REFDIR" "$DEP" "$OUT/logs"

URL="https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/902/167/145/GCF_902167145.1_Zm-B73-REFERENCE-NAM-5.0/GCF_902167145.1_Zm-B73-REFERENCE-NAM-5.0_genomic.fna.gz"
REF_GZ="$REFDIR/GCF_902167145.1_Zm-B73-REFERENCE-NAM-5.0_genomic.fna.gz"
REF="$REFDIR/GCF_902167145.1_Zm-B73-REFERENCE-NAM-5.0_genomic.fna"
INDEX="$REFDIR/bowtie2/B73_v5"

if [[ ! -s "$REF_GZ" ]]; then
  curl --fail --location --continue-at - --retry 8 --retry-all-errors \
    --output "$REF_GZ" "$URL"
fi
gzip -t "$REF_GZ"
if [[ ! -s "$REF" ]]; then pigz -dc "$REF_GZ" > "$REF"; fi
mkdir -p "$(dirname "$INDEX")"
if [[ ! -s "$INDEX.1.bt2" && ! -s "$INDEX.1.bt2l" ]]; then
  bowtie2-build --threads "$THREADS" "$REF" "$INDEX" > "$OUT/logs/host_bowtie2_build.log" 2>&1
fi

printf 'run_accession\tinput_pairs\tboth_unmapped_pairs\tretained_fraction\treference\n' > "$DEP/host_depletion_summary.tsv"
for run in SRR11128411 SRR11128414 SRR11128415; do
  r1="$OUT/clean/${run}_R1.fastq.gz"
  r2="$OUT/clean/${run}_R2.fastq.gz"
  o1="$DEP/${run}_R1.fastq.gz"
  o2="$DEP/${run}_R2.fastq.gz"
  if [[ ! -s "$o1" || ! -s "$o2" ]]; then
    bowtie2 --very-sensitive -x "$INDEX" -1 "$r1" -2 "$r2" -p "$THREADS" \
      2> "$OUT/logs/host_mapping_${run}.log" | \
      samtools view -@ "$THREADS" -b -f 12 -F 256 - | \
      samtools sort -@ "$THREADS" -n -T "$OUT/${run}.hostsort" - | \
      samtools fastq -@ "$THREADS" -1 "$o1" -2 "$o2" -0 /dev/null -s /dev/null -n - \
      2>> "$OUT/logs/host_mapping_${run}.log"
  fi
  input_pairs=$(gzip -cd "$r1" | awk 'END{print NR/4}')
  kept_pairs=$(gzip -cd "$o1" | awk 'END{print NR/4}')
  retained=$(awk -v k="$kept_pairs" -v i="$input_pairs" 'BEGIN{print (i?k/i:0)}')
  printf '%s\t%s\t%s\t%s\t%s\n' "$run" "$input_pairs" "$kept_pairs" "$retained" "$REF" >> "$DEP/host_depletion_summary.tsv"
done

touch "$DEP/HOST_DEPLETION_COMPLETE"
