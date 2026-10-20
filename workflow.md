# qiqi-dream-swarm · 编排细节（workflow.md）

> 本文是 `SKILL.md` 的展开。所有阈值、字段名均与 `scripts/swarmflow.py` 保持一致；
> 凡与原件（`core/dreaming/*`）不同之处，均在「来源与差异」注明。

---


## Overview

```mermaid
graph TD
  IN[调用方输入 memories/memory_files] --> A[01 light 轻梦官<br/>硬前置：去重/概念/SWR]
  A -->|candidates[]| B[02 scorer 信号评分官<br/>闸门·可复用]
  B -->|eligible ranked| C[03 deep 深梦官<br/>晋升与级联淘汰]
  C -->|top20 + 上下文| D[04 rem 快速眼动官<br/>需 LLM]
  D -. 拿不到 LLM .-> X[needs_llm 交接包]
  C -->|promotion_records| E[05 hippo 海马官<br/>需 LLM+KG]
  E -. 拿不到 KG .-> Y[needs_llm（needs=llm+kg_engine）]
  E --> OUT[固化后的实体关系图谱]
```

Leader（宿主编排器）按阶段顺序派遣角色；标注「硬前置」的阶段失败则整轮终止；标注「需 LLM」的阶段在无模型能力时降级输出交接包，流程不中断、不编造。

---


## Detailed Steps

角色以 `core/dreaming/` 的**实际实现**为准：`LightPhase`(轻梦) / `SignalScorer`(信号评分)
/ `DeepPhase`(深梦) / `REMPhase`(快速眼动) / `HippoPhase`(海马) —— **5 个角色**。

> **顺序差异**：原件 `DreamingController.run` 的真实顺序是
> `light → rem(情感) → rem(生成) → deep → hippo`，且 `scorer` 内嵌于 light/deep。
> 本团队按任务建议采用 `轻梦 → 评分 → 深梦 → 快速眼动 → 海马`，并把评分官**显式**独立为闸门阶段。

| # | 阶段 | 负责角色 | 输入 | 输出 | 验收标准 |
|:--|:--|:--|:--|:--|:--|
| 1 | `01-light` 轻梦 | light 轻梦官 | `input.memories[]` 或 `input.memory_files[]`、`input.recall_records?`、`input.feed_data?` | `light{…}` + `candidates[]` | `candidates≥1`；`duplicates_removed == total−unique`；候选含 `content/source_file/concepts` |
| 2 | `02-score` 评分 | scorer 信号评分官 | `candidates[]` | `scoring{count,eligible_count,ranked[]}` | 六信号齐备、`total_score` 降序、`eligible` 严格按 0.5/2/2 门槛 |
| 3 | `03-deep` 深梦 | deep 深梦官 | `candidates[]` + `input.rem_boost?` | `deep{candidates_evaluated,passed_*,promoted,promotion_records[],cascade{}}` | 晋升记录含 `content/source_file/score/section`；CASCADE 四项齐备；产物落 run 目录 artifact |
| 4 | `04-rem` 快速眼动 | rem 快速眼动官 | `candidates[]` top20 + `03-deep` 上下文 | `{}`（`needs_llm`） | `outputs=={}`；附 `source_memories`/情感词表/`expected_output_schema` |
| 5 | `05-hippo` 海马 | hippo 海马官 | `03-deep` 晋升结果（+ 可选 `04-rem`） | `{}`（`needs_llm`，`needs=llm+kg_engine`） | `outputs=={}`；`needs` 标明 `kg_engine` |

### 纯规则 vs 需要 LLM（本团队的核心诚实点）

| 阶段 | 性质 | 依据 |
|:--|:--|:--|
| 01-light | **纯规则** | 去重(md5)/概念(正则)/SWR 公式/遗忘曲线，均为可计算步骤 |
| 02-score | **纯规则** | 六信号加权 + 三项门槛；`relevance` 的向量语义增强**缺失即降级**为纯平均 |
| 03-deep | **纯规则** | CASCADE 公式 + 门槛 + 关键词路由章节 + 落盘 |
| 04-rem | **需 LLM** | 跨域**语义**重组；原件用 `random` 拼 `[梦境合成]…` 伪内容，不复刻 |
| 05-hippo | **需 LLM+KG** | 实体/关系抽取（语义）+ 图谱引擎（`hipporag_fusion` 未随包提供） |

### 来源与差异

| 阶段 | 来源 | 差异（如实说明） |
|:--|:--|:--|
| 01-light | `light_phase.py` | 复刻 `get_memory_hash`/`_extract_concepts`/去重/默认召回/`swr_gain`/`forgetting_retention`；`load_recent_memories` 的"扫最近 N 天文件"改为由调用方给 `memories` 或 `memory_files` |
| 02-score | `signal_scorer.py` | 复刻六大权重与门槛；**删除** `_get_embedding_if_available` 的外部嵌入依赖（缺失即降级） |
| 03-deep | `deep_phase.py` | 复刻 CASCADE/门槛/`determine_section`；**`write_to_memory` 改写 run 目录 artifact**（原件写宿主 `MEMORY.md`） |
| 04-rem | `rem_phase.py` | 保留情感/主题/新颖度的**公式说明**，但生成式梦境一律 `needs_llm`；**不复刻 random 拼串** |
| 05-hippo | `hippo_phase.py` | 原件依赖未随包提供的 `hipporag_fusion`；本阶段 `needs_llm`，`needs=llm+kg_engine` |

---

## 二、交接协议

### 2.1 通用交接包 schema

```jsonc
{
  "swarm": "qiqi-dream-swarm",     // 必填，常量
  "stage": "01-light",             // 必填
  "stage_name": "轻梦",            // 必填
  "role": "light", "role_name": "轻梦官",  // 必填
  "prompt_file": "roles/light.md", // 必填，相对技能根目录
  "depends_on": [],                // 必填，数组
  "status": "ok",                  // 必填：ok | needs_llm | needs_executor | needs_input | failed | skipped
  "started_at": "ISO8601", "finished_at": "ISO8601",   // 必填，UTC
  "inputs": { }, "outputs": { },   // 必填；status=needs_llm 时 outputs 必须为 {}
  "validation": { "checks": [ {"name":"…","passed":true,"detail":"…"} ], "passed": true },
  "uncertainty": ["…"],            // 必填，数组
  "next": "02-score"               // 由引擎回填
}
```

### 2.2 needs_llm 扩展契约（阶段 4、5 强制）

```jsonc
{
  "status": "needs_llm",
  "stage": "04-rem",
  "role": "rem",
  "prompt_file": "roles/rem.md",
  "input": { "memory_count":4, "source_memories":[ … ], "emotion_tag_vocabulary":[ … ],
             "promoted_count":2, "expected_output_schema":{ … } },
  "outputs": {},          // ★ 必须为空 —— 不得编造梦境
  "needs": "llm"          // 05-hippo 为 "llm+kg_engine"
}
```

### 2.3 校验规则（脚本 `_valid_packet()` 实现）

1. 必须含全部 `REQUIRED_KEYS`（见 2.1）。
2. `status` 必须属于枚举集合。
3. `uncertainty` 必须是数组。
4. 若 `status == "needs_llm"`：必须含 `stage/role/prompt_file/input`，**且 `outputs` 必须为空**。
5. 若 `status ∈ {ok, failed}`：`validation.checks` 必须存在；`status == "ok"` 时 `checks` 非空。

---

## 三、失败与降级

### 3.1 重试 / 超时 / 可跳过性

| 阶段 | 重试次数 | 超时 | 能否跳过 | 说明 |
|:--|:--|:--|:--|:--|
| 01-light | 0 | <1s（纯内存计算） | **否（硬前置）** | 无真实记忆则无从治理 |
| 02-score | 0 | <1s | 是 | 缺候选记 `skipped` |
| 03-deep | 0 | <1s | 是 | 缺候选记 `skipped` |
| 04-rem | 宿主 LLM 通道自定 | 建议 120s | 是（非硬前置） | 缺候选记 `skipped`；正常时 `needs_llm` |
| 05-hippo | 宿主 LLM+KG 自定 | 建议 180s | 是（非硬前置） | 缺 `03-deep` 记 `skipped`；正常时 `needs_llm` |

### 3.2 降级矩阵

| 场景 | 阶段状态 | 整体状态 | 后续行为 | `uncertainty` 标注 |
|:--|:--|:--|:--|:--|
| 无 `memories` 且无 `memory_files` | `01-light = needs_input` | `blocked` | 停止 02–05 | 未提供任何真实记忆 |
| 有输入但无有效段落（全 `len<20`） | `01-light = needs_llm` | `blocked` | 停止 | 无长度≥20 的有效段落 |
| 无 LLM | `04-rem = needs_llm` | `partial` | 05 照跑（或同样 needs_llm） | 跨域重组需宿主 LLM |
| 无 KG 引擎 | `05-hippo = needs_llm` | `partial` | 结束 | 实体/关系抽取需 LLM，图谱引擎未随包提供 |
| 无候选达标 | `03-deep = ok(promoted=0)` | 取决于其它阶段 | artifact 不写出 | "无候选通过晋升门槛（不编造晋升记录）" |
| 阶段异常 | 该阶段 `failed` | `failed` | 停止，退出码 2 | 异常摘要（宿主异常层捕获） |

### 3.3 不确定性标注的统一约定

- 机器可读：写入 `uncertainty[]` 与 `validation.passed`（失败时不得为真）。
- 人类可读：写入 `note`。
- **降级必须声明**：`relevance` 未做向量语义增强、概念为正则抽取、CASCADE 为公式估算，均须写明。
- **禁止**伪造晋升记录/梦境片段/实体三元组来"让流程看起来跑完"。

---

## 四、终止条件

| 终止类型 | 判定 |
|:--|:--|
| **正常完成** | 5 阶段全部 `status=ok` → `overall_status=completed`，退出码 0 |
| **部分完成（需宿主补 LLM/KG）** | 至少一个非硬前置阶段为 `needs_llm`，其余可执行阶段均 `ok` → `partial`，退出码 0 |
| **阻塞** | **硬前置** `01-light` 出现 `needs_input`/`needs_llm` → `blocked`，停止推进，退出码 2 |
| **失败** | 任何阶段 `status=failed` → `failed`，退出码 2 |
| **需人工介入** | 出现 `blocked`；或 `04-rem`/`05-hippo` 的 `needs_llm` 未被宿主回填而用户要求"已完成固化"；或 `03-deep` 晋升 0 条而用户预期有产出 |

> `needs_llm` 不是失败，而是一次"如实交棒"：把该阶段该做什么（`input`）与该看哪份提示词（`prompt_file`）明确交给宿主。

---

## 五、产物落盘

```
<workspace>/data/qiqi-dream-swarm/<run_id>/
├── 01-light.json                       ← 阶段1 交接包（含 candidates[]）
├── 02-score.json                       ← 阶段2 交接包
├── 03-deep.json                        ← 阶段3 交接包
├── 04-rem.json                         ← needs_llm（outputs 为空）
├── 05-hippo.json                       ← needs_llm（outputs 为空）
├── artifact-MEMORY.promotions.md       ← 阶段3 晋升候选（★ 非宿主 MEMORY.md，只是 artifact）
└── run.json                            ← 运行清单
```

- **命名规则**：`<workspace>/data/qiqi-dream-swarm/<run_id>/NN-<stage>.json`（`NN` 为两位阶段序号，`<stage>` 为阶段名）。
- `<workspace>` 解析顺序：`--workspace` > `QIQI_WORKSPACE` > 当前目录。
- `<run_id>` 缺省为 `<UTC时间戳>-<输入哈希前8位>`，可用 `--run-id` 覆盖。
- 落盘时机：每阶段执行完立即落盘（即使后续阻塞，已完成阶段的产物仍保留）。
- **不写** `MEMORY.md` / `memory/` / `config/` / `data/hipporag/`（宿主区域）；不联网；不调用 LLM。幂等：同 `run_id` 覆盖写。


## Acceptance Criteria

- 每个确定性阶段产物齐备且自检通过（run.json 中该阶段 status=done）；
- 标注「硬前置」的阶段无 skipped；
- 所有 needs_llm 阶段均输出规范交接包（outputs 为空 + needs 字段），全文无编造内容；
- 最终报告含每个阶段的输入/输出/验收结果与失败原因（如有）。
