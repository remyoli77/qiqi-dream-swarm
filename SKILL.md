---
name: qiqi-dream-swarm
version: 1.0.0
kind: swarm-skill
roles:
  - id: light
    kind: ai_agent
    purpose: 只负责记忆浅层整理：去重、概念抽取、SWR 标记，产出候选 candidates[]，不评分
    tools:
      - python3
  - id: scorer
    kind: ai_agent
    purpose: 只负责给候选打信号分并按阈值定准入资格，是可独立复用的闸门
    tools:
      - python3
  - id: deep
    kind: ai_agent
    purpose: 只负责按评分结果评估晋升与级联淘汰，输出 promotion_records[] 与 cascade
    tools:
      - python3
  - id: rem
    kind: ai_agent
    purpose: 只负责跨域语义重组发现新联系，需 LLM；不可得时输出 needs_llm 交接包
    tools:
      - python3
  - id: hippo
    kind: ai_agent
    purpose: 只负责把晋升结果固化为实体关系图谱，需 LLM+KG 引擎；不可得时如实输出 needs_llm
    tools:
      - python3
description: |
  记忆四相治理团队（5 角色）：把一批原始记忆做「睡眠式」治理——浅层整理 → 深层关联 → 跨域重组 → 固化入库，
  由信号评分官作闸门决定哪些记忆值得进入下一相；包含去重压缩、提取关联、发现跨域联系、固化重要条目、淘汰冗余。
  当用户需要「整理一批记忆/笔记」「从素材里沉淀长期记忆」「给记忆去重并挑出精华」时使用。
  触发词：梦境治理、记忆整理、记忆固化、四相治理、轻梦深梦、快速眼动、海马固化、记忆去重、dream swarm。
---

# qiqi-dream-swarm - 记忆四相治理团队

## 💕 团队定位

记忆不是"存起来就完了"。一个角色做完会同时犯四个错：**只存不筛**（什么都留，噪声淹没信号）、**只筛不连**（不留关联，知识成孤岛）、**只连不重组**（从不产生新联系）、**只进不出**（不淘汰、不固化）。原 `core/dreaming` 正是一条仿生睡眠流水线：**轻梦去重取候选 → 评分官当闸门 → 深梦评估晋升 → REM 跨域重组 → 海马固化入库**，每一步都可独立检验。

所以这里拆成 **5 个角色**：轻梦官只负责"浅层整理"（去重/概念/SWR），评分官只负责"打分定门槛"（**闸门，可复用**），深梦官只负责"评估晋升与淘汰"，快速眼动官负责"跨域语义重组"（**需 LLM**），海马官负责"实体关系图谱固化"（**需 LLM+KG 引擎**）。

> **角色数说明**：任务书称"记忆四相治理团队（5 角色）：轻梦/深梦/快速眼动/海马 + 信号评分官"。经核对 `core/dreaming/`，实际就是 **light / deep / rem / hippo 四相 + signal_scorer 一个评分闸门**，与线索一致。

## Roles

| id | 角色 | 何时派遣 | 输入 | 输出 | 提示词文件 |
|:--|:--|:--|:--|:--|:--|
| light | 轻梦官 | 阶段1（硬前置） | `input.memories[]` 或 `input.memory_files[]`、`input.recall_records?` | `light{…}` + `candidates[]` | roles/light.md |
| scorer | 信号评分官 | 阶段2（闸门，可复用） | 轻梦的 `candidates[]` | `scoring{count,eligible_count,ranked[]}` | roles/scorer.md |
| deep | 深梦官 | 阶段3 | `candidates[]` + `input.rem_boost?` | `deep{…,promotion_records[],cascade{}}` | roles/deep.md |
| rem | 快速眼动官 | 阶段4（**需 LLM**） | `candidates[]` top20 + 深梦上下文 | `{}`（`needs_llm` 交接包） | roles/rem.md |
| hippo | 海马官 | 阶段5（**需 LLM+KG**） | 深梦的晋升结果（+ 可选 REM 结果） | `{}`（`needs_llm`，`needs=llm+kg_engine`） | roles/hippo.md |

## Workflow

```
[01-light 轻梦官]  ← 硬前置：没有真实记忆就没有治理
        │ candidates[]（去重 + 概念 + 召回合并 + SWR/遗忘曲线）
        ▼
[02-score 信号评分官] ← 闸门：六信号加权 + 三项门槛（0.5 / 2 / 2），可复用
        │ 排序 + eligible
        ▼
[03-deep 深梦官]   ← NREM-CASCADE 评估 + 晋升（写 run 目录 artifact，不写宿主 MEMORY.md）
        │ promotion_records[]（含章节路由）
        ▼
[04-rem 快速眼动官] ← 需 LLM；本骨架输出 needs_llm ──► 跨域语义重组 / 生成式梦境
        │ 梦境片段（待宿主回填）
        ▼
[05-hippo 海马官]  ← 需 LLM+KG；本骨架输出 needs_llm ──► 实体关系抽取 + 图谱固化 + DEEP-SLEEP 迁移
        ▼
       完成（当 04/05 为 needs_llm 时整体状态 = partial）
```

- **阶段1 轻梦**：浅层整理。验收：`candidates≥1`，`duplicates_removed == total−unique`，候选含 `content/source_file/concepts`。
- **阶段2 评分**：闸门打分。验收：六信号齐备、`total_score` 降序、`eligible` 严格按门槛（不达标即 `false`）。
- **阶段3 深梦**：评估与晋升。验收：晋升记录含 `content/source_file/score/section`；CASCADE 四项齐备；产物落 run 目录 artifact。
- **阶段4 快速眼动**：跨域重组。验收：`needs_llm` 且 `outputs=={}`。**本阶段不产出内容。**
- **阶段5 海马**：固化入库。验收：`needs_llm`（`needs=llm+kg_engine`）且 `outputs=={}`。**本阶段不产出内容。**

### 哪些相位需要 LLM，哪些纯规则可执行

| 相位 | 性质 | 说明 |
|:--|:--|:--|
| 轻梦（去重/概念/SWR/遗忘） | 🟢 **纯规则** | md5 去重、正则概念、数学公式 |
| 评分（六信号 + 门槛） | 🟢 **纯规则** | 加权求和；`relevance` 的向量增强缺失即降级为纯平均 |
| 深梦（CASCADE + 晋升 + 淘汰） | 🟢 **纯规则** | 公式 + 门槛 + 关键词路由 + 写 artifact |
| 快速眼动（跨域重组） | 🔴 **需 LLM** | 语义重组；原件用 `random` 拼伪梦境，**不复刻** |
| 海马（实体关系 + 图谱固化） | 🔴 **需 LLM + KG 引擎** | 语义抽取 + `hipporag_fusion`（未随包提供） |

## 📁 文件结构

```
qiqi-dream-swarm/
├── SKILL.md                    ← 本文件（索引 + 角色表 + 编排图 + 契约）
├── workflow.md                 ← 编排细节：阶段/契约/失败降级/终止条件
├── roles/
│   ├── light.md                ← 轻梦官：浅层整理（去重/概念/SWR）
│   ├── scorer.md               ← 信号评分官：六信号 + 三项门槛（闸门）
│   ├── deep.md                 ← 深梦官：CASCADE + 晋升 + 淘汰
│   ├── rem.md                  ← 快速眼动官：需 LLM，输出 needs_llm
│   └── hippo.md                ← 海马官：需 LLM+KG，输出 needs_llm
├── scripts/swarmflow.py        ← 可执行编排骨架（仅标准库）
└── samples/
    └── example-input.json      ← 示例输入（⚠️ 虚构，仅用于 selftest）
```

## 🔧 使用方式

```bash
# 1) 查看 DAG、纯规则/需 LLM 划分与各阶段角色/输入/输出（不产生副作用）
python3 scripts/swarmflow.py plan

# 2) 正式运行（产物落到 <workspace>/data/qiqi-dream-swarm/<run_id>/NN-<stage>.json）
QIQI_WORKSPACE=/path/to/ws python3 scripts/swarmflow.py run --input my-memories.json --run-id r20260916

# 3) 查看某次 run 的状态（默认纯 JSON，可被 json.loads 解析；加 --format text 才附人类可读摘要）
QIQI_WORKSPACE=/path/to/ws python3 scripts/swarmflow.py status --run-id r20260916
QIQI_WORKSPACE=/path/to/ws python3 scripts/swarmflow.py status --run-id r20260916 --format text

# 4) 自检（用 samples 跑通全部阶段，打印逐步 PASS/FAIL）
python3 scripts/swarmflow.py selftest
```

工作区解析顺序：`--workspace` > 环境变量 `QIQI_WORKSPACE` > 当前目录。脚本内**无任何硬编码路径**。

## 📜 交接协议

阶段间交换 **交接包（handoff packet）**，统一 schema：

```json
{
  "swarm": "qiqi-dream-swarm",     // 必填
  "stage": "01-light",             // 必填
  "stage_name": "轻梦",            // 必填
  "role": "light", "role_name": "轻梦官",   // 必填
  "prompt_file": "roles/light.md", // 必填
  "depends_on": [],                // 必填
  "status": "ok",                  // ok|needs_llm|needs_executor|needs_input|failed|skipped
  "started_at": "...", "finished_at": "...",
  "inputs": {}, "outputs": {},     // 必填（needs_llm 时 outputs 必须为 {}）
  "validation": {"checks": [{"name":"","passed":true,"detail":""}], "passed": true},
  "uncertainty": ["..."],          // 必填，数组
  "next": "02-score"
}
```

**needs_llm 专用契约**（本团队 04-rem / 05-hippo 遵守）：必须额外含
`{"status":"needs_llm","stage":...,"role":...,"prompt_file":...,"input":<给 LLM 的完整载荷>,"needs":...}`，
且 `outputs` 必须为空对象——**绝不允许填入任何"看起来像梦境片段/实体三元组"的内容**。

校验规则见 `workflow.md` 与脚本内 `_valid_packet()`。

## 🛡️ 失败与降级

| 情况 | 行为 |
|:--|:--|
| 无 `memories` 且无 `memory_files` | 01-light 输出 `needs_input` → 硬前置未满足，整体 `blocked`，停止后续 |
| 有输入但全为短段/标题行 | 01-light 输出 `needs_llm` → 整体 `blocked` |
| **缺 `recall_records`/嵌入数据**（D1） | 02-score 六信号中的频率/查询多样性/新鲜度/巩固度全为 0 → `eligible=0`；此时**不静默产空**：该阶段标记 `degraded=true` 并给出 `needs_input`（缺失字段清单），`run.json` 亦带 `degraded=true` + `needs_input`，**退出码 2** |
| 无候选达标 | 03-deep 仍 `ok`（`promoted=0`），不写 artifact，`uncertainty` 注明 |
| 无 LLM / REM 不可用 | 04-rem 输出 `needs_llm`（**非硬前置**）→ 流程继续 |
| 无 KG 引擎 | 05-hippo 输出 `needs_llm`（`needs=llm+kg_engine`）→ 流程结束，整体 `partial` |
| `relevance` 缺向量增强 | 评分官按纯平均计算，并在 `uncertainty` 声明"未做向量语义增强" |
| 任何阶段抛异常 | 该阶段 `failed`，整体 `failed`，退出码 2 |

> **D1 说明**：无 recall/嵌入数据时，"可交付性"完全依赖宿主是否提供召回数据。为避免安静地产出空结果，
> 该情形被显式判定为 **`degraded` + `needs_input`**（列出缺哪些字段，如 `input.recall_records` /
> `input.memories[].recall`），并以**非零退出码 2** 返回，等待宿主补数据后重投。

**降级后如何标注不确定性**：一律写入交接包 `uncertainty[]`，并把 `validation.passed` 置 `false`/`null` 而非伪装通过。

## 🔥 五行归属

| 角色 | 五行 | 依据 |
|:--|:--|:--|
| 轻梦官 | 💧 水行 | 浅层整理 / 记忆存储 |
| 信号评分官 | ⚔️ 金行 | 阈值把关、筛选 |
| 深梦官 | 🏔️ 土行 | 深层关联、固化中枢 |
| 快速眼动官 | 🔥 火行 | 跨域重组、生成 |
| 海马官 | 💧 水行 | 知识图谱记忆（原件标注"水行 → 知识图谱记忆"） |
| 团队整体 | 🏔️ 土行 | 协调中枢 |

## 🔗 与框架的对应关系

| 本团队角色 | 来源 core 模块 | 说明 |
|:--|:--|:--|
| light 轻梦官 | `core/dreaming/light_phase.py::LightPhase` + `BioRhythmSWR` | 复刻 md5 去重 / 正则概念 / 召回合并 / `swr_gain` / 遗忘曲线 |
| scorer 信号评分官 | `core/dreaming/signal_scorer.py::SignalScorer` | 复刻六大权重（0.24/0.30/0.15/0.15/0.10/0.06）+ 门槛（0.5/2/2）；**去除**外部嵌入依赖 |
| deep 深梦官 | `core/dreaming/deep_phase.py::DeepPhase` + `NREMCascade` | 复刻 CASCADE / 门槛（0.5/1/1）/ 章节路由；**改写 artifact**（不写宿主 `MEMORY.md`） |
| rem 快速眼动官 | `core/dreaming/rem_phase.py::REMPhase` | 保留公式说明；生成式梦境一律 `needs_llm`；**不复刻 random 拼串** |
| hippo 海马官 | `core/dreaming/hippo_phase.py::HippoPhase` | 复刻流程与 `_calc_deep_sleep` 公式；依赖的 `hipporag_fusion` 未随包提供 → `needs_llm` |
| 编排调度 | `core/dreaming/__init__.py::DreamingController` | 单例 + 后台线程 + Darwin 评估；本骨架改为**可参数化、无单例、无后台线程**的流水线 |
| 梦境日记 | `core/dreaming/dream_diary.py::DreamDiary` | 人类可读日记生成；本骨架未内联（可作为宿主后处理） |
| 自动调度 | `core/dreaming/auto_dream_scheduler.py` | 空闲检测/定时；本骨架剥离（属宿主调度职责） |

## ⚠️ 迁移注意

1. **不写宿主记忆区**：原件 `DeepPhase.write_to_memory` 会改宿主 `MEMORY.md`，`DreamDiary` 写 `memory/dreams_enhanced.md`，`HippoPhase` 写 `data/hipporag/`。本骨架**全部改写 run 目录的 `artifact-MEMORY.promotions.md`**，真正落库由宿主执行。
2. **绝不复刻随机占位**：原件"生成式梦境"用 `random.sample` 拼 `"[梦境合成] …"`（`dreaming/__init__.py:94-105`、`rem_phase.py`），本骨架一律 `needs_llm`（与 `MIGRATION_NOTES.md` 第 2 条一致）。
3. **依赖缺口**：`hippo_phase.py` 依赖 `core/wuxing/water/hipporag_fusion.py`（未随本包提供）；`signal_scorer.py` 的向量语义增强依赖 `core/wuxing/water/online_embedding.py`（未随包提供）。二者缺失时分别降级为 `needs_llm` 与"纯平均"，并声明。
4. **路径参数化**：原件多处硬编码 `Path(__file__).parent.parent.parent` 作为工作区、并写入 `memory/`。本骨架统一走 `--workspace` / `QIQI_WORKSPACE`，产物只落 `<workspace>/data/qiqi-dream-swarm/`。
5. **登记却"有名无实"的记忆技能（重要事实）**：框架 `config/skill_registry.json` 登记了 **7 个记忆/管家类技能** ——
   `qiqi-memory-butler`、`qiqi-llm-memory`、`memory-tiering-manager`、`experimental-memory-install`、
   `experimental-memory-install-online`、`qiqi-auto-recall`、`qiqi-task-butler`。
   **本次核实**：前 **5 个**在磁盘上**没有对应目录**（只有登记，无法安装）；后 2 个（`qiqi-auto-recall`、`qiqi-task-butler`）在盘存在。
   → 任务书所说的"7 个登记但无目录"中，实测为 **5 个**。**本团队正是用来填补这批"有名无实"的登记项**：它把 `core/dreaming` 里真实存在的四相治理实现，落成一个可安装、可执行的记忆治理团队。
   （`module_registry.json` 另有 `memory_butler` / `llm_memory` / `auto_recall` 等模块级登记项指向 `core/bedroom/skills/...`，同一事实的另一个视角。）
6. **不写宿主配置区/记忆区**：产物全部在 `data/` 下，可整目录删除，幂等。
7. **引入前先过 `skill-scope` 内容安全校验**（框架 `AGENTS.md` 的强制要求）。

## 📝 更新日志

- 2026-09-16：由 core 模块改造为 Swarm Skill（5 角色 + 可执行编排骨架）。
- 2026-09-16（修复轮）：① D1 缺 recall/嵌入数据时显式 `degraded`+`needs_input` 且退出码 2（不再静默产空）；
  ② D2 `plan` 标出 03-deep 的降级路径；③ B1 输入层错误统一 stdout JSON + rc=2；④ B2 `status` 默认纯 JSON，
  人类可读内容走 `--format text`；⑤ selftest 增补 D1 与 B1/B2 回归。

## 前置条件（Precondition）

- Python ≥ 3.12（仅标准库，无第三方依赖）。
- 调用方必须提供**真实记忆**：`input.memories[]`（含 `content`）或 `input.memory_files[]`（存在的 `.md` 路径）。
- 若要走通"跨域重组 → 图谱固化"，需宿主提供 LLM 通道与知识图谱引擎；否则 04/05 保持 `needs_llm`。
- 若仅供框架内部调用，工作区应通过 `--workspace` 或 `QIQI_WORKSPACE` 显式指定。

## 后置效果（Effect）

- `eff_add`：
  - `<workspace>/data/qiqi-dream-swarm/<run_id>/01-light.json` … `05-hippo.json`
  - `<workspace>/data/qiqi-dream-swarm/<run_id>/artifact-MEMORY.promotions.md`（晋升候选，★ 非宿主 `MEMORY.md`）
  - `<workspace>/data/qiqi-dream-swarm/<run_id>/run.json`（运行清单）
  - 逐步向 stdout 打印 JSON 运行清单（`ensure_ascii=False, indent=2`）
- `eff_event`：`swarm.stage.completed`（每阶段完成触发一次，携带 `stage`/`role`/`status`）；`dream.memory_promoted`（有晋升记录时触发）。
  说明：本骨架**不主动向宿主事件总线发消息**（原件依赖 `core.linkage_bus`，属架构粘合层，迁移时有意剥离）；事件由宿主观察到产物落盘后自行发出。

## 副作用说明

- **写文件**：仅在 `<workspace>/data/qiqi-dream-swarm/<run_id>/` 下创建文件。不修改、不删除该目录外的任何文件，**不写 `MEMORY.md` / `memory/` / `config/` / `data/hipporag/`**。
- **读文件**：只读 `--input` 指定的输入 JSON，以及 `input.memory_files[]` 明确列出的记忆文件。
- **网络**：**不发起任何网络请求**。
- **不调用 LLM**：04-rem / 05-hippo 一律输出 `needs_llm` 交接包，绝不自行编造梦境或实体三元组。
- **幂等性**：相同 `--run-id` 重复运行覆盖该 `run_id` 目录下同名文件；不同 `run_id` 互不影响。
- **退出码**：`0`=completed/partial；`2`=blocked/failed、`degraded`（缺 recall 数据）或输入层错误（非法 JSON/字段类型错误/run 目录不可写/文件缺失）。输入层错误一律 **stdout 输出 `{"error":...}`**，不抛栈。
- **`status` 输出**：默认只输出 `run.json` 原样 JSON（可直接 `json.loads`）；人类可读摘要仅在 `--format text` 时追加。


## Files

| 文件 | 内容 |
|:--|:--|
| SKILL.md | 本文件（入口） |
| workflow.md | 编排细节（Overview/Detailed Steps/Acceptance Criteria + mermaid） |
| bind.md | 资源/行为/失败约束 |
| dependencies.yaml | 角色技能/工具依赖 |
| roles/*.md | 各角色完整提示词 |
| scripts/swarmflow.py | 可执行编排（plan/run/status/selftest） |
