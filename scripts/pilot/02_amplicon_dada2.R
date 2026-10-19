#!/usr/bin/env Rscript
# Study-stratified ASV inference for the pilot. PacBio CCS and Illumina paired
# data are processed independently; no cross-platform ASV pooling is allowed.

suppressPackageStartupMessages({
  library(dada2)
  library(data.table)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else Sys.getenv("LITTLEDREAM_ROOT", getwd())
threads <- if (length(args) >= 2) as.integer(args[[2]]) else 8L
study_filter <- if (length(args) >= 3) args[[3]] else ""
meta_path <- file.path(root, "metadata", "sequencing_runs.tsv")
out_root <- file.path(root, "tmp", "analysis", "amplicon")
dir.create(out_root, recursive = TRUE, showWarnings = FALSE)

meta <- fread(meta_path, sep = "\t", na.strings = c("", "NA"), data.table = FALSE)
meta <- meta[meta$sequencing_type == "16S" & meta$download_eligible == "yes", , drop = FALSE]

find_run_files <- function(run, batch) {
  base <- if (batch == "core_a_rice") {
    file.path(root, "raw_data", "16S", "core_a_rice", "INSDC", run)
  } else {
    file.path(root, "raw_data", "16S", "technical_amplicon", "INSDC", run)
  }
  sort(list.files(base, pattern = "\\.(fastq|fq)\\.gz$", full.names = TRUE))
}

write_asv_outputs <- function(seqtab.nochim, study_meta, study_out, tracking) {
  seqs <- colnames(seqtab.nochim)
  asv_ids <- sprintf("ASV%06d", seq_along(seqs))
  count <- as.data.frame(seqtab.nochim, check.names = FALSE)
  colnames(count) <- asv_ids
  count <- cbind(sample_id = rownames(count), count)
  fwrite(count, file.path(study_out, "asv_count.tsv"), sep = "\t")
  fwrite(study_meta, file.path(study_out, "sample_metadata.tsv"), sep = "\t", na = "")
  fwrite(tracking, file.path(study_out, "read_tracking.tsv"), sep = "\t", na = "")
  fasta <- unlist(Map(function(id, seq) c(paste0(">", id), seq), asv_ids, seqs))
  writeLines(fasta, file.path(study_out, "asv_sequences.fasta"), useBytes = TRUE)
  saveRDS(list(seqtab = seqtab.nochim, metadata = study_meta, sequences = setNames(seqs, asv_ids)),
          file.path(study_out, "dada2_result.rds"))
}

process_pacbio <- function(study_meta, study_out) {
  files <- vapply(study_meta$Run_accession, function(run) {
    hits <- find_run_files(run, "core_a_rice")
    if (length(hits) != 1L) stop("Expected one PacBio FASTQ for ", run, "; found ", length(hits))
    hits[[1]]
  }, character(1))
  names(files) <- study_meta$sample_id
  filtered_dir <- file.path(study_out, "filtered")
  dir.create(filtered_dir, recursive = TRUE, showWarnings = FALSE)
  filtered <- file.path(filtered_dir, paste0(names(files), ".fastq.gz"))

  primers <- unique(study_meta[, c("primer_forward", "primer_reverse")])
  if (nrow(primers) != 1L) stop("PacBio study has inconsistent primers")
  # Archive inspection showed that PRJNA725973 begins downstream of 27F and
  # ends upstream of 1492R: the submitter already removed both primers.  A
  # second removePrimers(..., orient=TRUE) therefore discards 100% of reads.
  # Preserve that discrepancy explicitly and do not trim the archive again.
  primer_status <- "archive_reads_already_primer_trimmed"
  ft <- filterAndTrim(files, filtered, maxN = 0, minQ = 3,
                      minLen = 1000, maxLen = 1700,
                      rm.phix = FALSE, compress = TRUE,
                      multithread = threads, verbose = TRUE)
  err <- learnErrors(filtered, errorEstimationFunction = PacBioErrfun,
                     multithread = threads, randomize = TRUE, verbose = TRUE)
  derep <- derepFastq(filtered, verbose = TRUE)
  names(derep) <- names(files)
  dada_out <- dada(derep, err = err, BAND_SIZE = 32,
                   multithread = threads, verbose = TRUE)
  seqtab <- makeSequenceTable(dada_out)
  seqtab.nochim <- removeBimeraDenovo(seqtab, method = "consensus",
                                     multithread = threads, verbose = TRUE)
  getN <- function(x) sum(getUniques(x))
  tracking <- data.frame(
    sample_id = names(files),
    input = ft[, 1], primer_trimmed = ft[, 1], filtered = ft[, 2],
    denoised = vapply(dada_out, getN, numeric(1)),
    nonchim = rowSums(seqtab.nochim), primer_status = primer_status,
    check.names = FALSE
  )
  write_asv_outputs(seqtab.nochim, study_meta, study_out, tracking)
}

process_illumina <- function(study_meta, study_out) {
  cutadapt <- Sys.which("cutadapt")
  if (!nzchar(cutadapt)) stop("cutadapt is not on PATH")
  pairs <- lapply(study_meta$Run_accession, function(run) find_run_files(run, "amplicon_technical"))
  bad <- which(lengths(pairs) != 2L)
  if (length(bad)) stop("Expected two FASTQs for: ", paste(study_meta$Run_accession[bad], collapse = ","))
  fwd <- vapply(pairs, `[[`, character(1), 1L)
  rev <- vapply(pairs, `[[`, character(1), 2L)
  sample_ids <- study_meta$sample_id
  trim_dir <- file.path(study_out, "primer_trimmed")
  filt_dir <- file.path(study_out, "filtered")
  dir.create(trim_dir, recursive = TRUE, showWarnings = FALSE)
  dir.create(filt_dir, recursive = TRUE, showWarnings = FALSE)
  trimF <- file.path(trim_dir, paste0(sample_ids, "_R1.fastq.gz"))
  trimR <- file.path(trim_dir, paste0(sample_ids, "_R2.fastq.gz"))
  filtF <- file.path(filt_dir, paste0(sample_ids, "_R1.fastq.gz"))
  filtR <- file.path(filt_dir, paste0(sample_ids, "_R2.fastq.gz"))
  primers <- unique(study_meta[, c("primer_forward", "primer_reverse")])
  if (nrow(primers) != 1L) stop("Study has inconsistent primers")

  for (i in seq_along(fwd)) {
    status <- system2(cutadapt, c(
      "--discard-untrimmed", "--minimum-length", "50",
      "-g", primers$primer_forward, "-G", primers$primer_reverse,
      "-o", trimF[[i]], "-p", trimR[[i]], fwd[[i]], rev[[i]]
    ), stdout = file.path(study_out, "cutadapt.log"), stderr = file.path(study_out, "cutadapt.log"))
    if (status != 0L) stop("cutadapt failed for ", sample_ids[[i]])
  }
  ft <- filterAndTrim(trimF, filtF, trimR, filtR,
                      maxN = 0, maxEE = c(2, 2), truncQ = 2, minLen = 50,
                      rm.phix = TRUE, compress = TRUE,
                      multithread = threads, verbose = TRUE)
  errF <- learnErrors(filtF, multithread = threads, randomize = TRUE, verbose = TRUE)
  errR <- learnErrors(filtR, multithread = threads, randomize = TRUE, verbose = TRUE)
  derepF <- derepFastq(filtF, verbose = TRUE)
  derepR <- derepFastq(filtR, verbose = TRUE)
  names(derepF) <- names(derepR) <- sample_ids
  dadaF <- dada(derepF, err = errF, multithread = threads, verbose = TRUE)
  dadaR <- dada(derepR, err = errR, multithread = threads, verbose = TRUE)
  mergers <- mergePairs(dadaF, derepF, dadaR, derepR, verbose = TRUE)
  seqtab <- makeSequenceTable(mergers)
  seqtab.nochim <- removeBimeraDenovo(seqtab, method = "consensus",
                                     multithread = threads, verbose = TRUE)
  getN <- function(x) sum(getUniques(x))
  tracking <- data.frame(
    sample_id = sample_ids, input = ft[, 1], filtered = ft[, 2],
    denoisedF = vapply(dadaF, getN, numeric(1)),
    denoisedR = vapply(dadaR, getN, numeric(1)),
    merged = vapply(mergers, getN, numeric(1)),
    nonchim = rowSums(seqtab.nochim), check.names = FALSE
  )
  write_asv_outputs(seqtab.nochim, study_meta, study_out, tracking)
}

studies <- unique(meta$study_id)
if (nzchar(study_filter)) studies <- intersect(studies, study_filter)
if (!length(studies)) stop("No requested study found: ", study_filter)
for (study in studies) {
  message("Processing study: ", study)
  study_meta <- meta[meta$study_id == study, , drop = FALSE]
  study_out <- file.path(out_root, study)
  dir.create(study_out, recursive = TRUE, showWarnings = FALSE)
  log_file <- file.path(study_out, "pipeline.log")
  tryCatch({
    if (all(study_meta$platform == "PACBIO_SMRT")) process_pacbio(study_meta, study_out)
    else process_illumina(study_meta, study_out)
    writeLines("pass", file.path(study_out, "STATUS"))
  }, error = function(e) {
    writeLines(c("fail", conditionMessage(e)), file.path(study_out, "STATUS"))
    message("FAILED ", study, ": ", conditionMessage(e))
  })
}
