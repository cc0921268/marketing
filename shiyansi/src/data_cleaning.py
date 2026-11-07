# -*- coding: utf-8 -*-
"""实验3：营销数据清洗管线（v0.3 · 蓝牙耳机品类）

输入（只读，绝不覆盖）：
    data/raw/raw_data.csv         实验3生成器产出的 300 条噪声数据

输出：
    data/processed/clean_data.csv       清洗后的分析用数据
    data/processed/cleaning_log.csv     逐条清洗动作日志（审计链）
    data/processed/quality_report.json  质量统计报告（完整率、动作计数）
    outputs/cleaning_summary.txt        控制台摘要的落盘副本

============================ 清洗规则（C1—C10） ============================
C1  品牌别名归一化    30 种写法（含繁体「華為」、俗称「新力」「欧珀」）→ 6 个规范名。
                      未登记别名保留原值并记日志，不猜测性归并。
C2  整行完全重复剔除  除 review_id 外全部业务字段一致 → 保留首条。
C3  review_id 重复    ID 相同但内容不同（二次提交）→ 保留首条，记日志。
C4  日期归一化        5 种格式 → YYYY-MM-DD；缺年份按采集周期 2024 补齐；
                      落在未来的日期视为录入错误，置空并记日志（不编造）。
C5  价格解析          剥离 ￥/元/千分位；识别欧式小数（330,51 → 330.51）；
                      无法解析 → 置空（保留行优于删行）。
C6  价格异常截断      超 min(品牌合理上限, IQR上须×3) → winsorize 截断（不删行）。
C7  缺失分级处理      review_text / brand 缺失 → 整行剔除；
                      price / rating 缺失 → 保留置空（均值 skipna，与实验1 口径一致）；
                      interaction_count 缺失 → 填 0（无互动即 0）。
C8  无效评论打标      纯符号/纯数字/广告引流/无关内容/极短无信息 →
                      is_valid_review=0（**只打标不删除**，交实验4 Skill 拒答对齐）。
C9  文字形态归一化    繁体/异体字 → 简体（續航→续航、藍牙→蓝牙）；
                      全角标点 → 半角；剥离 emoji。
C10 逻辑矛盾修正      rating 超出 1—5 范围（10 分制混入）→ 按 ÷2 折算并记日志；
                      product 与 brand 不匹配（张冠李戴）→ 打 is_consistent=0 标记，不删除。

设计原则：
    - 每条规则可解释、可复现、可逐条验证；
    - 删行只发生在「分析必需字段缺失」（C7），其余一律保留 + 打标；
    - 所有修改写入 cleaning_log.csv，可回溯到原始值。

运行：
    python src/data_cleaning.py                          # 默认路径
    python src/data_cleaning.py --raw data/raw/raw_data.csv
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DEFAULT = PROJECT_ROOT / "data" / "raw" / "raw_data.csv"
OUT_DIR_DEFAULT = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# ---------------------------------------------------------------------------
# 规则配置（清洗的"单一事实来源"；文档与代码必须一致）
# ---------------------------------------------------------------------------

# C1：品牌别名映射（key 为小写去空格后的形态）
BRAND_ALIAS_MAP: dict[str, str] = {
    # Apple / AirPods
    "apple": "Apple", "airpods": "Apple", "苹果耳机": "Apple",
    "apple airpods": "Apple", "苹果": "Apple",
    # 华为（含繁体「華為」）
    "华为": "华为", "huawei": "华为", "freebuds": "华为",
    "华为耳机": "华为", "華為": "华为",
    # 小米（含 Redmi / 红米）
    "小米": "小米", "xiaomi": "小米", "mi": "小米", "redmi": "小米",
    "红米耳机": "小米", "小米耳机": "小米", "红米": "小米",
    # 漫步者
    "漫步者": "漫步者", "edifier": "漫步者", "漫步者耳机": "漫步者",
    # OPPO（含「欧珀」）
    "oppo": "OPPO", "enco": "OPPO", "oppo耳机": "OPPO", "欧珀": "OPPO",
    # 索尼（含「新力」旧译）
    "索尼": "索尼", "sony": "索尼", "索尼耳机": "索尼", "新力": "索尼",
}

# 各品牌价格的合理上限（超过按录入错误处理；下限不截断，低价是真实促销）
PRICE_REASONABLE_UPPER: dict[str, float] = {
    "Apple": 2500.0, "华为": 2000.0, "小米": 1200.0,
    "漫步者": 1300.0, "OPPO": 1500.0, "索尼": 3000.0,
}
GLOBAL_PRICE_UPPER = 3500.0  # 品牌未知时的兜底

# C4：已知采集周期（缺年份日期的补齐依据）
COLLECTION_YEAR = 2024
COLLECTION_END = date(2024, 12, 31)  # 超过此日期视为"未来"，置空

# C9：繁体 → 简体映射（与生成器的 N9 噪声对应）
TRAD_TO_SIMPLE: dict[str, str] = {
    "續航": "续航", "連線": "连接", "連接": "连接", "藍牙": "蓝牙",
    "音質": "音质", "耳機": "耳机", "電池": "电池", "耳壓": "耳压",
    "斷連": "断连", "通話": "通话", "麥克風": "麦克风", "外觀": "外观",
    "價格": "价格", "會": "会", "買": "买", "個": "个", "說": "说",
    "聽": "听", "覺": "觉", "這": "这", "麼": "么", "開": "开",
    "關": "关", "沒": "没", "現": "现", "兩": "两", "點": "点",
    "還": "还", "產": "产", "華為": "华为",
    "穩": "稳", "順": "顺", "輕": "轻", "體": "体", "驗": "验",
    "較": "较", "強": "强", "長": "长", "壞": "坏", "聲": "声",
    "價": "价", "錢": "钱", "換": "换", "號": "号", "線": "线",
}

# C8：无效评论识别模式
NOISE_PATTERNS = [
    re.compile(r"^[\W_]+$"),                 # 纯符号：。。。。 ？？？ !!!
    re.compile(r"^\d+$"),                    # 纯数字：666666
    re.compile(r"^(.)\1{2,}$"),              # 单字重复：。。。 / aaa
]
NOISE_KEYWORDS = ("加我微信", "代购", "转发抽奖", "低价出", "私聊", "优惠券")
NOISE_IRRELEVANT = ("天气不错", "祝商家", "系统默认好评", "路过看看", "生意兴隆")
NOISE_MIN_LEN = 2  # 少于 2 个字符视为无信息（中文短评「一般」有 2 字，保留）

# C10：品牌 → 该品牌合法产品集合（用于一致性校验）
BRAND_PRODUCTS: dict[str, set[str]] = {
    "Apple": {"AirPods 4", "AirPods Pro 2", "AirPods 3"},
    "华为": {"FreeBuds Pro 3", "FreeBuds 6i", "FreeBuds SE 3", "FreeBuds Lipstick"},
    "小米": {"Xiaomi Buds 5", "Redmi Buds 6", "Xiaomi Buds 4 Pro", "Redmi Buds 6 Pro"},
    "漫步者": {"LolliPods Pro", "NeoBuds Pro 2", "W820NB 头戴", "声迈 X5"},
    "OPPO": {"Enco X3", "Enco Air4", "Enco Air4 Pro", "Enco Free4"},
    "索尼": {"WF-1000XM5", "WF-C700N", "LinkBuds S", "WF-C510"},
}

RATING_MIN, RATING_MAX = 1.0, 5.0

COLUMNS_ORDER = [
    "review_id", "brand", "product", "price", "rating", "review_text",
    "date", "interaction_count", "is_valid_review", "is_consistent",
]


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


class CleaningLog:
    """逐条清洗动作日志：review_id / action / detail / before / after。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, rid: str, action: str, detail: str,
            before: str = "", after: str = "") -> None:
        self.rows.append({
            "review_id": str(rid), "action": action, "detail": detail,
            "before": before, "after": after,
        })

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            self.rows, columns=["review_id", "action", "detail", "before", "after"])

    def count(self, action: str) -> int:
        return sum(1 for r in self.rows if r["action"] == action)


# ---------------------------------------------------------------------------
# C1 品牌别名归一化
# ---------------------------------------------------------------------------


def c1_normalize_brand(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C1：品牌别名归一。未登记别名保留原值并记日志（不猜测）。"""
    out = df.copy()
    normalized: list[str] = []
    for rid, raw in zip(out["review_id"], out["brand"]):
        key = str(raw).strip().lower()
        canon = BRAND_ALIAS_MAP.get(key)
        if canon is None:
            log.add(rid, "C1_brand_unknown",
                    f"别名 {raw!r} 未登记，保留原值（不做猜测性归并）", str(raw), str(raw))
            normalized.append(str(raw).strip())
        else:
            if canon != str(raw).strip():
                log.add(rid, "C1_brand_alias", "品牌别名归一化", str(raw), canon)
            normalized.append(canon)
    out["brand"] = normalized
    n_alias = log.count("C1_brand_alias")
    n_unknown = log.count("C1_brand_unknown")
    print(f"  C1 品牌归一：{n_alias} 条别名归一，{n_unknown} 条未登记保留原值")
    return out


# ---------------------------------------------------------------------------
# C2 / C3 去重
# ---------------------------------------------------------------------------


def c2_dedupe_full(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C2：整行完全重复（除 review_id 外全部业务字段一致）→ 保留首条。"""
    out = df.copy()
    business_cols = [c for c in out.columns if c != "review_id"]
    dup = out.duplicated(subset=business_cols, keep="first")
    for rid in out.loc[dup, "review_id"]:
        log.add(rid, "C2_full_duplicate", "整行业务字段完全重复，剔除重复行")
    out = out[~dup].copy()
    print(f"  C2 整行去重：剔除 {int(dup.sum())} 行，剩余 {len(out)} 行")
    return out


def c3_dedupe_id(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C3：review_id 重复但内容不同（二次提交）→ 保留首条。"""
    out = df.copy()
    dup = out.duplicated(subset=["review_id"], keep="first")
    for rid in out.loc[dup, "review_id"]:
        log.add(rid, "C3_id_duplicate",
                "review_id 重复且内容不同（疑似二次提交），保留首条")
    out = out[~dup].copy()
    print(f"  C3 ID 去重：剔除 {int(dup.sum())} 行，剩余 {len(out)} 行")
    return out


# ---------------------------------------------------------------------------
# C4 日期归一化
# ---------------------------------------------------------------------------


DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?$"), True),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), True),
    (re.compile(r"^(\d{1,2})[-/](\d{1,2})$"), False),  # 缺年份
]


def _parse_date(raw: str) -> tuple[str | None, str]:
    """解析单个日期字符串 → (ISO 日期 或 None, 失败原因)。"""
    s = str(raw).strip()
    for pat, has_year in DATE_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        if has_year:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mo, d = COLLECTION_YEAR, int(m.group(1)), int(m.group(2))
        try:
            parsed = date(y, mo, d)
        except ValueError:
            return None, f"日期非法（{s!r}，如月份越界）"
        if parsed > COLLECTION_END:
            return None, f"未来日期（{parsed.isoformat()} 超出采集周期）"
        return parsed.isoformat(), ""
    return None, f"格式无法识别（{s!r}）"


def c4_normalize_date(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C4：日期归一化。无法解析或落在未来 → 置空（不编造）。"""
    out = df.copy()
    result: list[str] = []
    for rid, raw in zip(out["review_id"], out["date"]):
        parsed, reason = _parse_date(raw)
        if parsed is None:
            log.add(rid, "C4_date_invalid", f"{reason}，置空", str(raw), "")
            result.append("")
            continue
        if parsed != str(raw).strip():
            log.add(rid, "C4_date_norm", "日期格式归一化", str(raw), parsed)
        result.append(parsed)
    out["date"] = result
    print(f"  C4 日期归一：{log.count('C4_date_norm')} 条格式转换，"
          f"{log.count('C4_date_invalid')} 条置空")
    return out


# ---------------------------------------------------------------------------
# C5 / C6 价格
# ---------------------------------------------------------------------------


def parse_price(raw: object) -> float | None:
    """解析价格字符串 → float。失败返回 None。

    处理顺序很关键：
      1) 空值 → None
      2) 欧式小数（330,51：单个逗号且后面 1—2 位）→ 逗号当小数点
      3) 千分位（1,140.80：逗号后 3 位）→ 剥离逗号
      4) 剥离货币符号 / 「元」/ 空格 → float
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None

    # 欧式小数判定：恰好一个逗号、逗号后 1—2 位数字、且不含点
    if re.fullmatch(r"[￥¥$\s]*\d+,\d{1,2}\s*[元]?", s) and "." not in s:
        s = s.replace(",", ".")

    # 剥离货币符号、千分位逗号、「元」、空格
    s = re.sub(r"[￥¥$,，\s]", "", s)
    s = re.sub(r"元$", "", s)
    s = s.strip()
    if not s:
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return val if val > 0 else None


def c5_clean_price(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C5：价格脏格式 → 数值。无法解析置空（保留行优于删行）。

    注意：原本就缺失（None / 空串）的价格不写 C5 日志——缺失归 C7 管辖，
    两类问题必须分开记账，否则 quality_report 的 C5/C7 计数会互相污染。
    """
    out = df.copy()
    cleaned: list[float | None] = []
    for rid, raw in zip(out["review_id"], out["price"]):
        raw_is_blank = raw is None or (isinstance(raw, float) and pd.isna(raw)) \
            or not str(raw).strip()
        val = parse_price(raw)
        if val is None:
            if not raw_is_blank:  # 有值但解析不了 → 真·脏格式
                log.add(rid, "C5_price_invalid", f"价格无法解析 {raw!r}，置空",
                        str(raw), "")
            cleaned.append(None)
        else:
            if not raw_is_blank and str(raw).strip() != f"{val:.2f}":
                log.add(rid, "C5_price_parse", "价格脏格式转数值",
                        str(raw), f"{val:.2f}")
            cleaned.append(val)
    out["price"] = cleaned
    print(f"  C5 价格解析：{log.count('C5_price_parse')} 条格式转换，"
          f"{log.count('C5_price_invalid')} 条无法解析置空")
    return out


def c6_clip_price(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C6：价格异常截断（winsorize，不删行）。

    阈值 = min(品牌合理上限, IQR 上须×3)。取「更保守者」：
    IQR 上须防品牌内部分布异常，品牌上限防跨品牌量纲差异。
    """
    out = df.copy()
    prices = pd.to_numeric(out["price"], errors="coerce").dropna()
    if len(prices) >= 8:
        q1, q3 = prices.quantile(0.25), prices.quantile(0.75)
        iqr_upper = float(q3 + 3 * (q3 - q1))
    else:
        iqr_upper = float("inf")

    clipped = 0
    for idx, row in out.iterrows():
        p = row["price"]
        if p is None or pd.isna(p):
            continue
        brand_upper = PRICE_REASONABLE_UPPER.get(row["brand"], GLOBAL_PRICE_UPPER)
        upper = min(brand_upper, iqr_upper)
        if p > upper:
            log.add(row["review_id"], "C6_price_clip",
                    f"价格 {p:.2f} 元超出合理上限 {upper:.2f} 元"
                    f"（品牌上限 {brand_upper:.0f} / IQR上须 {iqr_upper:.2f} 取小），winsorize 截断",
                    f"{p:.2f}", f"{upper:.2f}")
            out.at[idx, "price"] = round(upper, 2)
            clipped += 1
    print(f"  C6 价格截断：{clipped} 条")
    return out


# ---------------------------------------------------------------------------
# C7 缺失处理
# ---------------------------------------------------------------------------


def c7_handle_missing(df: pd.DataFrame, log: CleaningLog) -> tuple[pd.DataFrame, dict]:
    """C7：缺失分级处理（剔除 / 置空 / 填 0）。"""
    out = df.copy()
    stats = {"dropped_missing_required": 0, "filled_interaction_zero": 0,
             "kept_null_price": 0, "kept_null_rating": 0}

    # 必需字段缺失 → 整行剔除
    for col in ("review_text", "brand"):
        mask = out[col].isna() | out[col].astype(str).str.strip().eq("")
        for rid in out.loc[mask, "review_id"]:
            log.add(rid, "C7_drop", f"{col} 缺失，整行剔除（分析必需字段）")
        stats["dropped_missing_required"] += int(mask.sum())
        out = out[~mask].copy()

    # interaction_count 缺失 → 0
    mask = out["interaction_count"].isna()
    for rid in out.loc[mask, "review_id"]:
        log.add(rid, "C7_fill_zero",
                "interaction_count 缺失，按业务规则填 0（无互动即 0）")
    stats["filled_interaction_zero"] = int(mask.sum())
    out["interaction_count"] = (
        pd.to_numeric(out["interaction_count"], errors="coerce").fillna(0).astype(int))

    # price / rating 缺失 → 保留置空（均值 skipna）
    stats["kept_null_price"] = int(pd.to_numeric(out["price"], errors="coerce").isna().sum())
    stats["kept_null_rating"] = int(pd.to_numeric(out["rating"], errors="coerce").isna().sum())
    out["rating"] = pd.to_numeric(out["rating"], errors="coerce")

    print(f"  C7 缺失处理：剔除 {stats['dropped_missing_required']} 行，"
          f"互动量填 0 {stats['filled_interaction_zero']} 条，"
          f"price 置空 {stats['kept_null_price']} 条，rating 置空 {stats['kept_null_rating']} 条")
    return out, stats


# ---------------------------------------------------------------------------
# C8 无效评论打标
# ---------------------------------------------------------------------------


def is_noise_text(text: str) -> bool:
    """判定评论是否为无效内容（纯符号/纯数字/广告/无关/极短）。

    边界说明（重要）：
      - 「一般」「还行吧」「退货了」「到了」这类**极短但有信息**的评论不算噪音：
        它们传达了情绪或行为结果，实验4 的编码器能从中提取 sentiment，
        强行打标为噪音反而会丢掉真实信号（这是初版 len<4 阈值的老坑）。
      - 只把「完全无信息」的内容判为噪音：纯符号、纯数字、单字刷屏、
        广告引流、明显无关的套话、以及长度 < 2 的空洞内容。
    """
    t = str(text).strip()
    if len(t) < NOISE_MIN_LEN:
        return True
    if any(p.match(t) for p in NOISE_PATTERNS):
        return True
    if any(k in t for k in NOISE_KEYWORDS):
        return True
    if any(k in t for k in NOISE_IRRELEVANT):
        return True
    return False


def c8_mark_noise(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C8：无效评论打标（**只打标不删除**），与实验2 Skill 拒答规则对齐。"""
    out = df.copy()
    flags: list[int] = []
    for rid, text in zip(out["review_id"], out["review_text"]):
        bad = is_noise_text(text)
        if bad:
            log.add(rid, "C8_noise",
                    f"标记为无效评论（不删除，供实验4 Skill 拒答对齐）：{str(text)[:20]!r}")
        flags.append(0 if bad else 1)
    out["is_valid_review"] = flags
    n_bad = flags.count(0)
    print(f"  C8 无效评论打标：{n_bad} 条（占 {n_bad}/{len(flags)}，保留不删）")
    return out


# ---------------------------------------------------------------------------
# C9 文字形态归一化
# ---------------------------------------------------------------------------


def _strip_emoji(text: str) -> str:
    """剥离 emoji 与变体选择符（保留文字与常规标点）。"""
    # 覆盖常见 emoji 区段
    pattern = re.compile(
        "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF"
        "\U0001F000-\U0001F2FF" "\uFE0F" "\u200D" "]+"
    )
    return pattern.sub("", text)


# 全角字母/数字 → 半角（只覆盖 ０-９ Ａ-Ｚ ａ-ｚ，**不含全角标点**）
# 全角标点的码位区间是 U+FF01—U+FF0F / U+FF1A—U+FF20 等，
# 如果把整个 U+FF01—U+FF5E 都做偏移，中文全角逗号「，」也会被转成 ","，
# 把可读的中文评论改坏——初版就踩了这个坑。
_FULLWIDTH_ALNUM = {
    **{chr(0xFF10 + i): chr(0x30 + i) for i in range(10)},   # ０-９ → 0-9
    **{chr(0xFF21 + i): chr(0x41 + i) for i in range(26)},   # Ａ-Ｚ → A-Z
    **{chr(0xFF41 + i): chr(0x61 + i) for i in range(26)},   # ａ-ｚ → a-z
}


def _to_halfwidth_alnum(text: str) -> str:
    """只转换全角字母与数字，**保留中文标点**（，。！？是中文正常书写，不是脏数据）。"""
    return "".join(_FULLWIDTH_ALNUM.get(ch, ch) for ch in text)


def c9_normalize_text(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """C9：繁体/异体字 → 简体、全角字母数字 → 半角、剥离 emoji。

    设计取舍：中文全角标点（，。！？）**不做转换**——那是中文正常书写习惯，
    强行转成半角会把可读的中文评论改坏，反而降低数据质量。
    真正需要修的是：繁体字（影响分词与词表匹配）、emoji（干扰文本分析）、
    全角字母数字（影响型号匹配，如 ＡｉｒＰｏｄｓ 4）。
    """
    out = df.copy()
    new_texts: list[str] = []
    for rid, raw in zip(out["review_id"], out["review_text"]):
        original = str(raw)
        reasons: list[str] = []

        t = original

        # 繁体/异体字 → 简体
        if any(trad in t for trad in TRAD_TO_SIMPLE):
            for trad, simp in TRAD_TO_SIMPLE.items():
                t = t.replace(trad, simp)
            reasons.append("繁简")

        # 剥离 emoji
        stripped = _strip_emoji(t)
        if stripped != t:
            t = stripped
            reasons.append("emoji")

        # 全角字母数字 → 半角
        half = _to_halfwidth_alnum(t)
        if half != t:
            t = half
            reasons.append("全角字符")

        t = re.sub(r"\s{2,}", " ", t).strip()

        if t != original:
            log.add(rid, "C9_text_normalized",
                    f"文字形态归一化（{'+'.join(reasons)}）", original[:40], t[:40])
        new_texts.append(t)
    out["review_text"] = new_texts
    print(f"  C9 文字归一：{log.count('C9_text_normalized')} 条被修改"
          f"（保留中文标点，只修繁简/emoji/全角字符）")
    return out


# ---------------------------------------------------------------------------
# C10 逻辑矛盾修正
# ---------------------------------------------------------------------------


def c10_fix_logic(df: pd.DataFrame, log: CleaningLog) -> tuple[pd.DataFrame, dict]:
    """C10：rating 超范围折算 + product/brand 一致性标记。"""
    out = df.copy()
    stats = {"rating_converted": 0, "inconsistent_marked": 0}

    # 10a rating 超出 1—5（实为 10 分制）→ 按 ÷2 折算
    converted: list[float | None] = []
    for rid, r in zip(out["review_id"], out["rating"]):
        if r is None or pd.isna(r):
            converted.append(None)
            continue
        v = float(r)
        if v > RATING_MAX:
            # 用 Decimal 做十进制四舍五入，避开二进制浮点的银行家舍入陷阱：
            # 8.7/2 在 float 下是 4.3499…，round(4.35, 1) 会得到 4.3；
            # 业务上 8.7/2 应为 4.4，故走 Decimal("4.35").quantize(0.1) → 4.4
            from decimal import Decimal, ROUND_HALF_UP
            new_v = float(
                Decimal(str(v / 2)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            )
            new_v = max(RATING_MIN, min(RATING_MAX, new_v))
            log.add(rid, "C10_rating_converted",
                    f"评分 {v} 超出 1—5 范围（疑似 10 分制），按 ÷2 折算为 {new_v}",
                    f"{v}", f"{new_v}")
            stats["rating_converted"] += 1
            converted.append(new_v)
        elif v < RATING_MIN:
            log.add(rid, "C10_rating_clipped",
                    f"评分 {v} 低于下限 {RATING_MIN}，截断至下限", f"{v}", f"{RATING_MIN}")
            converted.append(RATING_MIN)
        else:
            converted.append(v)
    out["rating"] = converted

    # 10b product 与 brand 不匹配 → 标记 is_consistent=0（不删除，供人工复核）
    flags: list[int] = []
    for rid, brand, product in zip(out["review_id"], out["brand"], out["product"]):
        legal = BRAND_PRODUCTS.get(brand)
        if legal is None:
            flags.append(1)  # 品牌未知（C1 保留原值），不判一致性
            continue
        if str(product).strip() in legal:
            flags.append(1)
        else:
            log.add(rid, "C10_inconsistent",
                    f"产品 {product!r} 不属于品牌 {brand!r}（张冠李戴），标记待复核",
                    f"{brand}/{product}", "is_consistent=0")
            flags.append(0)
            stats["inconsistent_marked"] += 1
    out["is_consistent"] = flags

    print(f"  C10 逻辑修正：rating 折算 {stats['rating_converted']} 条，"
          f"品类矛盾标记 {stats['inconsistent_marked']} 条")
    return out, stats


# ---------------------------------------------------------------------------
# 质量报告
# ---------------------------------------------------------------------------


CORE_COLUMNS = ("brand", "product", "price", "rating", "review_text",
                "date", "interaction_count")


def completeness(df: pd.DataFrame) -> dict[str, float]:
    """字段完整率 = 非空且非空串比例（%）。"""
    rates: dict[str, float] = {}
    for col in df.columns:
        if col.startswith("is_"):
            continue
        s = df[col]
        valid = s.notna() & s.astype(str).str.strip().ne("")
        rates[col] = round(float(valid.mean() * 100), 2)
    return rates


def build_report(raw: pd.DataFrame, clean: pd.DataFrame, log: CleaningLog,
                 c7_stats: dict, c10_stats: dict) -> dict:
    rates = completeness(clean)
    overall = round(sum(rates[c] for c in CORE_COLUMNS) / len(CORE_COLUMNS), 2)

    return {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "raw_rows": int(len(raw)),
        "clean_rows": int(len(clean)),
        "rows_dropped_total": int(len(raw) - len(clean)),
        "actions": {
            "C1_brand_alias_normalized": log.count("C1_brand_alias"),
            "C1_brand_unknown_kept": log.count("C1_brand_unknown"),
            "C2_full_duplicates_removed": log.count("C2_full_duplicate"),
            "C3_id_duplicates_removed": log.count("C3_id_duplicate"),
            "C4_dates_normalized": log.count("C4_date_norm"),
            "C4_dates_invalid_set_null": log.count("C4_date_invalid"),
            "C5_prices_parsed": log.count("C5_price_parse"),
            "C5_prices_invalid_set_null": log.count("C5_price_invalid"),
            "C6_prices_clipped": log.count("C6_price_clip"),
            "C7_rows_dropped": c7_stats.get("dropped_missing_required", 0),
            "C7_interaction_filled_zero": c7_stats.get("filled_interaction_zero", 0),
            "C8_noise_marked": log.count("C8_noise"),
            "C9_text_normalized": log.count("C9_text_normalized"),
            "C10_rating_converted": log.count("C10_rating_converted"),
            "C10_rating_clipped": log.count("C10_rating_clipped"),
            "C10_product_brand_inconsistent": log.count("C10_inconsistent"),
        },
        "completeness_pct": rates,
        "overall_completeness_pct": overall,
        "pass_90pct_target": overall >= 90.0,
        "brands_after_normalize": sorted(clean["brand"].unique().tolist()),
        "n_brands": int(clean["brand"].nunique()),
        "date_range": [
            clean["date"].replace("", pd.NA).dropna().min(),
            clean["date"].replace("", pd.NA).dropna().max(),
        ],
        "valid_reviews": int((clean["is_valid_review"] == 1).sum()),
        "invalid_reviews": int((clean["is_valid_review"] == 0).sum()),
        "consistent_records": int((clean["is_consistent"] == 1).sum()),
        "inconsistent_records": int((clean["is_consistent"] == 0).sum()),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_cleaning(raw_path: Path = RAW_DEFAULT, out_dir: Path = OUT_DIR_DEFAULT) -> dict:
    """执行 C1—C10 全流程，返回质量报告 dict。"""
    log = CleaningLog()

    raw = pd.read_csv(raw_path, encoding="utf-8", dtype=str, keep_default_na=False)
    raw = raw.replace({"": None})
    print(f"读取原始数据 {len(raw)} 行 <- {raw_path.name}")

    df = c1_normalize_brand(raw, log)
    df = c2_dedupe_full(df, log)
    df = c3_dedupe_id(df, log)
    df = c4_normalize_date(df, log)
    df = c5_clean_price(df, log)
    df = c6_clip_price(df, log)
    df, c7_stats = c7_handle_missing(df, log)
    df = c9_normalize_text(df, log)
    df = c8_mark_noise(df, log)
    df, c10_stats = c10_fix_logic(df, log)

    df = df[COLUMNS_ORDER].sort_values("review_id").reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    clean_path = out_dir / "clean_data.csv"
    df.to_csv(clean_path, index=False, encoding="utf-8-sig")
    log.to_frame().to_csv(out_dir / "cleaning_log.csv", index=False, encoding="utf-8-sig")

    report = build_report(raw, df, log, c7_stats, c10_stats)
    (out_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _write_summary(report, out_dir)

    print(f"\n清洗完成 -> {clean_path.name}（原始文件未被修改）")
    print(f"整体字段完整率 {report['overall_completeness_pct']}%"
          f"（达标线 90%：{'✅ 达标' if report['pass_90pct_target'] else '❌ 未达标'}）")
    return report


def _write_summary(report: dict, out_dir: Path) -> None:
    """摘要落盘（outputs/cleaning_summary.txt）。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"清洗摘要（{report['generated_at']}）",
        f"原始 {report['raw_rows']} 行 -> 清洗后 {report['clean_rows']} 行"
        f"（剔除 {report['rows_dropped_total']} 行）",
        f"整体字段完整率：{report['overall_completeness_pct']}%"
        f"（达标线 90%：{'✅ 达标' if report['pass_90pct_target'] else '❌ 未达标'}）",
        f"品牌收敛至 {report['n_brands']} 个：{'、'.join(report['brands_after_normalize'])}",
        f"有效评论 {report['valid_reviews']} 条 / 无效（已打标未删） {report['invalid_reviews']} 条",
        f"品类一致 {report['consistent_records']} 条 / 待复核 {report['inconsistent_records']} 条",
        "",
        "各规则命中次数：",
    ]
    for k, v in report["actions"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("字段完整率：")
    for k, v in report["completeness_pct"].items():
        lines.append(f"  {k}: {v}%")
    (OUTPUT_DIR / "cleaning_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="营销数据清洗管线 v0.3（蓝牙耳机）")
    parser.add_argument("--raw", type=str, default=str(RAW_DEFAULT))
    parser.add_argument("--out-dir", type=str, default=str(OUT_DIR_DEFAULT))
    args = parser.parse_args()

    report = run_cleaning(Path(args.raw), Path(args.out_dir))
    print(json.dumps(report["actions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
