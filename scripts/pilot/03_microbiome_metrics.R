#!/usr/bin/env Rscript
# Produces study-separated alpha/beta diversity and distance-to-0N metrics.

suppressPackageStartupMessages({
  library(data.table)
  library(vegan)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else Sys.getenv("LITTLEDREAM_ROOT", getwd())
amp_root <- file.path(root, "tmp", "analysis", "amplicon")
out <- file.path(root, "tmp", "result", "tables")
dir.create(out, recursive = TRUE, showWarnings = FALSE)

alpha_all <- list()
pcoa_all <- list()
departure_all <- list()
permanova_all <- list()
dispersion_all <- list()
raup_all <- list()

bray_to_reference <- function(x, reference) {
  as.numeric(vegdist(rbind(x, reference), method = "bray"))[1]
}

adonis_rows <- function(fit, study, analysis_set, model_role, stratum_id,
                        permutation_scheme, note) {
  if (inherits(fit, "error")) {
    return(data.frame(
      study_id = study, analysis_set = analysis_set, model_role = model_role,
      stratum_id = stratum_id, term = "ERROR", Df = NA, SumOfSqs = NA,
      R2 = NA, F = NA, p_value = NA, permutation_scheme = permutation_scheme,
      note = conditionMessage(fit), stringsAsFactors = FALSE
    ))
  }
  tab <- as.data.frame(fit)
  tab$term <- rownames(tab)
  data.frame(
    study_id = study, analysis_set = analysis_set, model_role = model_role,
    stratum_id = stratum_id, term = tab$term, Df = tab$Df,
    SumOfSqs = tab$SumOfSqs, R2 = tab$R2, F = tab$F,
    p_value = tab$`Pr(>F)`, permutation_scheme = permutation_scheme,
    note = note, row.names = NULL, check.names = FALSE,
    stringsAsFactors = FALSE
  )
}

dispersion_row <- function(distance, groups, study, analysis_set, model_role,
                           stratum_id, note) {
  fit <- tryCatch(betadisper(distance, groups), error = function(e) e)
  if (inherits(fit, "error")) {
    return(data.frame(
      study_id = study, analysis_set = analysis_set, model_role = model_role,
      stratum_id = stratum_id, F = NA, p_value = NA,
      permutation_scheme = "999 unrestricted permutations",
      note = paste("PERMDISP failed:", conditionMessage(fit)),
      stringsAsFactors = FALSE
    ))
  }
  perm <- tryCatch(permutest(fit, permutations = 999), error = function(e) e)
  if (inherits(perm, "error")) {
    return(data.frame(
      study_id = study, analysis_set = analysis_set, model_role = model_role,
      stratum_id = stratum_id, F = NA, p_value = NA,
      permutation_scheme = "999 unrestricted permutations",
      note = paste("PERMDISP permutation test failed:", conditionMessage(perm)),
      stringsAsFactors = FALSE
    ))
  }
  data.frame(
    study_id = study, analysis_set = analysis_set, model_role = model_role,
    stratum_id = stratum_id, F = unname(perm$tab[1, "F"]),
    p_value = unname(perm$tab[1, "Pr(>F)"]),
    permutation_scheme = "999 unrestricted permutations",
    note = note, stringsAsFactors = FALSE
  )
}

all_rds <- list.files(amp_root, pattern = "dada2_tax_filtered_result\\.rds$", recursive = TRUE, full.names = TRUE)
if (!length(all_rds)) all_rds <- list.files(amp_root, pattern = "^dada2_result\\.rds$", recursive = TRUE, full.names = TRUE)
for (rds in all_rds) {
  obj <- readRDS(rds)
  counts <- obj$seqtab
  meta <- obj$metadata
  tracking_path <- file.path(dirname(rds), "read_tracking.tsv")
  tracking <- if (file.exists(tracking_path)) fread(tracking_path, sep = "\t", data.table = FALSE) else NULL
  study <- unique(meta$study_id)
  if (length(study) != 1L) stop("Mixed study in ", rds)
  meta$N_rate <- as.numeric(sub("^N", "", meta$treatment_id))
  meta$replicate <- sub(".*replicate=([^;]+).*", "\\1", meta$notes)
  rownames(meta) <- meta$sample_id
  meta <- meta[rownames(counts), , drop = FALSE]
  keep <- rowSums(counts) > 0
  counts <- counts[keep, , drop = FALSE]
  meta <- meta[keep, , drop = FALSE]
  if (!is.null(tracking)) {
    ti <- match(rownames(counts), tracking$sample_id)
    meta$input_reads <- tracking$input[ti]
    meta$nonchim_reads <- tracking$nonchim[ti]
    meta$read_retention_fraction <- meta$nonchim_reads / meta$input_reads
    meta$read_qc_flag <- ifelse(meta$nonchim_reads >= 1000 & meta$read_retention_fraction >= 0.10,
                               "pass", "caution_low_retention_or_depth")
  } else {
    meta$input_reads <- NA_real_
    meta$nonchim_reads <- rowSums(counts)
    meta$read_retention_fraction <- NA_real_
    meta$read_qc_flag <- "tracking_unavailable"
  }
  rel <- counts / rowSums(counts)

  rarefaction_depth <- min(rowSums(counts))
  set.seed(sum(utf8ToInt(study)) + 1000L)
  rare <- rrarefy(counts, sample = rarefaction_depth)

  alpha <- data.frame(
    study_id = study,
    sample_id = rownames(counts),
    site_id = meta$site_id,
    soil_compartment = meta$soil_compartment,
    N_rate = meta$N_rate,
    replicate = meta$replicate,
    library_size = rowSums(counts),
    input_reads = meta$input_reads,
    read_retention_fraction = meta$read_retention_fraction,
    read_qc_flag = meta$read_qc_flag,
    rarefaction_depth = rarefaction_depth,
    observed_asv = specnumber(rare),
    shannon = diversity(rare, index = "shannon"),
    alpha_note = if (rarefaction_depth < 1000) "low minimum library; interpret cautiously" else "rarefied within study to minimum retained library",
    stringsAsFactors = FALSE
  )
  alpha$delta_shannon_vs_zeroN <- NA_real_
  alpha$delta_observed_asv_vs_zeroN <- NA_real_
  alpha_key <- paste(alpha$site_id, alpha$soil_compartment, sep = "||")
  for (group in unique(alpha_key)) {
    idx <- which(alpha_key == group)
    zero <- idx[alpha$N_rate[idx] == 0]
    if (length(zero)) {
      alpha$delta_shannon_vs_zeroN[idx] <- alpha$shannon[idx] - mean(alpha$shannon[zero])
      alpha$delta_observed_asv_vs_zeroN[idx] <- alpha$observed_asv[idx] - mean(alpha$observed_asv[zero])
    }
  }
  alpha_all[[study]] <- alpha

  dist <- vegdist(rel, method = "bray")
  pcoa <- cmdscale(dist, k = 2, eig = TRUE, add = TRUE)
  variance <- pcoa$eig[pcoa$eig > 0] / sum(pcoa$eig[pcoa$eig > 0])
  pcoa_all[[study]] <- data.frame(
    study_id = study, sample_id = rownames(pcoa$points),
    site_id = meta[rownames(pcoa$points), "site_id"],
    soil_compartment = meta[rownames(pcoa$points), "soil_compartment"],
    N_rate = meta[rownames(pcoa$points), "N_rate"],
    PCoA1 = pcoa$points[, 1], PCoA2 = pcoa$points[, 2],
    PCoA1_variance = variance[[1]], PCoA2_variance = variance[[2]],
    stringsAsFactors = FALSE
  )

  group_key <- paste(meta$site_id, meta$soil_compartment, sep = "||")
  departure <- lapply(unique(group_key), function(group) {
    idx <- which(group_key == group)
    zero <- idx[meta$N_rate[idx] == 0]
    if (!length(zero)) return(NULL)
    reference <- colMeans(rel[zero, , drop = FALSE])
    data.frame(
      study_id = study,
      sample_id = rownames(rel)[idx],
      site_id = meta$site_id[idx],
      soil_compartment = meta$soil_compartment[idx],
      N_rate = meta$N_rate[idx],
      replicate = meta$replicate[idx],
      distance_to_zeroN_centroid = apply(rel[idx, , drop = FALSE], 1, bray_to_reference, reference = reference),
      zeroN_reference_n = length(zero), stringsAsFactors = FALSE
    )
  })
  departure_all[[study]] <- do.call(rbind, departure)

  # Presence/absence Raup-Crick is retained as one exploratory null-model
  # community-assembly layer. Values are standardized to [-1, 1]; it is not
  # presented as betaNTI or as a definitive stochastic/deterministic fraction.
  set.seed(sum(utf8ToInt(study)))
  rc <- raupcrick(counts > 0, null = "r1", nsimul = 999, chase = FALSE)
  rc_mat <- as.matrix(rc) * 2 - 1
  rc_departure <- lapply(unique(group_key), function(group) {
    idx <- which(group_key == group)
    zero <- idx[meta$N_rate[idx] == 0]
    if (!length(zero)) return(NULL)
    values <- vapply(idx, function(i) {
      refs <- if (i %in% zero && length(zero) > 1L) setdiff(zero, i) else zero
      mean(rc_mat[i, refs, drop = TRUE])
    }, numeric(1))
    refs_n <- vapply(idx, function(i) {
      if (i %in% zero && length(zero) > 1L) length(zero) - 1L else length(zero)
    }, integer(1))
    data.frame(
      study_id = study, sample_id = rownames(counts)[idx],
      site_id = meta$site_id[idx], soil_compartment = meta$soil_compartment[idx],
      N_rate = meta$N_rate[idx], replicate = meta$replicate[idx],
      raup_crick_to_zeroN_mean = values,
      zeroN_reference_n = refs_n,
      metric_note = "presence-absence Raup-Crick, 999 null simulations; self-comparisons excluded when possible; exploratory assembly layer",
      stringsAsFactors = FALSE
    )
  })
  raup_all[[study]] <- do.call(rbind, rc_departure)

  perm_meta <- meta
  perm_meta$N_factor <- factor(perm_meta$N_rate)
  # Primary N effect: pool only standardized, study-internal distances and
  # restrict permutations within the relevant site/compartment stratum.  Main
  # effects and N-by-stratum interactions are reported by separate models so a
  # significant interaction cannot silently replace the N main effect.
  perm_meta$stratum <- factor(paste(perm_meta$site_id, perm_meta$soil_compartment, sep = "||"))
  has_strata <- nlevels(perm_meta$stratum) > 1L
  primary_formula <- if (has_strata) dist ~ N_factor + stratum else dist ~ N_factor
  primary <- tryCatch(
    adonis2(primary_formula, data = perm_meta, permutations = 999, by = "margin",
            strata = if (has_strata) perm_meta$stratum else NULL),
    error = function(e) e
  )
  study_perm <- list(adonis_rows(
    primary, study, "all_samples", "primary_N_effect_adjusted_for_stratum", "all",
    if (has_strata) "999 permutations restricted within site||soil_compartment" else "999 unrestricted permutations",
    "Study-internal primary N effect; inspect PERMDISP before location-shift interpretation"
  ))

  # Direct subgroup estimates.  They are descriptive/exploratory in this Pilot
  # and avoid treating rhizosphere/bulk or different sites as one homogeneous
  # sample pool.
  for (level in levels(perm_meta$stratum)) {
    idx <- which(perm_meta$stratum == level)
    sub_meta <- droplevels(perm_meta[idx, , drop = FALSE])
    if (length(idx) >= 6L && nlevels(sub_meta$N_factor) >= 2L) {
      sub_dist <- as.dist(as.matrix(dist)[idx, idx, drop = FALSE])
      subgroup <- tryCatch(
        adonis2(sub_dist ~ N_factor, data = sub_meta, permutations = 999, by = "margin"),
        error = function(e) e
      )
      study_perm[[length(study_perm) + 1L]] <- adonis_rows(
        subgroup, study, "all_samples", "subgroup_N_effect", level,
        "999 unrestricted permutations within stratum",
        "Exploratory study/site/compartment-specific N effect"
      )
    }
  }

  if (has_strata && all(table(perm_meta$N_factor, perm_meta$stratum) >= 2L)) {
    interaction <- tryCatch(
      adonis2(dist ~ N_factor * stratum, data = perm_meta, permutations = 999,
              by = "margin", strata = perm_meta$stratum),
      error = function(e) e
    )
    study_perm[[length(study_perm) + 1L]] <- adonis_rows(
      interaction, study, "all_samples", "N_by_stratum_interaction", "all",
      "999 permutations restricted within site||soil_compartment; interaction term only",
      "Exploratory direct interaction test; do not infer difference from separate significance"
    )
  }
  permanova_all[[study]] <- rbindlist(study_perm, fill = TRUE)

  qc_idx <- which(perm_meta$read_qc_flag == "pass")
  if (length(qc_idx) >= 6 && length(unique(perm_meta$N_factor[qc_idx])) >= 2) {
    qc_dist <- as.dist(as.matrix(dist)[qc_idx, qc_idx, drop = FALSE])
    qc_meta <- droplevels(perm_meta[qc_idx, , drop = FALSE])
    qc_meta$stratum <- factor(paste(qc_meta$site_id, qc_meta$soil_compartment, sep = "||"))
    qc_has_strata <- nlevels(qc_meta$stratum) > 1L
    qc_formula <- if (qc_has_strata) qc_dist ~ N_factor + stratum else qc_dist ~ N_factor
    qc_perm <- tryCatch(
      adonis2(qc_formula, data = qc_meta, permutations = 999, by = "margin",
              strata = if (qc_has_strata) qc_meta$stratum else NULL),
      error = function(e) e
    )
    permanova_all[[paste0(study, "_qc")]] <- adonis_rows(
      qc_perm, study, "QC_pass_retention_ge_0.10_and_nonchim_ge_1000",
      "primary_N_effect_adjusted_for_stratum", "all",
      if (qc_has_strata) "999 permutations restricted within site||soil_compartment" else "999 unrestricted permutations",
      paste("QC sensitivity; retained", length(qc_idx), "samples; inspect PERMDISP")
    )
  }

  study_disp <- list(dispersion_row(
    dist, perm_meta$N_factor, study, "all_samples", "overall_N_dispersion", "all",
    "PERMDISP by N rate across the balanced study design; inspect stratum-specific rows"
  ))
  for (level in levels(perm_meta$stratum)) {
    idx <- which(perm_meta$stratum == level)
    sub_meta <- droplevels(perm_meta[idx, , drop = FALSE])
    if (length(idx) >= 6L && nlevels(sub_meta$N_factor) >= 2L) {
      sub_dist <- as.dist(as.matrix(dist)[idx, idx, drop = FALSE])
      study_disp[[length(study_disp) + 1L]] <- dispersion_row(
        sub_dist, sub_meta$N_factor, study, "all_samples",
        "subgroup_N_dispersion", level,
        "Stratum-specific PERMDISP by N rate"
      )
    }
  }
  if (length(qc_idx) >= 6L && nlevels(droplevels(perm_meta$N_factor[qc_idx])) >= 2L) {
    qc_dist <- as.dist(as.matrix(dist)[qc_idx, qc_idx, drop = FALSE])
    qc_meta <- droplevels(perm_meta[qc_idx, , drop = FALSE])
    study_disp[[length(study_disp) + 1L]] <- dispersion_row(
      qc_dist, qc_meta$N_factor, study,
      "QC_pass_retention_ge_0.10_and_nonchim_ge_1000",
      "overall_N_dispersion", "all",
      paste("QC sensitivity PERMDISP; retained", length(qc_idx), "samples")
    )
    for (level in levels(qc_meta$stratum)) {
      local_idx <- which(qc_meta$stratum == level)
      local_meta <- droplevels(qc_meta[local_idx, , drop = FALSE])
      if (length(local_idx) >= 6L && nlevels(local_meta$N_factor) >= 2L) {
        local_dist <- as.dist(as.matrix(qc_dist)[local_idx, local_idx, drop = FALSE])
        study_disp[[length(study_disp) + 1L]] <- dispersion_row(
          local_dist, local_meta$N_factor, study,
          "QC_pass_retention_ge_0.10_and_nonchim_ge_1000",
          "subgroup_N_dispersion", level,
          paste("QC sensitivity stratum-specific PERMDISP; retained", length(local_idx), "samples")
        )
      }
    }
  }
  dispersion_all[[study]] <- rbindlist(study_disp, fill = TRUE)
}

fwrite(rbindlist(alpha_all, fill = TRUE), file.path(out, "alpha_diversity.tsv"), sep = "\t", na = "")
fwrite(rbindlist(pcoa_all, fill = TRUE), file.path(out, "bray_pcoa.tsv"), sep = "\t", na = "")
fwrite(rbindlist(departure_all, fill = TRUE), file.path(out, "zeroN_departure.tsv"), sep = "\t", na = "")
fwrite(rbindlist(permanova_all, fill = TRUE), file.path(out, "permanova.tsv"), sep = "\t", na = "")
fwrite(rbindlist(dispersion_all, fill = TRUE), file.path(out, "permdisp.tsv"), sep = "\t", na = "")
fwrite(rbindlist(raup_all, fill = TRUE), file.path(out, "raup_crick_zeroN.tsv"), sep = "\t", na = "")
