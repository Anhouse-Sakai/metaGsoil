# 项目工具变更记录

## 2026-08-12

1. 从 `/mnt/sakai/paperdata/metagenome_downloader_bundle` 建立项目专用副本。
2. 尚未修改源代码。
3. 后续只允许经过审核的逐Run白名单进入下载流程。

## 2026-08-12 - Pilot safety gate

- Added `--run-allowlist` hard gating for explicit SRR/ERR/DRR accessions.
- BioProject expansion and supplementary-discovery are disabled while the gate is active.
- Resolution aborts on unexpected or missing runs.
- ENA output now preserves run/sample/experiment aliases, sample title, instrument model, read count and base count.
- Local syntax test and live ENA resolution test passed; three project batches passed remote resolve-only audit.
