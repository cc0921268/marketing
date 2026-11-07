# -*- coding: utf-8 -*-
"""实验3：清洗管线单元测试（v0.3 · 蓝牙耳机品类）

覆盖：
    - 生成器：可复现、恰好 300 条、10 类噪声齐全
    - C1  品牌别名归一（含繁体「華為」、俗称「新力」「欧珀」）
    - C2  整行完全重复剔除
    - C3  review_id 重复（内容不同）保留首条
    - C4  日期 5 种格式归一 + 未来日期置空
    - C5  价格脏格式解析（￥/元/千分位/欧式小数）
    - C6  价格异常 winsorize 截断（不删行）
    - C7  缺失分级处理（剔除/置空/填 0）
    - C8  无效评论打标（只标不删）
    - C9  文字形态归一（繁简/emoji/全角，保留中文标点）
    - C10 rating 超范围折算 + 产品品牌一致性标记
    - 端到端：raw 不被修改、幂等、完整率 ≥90%、品牌收敛 6 个、日志结构

运行：
    python tests/test_cleaning.py
    python -m pytest tests/test_cleaning.py -v
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_cleaning import (  # noqa: E402
    BRAND_ALIAS_MAP, BRAND_PRODUCTS, COLLECTION_YEAR, TRAD_TO_SIMPLE, CleaningLog,
    c1_normalize_brand, c2_dedupe_full, c3_dedupe_id, c4_normalize_date,
    c5_clean_price, c6_clip_price, c7_handle_missing, c8_mark_noise,
    c9_normalize_text, c10_fix_logic, is_noise_text, parse_price,
    run_cleaning,
)
from src.generate_raw_data import generate, write_csv  # noqa: E402

RAW = PROJECT_ROOT / "data" / "raw" / "raw_data.csv"
PROCESSED = PROJECT_ROOT / "data" / "processed"
CLEAN = PROCESSED / "clean_data.csv"
LOG = PROCESSED / "cleaning_log.csv"
REPORT = PROCESSED / "quality_report.json"

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, msg: str = "") -> None:
    _results.append((name, bool(cond), msg))
    flag = "PASS" if cond else "FAIL"
    print(f"[{flag}] {name}" + (f" — {msg}" if msg and not cond else ""))


def _mkdf(rows: list[dict]) -> pd.DataFrame:
    """构造测试 DataFrame（列与原始 CSV 一致）。"""
    base = {
        "review_id": "R0001", "brand": "华为", "product": "FreeBuds 6i",
        "price": "599.00", "rating": "4.0",
        "review_text": "降噪效果不错，通勤够用。", "date": "2024-03-01",
        "interaction_count": "10",
    }
    out = []
    for r in rows:
        row = dict(base)
        row.update(r)
        out.append(row)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# 生成器
# ---------------------------------------------------------------------------


def test_generator_reproducible() -> None:
    """同一 seed 两次生成必须逐字节一致。"""
    tmp1 = Path("/tmp/_gen1.csv")
    tmp2 = Path("/tmp/_gen2.csv")
    write_csv(generate(n=100, seed=42), tmp1)
    write_csv(generate(n=100, seed=42), tmp2)
    h1 = hashlib.md5(tmp1.read_bytes()).hexdigest()
    h2 = hashlib.md5(tmp2.read_bytes()).hexdigest()
    check("test_generator_reproducible_with_same_seed", h1 == h2, f"{h1} != {h2}")


def test_generator_row_count() -> None:
    """生成条数必须恰好等于请求条数。"""
    check("test_generator_exact_row_count", len(generate(n=300, seed=42)) == 300)


def test_generator_noise_coverage() -> None:
    """10 类噪声必须真的注入了（不能只在文档里写）。"""
    recs = generate(n=300, seed=42)
    texts = [str(r["review_text"]) for r in recs]
    brands = [str(r["brand"]) for r in recs]
    prices = [str(r["price"]) for r in recs if r["price"]]
    dates = [str(r["date"]) for r in recs]
    ratings = [r["rating"] for r in recs if r["rating"] is not None]

    n_alias = len(set(brands))
    has_messy_price = any(("￥" in p) or ("元" in p) or ("," in p) for p in prices)
    n_big = sum(1 for p in prices if parse_price(p) and parse_price(p) > 5000)
    n_date_fmt = len({
        ("iso" if "-" in d else "slash" if "/" in d else
         "cn" if "年" in d else "compact") for d in dates
    })
    n_missing = (sum(1 for r in recs if not r["price"])
                 + sum(1 for r in recs if r["rating"] is None)
                 + sum(1 for r in recs if r["interaction_count"] is None))
    ids = [r["review_id"] for r in recs]
    has_dup = len(ids) != len(set(ids))
    has_noise = any(is_noise_text(t) for t in texts)
    has_trad = any(any(ch in t for ch in "續連藍音耳電斷通麥說聽") for t in texts)
    has_bad_rating = any(float(r) > 5 for r in ratings)
    has_future = any(d.startswith("2025") for d in dates)

    check("test_generator_noise_N1_brand_alias", n_alias >= 10, f"仅 {n_alias} 种写法")
    check("test_generator_noise_N2_messy_price", has_messy_price)
    check("test_generator_noise_N3_price_x10", n_big >= 1, f"{n_big} 条")
    check("test_generator_noise_N4_date_formats", n_date_fmt >= 4, f"{n_date_fmt} 种")
    check("test_generator_noise_N5_missing", n_missing >= 10, f"{n_missing} 处")
    check("test_generator_noise_N6_N7_duplicates", has_dup)
    check("test_generator_noise_N8_invalid_review", has_noise)
    check("test_generator_noise_N9_traditional", has_trad)
    check("test_generator_noise_N10_rating_out_of_range", has_bad_rating)
    check("test_generator_noise_N10_future_date", has_future)


# ---------------------------------------------------------------------------
# C1 品牌别名
# ---------------------------------------------------------------------------


def test_c1_brand_alias() -> None:
    df = pd.DataFrame({
        "review_id": ["A", "B", "C", "D", "E", "F", "G", "H"],
        "brand": ["airpods", "華為", "Redmi", "EDIFIER", "欧珀", "新力",
                  "Apple AirPods", "XXXXX未知品牌"],
    })
    lg = CleaningLog()
    out = c1_normalize_brand(df, lg)
    got = list(out["brand"])
    check("test_c1_brand_alias_normalized",
          got == ["Apple", "华为", "小米", "漫步者", "OPPO", "索尼", "Apple", "XXXXX未知品牌"],
          f"实得 {got}")
    check("test_c1_unknown_alias_kept", got[-1] == "XXXXX未知品牌")
    check("test_c1_unknown_logged", lg.count("C1_brand_unknown") == 1)


def test_c1_all_aliases_covered() -> None:
    """映射表覆盖生成器全部别名（否则会漏归一）。"""
    from src.generate_raw_data import BRAND_ALIASES
    missing = []
    for canon, aliases in BRAND_ALIASES.items():
        for a in aliases:
            if BRAND_ALIAS_MAP.get(a.strip().lower()) != canon:
                missing.append(a)
    check("test_c1_alias_map_covers_generator", not missing, f"缺失 {missing}")


# ---------------------------------------------------------------------------
# C2 / C3 去重
# ---------------------------------------------------------------------------


def test_c2_full_duplicate() -> None:
    df = _mkdf([
        {"review_id": "A"},
        {"review_id": "A"},          # 整行重复（含 ID）
        {"review_id": "B", "price": "699.00"},
    ])
    lg = CleaningLog()
    out = c2_dedupe_full(df, lg)
    check("test_c2_full_duplicate_removed", len(out) == 2, f"实得 {len(out)}")
    check("test_c2_full_duplicate_logged", lg.count("C2_full_duplicate") == 1)


def test_c3_id_duplicate_different_content() -> None:
    """ID 相同但内容不同 → C3 保留首条，C2 不应误删。"""
    df = _mkdf([
        {"review_id": "A", "rating": "4.5"},
        {"review_id": "A", "rating": "3.5"},   # ID 同、内容不同
    ])
    lg2 = CleaningLog()
    after_c2 = c2_dedupe_full(df, lg2)
    check("test_c3_c2_does_not_eat_id_dup", len(after_c2) == 2,
          f"C2 误删了 ID 重复行，剩 {len(after_c2)}")
    lg3 = CleaningLog()
    after_c3 = c3_dedupe_id(after_c2, lg3)
    check("test_c3_id_duplicate_keeps_first", len(after_c3) == 1)
    check("test_c3_keeps_first_record", after_c3.iloc[0]["rating"] == "4.5")
    check("test_c3_id_duplicate_logged", lg3.count("C3_id_duplicate") == 1)


def test_c2_c3_are_disjoint_on_real_data() -> None:
    """真实数据上 C2/C3 各管一类重复，不能退化成一类。"""
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    c2 = report["actions"]["C2_full_duplicates_removed"]
    c3 = report["actions"]["C3_id_duplicates_removed"]
    check("test_c2_c3_both_hit_real_data", c2 > 0 and c3 > 0, f"C2={c2}, C3={c3}")


# ---------------------------------------------------------------------------
# C4 日期
# ---------------------------------------------------------------------------


def test_c4_date_formats() -> None:
    df = _mkdf([
        {"review_id": "A", "date": "2024-06-01"},
        {"review_id": "B", "date": "2024/6/1"},
        {"review_id": "C", "date": "20240601"},
        {"review_id": "D", "date": "2024年6月1日"},
        {"review_id": "E", "date": "6/1"},        # 缺年份 → 按 2024 补齐
    ])
    lg = CleaningLog()
    out = c4_normalize_date(df, lg)
    got = list(out["date"])
    check("test_c4_all_formats_to_iso", got == ["2024-06-01"] * 5, f"实得 {got}")
    check("test_c4_missing_year_filled", got[4] == f"{COLLECTION_YEAR}-06-01")


def test_c4_future_date_set_null() -> None:
    """未来日期视为录入错误 → 置空，不编造。"""
    df = _mkdf([{"review_id": "A", "date": "2025-09-22"}])
    lg = CleaningLog()
    out = c4_normalize_date(df, lg)
    check("test_c4_future_date_set_null", out.iloc[0]["date"] == "")
    check("test_c4_future_logged", lg.count("C4_date_invalid") == 1)


def test_c4_invalid_date_set_null() -> None:
    df = _mkdf([{"review_id": "A", "date": "2024-13-45"}])  # 月份/日期越界
    lg = CleaningLog()
    out = c4_normalize_date(df, lg)
    check("test_c4_invalid_date_set_null", out.iloc[0]["date"] == "")


# ---------------------------------------------------------------------------
# C5 价格
# ---------------------------------------------------------------------------


def test_c5_price_parsing() -> None:
    cases = {
        "￥1299.00": 1299.0,
        "1299元": 1299.0,
        "1,299.00": 1299.0,
        "330,51": 330.51,        # 欧式小数
        "699": 699.0,
        "  ￥ 899.9 ": 899.9,
    }
    bad = []
    for raw, want in cases.items():
        got = parse_price(raw)
        if got is None or abs(got - want) > 0.01:
            bad.append(f"{raw!r}→{got}（期望 {want}）")
    check("test_c5_price_formats_parsed", not bad, "; ".join(bad))


def test_c5_european_decimal_not_swollen() -> None:
    """欧式小数 330,51 不能变成 33051。"""
    got = parse_price("330,51")
    check("test_c5_european_decimal", got == 330.51, f"实得 {got}")


def test_c5_blank_price_no_log() -> None:
    """空价格归 C7 管，不该写 C5 日志（否则两份统计互相污染）。"""
    df = _mkdf([{"review_id": "A", "price": ""}, {"review_id": "B", "price": None}])
    lg = CleaningLog()
    c5_clean_price(df, lg)
    check("test_c5_blank_price_not_logged",
          lg.count("C5_price_invalid") == 0 and lg.count("C5_price_parse") == 0)


def test_c5_invalid_price_set_null() -> None:
    df = _mkdf([{"review_id": "A", "price": "面议"}])
    lg = CleaningLog()
    out = c5_clean_price(df, lg)
    check("test_c5_invalid_price_set_null", pd.isna(out.iloc[0]["price"]))
    check("test_c5_invalid_price_logged", lg.count("C5_price_invalid") == 1)


# ---------------------------------------------------------------------------
# C6 价格截断
# ---------------------------------------------------------------------------


def test_c6_price_clipped_not_dropped() -> None:
    """超上限价格 winsorize 截断，行必须保留。"""
    rows = [{"review_id": f"R{i:03d}", "brand": "小米", "price": float(300 + i)}
            for i in range(20)]
    rows.append({"review_id": "RBIG", "brand": "小米", "price": 99999.0})
    df = _mkdf(rows)
    lg = CleaningLog()
    out = c6_clip_price(df, lg)
    big = out[out["review_id"] == "RBIG"].iloc[0]
    check("test_c6_clipped_row_kept", len(out) == len(df))
    check("test_c6_clipped_to_brand_upper", big["price"] <= 1200.0, f"实得 {big['price']}")
    check("test_c6_clip_logged", lg.count("C6_price_clip") == 1)


def test_c6_nan_price_skipped() -> None:
    """缺失价格不应触发截断逻辑（NaN > 0 恒为 False 的老坑）。"""
    df = _mkdf([{"review_id": "A", "brand": "小米", "price": None}])
    lg = CleaningLog()
    out = c6_clip_price(df, lg)
    check("test_c6_nan_price_ignored",
          lg.count("C6_price_clip") == 0 and pd.isna(out.iloc[0]["price"]))


# ---------------------------------------------------------------------------
# C7 缺失
# ---------------------------------------------------------------------------


def test_c7_missing_rules() -> None:
    df = _mkdf([
        {"review_id": "A", "review_text": ""},                    # 必需缺失 → 删
        {"review_id": "B", "brand": ""},                          # 必需缺失 → 删
        {"review_id": "C", "price": None, "rating": None,
         "interaction_count": None},                              # 置空 + 填 0
    ])
    lg = CleaningLog()
    out, stats = c7_handle_missing(df, lg)
    check("test_c7_drop_missing_required", len(out) == 1, f"实得 {len(out)}")
    check("test_c7_kept_row_id", out.iloc[0]["review_id"] == "C")
    check("test_c7_interaction_filled_zero", int(out.iloc[0]["interaction_count"]) == 0)
    check("test_c7_price_kept_null", pd.isna(out.iloc[0]["price"]))
    check("test_c7_rating_kept_null", pd.isna(out.iloc[0]["rating"]))
    check("test_c7_stats_missing_dropped", stats["dropped_missing_required"] == 2)


# ---------------------------------------------------------------------------
# C8 噪音
# ---------------------------------------------------------------------------


def test_c8_noise_patterns() -> None:
    noise = ["。。。。。", "！！！", "666666", "111", "加我微信代购耳机5折",
             "转发抽奖", "今日天气不错", "祝商家生意兴隆", "x", ""]
    normal = ["一般", "还行吧", "退货了", "到了", "降噪不错", "音质很好但续航虚标"]
    bad_noise = [t for t in noise if not is_noise_text(t)]
    bad_normal = [t for t in normal if is_noise_text(t)]
    check("test_c8_noise_detected", not bad_noise, f"漏判 {bad_noise}")
    check("test_c8_short_but_informative_kept", not bad_normal, f"误判 {bad_normal}")


def test_c8_marked_not_deleted() -> None:
    df = _mkdf([
        {"review_id": "A", "review_text": "。。。。。"},
        {"review_id": "B", "review_text": "降噪很给力，地铁完全听不见。"},
    ])
    lg = CleaningLog()
    out = c8_mark_noise(df, lg)
    check("test_c8_noise_row_kept", len(out) == 2)
    check("test_c8_flag_values", list(out["is_valid_review"]) == [0, 1])


# ---------------------------------------------------------------------------
# C9 文字形态
# ---------------------------------------------------------------------------


def test_c9_traditional_to_simple() -> None:
    df = _mkdf([{"review_id": "A", "review_text": "續航一般，藍牙連接不穩。"}])
    lg = CleaningLog()
    out = c9_normalize_text(df, lg)
    got = out.iloc[0]["review_text"]
    check("test_c9_traditional_normalized", got == "续航一般，蓝牙连接不稳。",
          f"实得 {got!r}")


def test_c9_traditional_map_self_consistent() -> None:
    """繁简映射表自洽性：每条覆盖样本都能被替换且替换后不再含原繁体。

    这条用来卡住「映射表漏词条」这一类回归——历史上 TRAD_TO_SIMPLE 缺
    「穩→稳」时，C9 会静默漏归一，端到端测试看不出来。
    """
    sample_texts = [
        "續航一般，藍牙連接不穩。", "音質很好但價格偏貴", "耳機電池會斷連",
        "外觀好看，戴久了耳壓大", "通話麥克風聽不太清楚", "這款買回來就開不了機",
        "華為的降噪比新力強", "輕了不少，長時間戴也还行",
    ]
    for text in sample_texts:
        out = text
        for trad, simp in TRAD_TO_SIMPLE.items():
            out = out.replace(trad, simp)
        residual = [t for t in TRAD_TO_SIMPLE if t in out]
        check("test_c9_trad_map_covers", not residual,
              f"{text!r} 残留繁体 {residual}")


def test_c10_fixed_rows_never_reenter_clip_range() -> None:
    """折算后的 rating 不得再被 C10 判为超范围（避免重复折算）。"""
    df = _mkdf([{"review_id": "A", "rating": 10.0}, {"review_id": "B", "rating": 9.8}])
    lg = CleaningLog()
    out, _ = c10_fix_logic(df, lg)
    vals = [float(v) for v in out["rating"]]
    check("test_c10_second_pass_no_conversion",
          all(1.0 <= v <= 5.0 for v in vals), f"实得 {vals}")
    lg2 = CleaningLog()
    out2, stats2 = c10_fix_logic(out, lg2)
    check("test_c10_idempotent", stats2["rating_converted"] == 0,
          f"二次折算 {stats2['rating_converted']} 条")


def test_c9_emoji_stripped() -> None:
    df = _mkdf([{"review_id": "A", "review_text": "音质不错😂👍"}])
    lg = CleaningLog()
    out = c9_normalize_text(df, lg)
    check("test_c9_emoji_stripped", out.iloc[0]["review_text"] == "音质不错",
          f"实得 {out.iloc[0]['review_text']!r}")


def test_c9_chinese_punctuation_preserved() -> None:
    """中文全角标点是正常书写，**不能**被转成半角（初版 bug）。"""
    df = _mkdf([{"review_id": "A", "review_text": "降噪不错，续航一般。价格偏贵！"}])
    lg = CleaningLog()
    out = c9_normalize_text(df, lg)
    got = out.iloc[0]["review_text"]
    check("test_c9_chinese_punct_kept", "，" in got and "。" in got, f"实得 {got!r}")
    check("test_c9_chinese_punct_no_log", lg.count("C9_text_normalized") == 0)


def test_c9_fullwidth_alnum_converted() -> None:
    df = _mkdf([{"review_id": "A", "review_text": "ＡｉｒＰｏｄｓ 音质好"}])
    lg = CleaningLog()
    out = c9_normalize_text(df, lg)
    got = out.iloc[0]["review_text"]
    check("test_c9_fullwidth_alnum", "AirPods" in got, f"实得 {got!r}")


# ---------------------------------------------------------------------------
# C10 逻辑修正
# ---------------------------------------------------------------------------


def test_c10_rating_converted() -> None:
    """10 分制评分（8.7）按 ÷2 折算为 4.4，不删除。"""
    df = _mkdf([
        {"review_id": "A", "rating": 8.7},
        {"review_id": "B", "rating": 4.2},
    ])
    lg = CleaningLog()
    out, stats = c10_fix_logic(df, lg)
    check("test_c10_rating_converted_to_half",
          abs(float(out.iloc[0]["rating"]) - 4.4) < 1e-6,
          f"实得 {out.iloc[0]['rating']}")
    check("test_c10_normal_rating_untouched",
          abs(float(out.iloc[1]["rating"]) - 4.2) < 1e-6)
    check("test_c10_conversion_logged", lg.count("C10_rating_converted") == 1)


def test_c10_product_brand_consistency() -> None:
    """产品不属于该品牌 → 标记 is_consistent=0，不删除。"""
    df = _mkdf([
        {"review_id": "A", "brand": "华为", "product": "FreeBuds 6i"},
        {"review_id": "B", "brand": "华为", "product": "Redmi Buds 6"},  # 张冠李戴
    ])
    lg = CleaningLog()
    out, stats = c10_fix_logic(df, lg)
    check("test_c10_consistent_flagged_1", int(out.iloc[0]["is_consistent"]) == 1)
    check("test_c10_inconsistent_flagged_0", int(out.iloc[1]["is_consistent"]) == 0)
    check("test_c10_inconsistent_row_kept", len(out) == 2)
    check("test_c10_inconsistent_logged", lg.count("C10_inconsistent") == 1)


def test_c10_brand_product_map_complete() -> None:
    """BRAND_PRODUCTS 必须覆盖生成器全部产品（否则一致性校验会误报）。"""
    from src.generate_raw_data import PRODUCTS
    missing = []
    for brand, plist in PRODUCTS.items():
        for p, _, _ in plist:
            if p not in BRAND_PRODUCTS.get(brand, set()):
                missing.append(f"{brand}/{p}")
    check("test_c10_brand_product_map_matches_generator", not missing, f"缺失 {missing}")


# ---------------------------------------------------------------------------
# 端到端
# ---------------------------------------------------------------------------


def test_pipeline_outputs_exist() -> None:
    check("test_pipeline_clean_exists", CLEAN.exists())
    check("test_pipeline_log_exists", LOG.exists())
    check("test_pipeline_report_exists", REPORT.exists())


def test_raw_untouched() -> None:
    """清洗不得覆盖原始文件（用 md5 校验）。"""
    before = hashlib.md5(RAW.read_bytes()).hexdigest()
    run_cleaning(RAW, PROCESSED)
    after = hashlib.md5(RAW.read_bytes()).hexdigest()
    check("test_pipeline_raw_not_modified", before == after, f"{before} != {after}")


def test_pipeline_idempotent() -> None:
    """幂等：连续跑两次 clean_data.csv 逐字节一致。"""
    run_cleaning(RAW, PROCESSED)
    h1 = hashlib.md5(CLEAN.read_bytes()).hexdigest()
    run_cleaning(RAW, PROCESSED)
    h2 = hashlib.md5(CLEAN.read_bytes()).hexdigest()
    check("test_pipeline_idempotent", h1 == h2, f"{h1} != {h2}")


def test_completeness_target() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    rate = report["overall_completeness_pct"]
    check("test_completeness_above_90pct", rate >= 90.0, f"实得 {rate}%")
    check("test_completeness_flag_true", report["pass_90pct_target"] is True)


def test_brands_converged_to_six() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    brands = report["brands_after_normalize"]
    want = {"Apple", "华为", "小米", "漫步者", "OPPO", "索尼"}
    check("test_brands_converged_to_6", set(brands) == want, f"实得 {brands}")


def test_dates_all_iso_or_empty() -> None:
    df = pd.read_csv(CLEAN, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    bad = [d for d in df["date"] if d and not (len(d) == 10 and d[4] == "-" and d[7] == "-")]
    check("test_dates_all_iso_format", not bad, f"异常 {bad[:5]}")


def test_rating_in_range() -> None:
    df = pd.read_csv(CLEAN, encoding="utf-8-sig")
    r = pd.to_numeric(df["rating"], errors="coerce").dropna()
    check("test_rating_within_1_to_5", bool(((r >= 1.0) & (r <= 5.0)).all()),
          f"越界 {r[(r < 1) | (r > 5)].tolist()[:5]}")


def test_no_future_dates() -> None:
    df = pd.read_csv(CLEAN, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    future = [d for d in df["date"] if d and d > "2024-12-31"]
    check("test_no_future_dates", not future, f"实得 {future[:5]}")


def test_log_structure() -> None:
    df = pd.read_csv(LOG, encoding="utf-8-sig")
    check("test_log_columns",
          list(df.columns) == ["review_id", "action", "detail", "before", "after"],
          f"实得 {list(df.columns)}")
    check("test_log_not_empty", len(df) > 100, f"{len(df)} 行")
    check("test_log_all_have_review_id", df["review_id"].notna().all())


def test_report_structure() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    need = ["raw_rows", "clean_rows", "rows_dropped_total", "actions",
            "completeness_pct", "overall_completeness_pct", "pass_90pct_target",
            "brands_after_normalize", "date_range"]
    missing = [k for k in need if k not in report]
    check("test_report_required_keys", not missing, f"缺失 {missing}")
    check("test_report_row_math",
          report["rows_dropped_total"] == report["raw_rows"] - report["clean_rows"])


def test_clean_row_count_matches_raw() -> None:
    """清洗后行数 = 原始 - C2 - C3 - C7 剔除。"""
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    expect = (report["raw_rows"]
              - report["actions"]["C2_full_duplicates_removed"]
              - report["actions"]["C3_id_duplicates_removed"]
              - report["actions"]["C7_rows_dropped"])
    check("test_clean_row_math", report["clean_rows"] == expect,
          f"{report['clean_rows']} != {expect}")


def test_csv_readable_directly() -> None:
    """clean_data.csv 必须能被标准 csv 模块直接读（无编码问题）。"""
    with open(CLEAN, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    check("test_clean_csv_readable", len(rows) > 0)


def main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__}_raised", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    print(f"\n合计 {len(_results)} 项，通过 {passed} 项，失败 {failed} 项。")
    if failed:
        print("\n失败明细：")
        for name, ok, msg in _results:
            if not ok:
                print(f"  - {name}: {msg}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
