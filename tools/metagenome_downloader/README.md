# 下载范围说明（修正版）

默认清单现在是：

```text
download_manifest_target.tsv
```

它只包含：

1. Excel主表中的土壤/泥炭shotgun、MAG或可用于MAG重建的数据；
2. 主表中已经标记为“编号疑似错误”“项目号需核实”“样品数不一致”“公开状态待确认”的问题数据——这些仍然会尝试下载；
3. 少数仍属于土壤shotgun候选、且存在具体仓库编号，但仓库中是否包含原始FASTQ尚不确定的数据。

默认**不再尝试下载**：

- 仅16S/ITS等扩增子数据；
- 没有测序的研究；
- 书籍章节、综述、Perspective；
- 海水、非目标沉积物等不属于当前土壤数据范围的样品；
- 只有代谢组/蛋白质组编号的数据；
- 没有任何公开序列号、只能联系作者索取的数据。

旧的 `download_manifest_target.tsv` 仍保留，仅用于极端排查，不是默认下载清单。


# 土壤宏基因组批量下载工具

这套文件由当前 `soil_metagenome_data_catalog.xlsx` 自动生成。

## 文件

- `download_manifest_main.tsv`：只包含主表中的文章。
- `download_manifest_target.tsv`：主表 + “筛选记录”中提到过明确 accession 的文章。
  这会把已知的扩增子、沉积物、海水和可疑编号也纳入尝试，符合“先下载，之后再纠错”的要求。
- `download_all_metagenomes.py`：解析 accession、生成下载清单、下载并校验。
- `run_download.sh`：直接开始下载。
- `submit_download.slurm`：Slurm 服务器提交模板。

## 自动支持

1. **NCBI SRA / ENA / DDBJ 的 INSDC accession**
   - 支持 `PRJNA/PRJEB/SRP/SRA/SRR/ERR/ERS/SAMN...`
   - 优先通过 ENA File Report 获取原始 FASTQ 链接。
   - ENA 无结果时，回退到 `prefetch + fasterq-dump`。
   - 默认不筛除 16S/ITS 等数据；使用 `--metagenomic-only` 才只保留 `METAGENOMIC`。

2. **MG-RAST**
   - 支持 `mgmXXXXXXX.X`、表格里的纯数字 MG-RAST ID，以及 `mgp` 项目号。
   - 自动读取下载文件列表并选择 raw/upload/FASTQ/FASTA 类文件。

3. **Figshare / Zenodo**
   - 下载补充文件。
   - 自动扫描 CSV、TSV、TXT、JSON、XML 和 XLSX 中隐藏的 SRR/ERR/PRJ accession。
   - 发现新 accession 后继续解析和下载。这一步可用于全球 3321 个 SRA 样品清单。

## 暂时进入人工队列

以下数据库通常需要网页交互、账户、验证码、授权令牌，或缺少稳定匿名下载 API：

- CNCB-NGDC GSA：`CRA`、`PRJCA`
- NMDC China：`NMDC...`
- CNGBdb：`CNP...`
- JGI Genome Portal
- ggKbase
- Science Data Bank
- Dryad（保留 DOI，但未假设其文件 API）
- PRIDE（主要为蛋白质组/代谢组，不用于 MAG）

这些条目会写入：

```text
metagenome_downloads/logs/manual_download_queue.tsv
```

## 推荐安装

```bash
mamba create -n meta_download -c conda-forge -c bioconda \
  python=3.11 aria2 sra-tools pigz
mamba activate meta_download
```

脚本本身只使用 Python 标准库。`aria2c` 用于多连接、断点续传；没有 aria2c 时会回退到 curl 或 wget。

## 直接开始下载

```bash
cd metagenome_downloader_bundle
bash run_download.sh /data/metagenome_downloads
```

可设置并发：

```bash
JOBS=6 CONNECTIONS=4 THREADS=24 \
bash run_download.sh /data/metagenome_downloads
```


## MAG 下载清单过滤

解析完成后不要重新解析 DOI；直接基于已有解析结果过滤 MAG 需要的数据：

```bash
python3 filter_mag_downloads.py
```

默认输入优先使用：

```text
logs/resolved_files.tsv
```

如果在当前 bundle 目录运行且没有 `logs/`，会自动读取服务器现有结果：

```text
../data/logs/resolved_files.tsv
```

默认输出到输入文件同目录：

```text
logs/resolved_files_MAG.tsv
```

过滤逻辑：

- `source == ENA:fastq_ftp` 的记录全部保留；
- 其它来源仅保留 `.fastq`、`.fastq.gz`、`.fq`、`.fq.gz`、`.sra`、`.fasta`、`.fa`、`.tar.gz`、`.zip`；
- 删除 PDF、Word、Excel、CSV、图片、HTML、chrlist 等非序列文件；
- 删除 URL 或目标路径中明显属于 supplement、figure、table、readme、protocol、slides 等补充材料的文件。

重新过滤时直接再次运行同一命令即可覆盖生成：

```bash
python3 filter_mag_downloads.py
```

也可以显式指定输入输出：

```bash
python3 filter_mag_downloads.py   --input /mnt/sakai/paperdata/data/logs/resolved_files.tsv   --output /mnt/sakai/paperdata/data/logs/resolved_files_MAG.tsv
```

## 使用过滤后的清单下载

`run_download.sh` 会优先读取已经解析好的文件清单，不会重新解析 DOI。优先级为：

1. 环境变量 `RESOLVED_FILES` 指定的 TSV；
2. `logs/resolved_files_MAG.tsv`；
3. `logs/resolved_files.tsv`；
4. 输出目录下的 `logs/resolved_files_MAG.tsv`；
5. 输出目录下的 `logs/resolved_files.tsv`；
6. 服务器默认数据目录 `../data/logs/resolved_files_MAG.tsv`；
7. 服务器默认数据目录 `../data/logs/resolved_files.tsv`。

开始 MAG 下载：

```bash
bash run_download.sh /mnt/sakai/paperdata/data
```

只验证将使用哪个 TSV 并生成 aria2 输入清单、不真正下载：

```bash
DRY_RUN=1 bash run_download.sh /mnt/sakai/paperdata/data
```

恢复全部下载时，不需要重新解析；直接指定完整解析清单：

```bash
RESOLVED_FILES=/mnt/sakai/paperdata/data/logs/resolved_files.tsv bash run_download.sh /mnt/sakai/paperdata/data
```

如果所有已解析 TSV 都不存在，`run_download.sh` 才会回退到旧的 manifest 工作流。

## 先解析、不下载

强烈建议第一次先查看数据量和错误：

```bash
python3 download_all_metagenomes.py \
  --manifest download_manifest_all_known.tsv \
  --outdir /data/metagenome_downloads \
  --mode resolve
```

解析结果：

```text
logs/resolved_files.tsv
logs/unresolved.tsv
logs/manual_download_queue.tsv
logs/catalogue_rows_without_accessions.tsv
```

然后正式下载：

```bash
python3 download_all_metagenomes.py \
  --manifest download_manifest_all_known.tsv \
  --outdir /data/metagenome_downloads \
  --mode all \
  --jobs 6 \
  --connections 4 \
  --threads 24 \
  --yes
```

## 只下载主表

```bash
python3 download_all_metagenomes.py \
  --manifest download_manifest_main.tsv \
  --outdir /data/metagenome_downloads \
  --mode all \
  --yes
```

## 只保留真正的 shotgun metagenome

```bash
python3 download_all_metagenomes.py \
  --manifest download_manifest_main.tsv \
  --outdir /data/metagenome_downloads \
  --mode all \
  --metagenomic-only \
  --yes
```

## Slurm

修改或设置目录后提交：

```bash
BUNDLE_DIR=$PWD/metagenome_downloader_bundle \
OUTDIR=/data/metagenome_downloads \
sbatch metagenome_downloader_bundle/submit_download.slurm
```

## 输出目录

```text
metagenome_downloads/
├── INSDC/
├── INSDC_SRA_fallback/
├── MGRAST/
├── secondary/
├── sra_cache/
├── tmp/
└── logs/
```

脚本会按 URL 和目标路径去重，并用 ENA/MG-RAST 提供的 MD5 或文件大小进行校验。

## 重要提醒

当前目录包含：

- 数百个时间序列宏基因组；
- 一个包含 3321 个全球土壤宏基因组的汇编数据集；
- 多个几十到上百样品的项目；
- 额外的 MAG 和补充文件。

因此总数据量可能达到多 TB，甚至更高。`resolve` 阶段只会统计数据库明确返回的文件大小，实际总量可能更大。正式下载前应确认磁盘配额、inode 数量和网络策略。


## 按文章建立独立目录

下载完成后，`run_download.sh` 会自动运行：

```bash
python3 organize_by_article.py \
  --manifest download_manifest_all_known.tsv \
  --outdir /data/metagenome_downloads \
  --mode symlink
```

生成结构：

```text
metagenome_downloads/
├── INSDC/                         # 实际文件，只保存一份
├── MGRAST/
├── secondary/
└── by_article/
    ├── ARTICLE_INDEX.tsv
    ├── FILE_INDEX.tsv
    ├── 001_10.1371_journal...__Functional_Assays.../
    │   ├── article_info.tsv
    │   ├── files/
    │   ├── unresolved.tsv
    │   └── manual_download_queue.tsv
    ├── 002_10.1371_journal...__Metagenomic_Insights.../
    └── ...
```

默认使用**符号链接**，因此：

- 每篇文章都有独立目录；
- 同一个原始数据被两篇文章使用时，会同时出现在两个文章目录中；
- 物理文件只下载和保存一份，不会因为重复文章浪费数TB空间。

可用三种组织模式：

```bash
# 推荐：符号链接，不重复占空间
ORGANIZE_MODE=symlink bash run_download.sh /data/metagenome_downloads

# 硬链接，不重复占空间，但要求在同一文件系统
ORGANIZE_MODE=hardlink bash run_download.sh /data/metagenome_downloads

# 真正复制到每篇文章目录，会大量增加磁盘占用
ORGANIZE_MODE=copy bash run_download.sh /data/metagenome_downloads
```

已经下载过数据，也可以单独重新整理，不必重新下载：

```bash
python3 organize_by_article.py \
  --manifest download_manifest_all_known.tsv \
  --outdir /data/metagenome_downloads \
  --mode symlink
```
