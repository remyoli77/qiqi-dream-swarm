# qiqi-dream-swarm

> **标签**：`memory-management` `multi-agent` `knowledge-graph` `swarm-skill` `python`

> 多角色团队技能（Swarm Skill） · v1.0.0 · Python 3.10+ · 仅标准库，零第三方依赖

## 功能简介

**记忆四相治理：把一批原始记忆做"睡眠式"治理——去重压缩、提取关联、发现跨域联系、固化重要条目**

记忆四相治理团队（5 角色）：把一批原始记忆做「睡眠式」治理——浅层整理 → 深层关联 → 跨域重组 → 固化入库，
由信号评分官作闸门决定哪些记忆值得进入下一相；包含去重压缩、提取关联、发现跨域联系、固化重要条目、淘汰冗余。
当用户需要「整理一批记忆/笔记」「从素材里沉淀长期记忆」「给记忆去重并挑出精华」时使用。
触发词：梦境治理、记忆整理、记忆固化、四相治理、轻梦深梦、快速眼动、海马固化、记忆去重、dream swarm。


**触发词**：梦境治理、记忆整理、记忆固化、四相治理、轻梦深梦、快速眼动、海马固化、记忆去重、dream swarm


## 特点

- ✅ 自带 `selftest` 自检命令，开箱即验
- ✅ 仅用 Python 标准库，`pip install` 零依赖
- ✅ 工作区可参数化（`--workspace` / 环境变量 `QIQI_WORKSPACE`），无硬编码路径
- ✅ 默认输出 JSON，便于被其他智能体/流程编排调用
- ✅ 需要 LLM 推理的阶段输出 `needs_llm` 交接包，绝不编造内容

## 快速开始

```bash
python3 scripts/<入口脚本>.py selftest
```

## 来源与改动

- **来源模块**：`core/dreaming/`（light/deep/rem/hippo + signal_scorer）

### 诚实标注（未移植/边界）

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
   （`modul
…（详见 SKILL.md）


## 目录结构

```
SKILL.md
LICENSE
roles/deep.md
roles/hippo.md
roles/light.md
roles/rem.md
roles/scorer.md
samples/example-input.json
scripts/swarmflow.py
workflow.md
```

## 许可证

BSD-3-Clause（见 [LICENSE](LICENSE)）