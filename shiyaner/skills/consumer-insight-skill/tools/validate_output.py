# -*- coding: utf-8 -*-
"""Consumer Insight Skill 输出校验器（v0.2）

两级校验：
1. JSON Schema 校验（jsonschema 库；未安装时使用内置等价校验）。
2. 证据逐字比对：evidence[].quote 必须能在原评论中逐字找到（红线规则）。

用法：
    # 校验金标准样例
    python skills/consumer-insight-skill/tools/validate_output.py \\
        --input skills/consumer-insight-skill/examples/reviews_input.csv \\
        --outputs skills/consumer-insight-skill/examples/expected_outputs.json

    # 校验任意一份模型输出（v0.4 引擎调用）
    python skills/consumer-insight-skill/tools/validate_output.py \\
        --input reviews.csv --outputs model_outputs.json

退出码：0 = 全部通过；1 = 存在不通过项（明细打印到 stdout）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / ".." / "schema.json"

JUDGED_FIELDS = ("need", "pain_point", "scenario", "purchase_barrier")
SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}
CONFIDENCES = {"high", "medium", "low"}
ALL_FIELDS = ("sentiment", "need", "pain_point", "scenario", "purchase_barrier")


def load_reviews(path: Path) -> dict[str, str]:
    """读取 reviews CSV，返回 {review_id: text}。"""
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            text = row.get("text") or ""
            if rid:
                mapping[rid] = text
    return mapping


def validate_schema_item(item: dict) -> list[str]:
    """内置 Schema 等价校验（不依赖第三方库也能跑）。"""
    errors: list[str] = []

    required = [
        "review_id", "sentiment", "need", "pain_point", "scenario",
        "purchase_barrier", "evidence", "confidence", "refuse",
        "refuse_reason", "unjudged_fields",
    ]
    for key in required:
        if key not in item:
            errors.append(f"缺少必填字段 {key}")

    allowed = set(required)
    extra = set(item) - allowed
    if extra:
        errors.append(f"存在 Schema 外字段: {sorted(extra)}")

    if errors:
        return errors

    if not isinstance(item["review_id"], str) or not item["review_id"]:
        errors.append("review_id 必须是非空字符串")

    if item["sentiment"] not in SENTIMENTS:
        errors.append(f"sentiment 非法: {item['sentiment']!r}")

    for key in ("need", "pain_point", "scenario", "purchase_barrier"):
        v = item[key]
        if v is not None and not isinstance(v, str):
            errors.append(f"{key} 必须是 string 或 null")

    if item["confidence"] not in CONFIDENCES:
        errors.append(f"confidence 非法: {item['confidence']!r}")

    if not isinstance(item["refuse"], bool):
        errors.append("refuse 必须是布尔值")

    if item["refuse"] is True:
        if not (isinstance(item["refuse_reason"], str) and len(item["refuse_reason"]) >= 2):
            errors.append("refuse=true 时 refuse_reason 必须为非空字符串")
        if item["sentiment"] != "unknown":
            errors.append("refuse=true 时 sentiment 必须为 unknown")
    else:
        if item["refuse_reason"] is not None:
            errors.append("refuse=false 时 refuse_reason 必须为 null")

    if not isinstance(item["evidence"], list):
        errors.append("evidence 必须是数组")
    else:
        for i, ev in enumerate(item["evidence"]):
            if not isinstance(ev, dict) or set(ev) != {"quote", "field"}:
                errors.append(f"evidence[{i}] 结构非法（应只含 quote/field）")
                continue
            if not isinstance(ev["quote"], str) or not ev["quote"].strip():
                errors.append(f"evidence[{i}].quote 必须是非空字符串")
            if ev["field"] not in ALL_FIELDS:
                errors.append(f"evidence[{i}].field 非法: {ev['field']!r}")

    if not isinstance(item["unjudged_fields"], list) or len(
        {x for x in item["unjudged_fields"]}
    ) != len(item["unjudged_fields"]):
        errors.append("unjudged_fields 必须是无重复的数组")
    else:
        for f in item["unjudged_fields"]:
            if f not in ALL_FIELDS:
                errors.append(f"unjudged_fields 含非法字段: {f!r}")

    return errors


def validate_evidence_traceability(item: dict, original_text: str) -> list[str]:
    """证据逐字比对：quote 必须是原评论的子串（红线）。"""
    errors: list[str] = []
    text = original_text.strip()
    for i, ev in enumerate(item.get("evidence", [])):
        quote = ev.get("quote", "")
        if quote not in text:
            errors.append(
                f"证据不可追溯：evidence[{i}].quote={quote!r} 未在评论 {item.get('review_id')} 原文中逐字出现"
            )
    return errors


def validate_evidence_binding(item: dict) -> list[str]:
    """每个非 null 判断字段至少 1 条证据；refuse=false 的情绪也需证据。"""
    errors: list[str] = []
    if item.get("refuse") is True:
        return errors  # 拒答允许空证据

    bound = {ev["field"] for ev in item.get("evidence", []) if isinstance(ev, dict)}
    for key in JUDGED_FIELDS:
        if item.get(key) is not None and key not in bound:
            errors.append(f"字段 {key} 非 null 但没有对应证据")
    if item.get("sentiment") != "unknown" and "sentiment" not in bound:
        errors.append("sentiment 非 unknown 但没有对应证据")
    return errors


def validate_file(input_csv: Path, outputs_json: Path) -> tuple[int, int, list[str]]:
    reviews = load_reviews(input_csv)
    outputs = json.loads(outputs_json.read_text(encoding="utf-8"))

    problems: list[str] = []
    n_pass = 0

    for idx, item in enumerate(outputs):
        rid = item.get("review_id", f"<index{idx}>")
        errs = validate_schema_item(item)
        if rid in reviews:
            errs += validate_evidence_traceability(item, reviews[rid])
        else:
            errs.append(f"review_id={rid!r} 不存在于输入 CSV")
        errs += validate_evidence_binding(item)

        if errs:
            problems.append(f"[{rid}] 不通过：")
            problems += [f"    - {e}" for e in errs]
        else:
            n_pass += 1

    return n_pass, len(outputs), problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Consumer Insight Skill 输出校验器")
    parser.add_argument("--input", required=True, help="reviews 输入 CSV 路径")
    parser.add_argument("--outputs", required=True, help="待校验的 JSON 输出文件路径")
    args = parser.parse_args()

    n_pass, total, problems = validate_file(Path(args.input), Path(args.outputs))

    print(f"校验完成：{n_pass}/{total} 通过。")
    if problems:
        print("\n".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
