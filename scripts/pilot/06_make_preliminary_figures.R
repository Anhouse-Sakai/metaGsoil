#!/usr/bin/env Rscript
# R-only figure backend selected under the nature-figure contract.
# Core conclusion: the Pilot can visualize study-internal N trajectories, but
# the available evidence supports only descriptive, study-specific patterns.
# Archetype: quantitative grid.  Evidence chain: yield -> 0N community
# departure -> exploratory assembly -> shotgun function -> MAG abundance.
# All panels trace to TSV source data, show n/statistical boundaries, and are
# exported as editable SVG/PDF plus 600-dpi PNG previews.

suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(patchwork)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else Sys.getenv("LITTLEDREAM_ROOT", getwd())
tables <- file.path(root, "tmp", "result", "tables")
figdir <- file.path(root, "tmp", "result", "可视化result", "补充图")
dir.create(figdir, recursive = TRUE, showWarnings = FALSE)

palette_n <- c(`0` = "#4D4D4D", `60` = "#6C8EBF", `120` = "#5B9BD5",
               `150` = "#2E75B6", `180` = "#70AD47", `240` = "#ED7D31",
               `300` = "#C00000", `360` = "#7030A0")
theme_pilot <- theme_bw(base_size = 9, base_family = "Arial") +
  theme(panel.grid.minor = element_blank(), panel.grid.major = element_line(linewidth = 0.25, colour = "#E6E6E6"),
        axis.title = element_text(colour = "#222222"), axis.text = element_text(colour = "#222222"),
        strip.background = element_rect(fill = "#F3F3F3", colour = "#777777", linewidth = 0.3),
        plot.title = element_text(face = "bold", size = 10), legend.position = "bottom")
save_pair <- function(plot, stem, width, height) {
  if (!requireNamespace("svglite", quietly = TRUE)) stop("R package svglite is required for editable SVG export")
  svglite::svglite(file.path(figdir, paste0(stem, ".svg")), width = width, height = height)
  print(plot)
  dev.off()
  grDevices::cairo_pdf(file.path(figdir, paste0(stem, ".pdf")), width = width, height = height,
                       family = "sans")
  print(plot)
  dev.off()
  ggsave(file.path(figdir, paste0(stem, ".png")), plot, width = width, height = height,
         units = "in", dpi = 600, bg = "white")
}

alpha_path <- file.path(tables, "alpha_diversity.tsv")
pcoa_path <- file.path(tables, "bray_pcoa.tsv")
departure_path <- file.path(tables, "zeroN_departure.tsv")
yield_path <- file.path(tables, "rice_2020_yield_summary.tsv")
joint_path <- file.path(tables, "rice_joint_yield_microbiome.tsv")
raup_path <- file.path(tables, "raup_crick_zeroN.tsv")
mag_abundance_path <- file.path(tables, "mag_abundance.tsv")
mag_traits_path <- file.path(tables, "mag_traits.tsv")
shotgun_function_path <- file.path(tables, "shotgun_function.tsv")
permanova_path <- file.path(tables, "permanova.tsv")
permdisp_path <- file.path(tables, "permdisp.tsv")

fmt_p <- function(x) {
  if (length(x) == 0L || is.na(x)) return("NA")
  if (x < 0.001) return("<0.001")
  sprintf("%.3f", x)
}
study_stats <- data.table(study_id = character(), stats_label = character())
if (file.exists(permanova_path) && file.exists(permdisp_path)) {
  perm <- fread(permanova_path)
  disp <- fread(permdisp_path)
  required_perm <- c("study_id", "analysis_set", "model_role", "term", "R2", "p_value")
  required_disp <- c("study_id", "analysis_set", "model_role", "stratum_id", "p_value")
  if (all(required_perm %in% names(perm)) && all(required_disp %in% names(disp))) {
    p1 <- perm[analysis_set == "all_samples" &
                 model_role == "primary_N_effect_adjusted_for_stratum" & term == "N_factor",
               .SD[1], by = study_id]
    d1 <- disp[analysis_set == "all_samples" & model_role == "overall_N_dispersion" &
                 stratum_id == "all", .SD[1], by = study_id]
    study_stats <- merge(
      p1[, .(study_id, permanova_R2 = R2, permanova_p = p_value)],
      d1[, .(study_id, permdisp_p = p_value)], by = "study_id", all = TRUE
    )
    study_stats[, stats_label := sprintf(
      "PERMANOVA N: R²=%.3f, P=%s\nPERMDISP N: P=%s",
      permanova_R2, vapply(permanova_p, fmt_p, character(1)),
      vapply(permdisp_p, fmt_p, character(1))
    )]
  }
}

if (file.exists(alpha_path) && file.exists(pcoa_path)) {
  alpha <- fread(alpha_path)
  alpha[, N_rate_f := factor(N_rate, levels = sort(unique(N_rate)))]
  pcoa <- fread(pcoa_path)
  pcoa[, N_rate_f := factor(N_rate, levels = sort(unique(N_rate)))]
  pcoa_ann <- pcoa[, .(
    PCoA1_variance = first(PCoA1_variance), PCoA2_variance = first(PCoA2_variance), n = .N
  ), by = study_id]
  pcoa_ann <- merge(pcoa_ann, study_stats[, .(study_id, stats_label)], by = "study_id", all.x = TRUE)
  pcoa_ann[, annotation := sprintf(
    "PCoA1 %.1f%%; PCoA2 %.1f%%\nn=%d\n%s",
    100 * PCoA1_variance, 100 * PCoA2_variance, n,
    fifelse(is.na(stats_label), "Statistics pending", stats_label)
  )]
  p1 <- ggplot(pcoa, aes(PCoA1, PCoA2, colour = N_rate_f, shape = soil_compartment)) +
    geom_point(size = 2.2, alpha = 0.85) +
    geom_label(data = pcoa_ann, aes(x = -Inf, y = Inf, label = annotation), inherit.aes = FALSE,
               hjust = -0.04, vjust = 1.04, size = 2.15, linewidth = 0.18,
               fill = scales::alpha("white", 0.88), label.padding = grid::unit(0.10, "lines")) +
    facet_wrap(~study_id, scales = "free") +
    scale_colour_manual(values = palette_n, drop = FALSE) +
    labs(title = "A  Bray–Curtis community ordination", x = "PCoA axis 1", y = "PCoA axis 2",
         colour = expression(N~rate~(kg~ha^{-1})), shape = "Compartment") + theme_pilot
  p2 <- ggplot(alpha, aes(N_rate_f, shannon, colour = N_rate_f)) +
    geom_boxplot(width = 0.62, outlier.shape = NA, linewidth = 0.35) +
    geom_jitter(width = 0.12, size = 1.35, alpha = 0.75) +
    facet_grid(soil_compartment ~ study_id, scales = "free_x", space = "free_x") +
    scale_colour_manual(values = palette_n, guide = "none", drop = FALSE) +
    labs(title = "B  Within-sample diversity", x = expression(N~rate~(kg~ha^{-1})), y = "Shannon diversity") +
    theme_pilot
  combined <- p1 / p2 + plot_layout(heights = c(1, 1.1))
  save_pair(combined, "Supplementary_Figure_1_amplicon_pilot_overview", 9.0, 7.0)
}

if (file.exists(departure_path)) {
  dep <- fread(departure_path)
  dep[, N_rate_f := factor(N_rate, levels = sort(unique(N_rate)))]
  dep_ann <- dep[, .(n = .N), by = .(study_id, soil_compartment)]
  dep_ann <- merge(dep_ann, study_stats[, .(study_id, stats_label)], by = "study_id", all.x = TRUE)
  dep_ann[, annotation := sprintf(
    "n=%d\n%s", n, fifelse(is.na(stats_label), "Statistics pending", stats_label)
  )]
  p <- ggplot(dep, aes(N_rate_f, distance_to_zeroN_centroid, colour = N_rate_f)) +
    geom_hline(yintercept = 0, colour = "#999999", linewidth = 0.3) +
    geom_boxplot(width = 0.6, outlier.shape = NA, linewidth = 0.35) +
    geom_jitter(width = 0.1, size = 1.45, alpha = 0.8) +
    geom_label(data = dep_ann, aes(x = -Inf, y = Inf, label = annotation), inherit.aes = FALSE,
               hjust = -0.04, vjust = 1.04, size = 2.05, linewidth = 0.18,
               fill = scales::alpha("white", 0.88), label.padding = grid::unit(0.08, "lines")) +
    facet_grid(soil_compartment ~ study_id, scales = "free_x", space = "free_x") +
    scale_colour_manual(values = palette_n, guide = "none", drop = FALSE) +
    labs(title = "Microbiome departure from the zero-N reference centroid",
         subtitle = "Primary PERMANOVA adjusts for site/compartment; PERMDISP is shown; no global inference",
         x = expression(N~rate~(kg~ha^{-1})), y = "Bray–Curtis distance to zero-N centroid") + theme_pilot
  save_pair(p, "Figure_2_N_rate_vs_microbiome_departure", 9.0, 4.8)
}

if (file.exists(raup_path)) {
  rc <- fread(raup_path)
  rc[, N_rate_f := factor(N_rate, levels = sort(unique(N_rate)))]
  rc_ann <- rc[, .(annotation = sprintf("n=%d\nDescriptive only; no inferential test", .N)),
               by = .(study_id, soil_compartment)]
  p <- ggplot(rc, aes(N_rate_f, raup_crick_to_zeroN_mean, colour = N_rate_f)) +
    geom_hline(yintercept = 0, colour = "#777777", linewidth = 0.35, linetype = 2) +
    geom_boxplot(width = 0.6, outlier.shape = NA, linewidth = 0.35) +
    geom_jitter(width = 0.1, size = 1.4, alpha = 0.8) +
    geom_label(data = rc_ann, aes(x = -Inf, y = Inf, label = annotation), inherit.aes = FALSE,
               hjust = -0.04, vjust = 1.04, size = 2.05, linewidth = 0.18,
               fill = scales::alpha("white", 0.88), label.padding = grid::unit(0.08, "lines")) +
    facet_grid(soil_compartment ~ study_id, scales = "free_x", space = "free_x") +
    scale_colour_manual(values = palette_n, guide = "none", drop = FALSE) +
    labs(title = "Exploratory null-model community assembly response",
         subtitle = "Presence–absence Raup–Crick departure relative to zero-N samples; 999 simulations",
         x = expression(N~rate~(kg~ha^{-1})), y = "Mean standardized Raup–Crick to zero-N") + theme_pilot
  save_pair(p, "Figure_3_N_rate_vs_community_assembly", 9.0, 4.8)
}

if (file.exists(yield_path)) {
  y <- fread(yield_path)
  p_y <- ggplot(y, aes(N_rate_kg_ha_season, relative_yield_observed_max)) +
    geom_line(linewidth = 0.65, colour = "#2E75B6") + geom_point(size = 2.5, colour = "#2E75B6") +
    scale_x_continuous(breaks = y$N_rate_kg_ha_season) +
    labs(title = "A  Rice grain yield (2020)", subtitle = "Three approximate digitized treatment means; no inferential test",
         x = expression(N~rate~(kg~ha^{-1})), y = "Relative yield (observed maximum = 1)") + theme_pilot
  save_pair(p_y, "Figure_1_N_rate_vs_relative_yield", 4.7, 3.8)
  if (file.exists(joint_path)) {
    joint <- fread(joint_path)
    p_m <- ggplot(joint, aes(N_rate, microbiome_departure_mean, colour = soil_compartment)) +
      geom_line(linewidth = 0.65) + geom_point(size = 2.3) +
      geom_errorbar(aes(ymin = pmax(0, microbiome_departure_mean - microbiome_departure_sd),
                        ymax = microbiome_departure_mean + microbiome_departure_sd), width = 8, linewidth = 0.35) +
      scale_colour_manual(values = c("bulk soil" = "#4E79A7", rhizosphere = "#E15759")) +
      scale_x_continuous(breaks = sort(unique(joint$N_rate))) +
      labs(title = "B  Same-season microbiome departure", x = expression(N~rate~(kg~ha^{-1})),
           y = "Mean Bray–Curtis distance to zero-N centroid", colour = "Compartment") + theme_pilot
    # In the two-panel layout the full single-panel subtitle can extend into
    # panel B.  Wrap it explicitly and give the combined figure modestly more
    # horizontal/vertical room; no data or statistical layer is changed.
    p_y_joint <- p_y +
      labs(subtitle = "Three approximate digitized treatment means;\nno inferential test") +
      theme(plot.subtitle = element_text(size = 8, lineheight = 1.05))
    save_pair(p_y_joint + p_m + plot_layout(widths = c(1.0, 1.15)),
              "Supplementary_Figure_2_rice_same_season_joint", 9.0, 4.0)
  }
}

if (file.exists(shotgun_function_path)) {
  sf <- fread(shotgun_function_path)
  if (nrow(sf)) {
    p <- ggplot(sf, aes(N_rate, relative_abundance, colour = function_group, group = function_group)) +
      geom_line(linewidth = 0.65) + geom_point(size = 2.2) +
      labs(title = "Shotgun functional response (technical layer)",
           subtitle = "n=1 per treatment and NPK-confounded; no inferential statistics",
           x = expression(NPK~nominal~N~rate~(kg~ha^{-1})), y = "Mapped relative abundance",
           colour = "Function") + theme_pilot
  } else {
    p <- ggplot() + annotate("text", x = 0, y = 0,
      label = "No targeted KOfam function passed the declared hit criteria",
      size = 3.2) + xlim(-1, 1) + ylim(-1, 1) +
      labs(title = "Shotgun functional response (technical layer)",
           subtitle = "Empty result is reported explicitly; n=1 per NPK-confounded treatment") +
      theme_pilot + theme(axis.title = element_blank(), axis.text = element_blank(), axis.ticks = element_blank())
  }
  save_pair(p, "Figure_4_N_rate_vs_shotgun_function", 5.6, 4.2)
}

if (file.exists(mag_abundance_path) && file.exists(mag_traits_path)) {
  ma <- fread(mag_abundance_path)
  mt <- fread(mag_traits_path)
  if (nrow(ma) && nrow(mt)) {
    keep <- ma[, .(max_abundance = max(relative_abundance)), by = mag_id][order(-max_abundance)][1:min(.N, 20), mag_id]
    plot_data <- merge(ma[mag_id %in% keep], mt[, .(mag_id, genome_size_bp, gc_fraction)], by = "mag_id")
    p <- ggplot(plot_data, aes(N_rate, relative_abundance, group = mag_id, colour = gc_fraction)) +
      geom_line(alpha = 0.55, linewidth = 0.45) + geom_point(size = 1.6) +
      scale_colour_gradient(low = "#2C7BB6", high = "#D7191C", labels = scales::percent_format(accuracy = 1)) +
      labs(title = "Top MAG abundance patterns across nominal NPK treatments",
           subtitle = "Shared study co-assembly; top 20 by maximum abundance; n=1 per treatment; technical only",
           x = expression(NPK~nominal~N~rate~(kg~ha^{-1})), y = "Within-sample relative MAG abundance",
           colour = "MAG GC") + theme_pilot
  } else {
    p <- ggplot() + annotate("text", x = 0, y = 0,
      label = "No dereplicated MAG was available for abundance plotting",
      size = 3.2) + xlim(-1, 1) + ylim(-1, 1) +
      labs(title = "MAG abundance patterns (technical layer)",
           subtitle = "Empty result is reported explicitly; no biological inference") +
      theme_pilot + theme(axis.title = element_blank(), axis.text = element_blank(), axis.ticks = element_blank())
  }
  save_pair(p, "Figure_5_N_rate_vs_MAG_trait_abundance", 6.2, 4.5)
}
