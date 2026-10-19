#!/usr/bin/env Rscript
# Same-season yield calculations and conservative integration with 0N departure.

suppressPackageStartupMessages(library(data.table))
args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else Sys.getenv("LITTLEDREAM_ROOT", getwd())
out <- file.path(root, "tmp", "result", "tables")
dir.create(out, recursive = TRUE, showWarnings = FALSE)

y <- fread(file.path(root, "metadata", "yield_digitization.tsv"), sep = "\t")
y2020 <- y[study_id == "RICE_DONG_2021" & season_id == 2020]
y2020[, observed_max_yield := max(yield_t_ha)]
y2020[, relative_yield_observed_max := yield_t_ha / observed_max_yield]
y2020[, yield_gain_vs_zeroN_t_ha := yield_t_ha - yield_t_ha[N_rate_kg_ha_season == 0]]
y2020[, interpretation := "Three digitized treatment means only; descriptive curve, no threshold inference"]
fwrite(y2020, file.path(out, "rice_2020_yield_summary.tsv"), sep = "\t", na = "")

# A quadratic passes through three treatment means and is reported only as a
# visual guide. Its vertex is not treated as an agronomic optimum.
fit <- lm(yield_t_ha ~ N_rate_kg_ha_season + I(N_rate_kg_ha_season^2), data = y2020)
grid <- data.table(N_rate_kg_ha_season = seq(0, 300, by = 5))
grid[, predicted_yield_t_ha := predict(fit, newdata = grid)]
grid[, model_status := "exploratory interpolation; n=3 digitized treatment means"]
fwrite(grid, file.path(out, "rice_2020_yield_curve.tsv"), sep = "\t", na = "")

departure_path <- file.path(out, "zeroN_departure.tsv")
if (file.exists(departure_path)) {
  departure <- fread(departure_path, sep = "\t")
  rice <- departure[study_id == "RICE_DONG_2021",
    .(microbiome_departure_mean = mean(distance_to_zeroN_centroid),
      microbiome_departure_sd = sd(distance_to_zeroN_centroid),
      microbiome_sample_n = .N),
    by = .(study_id, site_id, soil_compartment, N_rate)]
  joint <- merge(rice, y2020[, .(N_rate = N_rate_kg_ha_season, yield_t_ha,
                                 relative_yield_observed_max, yield_gain_vs_zeroN_t_ha)],
                 by = "N_rate", all.x = TRUE)
  joint[, evidence_layer := "Core-A same-season rice; yield is figure-digitized"]
  fwrite(joint, file.path(out, "rice_joint_yield_microbiome.tsv"), sep = "\t", na = "")
}
