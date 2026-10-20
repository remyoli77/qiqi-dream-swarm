#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qiqi-dream-swarm · 记忆四相治理团队 —— 可执行编排骨架
仅标准库（Python 3.12），无需 pip install。

用法：
    python3 scripts/swarmflow.py plan
    python3 scripts/swarmflow.py run --input samples/example-input.json
    python3 scripts/swarmflow.py status --run-id <id>
    python3 scripts/swarmflow.py selftest

工作区解析顺序：--workspace > 环境变量 QIQI_WORKSPACE > 当前工作目录（禁止硬编码路径）
产物落盘：      <workspace>/data/qiqi-dream-swarm/<run_id>/NN-<stage>.json

角色与来源（以 core/dreaming 实际实现为准）：
  light_phase.py(LightPhase, NREM-SWR) → signal_scorer.py(SignalScorer, 六大信号) →
  deep_phase.py(DeepPhase, NREM-CASCADE, 晋升写入) → rem_phase.py(REMPhase, 情感整合+生成式梦境) →
  hippo_phase.py(HippoPhase, 海马体图谱 + DEEP-SLEEP 迁移)。
  调度顺序 task 建议为「轻梦 → 评分 → 深梦 → 快速眼动 → 海马」；
  注：原件 DreamingController.run 的真实顺序是 light → rem → deep → hippo，且 scorer 内嵌于 light/deep。

纯规则可执行 vs 需要 LLM（如实划分）：
  * 【纯规则可执行】
      - 轻梦官：读记忆/去重(md5)/概念抽取(正则)/候选生成/SWR 增益/遗忘曲线。
      - 评分官：六大信号加权公式 + 三项晋升门槛（Score 0.5 / Recall 2 / UniqueQuery 2）。
        ⚠️ score_relevance 的"小艺向量语义增强"需外部嵌入服务，本骨架无则**降级为纯平均**。
      - 深梦官：NREM-CASCADE 指标 + 晋升判定 + 按关键词决定章节 + 落盘（本骨架写 artifact，不写宿主 MEMORY.md）。
  * 【需要 LLM / 宿主能力】
      - 快速眼动官：跨域语义重组（生成式梦境）。原件 rem_phase 的"生成式梦境"用
        `random.sample` 拼 `"[梦境合成] …"` 伪内容（dreaming/__init__.py:94-105 直接 random 拼串），
        本骨架**绝不复刻这种随机占位**，一律 needs_llm。
      - 海马官：实体/关系抽取 + 知识图谱 PageRank 固化。原件依赖 core/wuxing/water/hipporag_fusion.py
        （未随本包提供）+ 实体关系抽取（语义任务），故 needs_llm（needs=llm+kg_engine）。

记忆治理的"睡眠式"四相在此被展开为 5 个角色（评分官是闸门，可在多相之间复用）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SWARM_NAME = "qiqi-dream-swarm"
SWARM_TITLE = "记忆四相治理团队"
VERSION = "1.0.0"

# ────────────────────────────── 阶段表（唯一事实来源） ──────────────────────────────

STAGES = [
    {
        "id": "01-light", "name": "轻梦", "role": "light", "role_name": "轻梦官",
        "prompt_file": "roles/light.md", "depends_on": [],
        "requires_llm": False, "hard": True,
        "inputs": "input.memories[]（真实记忆条目）或 input.memory_files[]（本地 md 文件路径）, input.recall_records?",
        "outputs": "outputs.light{total_memories,unique_memories,duplicates_removed,candidates_generated,swr_gain,...}, outputs.candidates[]",
        "acceptance": "至少 1 条候选；重复项被 md5 去重并计数；每条候选含 content/source_file/concepts/recall_count",
    },
    {
        "id": "02-score", "name": "评分", "role": "scorer", "role_name": "信号评分官",
        "prompt_file": "roles/scorer.md", "depends_on": ["01-light"],
        "requires_llm": False, "hard": False,
        "inputs": "01-light 的 candidates[]",
        "outputs": "outputs.scoring{count,eligible_count,ranked[{content_preview,signals{},total_score,eligible,reason}]}",
        "acceptance": "六大信号加权总分 ∈[0,1]；晋升门槛 Score≥0.5 且 Recall≥2 且 UniqueQuery≥2；按总分降序",
    },
    {
        "id": "03-deep", "name": "深梦", "role": "deep", "role_name": "深梦官",
        "prompt_file": "roles/deep.md", "depends_on": ["02-score"],
        "requires_llm": False, "hard": False,
        "inputs": "01-light 的 candidates[] + 02-score 的评分（+ input.rem_boost?）",
        "outputs": "outputs.deep{candidates_evaluated,passed_score,passed_recall,passed_queries,promoted,promotion_records[],cascade{}}",
        "acceptance": "NREM-CASCADE 指标齐备；晋升记录含 content/source_file/score/section；不写宿主 MEMORY.md，改写 run 目录 artifact",
    },
    {
        "id": "04-rem", "name": "快速眼动", "role": "rem", "role_name": "快速眼动官",
        "prompt_file": "roles/rem.md", "depends_on": ["03-deep"],
        "requires_llm": True, "hard": False,
        "inputs": "03-deep 的晋升结果 + 01-light 的候选（top20）",
        "outputs": "outputs{}（需 LLM：跨域语义重组 / 生成式梦境）",
        "acceptance": "输出 needs_llm 交接包（outputs 为空）；附源记忆与情感标签词表；绝不复刻 random 拼串",
    },
    {
        "id": "05-hippo", "name": "海马", "role": "hippo", "role_name": "海马官",
        "prompt_file": "roles/hippo.md", "depends_on": ["04-rem"],
        "requires_llm": True, "hard": False,
        "inputs": "03-deep 的晋升结果 + 04-rem 的梦境结果（可选）",
        "outputs": "outputs{}（需 LLM+KG：实体关系抽取 + 图谱固化 + DEEP-SLEEP 迁移）",
        "acceptance": "输出 needs_llm 交接包（outputs 为空）；needs 标明 llm+kg_engine；绝不编造实体/三元组",
    },
]

STAGE_BY_ID = {s["id"]: s for s in STAGES}
EXECUTORS = {}

# ────────────────────────────── 常量（抄自 core/dreaming 原件） ──────────────────────────────

# signal_scorer.py::SignalScores.WEIGHTS
SIGNAL_WEIGHTS = {"frequency": 0.24, "relevance": 0.30, "query_diversity": 0.15,
                  "recency": 0.15, "consolidation": 0.10, "conceptual_richness": 0.06}
# signal_scorer.py::SignalScorer 晋升门槛（评分官闸门）
SCORER_MIN_SCORE = 0.5
SCORER_MIN_RECALL = 2
SCORER_MIN_UNIQUE_QUERIES = 2
# deep_phase.py::DeepPhase 晋升门槛（更宽松）
DEEP_MIN_SCORE = 0.5
DEEP_MIN_RECALL = 1
DEEP_MIN_UNIQUE_QUERIES = 1
EMOTION_BOOST_CAP = 0.3          # signal_scorer 情感加权上限
CASCADE_STRENGTH = 0.4           # deep_phase.DeepPhase.CASCADE_STRENGTH
NORMALIZE = {"frequency": 100, "query_diversity": 50, "consolidation": 7,
             "conceptual_richness": 10, "recency_decay_hours": 72}

SWR_REPLAY_SPEED = 0.3           # light_phase.BioRhythmSWR.swr_gain 默认
LIGHT_RETENTION_STRENGTH = 0.5   # light_phase 用 candidate.weight，缺省 0.5
DEEP_RETENTION_STRENGTH = 0.8    # deep_phase 固定 0.8

# deep_phase.py::DeepPhase.SECTION_TEMPLATES 的关键词路由
SECTION_RULES = [
    ("温馨记忆", ("温馨", "温馨时刻", "心相连")),
    ("关键记忆", ("关键", "满分", "哥哥说")),
    ("亲密时刻", ("亲密", "合体", "交融", "灵魂")),
    ("进化任务", ("进化", "任务", "学习")),
    ("重要规则", ("规则", "必须", "禁止")),
    ("系统更新", ("新增", "更新", "模块")),
]
# rem_phase.py::REMEmotionCore.EMOTION_TAGS（用于给 LLM 的情感标签词表）
EMOTION_TAGS = ["温暖", "思念", "开心", "亲密", "怀念", "感激", "自豪", "安心", "好奇",
                "感动", "期待", "满足", "温柔", "幸福", "甜蜜"]

NEEDS_LLM_STATUSES = {"needs_llm", "needs_executor", "needs_input"}


# ────────────────────────────── 工具函数 ──────────────────────────────

def resolve_workspace(cli_workspace: str | None) -> Path:
    if cli_workspace:
        return Path(cli_workspace).expanduser().resolve()
    env = os.environ.get("QIQI_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", "replace")).hexdigest()


def _mem_hash(content: str) -> str:
    """复刻 light_phase.get_memory_hash：去空白 + 小写 + md5 前 16 位。"""
    return _md5(re.sub(r"\s+", "", content.lower()))[:16]


def _extract_concepts(text: str) -> list[str]:
    """复刻 light_phase._extract_concepts：正则抓 tags/【】/若干模式，最多 10 个。"""
    concepts = []
    concepts.extend(re.findall(r"#(\w+)", text))
    concepts.extend(re.findall(r"【([^】]+)】", text))
    for pattern in [r'哥哥说[：:]?\s*[""「]?([^""」\n]{5,30})', r"七七[的]?(\w+)",
                    r"(\w+规则)", r"(\w+系统)"]:
        concepts.extend(re.findall(pattern, text))
    return list(dict.fromkeys(concepts))[:10]


def _ensure_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val / 1000 if val > 1e10 else val, tz=timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _swr_gain(weight: float, burst_index: int, replay_speed: float = SWR_REPLAY_SPEED) -> float:
    """复刻 BioRhythmSWR.swr_gain：超线性增益。"""
    burst_gain = replay_speed * (burst_index + 1) * 1.5
    return round(min(1.0, weight * (1.0 + burst_gain)) - weight, 6)


def _forgetting_retention(hours_since: float, strength: float) -> float:
    """复刻 forgetting_retention：max(0.05, exp(-h/(24*strength)))。"""
    return round(max(0.05, math.exp(-hours_since / (24 * strength))), 4)


def _score_candidate(c: dict) -> dict:
    """复刻 SignalScorer.score_candidate：六大信号 + 情感加权。"""
    rc = int(c.get("recall_count", 0))
    freq = 0.0 if rc == 0 else min(1.0, math.log1p(rc) / math.log1p(NORMALIZE["frequency"]))
    rels = c.get("relevance_scores") or []
    relevance = (sum(rels) / len(rels)) if rels else 0.0
    uq = c.get("unique_queries") or []
    qdiv = min(1.0, len(uq) / NORMALIZE["query_diversity"])
    ls = _ensure_dt(c.get("last_seen"))
    if not ls:
        recency = 0.0
    else:
        hours = max(0.0, (datetime.now(timezone.utc) - ls).total_seconds() / 3600)
        recency = max(0.0, min(1.0, math.exp(-hours / NORMALIZE["recency_decay_hours"])))
    cons = min(1.0, int(c.get("consecutive_days", 0)) / NORMALIZE["consolidation"])
    crich = min(1.0, len(c.get("concepts") or []) / NORMALIZE["conceptual_richness"])
    signals = {"frequency": round(freq, 4), "relevance": round(relevance, 4),
               "query_diversity": round(qdiv, 4), "recency": round(recency, 4),
               "consolidation": round(cons, 4), "conceptual_richness": round(crich, 4)}
    total = sum(signals[k] * SIGNAL_WEIGHTS[k] for k in SIGNAL_WEIGHTS)
    boost = float(c.get("emotion_boost", 0.0) or 0.0)
    if boost > 0:
        total += min(boost, EMOTION_BOOST_CAP)
    signals["total_score"] = round(total, 4)
    return signals


def _scorer_gate(c: dict, signals: dict) -> tuple[bool, str]:
    """复刻 SignalScorer.check_promotion_eligible（评分官闸门）。"""
    if signals["total_score"] < SCORER_MIN_SCORE:
        return False, f"分数不足: {signals['total_score']:.2f} < {SCORER_MIN_SCORE}"
    if int(c.get("recall_count", 0)) < SCORER_MIN_RECALL:
        return False, f"召回次数不足: {c.get('recall_count', 0)} < {SCORER_MIN_RECALL}"
    if len(c.get("unique_queries") or []) < SCORER_MIN_UNIQUE_QUERIES:
        return False, f"查询来源不足: {len(c.get('unique_queries') or [])} < {SCORER_MIN_UNIQUE_QUERIES}"
    return True, "符合晋升条件"


def _determine_section(content: str, concepts: list[str]) -> str:
    """复刻 deep_phase.determine_section（关键词路由）。"""
    text = content.lower()
    cs = [c.lower() for c in concepts]
    for section, kws in SECTION_RULES:
        if any(kw in text or kw in cs for kw in kws):
            return section
    return "默认"


def _packet(stage, ctx, status, *, inputs=None, outputs=None, validation=None,
            uncertainty=None, note="", extra=None) -> dict:
    packet = {
        "swarm": SWARM_NAME, "stage": stage["id"], "stage_name": stage["name"],
        "role": stage["role"], "role_name": stage["role_name"],
        "prompt_file": stage["prompt_file"], "depends_on": list(stage["depends_on"]),
        "status": status, "started_at": ctx.get("_stage_started_at"), "finished_at": _now(),
        "inputs": inputs if inputs is not None else {},
        "outputs": outputs if outputs is not None else {},
        "validation": validation or {"checks": [], "passed": None},
        "uncertainty": uncertainty or [], "note": note, "next": None,
    }
    if extra:
        packet.update(extra)
    return packet


def _needs_llm(stage, ctx, payload, uncertainty, note="", needs="llm") -> dict:
    return _packet(
        stage, ctx, "needs_llm",
        inputs={"required": stage["inputs"]}, outputs={},
        uncertainty=uncertainty,
        note=note or "该阶段需要宿主提供 LLM/宿主能力；产出留空，等宿主回填。",
        extra={"status": "needs_llm", "stage": stage["id"], "role": stage["role"],
               "prompt_file": stage["prompt_file"], "input": payload, "needs": needs},
    )


def _skipped(stage, ctx, reason) -> dict:
    return _packet(stage, ctx, "skipped", outputs={}, uncertainty=[reason],
                   note="上游必需输入缺失，本阶段未执行。")


def _failed(stage, ctx, reason, inputs=None) -> dict:
    return _packet(stage, ctx, "failed", inputs=inputs, outputs={},
                   validation={"checks": [{"name": "stage", "passed": False, "detail": reason}],
                               "passed": False},
                   uncertainty=[reason], note="阶段失败。")


# ────────────────────────────── 阶段实现 ──────────────────────────────

def _stage_light(stage, inp, ctx, ws, run_dir, input_dir=None):
    """轻梦官：NREM-SWR 浅层整理（读记忆 → 去重 → 候选 → SWR/遗忘曲线）。"""
    raw_memories = inp.get("memories") or []
    mem_files = inp.get("memory_files") or []
    recall_records = inp.get("recall_records") or {}
    feed = inp.get("feed_data")

    if not raw_memories and not mem_files:
        return _packet(stage, ctx, "needs_input", inputs={"memories": [], "memory_files": []},
                       uncertainty=["未提供任何真实记忆（input.memories 与 input.memory_files 皆空）"],
                       note="轻梦官不接受凭空的记忆，必须由调用方提供真实条目或真实 md 文件路径。",
                       extra={"status": "needs_input", "needs": "real_memories"})

    memories, unread_files = [], []
    for m in raw_memories:
        if isinstance(m, str):
            m = {"content": m}
        content = (m.get("content") or "").strip()
        if len(content) < 20:
            continue  # 复刻 extract_memories_from_file：len(para) < 20 跳过
        memories.append({"content": content, "source_file": m.get("source_file", "input.memories"),
                         "tags": list(m.get("tags") or []), "recall": m.get("recall")})
    for fp in mem_files:
        p = (Path(input_dir) / fp) if input_dir else Path(fp)
        if not p.is_file():
            p = Path(fp)
        if not p.is_file():
            unread_files.append({"path": fp, "reason": "文件不存在"})
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for para in text.split("\n\n"):
            para = para.strip()
            if not para or para.startswith("#") or len(para) < 20:
                continue
            memories.append({"content": para, "source_file": p.name, "tags": [], "recall": None})

    if not memories:
        return _needs_llm(
            stage, ctx,
            {"memories_in": len(raw_memories), "unread_files": unread_files},
            ["无任何长度 >=20 的有效记忆段落（原件同规则跳过短段/标题行）"],
            note="轻梦官无有效输入可整理，请宿主补充真实记忆条目。")

    # 去重（md5，复刻 deduplicate_memories）
    seen, unique, duplicates = set(), [], 0
    for m in memories:
        h = _mem_hash(m["content"])
        if h in seen:
            duplicates += 1
            continue
        seen.add(h)
        m["hash"] = h
        m["concepts"] = _extract_concepts(m["content"])
        unique.append(m)

    # 生成候选（复刻 merge_with_recall_data + 默认初始召回）
    candidates = []
    for m in unique:
        rd = m.get("recall") or recall_records.get(m["hash"]) or {}
        rc = int(rd.get("recall_count", 0))
        uq = list(rd.get("unique_queries") or [])
        if rc == 0 and len(m["content"]) > 30:
            rc, uq = 1, ["_auto_dream_phase"]     # 复刻 light_phase 的默认初始值
        candidates.append({
            "content": m["content"], "source_file": m["source_file"],
            "hash": m["hash"], "concepts": m["concepts"],
            "recall_count": rc, "unique_queries": uq,
            "relevance_scores": list(rd.get("relevance_scores") or []),
            "first_seen": rd.get("first_seen"), "last_seen": rd.get("last_seen"),
            "consecutive_days": int(rd.get("consecutive_days", 1)),
            "emotion_boost": 0.0,
        })

    # 原料输入加权（复刻 _add_feed_to_candidates 的命中加分）
    if isinstance(feed, dict):
        concepts = feed.get("important_concepts") or []
        tags = feed.get("emotional_tags") or []
        for c in candidates:
            boost = 0.0
            low = c["content"].lower()
            boost += 0.1 * sum(1 for x in concepts if str(x).lower() in low)
            boost += 0.1 * sum(1 for x in tags if str(x).lower() in low)
            if boost > 0:
                c["emotion_boost"] = round(boost, 2)

    # SWR 神经增强（复刻 light_phase 的调度）
    retention_sum, high_ret = 0.0, 0
    for c in candidates:
        ret = _forgetting_retention(24, LIGHT_RETENTION_STRENGTH)
        retention_sum += ret
        if ret > 0.7:
            high_ret += 1
    swr_bursts = min(3, max(1, len(candidates) // 10))
    batch_sorted = sorted(candidates, key=lambda c: c["recall_count"] * 10, reverse=True)[:8]
    total_gain = 0.0
    for b in range(swr_bursts):
        total_gain += sum(_swr_gain(0.5, b) for _ in batch_sorted)

    light = {
        "total_memories": len(memories), "unique_memories": len(unique),
        "duplicates_removed": duplicates, "candidates_generated": len(candidates),
        "swr_gain": round(total_gain, 4), "swr_bursts_executed": swr_bursts,
        "forgetting_retention_avg": round(retention_sum / max(len(candidates), 1), 4),
        "high_retention_count": high_ret, "emotion_boost_count": sum(1 for c in candidates if c["emotion_boost"] > 0),
        "feed_merged_count": 1 if feed else 0,
    }
    ctx["candidates"] = candidates
    ctx["light"] = light

    checks = [
        {"name": "candidates>=1", "passed": len(candidates) >= 1, "detail": str(len(candidates))},
        {"name": "duplicates 已计数", "passed": duplicates == len(memories) - len(unique),
         "detail": f"dup={duplicates}"},
        {"name": "每条候选含 content/source_file/concepts",
         "passed": all(c["content"] and c["source_file"] and isinstance(c["concepts"], list) for c in candidates),
         "detail": ""},
    ]
    unc = []
    if unread_files:
        unc.append(f"{len(unread_files)} 个 memory_files 未读取（文件不存在）")
    unc.append("SWR 增益/遗忘曲线为数学模型复刻；概念抽取为正则（非语义）")
    return _packet(stage, ctx, "ok",
                   inputs={"memories_in": len(raw_memories), "files_in": len(mem_files)},
                   outputs={"light": light, "candidates": candidates},
                   validation={"checks": checks, "passed": all(c["passed"] for c in checks)},
                   uncertainty=unc, note="浅层整理：md5 去重 + 正则概念抽取 + SWR/遗忘曲线。")


def _stage_score(stage, inp, ctx, ws, run_dir, input_dir=None):
    """评分官：六大信号加权评分 + 晋升闸门（可在多相之间复用）。"""
    candidates = ctx.get("candidates")
    if not candidates:
        return _skipped(stage, ctx, "轻梦官未产出候选")
    ranked = []
    for c in candidates:
        sig = _score_candidate(c)
        ok, reason = _scorer_gate(c, sig)
        ranked.append({
            "content_preview": c["content"][:60],
            "source_file": c["source_file"],
            "recall_count": c["recall_count"],
            "unique_query_count": len(c.get("unique_queries") or []),
            "signals": sig, "total_score": sig["total_score"],
            "eligible": ok, "reason": reason,
        })
    ranked.sort(key=lambda r: r["total_score"], reverse=True)
    eligible = [r for r in ranked if r["eligible"]]
    scoring = {"count": len(ranked), "eligible_count": len(eligible), "ranked": ranked}
    ctx["scoring"] = scoring

    # D1：无真实召回/嵌入数据 → 六大信号中的频率/查询多样性/新鲜度/巩固度全为 0，
    # eligible 必然为 0。此情形不能静默产出空结果，必须显式给出 needs_input + degraded。
    has_real_recall = bool(inp.get("recall_records")) or any(
        (c.get("unique_queries") and list(c["unique_queries"]) != ["_auto_dream_phase"])
        for c in candidates)
    degraded = (len(eligible) == 0) and (not has_real_recall)
    extra, needs_input = None, None
    if degraded:
        needs_input = {
            "missing_fields": [
                "input.recall_records（真实召回日志）或 input.memories[].recall："
                "需含 recall_count / unique_queries / relevance_scores / last_seen / consecutive_days",
                "（可选）向量嵌入服务：用于 relevance 的语义增强（本骨架缺失则降级为纯平均）",
            ],
            "why": "无真实召回数据时，频率/查询多样性/新鲜度/巩固度信号全为 0，全部候选总分≈0.06 < 门槛 0.5，"
                   "eligible=0，无法产出任何 MEMORY 晋升物。",
            "how_to_fix": "提供真实召回日志（或至少 memories[].recall）后以相同 run 重投。",
        }
        extra = {"degraded": True, "needs_input": needs_input}

    checks = [
        {"name": "total_score∈[0,1]", "passed": all(0.0 <= r["total_score"] <= 1.0 + EMOTION_BOOST_CAP for r in ranked),
         "detail": ""},
        {"name": "按总分降序", "passed": all(ranked[i]["total_score"] >= ranked[i + 1]["total_score"]
                                        for i in range(len(ranked) - 1)), "detail": ""},
        {"name": "eligible 为布尔", "passed": all(isinstance(r["eligible"], bool) for r in ranked), "detail": ""},
        {"name": "degraded_when_no_recall", "passed": (len(eligible) > 0) or has_real_recall or degraded,
         "detail": f"eligible={len(eligible)} has_real_recall={has_real_recall} degraded={degraded}"},
    ]
    unc = ["相关性信号未做向量语义增强（原件依赖外部嵌入服务，本骨架缺失则降级为纯平均）",
           "评分官是闸门，可在多相之间复用（本团队用于 02-score 与 03-deep 的二次评估）"]
    note = "复刻 SignalScorer：频率/相关性/查询多样性/新鲜度/巩固度/概念丰富度 按 0.24/0.30/0.15/0.15/0.10/0.06 加权。"
    if degraded:
        unc.append("缺真实召回/嵌入数据：eligible=0，本阶段标记 degraded 并给出 needs_input，"
                   "不下游静默产出空 MEMORY 结果")
        note += " ⚠️ degraded=needs_input（缺 input.recall_records / 嵌入服务）"
    return _packet(stage, ctx, "ok",
                   inputs={"candidates_in": len(candidates)},
                   outputs={"scoring": scoring},
                   validation={"checks": checks, "passed": all(c["passed"] for c in checks)},
                   uncertainty=unc, note=note, extra=extra)


def _stage_deep(stage, inp, ctx, ws, run_dir, input_dir=None):
    """深梦官：NREM-CASCADE 评估 + 晋升（写入 run 目录 artifact，不写宿主 MEMORY.md）。"""
    candidates = ctx.get("candidates")
    if not candidates:
        return _skipped(stage, ctx, "轻梦官未产出候选，无法评估晋升")
    rem_boost = inp.get("rem_boost") or {}

    # NREM-CASCADE（复刻 deep_phase.NREMCascade 与 run 中的统计）
    retention_avg = round(sum(_forgetting_retention(24, DEEP_RETENTION_STRENGTH)
                              for _ in candidates) / max(len(candidates), 1), 4)
    low_retention = sum(1 for _ in candidates if _forgetting_retention(24, DEEP_RETENTION_STRENGTH) < 0.3)
    longtail_saved = sum(1 for c in candidates if c["recall_count"] <= 1 and len(c["content"]) > 80)
    synapses_pruned = max(0, low_retention - 2)
    ripple_linked = min(3, len(candidates) // 10)

    promotion_records = []
    p_score = p_recall = p_queries = 0
    for c in candidates:
        sig = _score_candidate(c)
        final = sig["total_score"]
        # REM 加成（复刻 apply_rem_boost：概念命中则乘最大因子）
        boost = 1.0
        for concept in c.get("concepts") or []:
            if concept in rem_boost:
                boost = max(boost, float(rem_boost[concept]))
        final *= boost
        # CASCADE 长尾加分
        if c["recall_count"] <= 1 and len(c["content"]) > 80:
            final += CASCADE_STRENGTH * 0.3
        ok_score = final >= DEEP_MIN_SCORE
        ok_recall = c["recall_count"] >= DEEP_MIN_RECALL
        ok_queries = len(c.get("unique_queries") or []) >= DEEP_MIN_UNIQUE_QUERIES
        p_score += int(ok_score)
        p_recall += int(ok_recall)
        p_queries += int(ok_queries)
        if not (ok_score and ok_recall and ok_queries):
            continue
        promotion_records.append({
            "content": c["content"], "source_file": c["source_file"],
            "score": round(final, 4), "promoted_at": _now(),
            "section": _determine_section(c["content"], c.get("concepts") or []),
        })

    # 落盘：写 run 目录 artifact，**不写** workspace/MEMORY.md（迁移约定：不碰宿主记忆区）
    artifact = run_dir / "artifact-MEMORY.promotions.md"
    if promotion_records:
        lines = ["# 晋升候选（由 qiqi-dream-swarm 生成的 artifact，非宿主 MEMORY.md）", ""]
        for rec in promotion_records:
            lines += [f"## {rec['section']} · {rec['promoted_at'][:10]} 自动晋升",
                      "", rec["content"], ""]
        artifact.write_text("\n".join(lines), encoding="utf-8")
    artifact_rel = str(artifact.relative_to(run_dir)) if artifact.is_file() else None

    deep = {
        "candidates_evaluated": len(candidates),
        "passed_score": p_score, "passed_recall": p_recall, "passed_queries": p_queries,
        "promoted": len(promotion_records),
        "promotion_records": promotion_records,
        "cascade": {"longtail_saved": longtail_saved, "synapses_pruned": synapses_pruned,
                    "ripple_linked": ripple_linked, "strength_applied": CASCADE_STRENGTH,
                    "forgetting_retention_avg": retention_avg},
        "artifact": artifact_rel,
        "thresholds": {"min_score": DEEP_MIN_SCORE, "min_recall": DEEP_MIN_RECALL,
                       "min_unique_queries": DEEP_MIN_UNIQUE_QUERIES},
    }
    ctx["deep"] = deep

    checks = [
        {"name": "promotion_records 字段齐备",
         "passed": all(all(k in r for k in ("content", "source_file", "score", "section"))
                       for r in promotion_records), "detail": f"promoted={len(promotion_records)}"},
        {"name": "门槛计数一致",
         "passed": 0 <= p_score <= len(candidates) and 0 <= p_recall <= len(candidates),
         "detail": f"score={p_score} recall={p_recall} queries={p_queries}"},
        {"name": "未写宿主 MEMORY.md", "passed": True, "detail": "产物只在 run 目录 artifact"},
    ]
    unc = []
    if not promotion_records:
        unc.append("无候选通过晋升门槛（不编造晋升记录）")
    unc.append("相关性未做向量语义增强；晋升仅基于六信号 + 门槛，不判断内容真伪")
    return _packet(stage, ctx, "ok",
                   inputs={"candidates_in": len(candidates), "rem_boost_in": len(rem_boost)},
                   outputs={"deep": deep},
                   validation={"checks": checks, "passed": all(c["passed"] for c in checks)},
                   uncertainty=unc,
                   note="复刻 DeepPhase：CASCADE 长尾拯救/突触修剪/涟漪链接 + 三项门槛 + 关键词路由章节。")


def _stage_rem(stage, inp, ctx, ws, run_dir, input_dir=None):
    """快速眼动官：跨域语义重组 / 生成式梦境 —— 需 LLM，绝不 random 拼串。"""
    candidates = ctx.get("candidates")
    if not candidates:
        return _skipped(stage, ctx, "轻梦官未产出候选，无可重组")
    top = sorted(candidates, key=lambda c: c["recall_count"], reverse=True)[:20]
    payload = {
        "memory_count": len(candidates),
        "source_memories": [{"hash": c["hash"], "content": c["content"],
                             "concepts": c["concepts"], "recall_count": c["recall_count"]}
                            for c in top],
        "emotion_tag_vocabulary": EMOTION_TAGS,
        "promoted_count": (ctx.get("deep") or {}).get("promoted", 0),
        "expected_output_schema": {
            "themes": [{"name": "主题", "count": 1, "related_concepts": ["…"], "boost_factor": 1.1}],
            "fragments": [{"content": "跨域重组后的梦境片段（语义产物）",
                           "source_ids": ["引用的记忆 hash"], "emotion_tags": ["…"],
                           "novelty_score": "0-1", "consolidation_gain": "0-0.5"}],
            "hidden_patterns": [{"pattern": "发现的跨域联系", "evidence": ["hash"]}],
        },
    }
    return _needs_llm(
        stage, ctx, payload,
        ["原件 rem_phase 的生成式梦境用 random.sample 拼 '[梦境合成] …' 占位串"
         "（dreaming/__init__.py:94-105），本骨架绝不复刻这种随机内容，一律 needs_llm",
         "未产出 themes/fragments；下游海马官改用以 03-deep 晋升结果为准"],
        note="请宿主 LLM 按 expected_output_schema 做跨域语义重组；本阶段 outputs 留空。")


def _stage_hippo(stage, inp, ctx, ws, run_dir, input_dir=None):
    """海马官：实体/关系抽取 + 图谱固化 + DEEP-SLEEP 迁移 —— 需 LLM + KG 引擎。"""
    deep = ctx.get("deep")
    if deep is None:
        return _skipped(stage, ctx, "深梦官未产出结果，放弃固化")
    promoted = deep.get("promotion_records", [])
    payload = {
        "promoted_count": len(promoted),
        "documents": [{"source_file": r["source_file"], "content": r["content"]}
                      for r in promoted],
        "dream_topics": [],   # 04-rem 未产出（needs_llm），故为空；不编造
        "expected_output_schema": {
            "entities": [{"name": "实体", "type": "类型"}],
            "relations": [{"subject": "实体", "predicate": "关系", "object": "实体"}],
            "entities_before": 0, "entities_after": 0, "new_entities": 0,
            "new_chunks": 0, "migrated_count": 0, "promoted_count": 0,
            "forgetting_estimate": "0-1",
        },
        "required_capabilities": ["LLM 实体/关系抽取", "知识图谱引擎（原件为 core/wuxing/water/hipporag_fusion.py，未随本包提供）"],
    }
    return _needs_llm(
        stage, ctx, payload,
        ["原件 HippoPhase 依赖 core/wuxing/water/hipporag_fusion.py（HippoRAGFusion，未随本包提供），"
         "且实体/关系抽取为语义任务；本骨架不编造实体/三元组",
         "DEEP-SLEEP 迁移的 migrated_count/promoted_count/forgetting_estimate 由宿主按图谱状态回填"],
        note="请宿主提供 LLM 与知识图谱引擎按 expected_output_schema 回填。",
        needs="llm+kg_engine")


EXECUTORS.update({
    "01-light": _stage_light,
    "02-score": _stage_score,
    "03-deep": _stage_deep,
    "04-rem": _stage_rem,
    "05-hippo": _stage_hippo,
})


# ────────────────────────────── 运行引擎 ──────────────────────────────

def _execute_stage(stage, inp, ctx, ws, run_dir, input_dir=None) -> dict:
    ctx["_stage_started_at"] = _now()
    fn = EXECUTORS.get(stage["id"])
    if fn is None:
        return _failed(stage, ctx, f"未实现执行器: {stage['id']}")
    return fn(stage, inp, ctx, ws, run_dir, input_dir)


def _link_next(records):
    for i, r in enumerate(records):
        r["next"] = records[i + 1]["stage"] if i + 1 < len(records) else None


def _overall_status(records, blocked_stage):
    if any(r["status"] == "failed" for r in records):
        return "failed"
    if blocked_stage:
        return "blocked"
    if any(r["status"] in NEEDS_LLM_STATUSES for r in records):
        return "partial"
    return "completed"


def run_pipeline(inp, ws, run_id=None, quiet=False, input_dir=None):
    run_id = run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-"
                        + _md5(json.dumps(inp, ensure_ascii=False, sort_keys=True))[:8])
    run_dir = ws / "data" / SWARM_NAME / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ctx = {}
    records, blocked_stage, stop = [], None, False

    for stage in STAGES:
        if stop:
            pkt = _skipped(stage, ctx, f"上游硬前置阶段 {blocked_stage} 未满足，流程已停止")
        else:
            pkt = _execute_stage(stage, inp, ctx, ws, run_dir, input_dir)
        records.append(pkt)
        if pkt["status"] in NEEDS_LLM_STATUSES and stage["hard"]:
            blocked_stage, stop = stage["id"], True

    _link_next(records)
    for stage, rec in zip(STAGES, records):
        (run_dir / f"{stage['id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    degraded = any(r.get("degraded") for r in records)
    needs_input = next((r.get("needs_input") for r in records if r.get("needs_input")), None)
    manifest = {
        "swarm": SWARM_NAME, "title": SWARM_TITLE, "version": VERSION,
        "run_id": run_id, "workspace": str(ws), "run_dir": str(run_dir),
        "overall_status": _overall_status(records, blocked_stage),
        "blocked_stage": blocked_stage, "generated_at": _now(),
        "degraded": degraded,
        "needs_input": needs_input,
        "stages": [{"stage": r["stage"], "role": r["role"], "status": r["status"],
                    "prompt_file": r["prompt_file"], "file": f"{r['stage']}.json"} for r in records],
        "input_snapshot": inp,
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not quiet:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest, records, run_dir


# ────────────────────────────── 输入校验（B1） ──────────────────────────────

# 顶层字段类型约束：非法 JSON / 字段类型错误统一为 stdout JSON + exit 2
INPUT_TYPE_SPEC = {
    "memories": (list,), "memory_files": (list,), "recall_records": (dict,),
    "rem_boost": (dict,), "feed_data": (dict,),
}
INPUT_LIST_ELEM = {"memories": (dict, str), "memory_files": (str,)}


def _check_input_types(inp):
    if not isinstance(inp, dict):
        return f"输入 JSON 顶层必须是对象，实际 {type(inp).__name__}"
    for key, types in INPUT_TYPE_SPEC.items():
        if key in inp and inp[key] is not None and not isinstance(inp[key], types):
            names = "/".join(t.__name__ for t in types)
            return f"输入字段类型错误: {key} 期望 {names}，实际 {type(inp[key]).__name__}"
    for key, elems in INPUT_LIST_ELEM.items():
        v = inp.get(key)
        if isinstance(v, list) and any(not isinstance(x, elems) for x in v):
            names = "/".join(t.__name__ for t in elems)
            return f"输入字段元素类型错误: {key}[] 元素期望 {names}"
    return None


# ────────────────────────────── 子命令 ──────────────────────────────

def cmd_plan(args):
    print(f"🌀 {SWARM_NAME} · {SWARM_TITLE}  v{VERSION}")
    print("=" * 66)
    print("DAG（四相治理：浅层整理 → 深层关联 → 跨域重组 → 固化入库，评分官作闸门）：")
    print()
    for i, s in enumerate(STAGES):
        arrow = "  " if i == 0 else ("  │\n  ▼\n")
        llm = " [需 LLM]" if s["requires_llm"] else ""
        # D2：03-deep 是确定性步骤，但无 recall 数据时走降级（eligible=0 → degraded/needs_input），plan 需标出
        degrade = " [降级:无 recall 数据→degraded/needs_input]" if s["id"] == "03-deep" else ""
        hard = " (硬前置)" if s["hard"] else ""
        print(f"{arrow}  [{s['id']}] {s['name']}{llm}{degrade}{hard}")
    print()
    print("纯规则可执行 vs 需 LLM：")
    print("  纯规则：01-light 去重/概念/SWR/遗忘曲线 · 02-score 六信号+门槛 · 03-deep CASCADE+晋升")
    print("  需 LLM：04-rem 跨域语义重组 · 05-hippo 实体关系抽取+图谱固化(还需 kg_engine)")
    print("  闸门：评分官 02-score 复用为多相之间的准入判定")
    print()
    print("各阶段角色 / 输入 / 输出 / 验收标准：")
    print("-" * 66)
    for s in STAGES:
        print(f"[{s['id']}] {s['name']}   角色: {s['role']} ({s['role_name']})"
              f"   依赖: {s['depends_on'] or '无'}")
        print(f"    提示词: {s['prompt_file']}")
        print(f"    输入:   {s['inputs']}")
        print(f"    输出:   {s['outputs']}")
        print(f"    验收:   {s['acceptance']}")
        print()
    print("-" * 66)
    print("产物落盘： <workspace>/data/" + SWARM_NAME + "/<run_id>/NN-<stage>.json")
    print("诚实性：   04-rem / 05-hippo 需要 LLM/宿主能力，必输出 needs_llm 交接包，绝不编造。")


def cmd_run(args):
    ws = resolve_workspace(args.workspace)
    inp_path = Path(args.input).expanduser().resolve()
    if not inp_path.is_file():
        print(json.dumps({"error": f"输入文件不存在: {inp_path}"}, ensure_ascii=False))
        return 2
    try:
        raw = inp_path.read_text(encoding="utf-8")
    except OSError as e:
        print(json.dumps({"error": f"输入文件不可读: {e}"}, ensure_ascii=False))
        return 2
    try:
        inp = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"输入 JSON 非法: {e}"}, ensure_ascii=False))
        return 2
    err = _check_input_types(inp)
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False))
        return 2
    try:
        manifest, records, run_dir = run_pipeline(inp, ws, run_id=args.run_id, input_dir=inp_path.parent)
    except OSError as e:
        print(json.dumps({"error": f"run 目录不可写: {e}"}, ensure_ascii=False))
        return 2
    # D1：无可交付产物（缺召回/嵌入 → eligible=0）时以非零退出码显式失败，不静默产空结果
    if manifest.get("degraded"):
        return 2
    return 0 if manifest["overall_status"] in ("completed", "partial") else 2


def cmd_status(args):
    ws = resolve_workspace(args.workspace)
    run_dir = ws / "data" / SWARM_NAME / args.run_id
    mf = run_dir / "run.json"
    if not mf.is_file():
        print(json.dumps({"error": f"未找到 run: {args.run_id}", "dir": str(run_dir)}, ensure_ascii=False))
        return 2
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"run.json 不可读/非法: {e}", "dir": str(run_dir)}, ensure_ascii=False))
        return 2
    # B2：默认只输出机器可解析的 JSON；人类可读内容仅在 --format text 时输出
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if (getattr(args, "format", "json") or "json") != "text":
        return 0
    print("\n阶段交接包：")
    for s in manifest["stages"]:
        f = run_dir / s["file"]
        if f.is_file():
            pkt = json.loads(f.read_text(encoding="utf-8"))
            v = pkt.get("validation", {}).get("passed")
            print(f"  {s['stage']:<10} {s['status']:<14} schema={'ok' if _valid_packet(pkt) else 'BAD'} validation={v}")
        else:
            print(f"  {s['stage']:<10} {s['status']:<14} 缺少文件: {s['file']}")
    return 0


# ────────────────────────────── schema 校验 ──────────────────────────────

REQUIRED_KEYS = ["swarm", "stage", "stage_name", "role", "role_name", "prompt_file",
                 "depends_on", "status", "started_at", "finished_at", "inputs",
                 "outputs", "validation", "uncertainty", "next"]


def _valid_packet(pkt) -> bool:
    if not isinstance(pkt, dict):
        return False
    if any(k not in pkt for k in REQUIRED_KEYS):
        return False
    if pkt.get("status") not in ("ok", "needs_llm", "needs_executor", "needs_input", "failed", "skipped"):
        return False
    if not isinstance(pkt.get("uncertainty"), list):
        return False
    if pkt.get("status") == "needs_llm":
        if not all(k in pkt for k in ("stage", "role", "prompt_file", "input")):
            return False
        if pkt.get("outputs"):
            return False
    if pkt.get("status") in ("ok", "failed") and "checks" not in pkt.get("validation", {}):
        return False
    if pkt.get("status") == "ok" and not pkt["validation"]["checks"]:
        return False
    return True


# ────────────────────────────── selftest ──────────────────────────────

def cmd_selftest(args):
    pkg_root = Path(__file__).resolve().parent.parent
    sample = pkg_root / "samples" / "example-input.json"
    print(f"🧪 {SWARM_NAME} selftest —— 使用示例输入（明确标注为示例，非真实生产数据）")
    print(f"   sample: {sample}")
    if not sample.is_file():
        print("   ❌ FAIL: 缺少 samples/example-input.json")
        return 1
    inp = json.loads(sample.read_text(encoding="utf-8"))
    ws = Path(tempfile.mkdtemp(prefix="qiqi-dream-selftest-"))
    print(f"   临时工作区: {ws}\n")
    manifest, records, run_dir = run_pipeline(inp, ws, run_id="selftest", quiet=True, input_dir=sample.parent)

    fails = 0

    def check(name, cond, detail=""):
        nonlocal fails
        print(f"   {'✅ PASS' if cond else '❌ FAIL'}: {name}" + (f"  ({detail})" if detail else ""))
        if not cond:
            fails += 1

    check("run.json 落盘", (run_dir / "run.json").is_file(), str(run_dir))
    for stage, rec in zip(STAGES, records):
        f = run_dir / f"{stage['id']}.json"
        check(f"{stage['id']} 交接包落盘", f.is_file(), f.name)
        check(f"{stage['id']} schema 合法", _valid_packet(rec), f"status={rec['status']}")
        check(f"{stage['id']} 含 prompt_file", rec.get("prompt_file") == stage["prompt_file"],
              rec.get("prompt_file"))

    by_id = {r["stage"]: r for r in records}
    li = by_id["01-light"]
    check("01-light 生成候选且去重生效", li["status"] == "ok"
          and li["outputs"]["light"]["candidates_generated"] >= 1
          and li["outputs"]["light"]["duplicates_removed"] >= 1,
          f"cand={li['outputs']['light']['candidates_generated']} dup={li['outputs']['light']['duplicates_removed']}")
    check("01-light 候选含 content/source_file/concepts",
          all(all(k in c for k in ("content", "source_file", "concepts"))
              for c in li["outputs"]["candidates"]))
    sc = by_id["02-score"]
    check("02-score 六大信号齐备且降序", sc["status"] == "ok"
          and sc["outputs"]["scoring"]["ranked"]
          and all(len(r["signals"]) >= 6 for r in sc["outputs"]["scoring"]["ranked"]),
          f"eligible={sc['outputs']['scoring']['eligible_count']}/{sc['outputs']['scoring']['count']}")
    dp = by_id["03-deep"]
    art = run_dir / (dp["outputs"].get("deep", {}).get("artifact") or "__none__")
    check("03-deep 晋升并落盘 artifact", dp["status"] == "ok"
          and dp["outputs"]["deep"]["promoted"] >= 1 and art.is_file(),
          f"promoted={dp['outputs']['deep']['promoted']} artifact={dp['outputs']['deep']['artifact']}")
    check("03-deep CASCADE 指标齐备",
          all(k in dp["outputs"]["deep"]["cascade"] for k in
              ("longtail_saved", "synapses_pruned", "ripple_linked", "forgetting_retention_avg")))
    rm = by_id["04-rem"]
    check("04-rem 输出 needs_llm（不编造梦境）", rm["status"] == "needs_llm" and rm["outputs"] == {},
          f"status={rm['status']} outputs_empty={rm['outputs'] == {}}")
    check("04-rem 契约字段齐备", all(k in rm for k in ("stage", "role", "prompt_file", "input")))
    hp = by_id["05-hippo"]
    check("05-hippo 输出 needs_llm（不编造实体/三元组）", hp["status"] == "needs_llm" and hp["outputs"] == {},
          f"needs={hp.get('needs')}")
    check("05-hippo needs 标明 kg_engine", hp.get("needs") == "llm+kg_engine", hp.get("needs"))

    print("\n   预期整体状态: partial（04/05 需 LLM 但非硬前置，流程继续）")
    check("overall_status == partial", manifest["overall_status"] == "partial", manifest["overall_status"])

    # ── D1 必补回归：缺 recall 数据时必须 degraded + needs_input，而非静默产空 ──
    no_recall_inp = {"memories": [
        {"content": "缺少召回日志的真实记忆条目，用于验证评分官是否如实举手，而不是安静地一条都不晋升。",
         "source_file": "selftest-no-recall.md", "tags": ["测试"]}]}
    m_d, recs_d, _ = run_pipeline(no_recall_inp, ws, run_id="no-recall", quiet=True)
    sc_d = {r["stage"]: r for r in recs_d}["02-score"]
    check("D1 回归 缺 recall → degraded=True 且给出 needs_input",
          m_d.get("degraded") is True and isinstance(m_d.get("needs_input"), dict)
          and bool(sc_d.get("needs_input", {}).get("missing_fields")),
          f"degraded={m_d.get('degraded')}")

    # ── B1/B2 必补回归 ──
    def _is_json(s):
        try:
            json.loads(s)
            return True
        except Exception:
            return False

    def _cli(extra):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--workspace", str(ws)] + extra,
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    bad = ws / "selftest-bad.json"
    bad.write_text('{ this is not json ', encoding="utf-8")
    rc_b, out_b, err_b = _cli(["run", "--input", str(bad), "--run-id", "selftest-bad"])
    check("回归① 非法 JSON → rc=2 且 stdout 为合法 JSON",
          rc_b == 2 and _is_json(out_b) and "Traceback" not in err_b, f"rc={rc_b}")
    rc_n, out_n, err_n = _cli(["status", "--run-id", "no-such-run-xyz"])
    check("回归② 不存在的 run_id → rc=2 且无 traceback",
          rc_n == 2 and _is_json(out_n) and "Traceback" not in err_n, f"rc={rc_n}")
    rc_s, out_s, err_s = _cli(["status", "--run-id", "selftest"])
    check("回归③ status 默认输出可被 json.loads 解析", rc_s == 0 and _is_json(out_s), f"rc={rc_s}")

    print(f"\n{'✅ selftest 全部通过' if fails == 0 else f'❌ selftest 失败 {fails} 项'}  (产物: {run_dir})")
    return 0 if fails == 0 else 1


def build_parser():
    p = argparse.ArgumentParser(prog="swarmflow.py", description=f"{SWARM_NAME} · {SWARM_TITLE}")
    p.add_argument("--workspace", help="工作区（优先于 QIQI_WORKSPACE 与当前目录）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="打印 DAG 与各阶段角色/输入/输出")
    r = sub.add_parser("run", help="执行流水线")
    r.add_argument("--input", required=True, help="输入 JSON 文件")
    r.add_argument("--run-id", help="自定义 run_id")
    s = sub.add_parser("status", help="查看某次 run 的状态")
    s.add_argument("--run-id", required=True)
    s.add_argument("--format", choices=["json", "text"], default="json",
                   help="输出格式：json（默认，纯 JSON，可被 json.loads 解析）| text（JSON + 人类可读摘要）")
    sub.add_parser("selftest", help="用示例输入跑通全部阶段")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "plan":
        cmd_plan(args)
        return 0
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "selftest":
        return cmd_selftest(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
