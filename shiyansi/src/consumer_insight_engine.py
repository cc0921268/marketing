# -*- coding: utf-8 -*-
"""实验4：AI + Python 消费者洞察引擎（v0.4 · 蓝牙耳机品类）

串联链路：
    clean_data.csv（实验3）
        -> 语义编码 encode_review()（实验2 Skill 口径）
        -> Pandas 统计（痛点排行 / 情绪分布 / 品牌交叉）
        -> 洞察报告 build_insight_report()（事实 / 推断 / 建议三分离）
        -> 证据追溯 top_evidence()（≥3 条原文 + review_id）

职责红线：
    - 所有计数、占比、排名由 pandas 计算，AI 不参与算数
    - AI 只接收统计表（不含零散原文），输出解释时必须标注事实/推断/建议
    - 任何结论必须能回溯到 review_id 与原文逐字片段
    - 百分比一律带分母，格式统一为 "28/267（10.5%）"

运行：
    python3 src/consumer_insight_engine.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEAN_DEFAULT = PROJECT_ROOT / "data" / "processed" / "clean_data.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# ---------------------------------------------------------------------------
# 9 类耳机痛点体系（从 237 个评论模板实际归纳）
# ---------------------------------------------------------------------------
# 每类：key=规范名，value=(中文全称, 关键词列表)
# 关键词采用"子串匹配"，因此"降噪"能命中"降噪名不副实"。
PAIN_DIMENSIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "anc": ("降噪", ("降噪", "隔音", "噪音", "太吵", "听不见报站", "噪音大")),
    "battery": ("续航", ("续航", "没电", "电量", "充电", "电池", "一天两充", "掉电")),
    "fit": ("佩戴舒适", ("佩戴", "耳朵", "耳塞", "腔体", "戴久", "戴一会",
                        "戴两小时", "不胀", "塞不进去", "总是掉", "耳压",
                        "头晕", "夹头", "夹耳")),
    "connection": ("连接稳定性", ("断连", "配对", "连接", "抽风", "切换", "连上",
                                  "断一下", "掉线")),
    "call": ("通话质量", ("通话", "麦克风", "收音", "听不清", "风噪", "开会",
                          "会议", "桶里")),
    "sound": ("音质", ("音质", "低音", "低频", "中高频", "发刺", "糊", "刮耳",
                       "声场", "人声", "闷", "轰头", "齿音", "破音")),
    "build": ("做工质感", ("做工", "划痕", "手感", "颜值", "质感", "拆封", "开合")),
    "service": ("售后服务", ("售后", "客服", "保修", "换货", "寄回", "自费检测",
                             "价格保护", "不理", "没消息")),
    "price": ("价格性价比", ("有点贵", "肉疼", "性价比", "太值", "价格", "虚高",
                             "偏贵", "降价", "值这个价")),
}

# 负向情感线索（抱怨/不满）
# 注意：转折词（但/就是/却/不过/然而）不在此列——它们是**极性切换信号**，
# 本身不带情感。把它们当负向线索会导致"音质没得说，就是连接抽风"整句被判负面，
# 并把"音质"误标为痛点。转折词见 CONTRAST_WORDS。
NEGATIVE_CUES = (
    "名不副实", "不值", "实在有点贵", "肉疼", "差", "糟", "问题", "失败", "严重",
    "疼", "晕", "掉", "断", "糊", "刺", "刮耳", "闷", "吵", "虚标", "拒绝",
    "被拒", "没消息", "形同虚设", "折腾", "抽风", "不一致", "偏小", "偏硬",
    "没声音", "没电", "掉得快", "太快", "不便", "麻烦", "可惜", "假", "虚",
)

# 转折词：标记"后半句情感翻面"
CONTRAST_WORDS = ("但", "但是", "就是", "却", "不过", "然而", "可惜", "只是")

# 正向情感线索（认可/满意）
POSITIVE_CUES = (
    "给力", "扎实", "惊喜", "不错", "太值", "性价比拉满", "很轻", "顺畅", "很快",
    "清楚", "细腻", "踏实", "漂亮", "有质感", "带感", "值了", "舒服", "满意",
    "推荐", "好用", "稳", "够用", "还行", "没得说", "音画同步",
)

# 中性/平淡线索
NEUTRAL_CUES = ("一般", "原装", "正常水平", "普通", "能用", "没有特别印象", "跟风")

# 场景词典（从数据中实际出现的场景）
SCENARIO_WORDS: dict[str, str] = {
    "地铁": "地铁通勤", "通勤": "地铁通勤", "高铁": "高铁", "出差": "出差",
    "办公室": "办公室", "会议": "视频会议", "图书馆": "图书馆", "宿舍": "宿舍",
    "开车": "开车", "跑步": "跑步", "健身": "健身房", "健身房": "健身房",
    "打游戏": "打游戏", "游戏": "打游戏",
}

# 购买障碍线索
BARRIER_CUES = {
    "价格太高": ("有点贵", "肉疼", "偏贵", "虚高", "不值"),
    "降价顾虑": ("刚买就降价", "价格保护"),
    "佩戴不适": ("塞不进去", "耳朵疼", "耳压", "头晕", "夹头"),
    "售后风险": ("售后", "客服", "自费检测", "换货被拒"),
}

# C8 已标记的噪音（引擎再兜一层，双重保险）
NOISE_PATTERNS = [
    re.compile(r"^[\W_]+$"),
    re.compile(r"^\d+$"),
    re.compile(r"^(.)\1{2,}$"),
]
NOISE_KEYWORDS = ("加我微信", "代购", "转发抽奖", "低价出", "私聊", "优惠券")
NOISE_IRRELEVANT = ("天气不错", "祝商家", "系统默认好评", "路过看看", "生意兴隆")
NOISE_MIN_LEN = 2

# 元数据（会被 report 引用）
ENGINE_VERSION = "v0.4"
DIMENSION_ORDER = list(PAIN_DIMENSIONS.keys())


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def fmt_ratio(count: int, total: int, digits: int = 1) -> str:
    """统一的占比格式：`28/267（10.5%）`。分母为 0 时返回 `0/0（—）`。"""
    if total <= 0:
        return f"{count}/0（—）"
    return f"{count}/{total}（{count / total * 100:.{digits}f}%）"


def _hit_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    """返回文本中命中的关键词列表（保持词典顺序，去重）。"""
    return [kw for kw in keywords if kw in text]


def split_clauses(text: str) -> list[str]:
    """按中文标点 + 转折词切分小句。

    为什么要切小句：整句做极性判断会把"降噪给力，可惜续航一般"判成
    降噪也负面。切句后每个维度只在自己所在的小句里判极性，
    才能得到"降噪=正面、续航=负面"的正确结果。

    还要在转折词处再切一刀，因为转折词可能出现在小句内部：
        "音质和降噪都不错，但开车戴一会儿耳朵就疼"
        -> ["音质和降噪都不错", "但", "开车戴一会儿耳朵就疼"]
    这样"耳朵疼"才不会被前面的"不错"带偏成正向。
    """
    # 先按标点切
    parts = re.split(r"[，。；！？、\n]", text)
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 再在转折词处切（保留转折词到后一段，作为极性信号）
        pattern = "(" + "|".join(re.escape(w) for w in CONTRAST_WORDS) + ")"
        pieces = re.split(pattern, part)
        buf = ""
        for piece in pieces:
            if not piece:
                continue
            if piece in CONTRAST_WORDS:
                if buf.strip():
                    out.append(buf.strip())
                buf = piece
            else:
                buf += piece
        if buf.strip():
            out.append(buf.strip())
    return out


def clause_polarity(clause: str) -> str:
    """单个小句的极性：negative / positive / neutral / none。"""
    neg = any(c in clause for c in NEGATIVE_CUES)
    pos = any(c in clause for c in POSITIVE_CUES)
    neu = any(c in clause for c in NEUTRAL_CUES)
    if neg and pos:
        # 同一小句内正负并存（"低音轰头但糊"）→ 以负向为主，因为抱怨通常更具体
        return "negative"
    if neg:
        return "negative"
    if pos:
        return "positive"
    if neu:
        return "neutral"
    return "none"


def find_dimension_clause(clauses: list[str], keywords: tuple[str, ...]) -> tuple[int, str] | None:
    """找到包含该维度关键词的小句，返回 (下标, 小句)。"""
    for i, c in enumerate(clauses):
        if any(kw in c for kw in keywords):
            return i, c
    return None


def find_all_dimension_clauses(clauses: list[str], keywords: tuple[str, ...]) -> list[tuple[int, str]]:
    """返回该维度**所有**命中位置 (下标, 小句)。

    为什么要全部：一个维度的抱怨可能分散在多句，
        "腔体太大"（中性） + "我的耳朵塞不进去"（中性） + "总是掉"（负面）
    只看第一个命中位置会漏判，必须找到一个负面小句为止。
    """
    return [(i, c) for i, c in enumerate(clauses) if any(kw in c for kw in keywords)]


def _judge_clause_negative(clause: str, clauses: list[str], idx: int, dim_key: str) -> bool:
    """判断某个维度小句是否构成"痛点"（负面）。

    三条规则按优先级：
        (a) 本小句本身负面                       -> 是
        (b) 本小句中性，后一小句负面且不属其他维度 -> 是
            （"腔体太大" + "总是掉"）
        (c) 本小句中性/正向，前一小句带转折词      -> 是
            （"降噪给力，可惜续航一般"）
    """
    pol = clause_polarity(clause)
    if pol == "negative":
        return True

    # (b) 向后看一句
    if pol == "none" and idx + 1 < len(clauses):
        nxt = clauses[idx + 1]
        if clause_polarity(nxt) == "negative":
            # 后句若明确属于别的维度，则不归到本维度
            others = [
                k for k, (_, kws) in PAIN_DIMENSIONS.items()
                if k != dim_key and any(w in nxt for w in kws)
            ]
            if not others:
                return True

    # (c) 向前看转折
    if pol in ("none", "positive") and idx > 0:
        prev = clauses[idx - 1]
        if any(w in prev for w in CONTRAST_WORDS) and pol == "none":
            return True

    return False


def _clip_clause(clause: str, keywords: list[str], max_len: int = 40) -> str:
    """从已定位的小句里截取证据片段（本身就是完整小句，直接返回）。"""
    c = clause.strip(" ，。；、")
    if not keywords or not c:
        return c[:max_len]
    # 小句通常已很短，直接用它，保证"逐字子串"
    return c[:max_len]


def _extract_quote(text: str, keywords: list[str], max_len: int = 40) -> str:
    """从原文中截取包含关键词的片段作为证据（逐字子串，不改写）。

    策略：定位第一个命中关键词，向其左右扩展，尽量落在标点边界上。
    """
    if not text:
        return ""
    if not keywords:
        return text[:max_len]

    pos = -1
    for kw in keywords:
        i = text.find(kw)
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0:
        return text[:max_len]

    # 以关键词为中心，向前后各扩 12 字
    start = max(0, pos - 12)
    end = min(len(text), pos + len(keywords[0]) + 16)

    # 向前找标点边界（不跨越逗号/句号，保证语义完整）
    for i in range(pos - 1, start - 1, -1):
        if text[i] in "，。；！？、":
            start = i + 1
            break
    # 向后找标点边界
    for i in range(end - 1, pos, -1):
        if text[i] in "，。；！？":
            end = i
            break

    quote = text[start:end].strip(" ，。；、")
    if not quote:
        quote = text[max(0, pos - 6): pos + 20]
    return quote[:max_len]


def detect_sentiment(text: str) -> tuple[str, str]:
    """情绪判定：positive / negative / neutral / mixed / unknown。

    返回 (情绪, 判定依据)。规则优先级：
        1. 正负线索都有 -> mixed（如"音质没得说，就是连接抽风"）
        2. 只有负向 -> negative
        3. 只有正向 -> positive
        4. 只有中性 -> neutral
        5. 都没有 -> unknown
    """
    if not text or not text.strip():
        return "unknown", "空文本"

    clauses = split_clauses(text)
    pols = [clause_polarity(c) for c in clauses]
    has_neg = "negative" in pols
    has_pos = "positive" in pols
    # 兜底：小句级都没判出来时，退回整句线索扫描
    if not has_neg and not has_pos:
        has_neg = any(c in text for c in NEGATIVE_CUES)
        has_pos = any(c in text for c in POSITIVE_CUES)

    neg = [c for c in NEGATIVE_CUES if c in text]
    pos = [c for c in POSITIVE_CUES if c in text]
    neu = [c for c in NEUTRAL_CUES if c in text]

    if has_neg and has_pos:
        return "mixed", f"正负并存（负:{neg[:2]} 正:{pos[:2]}）"
    if has_neg:
        return "negative", f"负向线索 {neg[:3]}"
    if has_pos:
        return "positive", f"正向线索 {pos[:3]}"
    if neu:
        return "neutral", f"中性线索 {neu[:2]}"
    return "unknown", "无明确情感线索"


def is_noise(text: str) -> tuple[bool, str]:
    """噪音判定（与实验3 C8 口径一致，双重保险）。"""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return True, "空文本"
    t = str(text).strip()
    if len(t) < NOISE_MIN_LEN:
        return True, f"长度 {len(t)} < {NOISE_MIN_LEN}"
    for pat in NOISE_PATTERNS:
        if pat.match(t):
            return True, "纯符号/纯数字/单字重复"
    for kw in NOISE_KEYWORDS:
        if kw in t:
            return True, f"广告引流（{kw}）"
    for kw in NOISE_IRRELEVANT:
        if kw in t:
            return True, f"无关内容（{kw}）"
    return False, ""


def detect_scenario(text: str) -> str | None:
    """场景识别，多个场景取第一个命中的（同一评论通常只讲一个主场景）。"""
    for word, label in SCENARIO_WORDS.items():
        if word in text:
            return label
    return None


def detect_barrier(text: str) -> str | None:
    """购买障碍识别。"""
    for label, cues in BARRIER_CUES.items():
        if any(c in text for c in cues):
            return label
    return None


# ---------------------------------------------------------------------------
# 语义编码（实验2 Skill 口径的确定性实现）
# ---------------------------------------------------------------------------


def encode_review(review_id: str, text: str, upstream_invalid: bool = False) -> dict[str, Any]:
    """单条评论 -> 结构化编码（严格对齐实验2 schema.json 的字段）。

    设计要点：
        - 痛点可多个（一句评论可能同时抱怨续航和佩戴），pain_point 取主痛点，
          全部痛点存 pain_points 列表（扩展字段，不破坏 schema 必填项）
        - 每个有值的判断字段都必须有 evidence 支撑（逐字子串）
        - 无法判断时给 null 并记入 unjudged_fields，绝不编造
        - upstream_invalid=True 表示实验3 的 C8 已判为噪音，此处直接拒答
          （双重保险：实验3 的判定优先，本引擎再兜一层正则）
    """
    text = "" if text is None else str(text)
    noise, noise_reason = is_noise(text)
    if not noise and upstream_invalid:
        noise, noise_reason = True, "实验3 C8 已标记为无效评论"

    result: dict[str, Any] = {
        "review_id": review_id,
        "sentiment": "unknown",
        "need": None,
        "pain_point": None,
        "scenario": None,
        "purchase_barrier": None,
        "evidence": [],
        "confidence": "low",
        "refuse": False,
        "refuse_reason": None,
        "unjudged_fields": [],
        # 扩展字段（不影响 schema 必填项，供统计使用）
        "pain_points": [],
        "pain_detail": [],
    }

    # 噪音直接拒答
    if noise:
        result["refuse"] = True
        result["refuse_reason"] = noise_reason
        result["unjudged_fields"] = [
            "sentiment", "need", "pain_point", "scenario", "purchase_barrier"
        ]
        result["pain_points"] = []
        return result

    sentiment, sent_reason = detect_sentiment(text)
    result["sentiment"] = sentiment

    evidence: list[dict[str, str]] = []
    if sentiment in ("positive", "negative", "mixed"):
        # 情绪证据：截取情感线索所在片段
        cue_pool = NEGATIVE_CUES + POSITIVE_CUES
        quote = _extract_quote(text, _hit_keywords(text, cue_pool))
        if quote:
            evidence.append({"quote": quote, "field": "sentiment"})
    else:
        result["unjudged_fields"].append("sentiment")

    # 逐维度扫描痛点（小句级极性判定，遍历该维度所有命中位置）
    clauses = split_clauses(text)
    pain_hits: list[dict[str, Any]] = []
    for key in DIMENSION_ORDER:
        label, keywords = PAIN_DIMENSIONS[key]
        positions = find_all_dimension_clauses(clauses, keywords)
        if not positions:
            continue

        # 逐个命中位置判极性，取第一个"判为负面"的位置作为证据锚点
        chosen: tuple[int, str] | None = None
        for pos, cl in positions:
            if _judge_clause_negative(cl, clauses, pos, key):
                chosen = (pos, cl)
                break
        if not chosen:
            continue
        idx, clause = chosen
        pol = "negative"
        _ = pol

        # (a) 维度小句本身是负面 -> 直接判定
        # (b) 维度小句中性，但后一小句以转折/承接词引导且为负面：
        #     "低音轰头" + "但糊"  -> 音质痛点；"腔体太大" + "总是掉" -> 佩戴痛点
        if pol == "none" and idx + 1 < len(clauses):
            nxt = clauses[idx + 1]
            nxt_pol = clause_polarity(nxt)
            # 后一小句是负面，且没有另起新维度主题（避免串到别的维度）
            other_dim = any(
                find_dimension_clause([nxt], kw) is not None
                for k, (_, kws) in PAIN_DIMENSIONS.items() if k != key
                for kw in [kws]
            )
            if nxt_pol == "negative" and not other_dim:
                pol = "negative"

        # (c) 前一小句含转折词且为负面 -> 当前小句是被抱怨的那句
        #     "降噪给力，可惜续航一般"：续航小句中性，前句有"可惜"
        if pol in ("none", "positive") and idx > 0:
            prev = clauses[idx - 1]
            if any(w in prev for w in CONTRAST_WORDS):
                if pol == "none":
                    pol = "negative"

        if pol != "negative":
            continue

        hits = _hit_keywords(clause, keywords) or _hit_keywords(text, keywords)
        pain_hits.append({
            "dimension": key,
            "label": label,
            "keywords": hits,
            "quote": _clip_clause(clause, hits),
        })

    if pain_hits:
        # 主痛点 = 第一个命中维度（DIMENSION_ORDER 顺序即业务优先级）
        primary = pain_hits[0]
        result["pain_point"] = primary["label"]
        result["pain_points"] = [p["label"] for p in pain_hits]
        result["pain_detail"] = pain_hits
        for p in pain_hits:
            if p["quote"]:
                evidence.append({"quote": p["quote"], "field": "pain_point"})
        # need 由痛点反推（"希望解决 X"），但只在有明确痛点时给出
        result["need"] = f"改善{primary['label']}体验"
    else:
        result["unjudged_fields"].append("pain_point")
        # 无痛点但有正向表达 -> need 为"认可/复购"
        if sentiment == "positive":
            result["need"] = "对现有体验的认可与复购意愿"

    scenario = detect_scenario(text)
    if scenario:
        result["scenario"] = scenario
        sc_quote = _extract_quote(text, [k for k in SCENARIO_WORDS if k in text])
        if sc_quote:
            evidence.append({"quote": sc_quote, "field": "scenario"})
    else:
        result["unjudged_fields"].append("scenario")

    barrier = detect_barrier(text)
    if barrier:
        result["purchase_barrier"] = barrier
    else:
        result["unjudged_fields"].append("purchase_barrier")

    result["evidence"] = evidence

    # 置信度：判断字段越多、证据越全 -> 越高
    judged = 5 - len(result["unjudged_fields"])
    covered = len({e["field"] for e in evidence})
    if judged >= 3 and covered >= 3:
        result["confidence"] = "high"
    elif judged >= 2:
        result["confidence"] = "medium"
    else:
        result["confidence"] = "low"

    return result


def encode_batch(df: pd.DataFrame, text_col: str = "review_text",
                 id_col: str = "review_id",
                 valid_col: str = "is_valid_review") -> pd.DataFrame:
    """批量编码，返回编码表（一行一评论）。

    若数据带实验3 的 `is_valid_review` 列，则 is_valid_review=0 的行
    直接被引擎判为拒答，保证拒答计数与实验3 口径一致。
    """
    rows = []
    has_valid = valid_col in df.columns
    for idx, (rid, text) in enumerate(zip(df[id_col], df[text_col])):
        upstream_bad = bool(has_valid and int(df[valid_col].iloc[idx]) == 0)
        rows.append(encode_review(str(rid), text, upstream_invalid=upstream_bad))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pandas 统计层（所有数字都在这里产生）
# ---------------------------------------------------------------------------


def load_clean(path: Path | str = CLEAN_DEFAULT) -> pd.DataFrame:
    return pd.read_csv(path)


def filter_valid(df: pd.DataFrame) -> pd.DataFrame:
    """只保留有效 + 品牌型号一致的记录（实验3 约定的派生列）。"""
    out = df.copy()
    if "is_valid_review" in out.columns:
        out = out[out["is_valid_review"] == 1]
    if "is_consistent" in out.columns:
        out = out[out["is_consistent"] == 1]
    return out


def sentiment_distribution(enc: pd.DataFrame, enc_all: pd.DataFrame | None = None) -> pd.DataFrame:
    """情绪分布表。

    分母口径：`enc_all`（全部原始记录）——这样拒答才能被统计到。
    若不给 enc_all，则退回用 enc，此时拒答恒为 0（因为噪音已被过滤）。
    """
    base = enc_all if enc_all is not None else enc
    total = len(base)
    order = ["positive", "negative", "neutral", "mixed", "unknown"]
    labels = {
        "positive": "正面", "negative": "负面", "neutral": "中立",
        "mixed": "混合", "unknown": "无法判断",
    }
    is_refuse = base["refuse"].astype(bool)

    rows = []
    for key in order:
        # 拒答记录的 sentiment 恒为 unknown，但它们是"另一类"，
        # 必须从"无法判断"里剔除，否则会重复计数
        n = int(((base["sentiment"] == key) & ~is_refuse).sum())
        rows.append({
            "情绪": labels[key],
            "编码值": key,
            "条数": n,
            "占比": fmt_ratio(n, total),
            "分母": total,
        })
    n_refuse = int(is_refuse.sum())
    rows.append({
        "情绪": "拒答（噪音）", "编码值": "refuse",
        "条数": n_refuse, "占比": fmt_ratio(n_refuse, total), "分母": total,
    })
    # 自检：五类情绪 + 拒答 应恰好等于 total
    s = sum(r["条数"] for r in rows)
    assert s == total, f"情绪分布合计 {s} != 分母 {total}"
    return pd.DataFrame(rows)


def pain_ranking(enc: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """痛点排行表。

    口径（重点）：
        - 分母 = 有效评论数（filter_valid 后的行数）
        - 一条评论若同时抱怨多个维度，每个维度各计 1 次（多选题口径）
        - 因此"各维度条数之和"可能大于分母，这是正常的，需在报告中说明
    """
    total = len(df)
    valid_ids = set(df["review_id"].astype(str))

    # 展开：一行一（评论, 维度）
    exploded: list[dict[str, Any]] = []
    for _, r in enc.iterrows():
        rid = str(r["review_id"])
        if rid not in valid_ids:
            continue
        if r["refuse"]:
            continue
        for dim in r["pain_points"]:
            exploded.append({"review_id": rid, "label": dim})

    if not exploded:
        return pd.DataFrame(columns=[
            "排名", "痛点维度", "提及条数", "占比", "分母", "占提及评论",
            "平均评分", "涉及品牌数", "证据数",
        ])

    exp_df = pd.DataFrame(exploded)
    # 每条评论的去重维度（用于"占提及评论"）
    pains_per_review = exp_df.groupby("review_id")["label"].nunique()
    n_reviews_with_pain = int((pains_per_review > 0).sum())

    # 关联评论主表拿评分/品牌
    merged = exp_df.merge(
        df[["review_id", "brand", "rating"]].assign(
            review_id=lambda x: x["review_id"].astype(str)
        ),
        on="review_id", how="left",
    )

    rows = []
    for label, grp in merged.groupby("label"):
        n = len(grp)
        dim_reviews = set(grp["review_id"])
        rows.append({
            "痛点维度": label,
            "提及条数": n,
            "占比": fmt_ratio(n, total),
            "分母": total,
            "占提及评论": f"{n}/{n_reviews_with_pain}",
            "提及评论数": n_reviews_with_pain,
            "平均评分": round(float(grp["rating"].mean()), 2) if grp["rating"].notna().any() else None,
            "涉及品牌数": int(grp["brand"].nunique()),
            "证据数": n,
        })

    out = pd.DataFrame(rows).sort_values(
        ["提及条数", "痛点维度"], ascending=[False, True]
    ).reset_index(drop=True)
    out.insert(0, "排名", range(1, len(out) + 1))
    return out


def brand_pain_cross(enc: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """品牌 x 痛点交叉表（行=品牌，列=痛点维度，值=提及条数）。"""
    valid_ids = set(df["review_id"].astype(str))
    labels = [v[0] for v in PAIN_DIMENSIONS.values()]

    records = []
    for brand, grp in df.groupby("brand"):
        ids = set(grp["review_id"].astype(str))
        sub = enc[enc["review_id"].astype(str).isin(ids)]
        n_brand = len(grp)
        row: dict[str, Any] = {"品牌": brand, "评论数": n_brand}
        counter: dict[str, int] = {lb: 0 for lb in labels}
        for _, r in sub.iterrows():
            if r["refuse"]:
                continue
            for lb in r["pain_points"]:
                counter[lb] = counter.get(lb, 0) + 1
        for lb in labels:
            row[lb] = counter[lb]
        row["痛点总数"] = sum(counter.values())
        records.append(row)

    out = pd.DataFrame(records)
    if not out.empty:
        out = out.sort_values("评论数", ascending=False).reset_index(drop=True)
    return out


def brand_sentiment_stats(enc: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """品牌 x 情绪交叉表，每格给 `n/品牌评论数（%）`。"""
    rows = []
    for brand, grp in df.groupby("brand"):
        ids = set(grp["review_id"].astype(str))
        sub = enc[enc["review_id"].astype(str).isin(ids)]
        total = len(grp)
        row: dict[str, Any] = {"品牌": brand, "评论数": total, "平均评分": round(float(grp["rating"].mean()), 2) if grp["rating"].notna().any() else None}
        for key, label in [("positive", "正面"), ("negative", "负面"),
                           ("neutral", "中立"), ("mixed", "混合")]:
            n = int((sub["sentiment"] == key).sum())
            row[label] = fmt_ratio(n, total)
        row["负面率"] = round(float((sub["sentiment"] == "negative").sum()) / total * 100, 1) if total else 0.0
        rows.append(row)
    out = pd.DataFrame(rows)
    return out.sort_values("负面率", ascending=False).reset_index(drop=True) if not out.empty else out


def top_evidence(enc: pd.DataFrame, df: pd.DataFrame, dimension: str,
                 k: int = 3) -> list[dict[str, Any]]:
    """取某痛点维度的前 k 条证据（含 review_id + 原文 + 逐字片段）。

    排序策略：先按评论互动量降序（代表关注度高），再按评分升序（抱怨更强烈的优先）。
    """
    label = dimension
    valid_ids = set(df["review_id"].astype(str))
    rows = []
    for _, r in enc.iterrows():
        rid = str(r["review_id"])
        if rid not in valid_ids or r["refuse"]:
            continue
        if label not in r["pain_points"]:
            continue
        match = next((p for p in r["pain_detail"] if p["label"] == label), None)
        if not match:
            continue
        rows.append({"review_id": rid, "quote": match["quote"]})
    if not rows:
        return []

    ev = pd.DataFrame(rows).merge(
        df[["review_id", "brand", "product", "rating", "interaction_count", "review_text"]]
        .assign(review_id=lambda x: x["review_id"].astype(str)),
        on="review_id", how="left",
    )
    ev = ev.sort_values(
        ["interaction_count", "rating"], ascending=[False, True], na_position="last"
    ).head(k)

    out = []
    for _, r in ev.iterrows():
        out.append({
            "review_id": r["review_id"],
            "brand": r["brand"],
            "product": r["product"],
            "rating": None if pd.isna(r["rating"]) else float(r["rating"]),
            "interaction_count": None if pd.isna(r["interaction_count"]) else int(r["interaction_count"]),
            "quote": r["quote"],
            "review_text": r["review_text"],
        })
    return out


# ---------------------------------------------------------------------------
# AI 解释层（只接收统计表，不接触原始零散文本）
# ---------------------------------------------------------------------------


def build_insight_report(stats: dict[str, pd.DataFrame], meta: dict[str, Any]) -> str:
    """基于统计表生成洞察报告，严格区分「事实数据 / 推断假设 / 行动建议」。

    设计原则：
        - 报告里的每个数字都从 stats 里取，不手写、不估算
        - 事实段只陈述统计结果；推断段必须标注依据；建议段必须可执行
        - 不出现"某品牌质量差"这类绝对化断言（合成数据，避免商业诋毁）
    """
    ranking = stats["pain_ranking"]
    senti = stats["sentiment"]
    brand_senti = stats["brand_sentiment"]
    cross = stats["brand_pain"]
    total = meta["total_reviews"]
    lines: list[str] = []

    lines.append("# 消费者洞察报告（v0.4 · 蓝牙耳机品类）")
    lines.append("")
    lines.append(f"> 生成时间：{meta['generated_at']}　|　"
                 f"样本：{total} 条有效评论（原始 {meta['raw_rows']} 条，"
                 f"拒答 {meta['refused']} 条）")
    lines.append("> 数据性质：**程序合成的模拟数据**，结论仅用于方法演示，"
                 "不代表任何真实品牌的市场表现。")
    lines.append("")

    # ---------------- 一、事实数据 ----------------
    lines.append("## 一、事实数据（可复算，分母已标明）")
    lines.append("")

    # 1.1 情绪结构
    lines.append("### 1.1 情绪结构")
    lines.append("")
    lines.append("| 情绪 | 条数 | 占比（分母=全部编码记录） |")
    lines.append("| --- | --- | --- |")
    for _, r in senti.iterrows():
        lines.append(f"| {r['情绪']} | {r['条数']} | {r['占比']} |")
    lines.append("")
    neg_row = senti[senti["编码值"] == "negative"]
    if not neg_row.empty:
        neg_n = int(neg_row.iloc[0]["条数"])
        lines.append(f"- 负面情绪 **{fmt_ratio(neg_n, len(meta['enc_all']))}**，"
                     f"分母为全部编码记录（含拒答）。")
    lines.append("")

    # 1.2 痛点排行
    lines.append("### 1.2 痛点排行（分母=有效评论数）")
    lines.append("")
    lines.append(f"- 分母口径：**{total} 条有效评论**（已剔除噪音与品牌型号不一致记录）")
    lines.append("- 计数口径：一条评论若同时抱怨多个维度，**每个维度各计 1 次**（多选题口径），"
                 "因此各维度条数之和大于分母属正常现象")
    lines.append("")
    lines.append("| 排名 | 痛点维度 | 提及条数 | 占比 | 占提及评论 | 平均评分 | 涉及品牌数 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for _, r in ranking.iterrows():
        avg = "—" if r["平均评分"] is None else f"{r['平均评分']}"
        lines.append(f"| {r['排名']} | {r['痛点维度']} | {r['提及条数']} | "
                     f"{r['占比']} | {r['占提及评论']} | {avg} | {r['涉及品牌数']} |")

    # 零提及维度单独说明：不是"没检查"，而是"检查了但没人抱怨"
    all_labels = [v[0] for v in PAIN_DIMENSIONS.values()]
    hit_labels = set(ranking["痛点维度"]) if not ranking.empty else set()
    zero_dims = [lb for lb in all_labels if lb not in hit_labels]
    if zero_dims:
        lines.append("")
        lines.append(f"- **零提及维度**：{'、'.join(zero_dims)}——"
                     "全集 9 个维度均已扫描，这些维度在本期数据中**未被抱怨**，"
                     "属于相对优势项（不代表不存在问题，只说明本期样本未出现）。")
    lines.append("")

    # 1.3 品牌情绪
    lines.append("### 1.3 品牌情绪分布")
    lines.append("")
    lines.append("| 品牌 | 评论数 | 正面 | 负面 | 中立 | 混合 | 负面率 | 平均评分 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for _, r in brand_senti.iterrows():
        avg = "—" if r["平均评分"] is None else f"{r['平均评分']}"
        lines.append(f"| {r['品牌']} | {r['评论数']} | {r['正面']} | {r['负面']} | "
                     f"{r['中立']} | {r['混合']} | {r['负面率']}% | {avg} |")
    lines.append("")

    # 1.4 品牌 x 痛点
    lines.append("### 1.4 品牌 × 痛点交叉（提及条数）")
    lines.append("")
    dim_labels = [c for c in cross.columns if c not in ("品牌", "评论数", "痛点总数")]
    header = "| 品牌 | 评论数 | " + " | ".join(dim_labels) + " | 痛点总数 |"
    sep = "| --- | --- | " + " | ".join(["---"] * len(dim_labels)) + " | --- |"
    lines.append(header)
    lines.append(sep)
    for _, r in cross.iterrows():
        cells = " | ".join(str(int(r[d])) for d in dim_labels)
        lines.append(f"| {r['品牌']} | {r['评论数']} | {cells} | {r['痛点总数']} |")
    lines.append("")

    # ---------------- 二、推断假设 ----------------
    lines.append("## 二、推断假设（基于事实，非确定结论）")
    lines.append("")
    if not ranking.empty:
        top1 = ranking.iloc[0]
        lines.append(f"**推断 1：{top1['痛点维度']}是当前最普遍的体验短板。**")
        lines.append(f"- 依据：{top1['提及条数']} 条评论提及，占有效评论 "
                     f"{top1['占比']}，排名第 1。")
        lines.append("- 边界：这是**提及频次**，不等于严重程度；"
                     "少数用户强烈抱怨的维度可能排名靠后。")
        lines.append("")

        if len(ranking) >= 2:
            top2 = ranking.iloc[1]
            lines.append(f"**推断 2：{top2['痛点维度']}是第二高频问题，且与第 1 名差距有限。**")
            gap = int(top1["提及条数"]) - int(top2["提及条数"])
            lines.append(f"- 依据：二者相差 {gap} 条"
                         f"（{top1['提及条数']} vs {top2['提及条数']}）。")
            lines.append("- 边界：差距在个位数时应视为**同一梯队**，不宜强行排序。")
            lines.append("")

    # 品牌维度推断：哪个品牌在某痛点上最集中
    if not cross.empty and dim_labels:
        max_brand, max_dim, max_val = None, None, -1
        for _, r in cross.iterrows():
            for d in dim_labels:
                v = int(r[d])
                if v > max_val:
                    max_val, max_brand, max_dim = v, r["品牌"], d
        if max_brand:
            brand_n = int(cross[cross["品牌"] == max_brand].iloc[0]["评论数"])
            lines.append(f"**推断 3：{max_brand} 在「{max_dim}」维度上的抱怨最集中。**")
            lines.append(f"- 依据：{max_val} 条提及 / 该品牌 {brand_n} 条评论"
                         f"（{max_val / brand_n * 100:.1f}%）。")
            lines.append("- 边界：样本量小的品牌（<20 条）单条提及就会显著抬升比例，需谨慎解读。")
            lines.append("")

    if not brand_senti.empty:
        worst = brand_senti.iloc[0]
        lines.append(f"**推断 4：{worst['品牌']} 的负面情绪占比最高（{worst['负面率']}%）。**")
        lines.append(f"- 依据：{worst['评论数']} 条评论中负面 "
                     f"{worst['负面']}，平均评分 {worst['平均评分']}。")
        lines.append("- 边界：**合成数据，不代表真实口碑**；且负面率与产品定位、"
                     "价格带相关，不能单独作为质量判断。")
        lines.append("")

    # ---------------- 三、行动建议 ----------------
    lines.append("## 三、行动建议（可执行，按优先级）")
    lines.append("")
    if not ranking.empty:
        for i, (_, r) in enumerate(ranking.head(3).iterrows(), 1):
            dim = r["痛点维度"]
            n = int(r["提及条数"])
            lines.append(f"**建议 {i}：优先解决「{dim}」——{n} 条提及（{r['占比']}）**")
            lines.append(f"- 动作：{_suggest_action(dim)}")
            lines.append(f"- 验证指标：该维度提及率从当前 {r['占比'].split('（')[-1].rstrip('）')} "
                         f"下降至下一版本目标值以下；建议每版本复算一次。")
            lines.append(f"- 证据入口：本报告 §四 的「{dim}」证据列表（≥3 条原文）。")
            lines.append("")
    lines.append("**通用建议：建立痛点提及率的版本基线**")
    lines.append(f"- 动作：把本版本各维度提及率（分母 {total}）作为基线，"
                 "后续每次数据更新后复算并对比。")
    lines.append("- 注意：**不要跨品类比较**，耳机痛点结构与咖啡、美妆完全不同。")
    lines.append("")

    # ---------------- 四、证据追溯 ----------------
    lines.append("## 四、证据追溯（逐条可查）")
    lines.append("")
    lines.append(f"每个核心痛点绑定 ≥3 条原始评论，可通过 `review_id` 回查 "
                 f"`data/processed/clean_data.csv` 与 `cleaning_log.csv`。")
    lines.append("")
    for _, r in ranking.head(meta.get("evidence_top_n", 5)).iterrows():
        dim = r["痛点维度"]
        evs = meta["evidence"].get(dim, [])
        lines.append(f"### {dim}（{r['提及条数']} 条提及，{r['占比']}）")
        lines.append("")
        if not evs:
            lines.append("_无可用证据_")
            lines.append("")
            continue
        for j, e in enumerate(evs, 1):
            rating = "—" if e["rating"] is None else e["rating"]
            inter = "—" if e["interaction_count"] is None else e["interaction_count"]
            lines.append(f"{j}. **`{e['review_id']}`**｜{e['brand']} {e['product']}｜"
                         f"评分 {rating}｜互动 {inter}")
            lines.append(f"   - 原文：「{e['review_text']}」")
            lines.append(f"   - 证据片段：「{e['quote']}」")
        lines.append("")

    # ---------------- 五、方法说明 ----------------
    lines.append("## 五、方法说明与限制")
    lines.append("")
    lines.append("| 项 | 说明 |")
    lines.append("| --- | --- |")
    lines.append(f"| 编码方式 | 确定性规则引擎（{ENGINE_VERSION}），"
                 "对齐实验2 Skill 的字段与拒答口径 |")
    lines.append("| 痛点维度 | 9 类：降噪 / 续航 / 佩戴舒适 / 连接稳定性 / 通话质量 / "
                 "音质 / 做工质感 / 售后服务 / 价格性价比 |")
    lines.append(f"| 分母 | 有效评论 {total} 条（已剔除噪音与品牌型号不一致） |")
    lines.append("| 计数 | 多选题口径，一条评论可计多个维度 |")
    lines.append("| 证据 | 逐字子串，未改写，可按 review_id 回查 |")
    lines.append("| 局限 | 规则引擎的语义理解弱于大模型，"
                 "否定句、反讽、隐含抱怨可能漏判 |")
    lines.append("| 数据 | **合成数据**，结论不可外推为真实市场判断 |")
    lines.append("")

    return "\n".join(lines)


def _suggest_action(dim: str) -> str:
    """按痛点维度给出可执行动作（避免空泛建议）。"""
    mapping = {
        "降噪": "在详情页用「地铁/办公室实测 dB 降噪曲线」替代形容词式宣传；"
                "对「降噪开启后耳压感」单独做一版通透模式引导。",
        "续航": "标注「单次续航 / 含仓总续航 / 快充 10 分钟可用时长」三个独立数值，"
                "避免只标理想值；对电池衰减给出明确保修口径。",
        "佩戴舒适": "提供耳塞尺寸自测指引（3 档），并在详情页标注腔体尺寸与重量；"
                    "对「戴久耳朵疼」给出更换耳塞的免费方案。",
        "连接稳定性": "明确「双设备切换」的操作路径与失败排查步骤；"
                      "在售前 FAQ 中前置说明多设备场景的已知限制。",
        "通话质量": "区分「安静环境 / 风噪环境」两种通话表现分别标称；"
                    "对风噪问题给出麦克风阵列的物理方案说明。",
        "音质": "给出可对照的频响曲线，避免只用「低音澎湃」这类主观词；"
                "对「中高频发刺」提供 EQ 预设。",
        "做工质感": "把「开合手感、缝隙、材质」做成短视频展示；"
                    "对拆封划痕建立开箱验货流程。",
        "售后服务": "承诺响应时效（如 48 小时内首次回复）；"
                    "把「保修范围」与「自费项目」在售前明确列出。",
        "价格性价比": "建立价格保护规则并公示；"
                      "用「同价位段配置对比表」回应「这个配置有点贵」。",
    }
    return mapping.get(dim, "针对该维度建立专项改进计划，并在下一版本复算提及率。")


# ---------------------------------------------------------------------------
# 端到端
# ---------------------------------------------------------------------------


@dataclass
class EngineResult:
    enc: pd.DataFrame
    stats: dict[str, pd.DataFrame]
    report: str
    meta: dict[str, Any] = field(default_factory=dict)


def run_engine(clean_path: Path | str = CLEAN_DEFAULT,
               out_dir: Path | str = OUTPUT_DIR,
               evidence_top_n: int = 5) -> EngineResult:
    """跑完整链路并落盘。"""
    clean_path = Path(clean_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load_clean(clean_path)
    df = filter_valid(raw)
    # 对**全部**原始记录编码（含被实验3 剔除的噪音），这样拒答才能被统计到
    enc_all = encode_batch(raw)
    # 统计用的编码表：只保留有效记录（与 df 口径一致）
    enc = enc_all[enc_all["review_id"].astype(str).isin(df["review_id"].astype(str))].reset_index(drop=True)

    total = len(df)
    refused_all = int(enc_all["refuse"].sum())
    refused = int(enc["refuse"].sum())

    ranking = pain_ranking(enc, df)
    senti = sentiment_distribution(enc, enc_all)
    brand_senti = brand_sentiment_stats(enc, df)
    cross = brand_pain_cross(enc, df)

    # 证据：前 N 个痛点各取 3 条
    evidence = {}
    for _, r in ranking.head(evidence_top_n).iterrows():
        evidence[r["痛点维度"]] = top_evidence(enc, df, r["痛点维度"], k=3)

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "engine_version": ENGINE_VERSION,
        "raw_rows": len(raw),
        "total_reviews": total,
        "refused": refused_all,
        "refused_in_valid": refused,
        "enc_all": enc_all,
        "evidence": evidence,
        "evidence_top_n": evidence_top_n,
    }
    stats = {
        "pain_ranking": ranking,
        "sentiment": senti,
        "brand_sentiment": brand_senti,
        "brand_pain": cross,
    }
    report = build_insight_report(stats, meta)

    # ---- 落盘 ----
    # 编码结果落全部记录（含拒答），保证"每条原始评论都有编码结论"可审计
    enc_all.to_json(out_dir / "encoding_results.json", orient="records",
                    force_ascii=False, indent=2)
    ranking.to_csv(out_dir / "pain_point_ranking.csv", index=False, encoding="utf-8-sig")
    senti.to_csv(out_dir / "sentiment_distribution.csv", index=False, encoding="utf-8-sig")
    brand_senti.to_csv(out_dir / "brand_sentiment.csv", index=False, encoding="utf-8-sig")
    cross.to_csv(out_dir / "brand_pain_cross.csv", index=False, encoding="utf-8-sig")
    (out_dir / "insight_report.md").write_text(report, encoding="utf-8")

    # 证据表（扁平化，便于抽查）
    ev_rows = []
    for dim, evs in evidence.items():
        for e in evs:
            ev_rows.append({
                "痛点维度": dim, "review_id": e["review_id"],
                "品牌": e["brand"], "产品": e["product"],
                "评分": e["rating"], "互动量": e["interaction_count"],
                "证据片段": e["quote"], "原文": e["review_text"],
            })
    if ev_rows:
        pd.DataFrame(ev_rows).to_csv(out_dir / "evidence_table.csv",
                                     index=False, encoding="utf-8-sig")

    return EngineResult(enc=enc, stats=stats, report=report, meta=meta)


def main() -> int:
    print("=" * 70)
    print("实验4 · AI+Python 消费者洞察引擎（v0.4 · 蓝牙耳机）")
    print("=" * 70)

    result = run_engine()
    meta = result.meta
    ranking = result.stats["pain_ranking"]
    senti = result.stats["sentiment"]

    print(f"\n原始 {meta['raw_rows']} 条 -> 有效 {meta['total_reviews']} 条"
          f"（拒答 {meta['refused']} 条）")

    print("\n[情绪分布]")
    for _, r in senti.iterrows():
        print(f"  {r['情绪']:8s} {r['条数']:4d}  {r['占比']}")

    print("\n[痛点排行 TOP5]")
    for _, r in ranking.head(5).iterrows():
        print(f"  {r['排名']}. {r['痛点维度']:8s} {r['提及条数']:4d} 条  "
              f"{r['占比']}  平均评分 {r['平均评分']}")

    print("\n[证据抽样] 每个核心痛点绑定 3 条：")
    for dim, evs in meta["evidence"].items():
        print(f"  {dim}: " + "、".join(e["review_id"] for e in evs))

    print(f"\n产出已写入 -> {OUTPUT_DIR}")
    print("  encoding_results.json / pain_point_ranking.csv / "
          "sentiment_distribution.csv")
    print("  brand_sentiment.csv / brand_pain_cross.csv / "
          "evidence_table.csv / insight_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
