# metaGsoil:农田氮肥—产量—微生物组 Pilot 流程

用公开的 16S / shotgun 数据,检验"氮肥梯度 → 作物产量 → 土壤微生物组"能否在多项研究间建模。
覆盖水稻、玉米、小麦。当前 Pilot 结论 `GO_WITH_MODIFICATIONS`(见 `results/feasibility/feasibility_report.md`)。

## 流程

| 阶段 | 脚本 | 做什么 |
|---|---|---|
| 准入 | `scripts/build_pilot_metadata.py`, `pilot/00_*` | 文献/accession 审计,逐 Run 白名单 |
| 下载 | `tools/metagenome_downloader/` | ENA 下载 + MD5 校验 |
| 质控 | `pilot/01_*` | 大小/MD5/gzip/FASTQ 结构 |
| 16S | `pilot/02*–04*` | 每项研究独立 DADA2、SILVA 注释、alpha/beta、相对 0N 偏离 |
| MAG | `pilot/05a,05b,07,08,10` | 宿主去除、co-assembly、MetaBAT2、dRep、CheckM2、KOfam |
| 收口 | `pilot/06,09,11,13` | 图、报告、机器 QA |

一键顺序见 `scripts/run_pilot.sh`。

## 复用要点

- 项目根目录由环境变量 `LITTLEDREAM_ROOT` 指定,默认当前目录,没有写死路径。
- 环境:`pilot_environment.yml`、`checkm2_environment.yml`,或用 `docker/`(见 `docker/README.md`)。
- 不入库的数据(需自行准备):`raw_data/`(FASTQ)、`reference_databases/`(SILVA 138.2、宿主基因组、CheckM2、KOfam)。
- 设计规则(可按自己项目改写):`数据质控与准入规则.md`、`项目执行补充规则.md`、`最终交付与扩展决策规则.md`。

## 已知局限

- 脚本里 `crop/宿主(B73)/研究 ID` 仍是本 Pilot 的具体设置,换课题需改 `05a`、`00_*` 与元数据。
- 缺 SRA Toolkit 回退(ENA 无直链时失败)。
- `tmp/result/` 下的最终报告与图件未入库(可由脚本重新生成)。
