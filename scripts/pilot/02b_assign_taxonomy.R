#!/usr/bin/env Rscript
# Study-independent SILVA assignment and explicit organelle/non-bacterial filter.

suppressPackageStartupMessages({
  library(dada2)
  library(data.table)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else Sys.getenv("LITTLEDREAM_ROOT", getwd())
reference <- if (length(args) >= 2) normalizePath(args[[2]], mustWork = TRUE) else
  file.path(root, "reference_databases", "silva", "silva_nr99_v138.2_toSpecies_trainset.fa.gz")
threads <- if (length(args) >= 3) as.integer(args[[3]]) else 16L
amp_root <- file.path(root, "tmp", "analysis", "amplicon")

summaries <- list()
composition <- list()
for (rds in list.files(amp_root, pattern = "^dada2_result\\.rds$", recursive = TRUE, full.names = TRUE)) {
  study_out <- dirname(rds)
  obj <- readRDS(rds)
  seqs <- unname(obj$sequences)
  asv_ids <- names(obj$sequences)
  message("Assigning SILVA taxonomy: ", basename(study_out), " (", length(seqs), " ASVs)")
  tax <- assignTaxonomy(seqs, reference, multithread = threads, tryRC = TRUE,
                        minBoot = 50, outputBootstraps = TRUE)
  taxmat <- tax$tax
  boots <- tax$boot
  taxdf <- data.frame(ASV = asv_ids, sequence = seqs, taxmat,
                      min_bootstrap = apply(boots, 1, function(x) if (all(is.na(x))) NA_real_ else min(x, na.rm = TRUE)),
                      stringsAsFactors = FALSE, check.names = FALSE)
  rank_text <- apply(taxmat, 1, function(x) paste(na.omit(x), collapse = ";"))
  kingdom <- if ("Kingdom" %in% colnames(taxmat)) taxmat[, "Kingdom"] else taxmat[, 1]
  taxdf$filter_reason <- ""
  taxdf$filter_reason[is.na(kingdom) | kingdom != "Bacteria"] <- "non_bacterial_or_unassigned_kingdom"
  organelle <- grepl("chloroplast|mitochond", rank_text, ignore.case = TRUE)
  taxdf$filter_reason[organelle] <- "chloroplast_or_mitochondria"
  taxdf$retained <- taxdf$filter_reason == ""
  fwrite(taxdf, file.path(study_out, "taxonomy_silva138_2.tsv"), sep = "\t", na = "")

  keep_seq <- seqs[taxdf$retained]
  filtered <- obj$seqtab[, colnames(obj$seqtab) %in% keep_seq, drop = FALSE]
  filtered_ids <- asv_ids[taxdf$retained]
  filtered_seqs <- seqs[taxdf$retained]
  id_by_seq <- setNames(filtered_ids, filtered_seqs)
  count <- as.data.frame(filtered, check.names = FALSE)
  colnames(count) <- unname(id_by_seq[colnames(filtered)])
  count <- cbind(sample_id = rownames(count), count)
  fwrite(count, file.path(study_out, "asv_count_taxonomy_filtered.tsv"), sep = "\t")
  saveRDS(list(seqtab = filtered, metadata = obj$metadata,
               sequences = setNames(filtered_seqs, filtered_ids), taxonomy = taxdf),
          file.path(study_out, "dada2_tax_filtered_result.rds"))
  if ("Phylum" %in% names(taxdf)) {
    phylum_by_seq <- setNames(taxdf$Phylum, taxdf$sequence)
    phylum_by_seq[is.na(phylum_by_seq) | phylum_by_seq == ""] <- "Unclassified_Bacteria"
    phyla <- sort(unique(phylum_by_seq[colnames(filtered)]))
    rows <- lapply(seq_len(nrow(filtered)), function(i) {
      totals <- tapply(filtered[i, ], phylum_by_seq[colnames(filtered)], sum)
      sid <- rownames(filtered)[i]
      mi <- match(sid, obj$metadata$sample_id)
      data.frame(study_id = basename(study_out), sample_id = sid,
                 site_id = obj$metadata$site_id[mi],
                 soil_compartment = obj$metadata$soil_compartment[mi],
                 N_rate = as.numeric(sub("^N", "", obj$metadata$treatment_id[mi])),
                 rank = "Phylum", taxon = names(totals), count = as.numeric(totals),
                 relative_abundance = as.numeric(totals) / sum(filtered[i, ]),
                 stringsAsFactors = FALSE)
    })
    composition[[basename(study_out)]] <- rbindlist(rows, fill = TRUE)
  }
  summaries[[basename(study_out)]] <- data.frame(
    study_id = basename(study_out), reference = reference,
    input_asv = nrow(taxdf), retained_asv = sum(taxdf$retained),
    filtered_non_bacterial = sum(taxdf$filter_reason == "non_bacterial_or_unassigned_kingdom"),
    filtered_organelle = sum(taxdf$filter_reason == "chloroplast_or_mitochondria"),
    input_reads = sum(obj$seqtab), retained_reads = sum(filtered),
    retained_read_fraction = sum(filtered) / sum(obj$seqtab),
    stringsAsFactors = FALSE
  )
}
fwrite(rbindlist(summaries, fill = TRUE), file.path(amp_root, "taxonomy_filter_summary.tsv"), sep = "\t", na = "")
fwrite(rbindlist(composition, fill = TRUE), file.path(amp_root, "taxonomic_composition.tsv"), sep = "\t", na = "")
result_tables <- file.path(root, "tmp", "result", "tables")
dir.create(result_tables, recursive = TRUE, showWarnings = FALSE)
fwrite(rbindlist(summaries, fill = TRUE), file.path(result_tables, "taxonomy_filter_summary.tsv"), sep = "\t", na = "")
fwrite(rbindlist(composition, fill = TRUE), file.path(result_tables, "taxonomic_composition.tsv"), sep = "\t", na = "")
