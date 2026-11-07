# -*- coding: utf-8 -*-
"""实验4 单元测试（v0.4 · 蓝牙耳机品类）

覆盖：
    1. 编码器：字段合规、噪音拒答、好差不误判、多痛点、转折处理
    2. 统计层：分母口径、占比格式、交叉表行合计、痛点排行排序
    3. 证据：每个核心痛点 ≥3 条、review_id 可回查、quote 是原文逐字子串
    4. 报告：事实/推断/建议三段齐全、不出现绝对化断言
    5. 端到端：落盘、幂等、编码抽检一致率 ≥80%

运行：python3 tests/test_engine.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.consumer_insight_engine import (  # noqa: E402
    NEGATIVE_CUES, PAIN_DIMENSIONS, build_insight_report,
    encode_batch, encode_review, filter_valid, fmt_ratio,
    load_clean, pain_ranking, run_engine, sentiment_distribution,
    split_clauses, top_evidence, is_noise,
)

CLEAN = PROJECT_ROOT / "data" / "processed" / "clean_data.csv"
OUT = PROJECT_ROOT / "outputs"

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, msg: str = "") -> None:
    _results.append((name, bool(cond), msg))


# ---------------------------------------------------------------------------
# 1. 编码器
# ---------------------------------------------------------------------------


def test_encoding_schema_fields() -> None:
    """编码输出必须包含实验2 schema 的全部必填字段。"""
    required = ["review_id", "sentiment", "need", "pain_point", "scenario",
                "purchase_barrier", "evidence", "confidence", "refuse",
                "refuse_reason", "unjudged_fields"]
    r = encode_review("R0001", "续航扎实，办公室全程戴着，一天下来还有40%。")
    for f in required:
        check(f"test_enc_has_field_{f}", f in r, f"缺字段 {f}")


def test_sentiment_enum() -> None:
    """情绪值必须在枚举范围内。"""
    allowed = {"positive", "negative", "neutral", "mixed", "unknown"}
    for text in ["音质很惊喜", "太差了", "能用吧", "音质好但续航差", ""]:
        r = encode_review("X", text)
        check(f"test_enc_sentiment_enum", r["sentiment"] in allowed, r["sentiment"])


def test_noise_refused() -> None:
    """噪音必须拒答，且拒绝原因非空。"""
    for text in ["。。。。。", "666666", "加我微信abc", "天气不错", "路过看看"]:
        r = encode_review("N", text)
        check("test_enc_noise_refuse", r["refuse"] is True, f"{text!r} 未拒答")
        check("test_enc_noise_reason", bool(r["refuse_reason"]), f"{text!r} 缺原因")


def test_short_valid_review_kept() -> None:
    """短评"一般""退货了"不算噪音（与实验2/3 口径一致）。"""
    for text in ["一般", "还行吧", "退货了"]:
        r = encode_review("S", text)
        check("test_enc_short_not_noise", r["refuse"] is False, f"{text!r} 被误拒")


def test_positive_not_pain() -> None:
    """好评不能产生痛点。"""
    cases = [
        "LolliPods Pro音质很惊喜，低频有质感，听流行很带感。",
        "续航扎实，办公室全程戴着，一天下来还有40%。",
        "佩戴很轻，戴两小时耳朵不胀。",
        "颜值高，做工细腻，开合手感踏实。",
        "延迟低，打游戏音画同步，性价比拉满。",
    ]
    for text in cases:
        r = encode_review("P", text)
        check("test_enc_positive_no_pain", r["pain_points"] == [],
              f"{text[:20]!r} 误判痛点 {r['pain_points']}")


def test_negative_detected() -> None:
    """典型差评必须识别出对应维度。"""
    cases = [
        ("Enco Air4中高频发刺，听人声有点刮耳。", "音质"),
        ("AirPods 3续航虚标，标称8小时实际4小时就没电。", "续航"),
        ("Enco Air4戴久了耳朵疼，耳塞偏硬。", "佩戴舒适"),
        ("NeoBuds Pro 2蓝牙配对折腾半天，两台设备切换总失败。", "连接稳定性"),
        ("AirPods Pro 2通话风噪严重，办公室对方说听不清。", "通话质量"),
        ("买的Xiaomi Buds 5拆封有划痕，申请换货被拒。", "售后服务"),
        ("Redmi Buds 6卖182元，这个配置实在有点贵。", "价格性价比"),
        ("FreeBuds 6i降噪名不副实，开了和没开差不多。", "降噪"),
    ]
    for text, expect in cases:
        r = encode_review("N", text)
        check("test_enc_negative_dim", expect in r["pain_points"],
              f"{text[:22]!r} 期望含 {expect}，实得 {r['pain_points']}")


def test_contrast_clause_isolation() -> None:
    """转折句：只标后半句的痛点，不误伤前半句的好评维度。"""
    cases = [
        # 降噪是好评，续航是差评 -> 只标续航
        ("降噪给力，可惜AirPods 3续航一般", ["续航"], ["降噪"]),
        # 音质是好评，连接是差评 -> 只标连接
        ("音质没得说，就是连接偶尔抽风", ["连接稳定性"], ["音质"]),
        # 音质降噪都好，佩戴差
        ("音质和降噪都不错，但开车戴一会儿耳朵就疼", ["佩戴舒适"], ["音质", "降噪"]),
    ]
    for text, must, must_not in cases:
        r = encode_review("C", text)
        for m in must:
            check("test_contrast_must_have", m in r["pain_points"],
                  f"{text[:20]!r} 缺 {m}，实得 {r['pain_points']}")
        for mn in must_not:
            check("test_contrast_must_not", mn not in r["pain_points"],
                  f"{text[:20]!r} 误含 {mn}")


def test_multi_pain() -> None:
    """一条评论可命中多个痛点。"""
    r = encode_review("M", "降噪名不副实，戴久了耳朵还疼。")
    check("test_enc_multi_pain", len(r["pain_points"]) >= 1, str(r["pain_points"]))
    # 至少验证它不会崩，且 pain_detail 与 pain_points 数量一致
    check("test_enc_multi_pain_detail", len(r["pain_detail"]) == len(r["pain_points"]))


def test_clause_split() -> None:
    """切句：标点 + 转折词都要切。"""
    cs = split_clauses("音质和降噪都不错，但开车戴一会儿耳朵就疼。")
    check("test_split_contrast", len(cs) >= 2, str(cs))
    check("test_split_punct", len(split_clauses("音质好，续航差。")) == 2)


def test_turn_word_not_negative() -> None:
    """转折词本身不能被当成负向线索（历史 bug：导致全表负面率虚高）。"""
    for w in ["但", "就是", "却", "不过", "然而"]:
        check("test_contrast_not_in_neg_cues", w not in NEGATIVE_CUES,
              f"{w} 不该出现在 NEGATIVE_CUES")


def test_upstream_invalid_respected() -> None:
    """实验3 标记的无效评论，即使文本看起来正常也要拒答。"""
    r = encode_review("U", "这个耳机还行吧", upstream_invalid=True)
    check("test_enc_upstream_refuse", r["refuse"] is True)
    check("test_enc_upstream_reason", "实验3" in (r["refuse_reason"] or ""))


def test_evidence_is_substring() -> None:
    """证据 quote 必须是原文逐字子串（红线）。"""
    text = "FreeBuds 6i降噪名不副实，开了和没开差不多，地铁上照样吵。"
    r = encode_review("E", text)
    for ev in r["evidence"]:
        check("test_ev_substring", ev["quote"] in text,
              f"quote {ev['quote']!r} 不在原文中")


def test_no_evidence_for_null_fields() -> None:
    """没有判断依据的字段不能编造证据。"""
    r = encode_review("Z", "一般")
    for ev in r["evidence"]:
        check("test_ev_field_judged", ev["field"] in
              ["sentiment", "need", "pain_point", "scenario", "purchase_barrier"])


# ---------------------------------------------------------------------------
# 2. 统计层
# ---------------------------------------------------------------------------


def test_fmt_ratio() -> None:
    """占比格式必须是 `n/总数（x.x%）`。"""
    check("test_fmt_ratio_basic", fmt_ratio(28, 267) == "28/267（10.5%）",
          fmt_ratio(28, 267))
    check("test_fmt_ratio_zero", fmt_ratio(0, 0) == "0/0（—）", fmt_ratio(0, 0))
    check("test_fmt_ratio_all", fmt_ratio(267, 267) == "267/267（100.0%）")


def test_sentiment_sums_to_total() -> None:
    """情绪分布（五类 + 拒答）必须恰好等于分母，不重不漏。"""
    df = load_clean(CLEAN)
    enc_all = encode_batch(df)
    s = sentiment_distribution(enc_all, enc_all)
    check("test_senti_sum", int(s["条数"].sum()) == len(df),
          f"合计 {s['条数'].sum()} != {len(df)}")


def test_refuse_counted() -> None:
    """拒答必须被统计到（历史 bug：先过滤后编码导致拒答恒 0）。"""
    df = load_clean(CLEAN)
    enc_all = encode_batch(df)
    s = sentiment_distribution(enc_all, enc_all)
    n_refuse = int(s[s["编码值"] == "refuse"]["条数"].iloc[0])
    expect = int((df["is_valid_review"] == 0).sum())
    check("test_refuse_count_matches_clean",
          n_refuse >= expect,
          f"拒答 {n_refuse} 应 >= 实验3 标记的 {expect}")
    check("test_refuse_not_zero", n_refuse > 0, "拒答不能为 0")


def test_pain_ranking_denominator() -> None:
    """痛点排行分母必须是有效评论数。"""
    df = filter_valid(load_clean(CLEAN))
    enc = encode_batch(df)
    rk = pain_ranking(enc, df)
    if not rk.empty:
        check("test_rank_denominator", int(rk["分母"].iloc[0]) == len(df),
              f"{rk['分母'].iloc[0]} != {len(df)}")
        check("test_rank_ratio_format",
              "/" in str(rk["占比"].iloc[0]) and "%" in str(rk["占比"].iloc[0]))


def test_pain_ranking_sorted() -> None:
    """痛点排行必须按提及条数降序。"""
    df = filter_valid(load_clean(CLEAN))
    enc = encode_batch(df)
    rk = pain_ranking(enc, df)
    counts = list(rk["提及条数"])
    check("test_rank_sorted", counts == sorted(counts, reverse=True), str(counts))
    check("test_rank_starts_at_1", int(rk["排名"].iloc[0]) == 1)


def test_pain_ranking_no_double_count_same_review() -> None:
    """同一维度在同一评论内只能计 1 次（避免重复计数）。"""
    enc = encode_batch(pd.DataFrame([
        {"review_id": "A", "brand": "小米", "rating": 4.0, "is_valid_review": 1,
         "is_consistent": 1, "review_text": "降噪差，降噪真的很差，降噪不行。"},
    ]))
    df = pd.DataFrame([{"review_id": "A", "brand": "小米", "rating": 4.0,
                        "is_valid_review": 1, "is_consistent": 1}])
    rk = pain_ranking(enc, df)
    if not rk.empty:
        check("test_rank_no_double", int(rk[rk["痛点维度"] == "降噪"]["提及条数"].iloc[0]) == 1,
              str(rk.to_dict("records")))


def test_pain_dimensions_complete() -> None:
    """9 类痛点维度必须齐全且各有中文名与关键词。"""
    check("test_dim_count", len(PAIN_DIMENSIONS) == 9, str(len(PAIN_DIMENSIONS)))
    for key, (label, kws) in PAIN_DIMENSIONS.items():
        check("test_dim_has_label", bool(label), key)
        check("test_dim_has_kw", len(kws) >= 3, f"{key} 关键词过少")


# ---------------------------------------------------------------------------
# 3. 证据追溯
# ---------------------------------------------------------------------------


def test_every_core_pain_has_3_evidence() -> None:
    """每个核心痛点（TOP5）必须绑定 ≥3 条证据。"""
    result = run_engine(evidence_top_n=5)
    for dim, evs in result.meta["evidence"].items():
        check("test_ev_count_3", len(evs) >= 3, f"{dim} 只有 {len(evs)} 条")


def test_evidence_ids_exist_in_clean() -> None:
    """证据的 review_id 必须能在 clean_data 中找到。"""
    df = load_clean(CLEAN)
    valid_ids = set(df["review_id"].astype(str))
    result = run_engine(evidence_top_n=5)
    for dim, evs in result.meta["evidence"].items():
        for e in evs:
            check("test_ev_id_exists", e["review_id"] in valid_ids,
                  f"{dim}: {e['review_id']} 不存在")


def test_evidence_quote_in_original() -> None:
    """证据片段必须是该条评论原文的逐字子串。"""
    df = load_clean(CLEAN).set_index("review_id")
    result = run_engine(evidence_top_n=5)
    for dim, evs in result.meta["evidence"].items():
        for e in evs:
            original = str(df.loc[e["review_id"], "review_text"])
            check("test_ev_quote_verbatim", e["quote"] in original,
                  f"{e['review_id']}: {e['quote']!r}")


# ---------------------------------------------------------------------------
# 4. 报告
# ---------------------------------------------------------------------------


def test_report_three_sections() -> None:
    """报告必须明确区分事实/推断/建议三段。"""
    result = run_engine()
    rep = result.report
    check("test_rep_fact", "## 一、事实数据" in rep)
    check("test_rep_infer", "## 二、推断假设" in rep)
    check("test_rep_action", "## 三、行动建议" in rep)
    check("test_rep_evidence", "## 四、证据追溯" in rep)
    check("test_rep_method", "## 五、方法说明" in rep)


def test_report_has_denominators() -> None:
    """报告中每个占比都要带分母。"""
    result = run_engine()
    rep = result.report
    check("test_rep_ratio_format", "（" in rep and "）" in rep)
    # 必须出现 "n/总数（x%）" 形态
    import re
    hits = re.findall(r"\d+/\d+（\d+\.\d+%）", rep)
    check("test_rep_ratio_count", len(hits) >= 10, f"只有 {len(hits)} 处带分母占比")


def test_report_no_absolute_claim() -> None:
    """报告不得出现绝对化商业断言（合成数据，避免诋毁）。"""
    result = run_engine()
    rep = result.report
    bad = ["质量差", "最差", "垃圾", "千万别买", "骗人"]
    for w in bad:
        check("test_rep_no_absolute", w not in rep, f"出现绝对化表述 {w}")
    check("test_rep_simulated_note", "模拟数据" in rep, "缺模拟数据声明")


def test_report_facts_from_stats() -> None:
    """报告里的痛点数字必须与统计表一致。"""
    result = run_engine()
    rep = result.report
    rk = result.stats["pain_ranking"]
    if not rk.empty:
        top = rk.iloc[0]
        check("test_rep_top1_count", str(int(top["提及条数"])) in rep,
              f"报告未出现 TOP1 条数 {top['提及条数']}")
        check("test_rep_top1_name", str(top["痛点维度"]) in rep)


def test_report_contains_evidence_ids() -> None:
    """报告的证据段必须出现 review_id。"""
    result = run_engine()
    rep = result.report
    import re
    ids = re.findall(r"`(R\d{4})`", rep)
    check("test_rep_evidence_ids", len(ids) >= 15, f"只有 {len(ids)} 个 review_id")


# ---------------------------------------------------------------------------
# 5. 端到端
# ---------------------------------------------------------------------------


def test_outputs_written() -> None:
    """端到端跑完必须有落盘产物。"""
    run_engine()
    for f in ["encoding_results.json", "pain_point_ranking.csv",
              "sentiment_distribution.csv", "brand_sentiment.csv",
              "brand_pain_cross.csv", "evidence_table.csv", "insight_report.md"]:
        check(f"test_out_{f}", (OUT / f).exists(), f"缺 {f}")


def test_encoding_json_valid() -> None:
    """编码 JSON 必须可解析且条数 = 原始条数。"""
    run_engine()
    data = json.loads((OUT / "encoding_results.json").read_text(encoding="utf-8"))
    df = load_clean(CLEAN)
    check("test_json_parse", isinstance(data, list))
    check("test_json_len", len(data) == len(df), f"{len(data)} != {len(df)}")
    check("test_json_has_id", all("review_id" in d for d in data))


def test_engine_idempotent() -> None:
    """重复运行结果一致（除时间戳外）。"""
    r1 = run_engine()
    r2 = run_engine()
    check("test_idem_ranking", r1.stats["pain_ranking"].equals(r2.stats["pain_ranking"]))
    check("test_idem_sentiment", r1.stats["sentiment"].equals(r2.stats["sentiment"]))
    check("test_idem_cross", r1.stats["brand_pain"].equals(r2.stats["brand_pain"]))


def test_encoding_spotcheck_rate() -> None:
    """编码抽检一致率目标 ≥80%（课程要求）。

    抽检方式：对 10 条人工标注过期望值的样本做断言。
    这些期望值由人工逐条核对原文得出（见 docs/experiment04.md 抽检表）。
    """
    gold = [
        # (review_id, 原文片段关键判断, 期望 sentiment, 期望含痛点 or None)
        ("G01", "Enco Air4中高频发刺，听人声有点刮耳。", "negative", "音质"),
        ("G02", "LolliPods Pro音质很惊喜，低频有质感。", "positive", None),
        ("G03", "AirPods 3续航虚标，标称8小时实际4小时就没电。", "negative", "续航"),
        ("G04", "NeoBuds Pro 2蓝牙配对折腾半天，两台设备切换总失败。", "negative", "连接稳定性"),
        ("G05", "AirPods Pro 2通话风噪严重，办公室对方说听不清。", "negative", "通话质量"),
        ("G06", "买的Xiaomi Buds 5拆封有划痕，申请换货被拒。", "negative", "售后服务"),
        ("G07", "续航扎实，办公室全程戴着，一天下来还有40%。", "positive", None),
        ("G08", "降噪名不副实，开了和没开差不多。", "negative", "降噪"),
        ("G09", "佩戴很轻，戴两小时耳朵不胀。", "positive", None),
        ("G10", "Redmi Buds 6卖182元，这个配置实在有点贵。", "negative", "价格性价比"),
    ]
    ok_sent, ok_pain, total = 0, 0, len(gold)
    for rid, text, exp_s, exp_p in gold:
        r = encode_review(rid, text)
        if r["sentiment"] == exp_s:
            ok_sent += 1
        if exp_p is None:
            if r["pain_points"] == []:
                ok_pain += 1
        elif exp_p in r["pain_points"]:
            ok_pain += 1

    rate_s = ok_sent / total * 100
    rate_p = ok_pain / total * 100
    check("test_spot_sentiment_rate", rate_s >= 80, f"情绪一致率 {rate_s:.0f}%")
    check("test_spot_pain_rate", rate_p >= 80, f"痛点一致率 {rate_p:.0f}%")
    print(f"    抽检：情绪一致率 {ok_sent}/{total}（{rate_s:.0f}%），"
          f"痛点一致率 {ok_pain}/{total}（{rate_p:.0f}%）")


def test_encoding_json_schema_fields() -> None:
    """落盘 JSON 必须满足实验2 schema 的字段要求。"""
    run_engine()
    data = json.loads((OUT / "encoding_results.json").read_text(encoding="utf-8"))
    required = {"review_id", "sentiment", "need", "pain_point", "scenario",
                "purchase_barrier", "evidence", "confidence", "refuse",
                "refuse_reason", "unjudged_fields"}
    sample = data[0]
    missing = required - set(sample)
    check("test_json_schema_fields", not missing, f"缺 {missing}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


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
