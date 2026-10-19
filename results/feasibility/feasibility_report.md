# 全球农田氮肥—产量—微生物组小数据集 Pilot 可行性评估

更新日期：2026-08-14  
项目根目录：`/mnt/sakai/littledream`

## 最终建议

# GO_WITH_MODIFICATIONS

可以开始扩大“文献发现、全文核验、补充材料提取、accession 审计和处理/Run 映射”，但现在不应启动全球尺度原始测序批量下载，也不应开始跨研究联合建模。

原因很直接：本轮 28 篇发现记录中只有 4 项完成了足以进入下载层的文章—归档—处理映射核验；其中只有 1 个研究满足 Core-A（同季 N + yield + raw 16S），Core-B 和 Core-AB 都是 0。这个数量触发锁定方案的停止规则 `Core-A < 5`。但是下载器硬闸门、三种 16S 数据处理、0N 参照指标和 study/site co-assembly 技术链已经能够被实际检验，因此继续扩大高质量元数据收集是合理的。

## 1. 文献发现

### 数量与作物

- 发现记录：28 篇。
- 研究范围内记录：27 篇；另有 1 篇 switchgrass，保留审计痕迹但明确排除。
- 文章标签分布：玉米 12、小麦 10、水稻 3、小麦—水稻轮作 2、switchgrass 1。
- 这不是最终纳入分布：其中 24 篇仍处于 `candidate_not_fully_audited`，空白字段表示未知。

### 期刊分布

| 期刊 | 篇数 |
|---|---:|
| Frontiers in Microbiology | 5 |
| Scientific Reports | 4 |
| Applied Soil Ecology | 3 |
| Microbiome | 2 |
| Agronomy | 2 |
| Frontiers in Plant Science | 2 |
| Microorganisms | 2 |
| 其他 8 种期刊 | 各 1 |

### JIF 审计

- JIF 已认证核验：0/28。
- `JIF_unverified`：28/28（100%）。
- IF>8 数量：不可计算，而不是 0。
- 原因：Pilot 环境没有认证 Clarivate Journal Citation Reports 数据。按锁定规则不猜测、不用第三方估算冒充 JCR。
- 因此无法比较“全部合格研究”和“IF>8 子集”；JIF 灵敏度分析须等机构 JCR 导出后再做。

## 2. 已深度核验研究的实验设计

深度核验并进入下载层的研究为 4 项：

| 研究 | 作物 | N 水平 | 0N | 同季产量 | 原始数据 | 分层 |
|---|---|---:|---|---|---|---|
| RICE_DONG_2021 | 水稻 | 3 | 有 | 有（图像数字化） | PacBio full-length 16S | Core-A |
| MAIZE_MENG_2024 | 玉米 | 6 | 有 | 无；样品 2023、产量止于 2022 | MiSeq V3–V4 16S | 16S-only |
| WHEAT_MA_2025 | 小麦 | 4 | 有 | 无；2018 样品、五年混合产量 | MiSeq V3–V4 16S | 16S-only |
| MAIZE_ENEBE_2020 | 玉米 | 3 | 有 | 无 | NovaSeq shotgun | MAG-only technical |

计数：

- ≥3 N 水平：4/4。
- ≥4 N 水平：2/4。
- ≥5 N 水平：1/4。
- 有 0N：4/4。
- 有同季产量：1/4。
- 明确混杂：1/4（MAG 研究 NPK 共变且 n=1）。

## 3. Core 数据集与停止规则

- Core-A：1。
- Core-B：0。
- Core-AB：0。
- 16S-only：2。
- MAG-only technical：1。

因此：

1. Core-A 明显少于锁定方案希望的 5–10 个；
2. 没有可用于 N_crop—shotgun/MAG 联合的 Core-B；
3. 现阶段只能演示框架，不能回答跨作物或全球一致性；
4. 不能用两个 16S-only 研究的非同季产量填补 Core 数量。

## 4. 原始测序与计算负载

- 16S 研究：3 个，102 Runs。
- shotgun 研究：1 个，3 Runs。
- Run 总数：105。
- 文件总数：192（PacBio 单文件 18；Illumina 16S 双端 168；shotgun 双端 6）。
- ENA 预计压缩数据量：7,374,732,125 bytes，约 7.37 GB（十进制）/ 6.87 GiB。
- 平台：PacBio Sequel II 18 Runs；Illumina MiSeq 84 Runs；Illumina NovaSeq 6000 3 Runs。
- 标记：full-length 16S 18 Runs；V3–V4 84 Runs；shotgun WGS 3 Runs。

全部文件已经实际下载，且通过预期字节数和 ENA MD5。这个规模对当前服务器不是瓶颈；真正的瓶颈是研究资格、产量季节匹配和 MAG 的生物重复/混杂。

## 5. 元数据完整性

### 深度核验的 4 项研究

| 变量 | 可用研究 | 缺失/不可用率 |
|---|---:|---:|
| N rate | 4/4 | 0% |
| 同季产量 | 1/4 | 75% |
| pH | 3/4 | 25% |
| SOC | 3/4 | 25% |
| TN | 3/4 | 25% |
| sampling depth | 3/4 | 25% |
| sampling stage | 3/4 | 25% |
| treatment duration | 3/4 | 25% |
| N form | 4/4 | 0% |
| fertilizer timing | 3/4 | 25% |
| coordinates | 3/4 | 25% |

### 全部 28 篇发现记录

24/28 尚未做完整全文核验，所以多数实验字段未知。这个阶段不能把“未知率约 85.7%”解释为文献真实缺失率；它反映的是审计工作量，而不是文章一定没报告。

## 6. 0N 灵敏度

- 当前 Core 研究：1 个，含 0N：1，不含 0N：0。
- 若 0N 设为 Core 必需条件：当前 Core 损失 0/1（0%）。
- 四个下载研究都含 0N，因此在本 Pilot 选择集中损失也是 0%。

建议：最终 Core 中应将 0N 设为硬条件，因为核心指标定义为 study 内相对 0N 的生态偏离；无 0N 研究仍可保留在 supplementary/external validation 层。这个建议不能外推为“全球候选不会因 0N 大量损失”，因为 24 篇尚未核验。

## 7. 数据处理可行性

### 16S

- 研究独立 DADA2 可运行；不同可变区不拼接 ASV 表。
- 玉米和小麦 MiSeq 已完成研究内去噪和嵌合体去除。
- 水稻 PacBio 揭示一个重要归档状态问题：FASTQ 已预去引物，不能机械重复执行论文所写引物去除；修复后按 full-length CCS 路线单独运行。
- bulk 与 rhizosphere 保持分开，0N 距离在 study/site/compartment 内计算。

结论：技术上可扩展，但大规模前需要把“论文引物”和“archive read 是否已去引物”设为显式字段，并加入自动 primer-presence 诊断。

### Shotgun/MAG

当前研究只适合技术压力测试，因为每处理 n=1、NPK 共变且无产量。全研究三个 N 处理使用同一个 co-assembly，之后逐 Run 回贴到共同参考；这种策略在方法上符合锁定设计，能避免 treatment-specific assembly 成功率被误当作存在/缺失。

即使该链条计算成功，也只能证明“当前服务器和脚本可执行”，不能证明 Core-B 足够、测序深度普遍足够或 N 导致某 MAG 改变。

## 8. 产量—微生物组联合解释边界

水稻 2020 三个 N 水平的图像数字化均值约为：

- 0 kg N ha⁻¹：8.635 t ha⁻¹；
- 150 kg N ha⁻¹：12.582 t ha⁻¹；
- 300 kg N ha⁻¹：12.286 t ha⁻¹。

在观测均值中，150 N 已达到最高值，300 N 没有继续增产。但只有三个处理均值且不是逐小区原始数据，因此只能说“出现平台/轻微回落的描述性迹象”，不能估计 N50/N90/断点或稳健最适 N。

## 9. 是否可以开始“大面积搜集数据”

正式扩大后的统计主线锁定为“研究内效应 → 全样本总体趋势 → 预设亚组交互 → 偏离研究审计与解释”。全样本层不合并不同扩增区/平台的原始ASV；亚组优先包括作物、土壤、气候、纬度、海拔、土壤区室和管理背景。每个结论须区分为共通、条件性共通、亚组特异或暂无统一结论，并同时报告总体估计、亚组估计、交互和剩余异质性。详细规则见 `tmp/result/reports/实验设计_全样本到亚组分析框架.md`。

可以扩大以下工作：

1. 按作物分层扩大文献发现；
2. 下载全文和补充材料；
3. 逐篇恢复站点×季节×处理×样品×Run×产量映射；
4. 建立白名单前的 accession 错号/错项目审计；
5. 优先寻找 ≥4 N、0N、同季产量和公开 raw reads 的 Core-A/Core-B。

暂时不要扩大以下工作：

1. 不要按 BioProject 整库批量下载所有候选；
2. 不要做跨研究统一 ASV 表；
3. 不要把 16S-only/MAG-only 与不匹配产量强行合并；
4. 不要开始全球层级模型，直到至少有 5 个可信 Core-A，并找到真正 Core-B；
5. 不要以 IF/JIF 替代实验质量审计。

## 10. 下一阶段硬条件与可放宽条件

### 必须保持为硬条件

- 小麦、玉米或水稻田间试验；
- 无机 N 是主要变化因子，P/K/有机投入不共变，或共变量可明确隔离；
- ≥3 N 水平；
- Core 中必须同一生长季配对 yield 与 microbiome；
- raw reads 可公开获取；
- treatment/sample/Run 映射可恢复；
- bulk 与 rhizosphere 分层；
- Core 的 0N 基线；
- 下载白名单和 MD5/结构 QC。

### 可放宽但必须分层

- 16S-only 和 MAG-only 可以保留并分别分析；
- Core 优先 ≥4/5 N，但 ≥3 N 可作描述性曲线，禁止不稳定断点；
- pH/SOC/TN、时间和坐标缺失不必立即排除，可作为质量分层；
- 无 0N 研究可进入 supplementary，不进入以 0N 为基线的核心层；
- 中等质量 MAG 可用于分类/丰度，但功能缺失解释必须考虑完整度。

### 只作灵敏度分析

- IF>8；不作为纳入条件，也不计入实验质量分数。

## 11. 最终判断

本 Pilot 证明了“严格 accession/样品映射 + 小规模 raw reads 下载 + study-independent 16S + study/site co-assembly”的工程路径具有可执行性，也证明了不能相信文章标题或 Data Availability 就直接合并数据。最大的限制不是计算资源，而是 Core 数据稀缺：同季产量缺失或年份不匹配占核验研究的 75%，Core-B/AB 为 0。

所以推荐 **GO_WITH_MODIFICATIONS**：立即扩大文献和元数据审计，目标是优先补足至少 5 个 Core-A 和至少 1–3 个真正 Core-B；在达到该闸门前，停止全球 raw-data 批量下载和联合结论生产。

<!-- AUTO_TECHNICAL_STATUS_BEGIN -->
## 最终技术链状态

- B73 RefGen_v5 宿主去除完成 3/3 Runs；双端均未比对的保留比例范围为 99.8266%–99.9343%。
- MAG 技术链状态：`pass`；MAG traits 行数 21，丰度行数 63，目标 KOfam 命中行数 49。
- CheckM2 最终状态：`pass`。若无 bin，必须以显式 `no_bins_recovered` 交付；若有 bin，只有 CheckM2 pass 后完整度/污染度才可使用。
- 由于每处理 n=1、NPK 共变且无产量，以上结果仅证明技术链能否运行，不用于氮肥因果效应或显著性。

上述状态不改变 `GO_WITH_MODIFICATIONS`：可扩大文献与元数据审计，但 Core-A<5、Core-B=0，不得直接扩大为全球原始数据下载和联合结论生产。
<!-- AUTO_TECHNICAL_STATUS_END -->
