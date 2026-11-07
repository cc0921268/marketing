# -*- coding: utf-8 -*-
"""实验2 单元测试（v0.2）：Consumer Insight Skill

覆盖：
1. 金标准样例全部通过校验器（Schema + 证据逐字比对 + 证据绑定）
2. schema.json 自身合法（官方 jsonschema Draft202012 检查）
3. 红线规则：伪造证据、改写摘录必须被拦下
4. 拒答样例的格式约束（refuse=true ⇒ sentiment=unknown、reason 必填）
5. 同一输入结构稳定性（字段契约固定）

运行：
    python -m pytest tests/test_skill.py -v
    # 或
    python tests/test_skill.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills.consumer_insight_skill_compat import load_examples  # noqa: E402  # noqa: E402

SKILL_DIR = PROJECT_ROOT / "skills" / "consumer-insight-skill"

sys.path.insert(0, str(SKILL_DIR / "tools"))

import validate_output as vo  # noqa: E402


def _examples() -> tuple[dict[str, str], list[dict]]:
    reviews = vo.load_reviews(SKILL_DIR / "examples" / "reviews_input.csv")
    outputs = json.loads((SKILL_DIR / "examples" / "expected_outputs.json").read_text(encoding="utf-8"))
    return reviews, outputs


# ---------------------------------------------------------------------------
# 1. 金标准全部通过
# ---------------------------------------------------------------------------


def test_all_examples_pass_validation():
    reviews, outputs = _examples()
    problems: list[str] = []
    for item in outputs:
        rid = item["review_id"]
        errs = vo.validate_schema_item(item)
        errs += vo.validate_evidence_traceability(item, reviews[rid])
        errs += vo.validate_evidence_binding(item)
        if errs:
            problems.append(f"{rid}: {errs}")
    assert not problems, f"金标准样例存在不通过项: {problems}"


def test_schema_file_is_valid_draft2020_12():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return  # 未安装 jsonschema 时跳过（validate_output 有内置等价校验兜底）
    schema = json.loads((SKILL_DIR / "schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    _, outputs = _examples()
    validator = Draft202012Validator(schema)
    for item in outputs:
        errs = list(validator.iter_errors(item))
        assert not errs, f"{item['review_id']} 不符合 schema.json: {[e.message for e in errs]}"


def test_example_count_is_10():
    _, outputs = _examples()
    assert len(outputs) == 10


def test_review_ids_match_input():
    reviews, outputs = _examples()
    assert {o["review_id"] for o in outputs} == set(reviews.keys())


# ---------------------------------------------------------------------------
# 2. 红线规则：伪造证据必须被拦下
# ---------------------------------------------------------------------------


def test_fabricated_quote_rejected():
    """evidence.quote 若不在原评论中（编造/改写），必须校验失败。"""
    reviews, outputs = _examples()
    item = json.loads(json.dumps(outputs[0]))  # 深拷贝 R001
    item["evidence"].append({"quote": "服务态度极差，店员骂人", "field": "pain_point"})
    errs = vo.validate_evidence_traceability(item, reviews["R001"])
    assert any("不可追溯" in e for e in errs)


def test_modified_quote_rejected():
    """把摘录改一个字（如加句号）也应被拦下。"""
    reviews, outputs = _examples()
    item = json.loads(json.dumps(outputs[0]))
    item["evidence"][0]["quote"] = item["evidence"][0]["quote"] + "。"
    errs = vo.validate_evidence_traceability(item, reviews["R001"])
    assert errs, "改写后的摘录不应通过逐字比对"


def test_unbound_nonnull_field_rejected():
    """非 null 判断字段没有证据 → 必须失败。"""
    _, outputs = _examples()
    item = json.loads(json.dumps(outputs[5]))  # R006
    item["evidence"] = [e for e in item["evidence"] if e["field"] != "need"]
    errs = vo.validate_evidence_binding(item)
    assert any("need" in e for e in errs)


def test_refuse_review_has_no_evidence_and_unknown_sentiment():
    reviews, outputs = _examples()
    for rid in ("R005", "R009"):
        item = next(o for o in outputs if o["review_id"] == rid)
        assert item["refuse"] is True
        assert item["sentiment"] == "unknown"
        assert item["evidence"] == []
        assert isinstance(item["refuse_reason"], str) and len(item["refuse_reason"]) >= 2


# ---------------------------------------------------------------------------
# 3. 结构稳定性与字段契约
# ---------------------------------------------------------------------------


def test_output_keys_are_fixed_contract():
    _, outputs = _examples()
    expected = {
        "review_id", "sentiment", "need", "pain_point", "scenario",
        "purchase_barrier", "evidence", "confidence", "refuse",
        "refuse_reason", "unjudged_fields",
    }
    for item in outputs:
        assert set(item.keys()) == expected, f"{item['review_id']} 字段契约不符"


def test_null_fields_are_listed_in_unjudged():
    """非拒答样例中，值为 null 的判断字段必须出现在 unjudged_fields。"""
    _, outputs = _examples()
    for item in outputs:
        if item["refuse"]:
            continue
        for f in ("need", "pain_point", "scenario", "purchase_barrier"):
            if item[f] is None:
                assert f in item["unjudged_fields"], f"{item['review_id']}.{f} 为 null 但未列入 unjudged_fields"


def test_sentiment_coverage_spans_five_types():
    """样例集合应覆盖 positive/negative/neutral/mixed/unknown 五类。"""
    _, outputs = _examples()
    sentiments = {o["sentiment"] for o in outputs}
    assert sentiments == {"positive", "negative", "neutral", "mixed", "unknown"}


def test_confidence_values_valid():
    _, outputs = _examples()
    assert all(o["confidence"] in {"high", "medium", "low"} for o in outputs)


def test_load_examples_helper():
    """兼容加载器可正常工作（供 v0.4 引擎复用）。"""
    reviews, outputs = load_examples()
    assert len(reviews) >= 10
    assert len(outputs) == 10


# ---------------------------------------------------------------------------
# 手动执行入口
# ---------------------------------------------------------------------------


def _run_all() -> None:
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_")]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed.append(name)
            print(f"[FAIL] {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[PASS] {name}")
    print(f"\n合计 {len(tests)} 项，通过 {passed} 项，失败 {len(failed)} 项。")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
