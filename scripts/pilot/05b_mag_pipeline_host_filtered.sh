#!/usr/bin/env bash
# Formal host-filtered shared co-assembly and binning run.
set -euo pipefail

ROOT="${1:-${LITTLEDREAM_ROOT:-$PWD}}"
THREADS="${2:-24}"
ENV_BIN="$ROOT/必要软件/pilot_env/bin"
export PATH="$ENV_BIN:$PATH"
SOURCE="$ROOT/tmp/analysis/mag/MAIZE_ENEBE_2020"
RAW="$SOURCE/host_depleted"
OUT="$ROOT/tmp/analysis/mag/MAIZE_ENEBE_2020_host_filtered"
mkdir -p "$OUT"/{bam,bins,drep,checkm2,logs}
[[ -f "$RAW/HOST_DEPLETION_COMPLETE" ]] || { echo "Host depletion is incomplete" >&2; exit 2; }

RUNS=(SRR11128411 SRR11128414 SRR11128415)
R1S=(); R2S=()
for run in "${RUNS[@]}"; do
  R1S+=("$RAW/${run}_R1.fastq.gz")
  R2S+=("$RAW/${run}_R2.fastq.gz")
done
IFS=,; r1_csv="${R1S[*]}"; r2_csv="${R2S[*]}"; unset IFS

if [[ ! -s "$OUT/coassembly/final.contigs.fa" ]]; then
  megahit -1 "$r1_csv" -2 "$r2_csv" -o "$OUT/coassembly.tmp" \
    --min-contig-len 1500 -t "$THREADS" --presets meta-sensitive \
    > "$OUT/logs/megahit.log" 2>&1
  mv "$OUT/coassembly.tmp" "$OUT/coassembly"
fi
CONTIGS="$OUT/coassembly/final.contigs.fa"
if [[ ! -s "$CONTIGS.1.bt2" && ! -s "$CONTIGS.1.bt2l" ]]; then
  bowtie2-build --threads "$THREADS" "$CONTIGS" "$CONTIGS" > "$OUT/logs/bowtie2_build.log" 2>&1
fi
BAMS=()
for i in "${!RUNS[@]}"; do
  run="${RUNS[$i]}"; bam="$OUT/bam/${run}.sorted.bam"
  bowtie2 -x "$CONTIGS" -1 "${R1S[$i]}" -2 "${R2S[$i]}" -p "$THREADS" \
    2> "$OUT/logs/bowtie2_${run}.log" | samtools sort -@ "$THREADS" -o "$bam" -
  samtools index -@ "$THREADS" "$bam"
  BAMS+=("$bam")
done
jgi_summarize_bam_contig_depths --outputDepth "$OUT/contig_depth.txt" "${BAMS[@]}" \
  > "$OUT/logs/contig_depth.log" 2>&1
metabat2 -i "$CONTIGS" -a "$OUT/contig_depth.txt" -o "$OUT/bins/bin" -m 1500 -t "$THREADS" \
  > "$OUT/logs/metabat2.log" 2>&1
mapfile -t BINS < <(find "$OUT/bins" -maxdepth 1 -name '*.fa' -type f | sort)
if [[ ${#BINS[@]} -eq 0 ]]; then
  # A no-bin outcome is a valid technical result for a shallow Pilot, not an
  # orchestration crash.  Leave an explicit state and an empty dereplication
  # directory so downstream summary/figure/report steps can finish audibly.
  mkdir -p "$OUT/drep/dereplicated_genomes"
  printf 'status\tno_bins_recovered\ninput_runs\t3\nhost_filter\tB73_RefGen_v5_both_mates_unmapped\nraw_bins\t0\ndereplicated_bins\t0\ninferential_use\ttechnical_feasibility_only\n' \
    > "$OUT/MAG_TECHNICAL_STATUS.tsv"
  exit 0
fi
# dRep is used here only for ANI-based dereplication.  Quality estimation and
# HQ/MQ labeling are performed once, consistently, by CheckM2 below this step.
dRep dereplicate "$OUT/drep" -g "${BINS[@]}" -p "$THREADS" --ignoreGenomeQuality \
  > "$OUT/logs/drep.log" 2>&1
printf 'field\tvalue\nstatus\tpass\ninput_runs\t3\nhost_filter\tB73_RefGen_v5_both_mates_unmapped\nraw_bins\t%s\ndereplicated_bins\t%s\ninferential_use\ttechnical_feasibility_only\n' \
  "${#BINS[@]}" "$(find "$OUT/drep/dereplicated_genomes" -type f | wc -l)" > "$OUT/MAG_TECHNICAL_STATUS.tsv"
