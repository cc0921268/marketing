# -*- coding: utf-8 -*-
"""Consumer Insight Skill 加载辅助（v0.2）

为 tests 与后续 v0.4 引擎提供统一的样例加载入口。
目录名含连字符（consumer-insight-skill）不能作为包名导入，
因此用文件路径方式加载，保持 Skill 目录结构不被改动。
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / "skills" / "consumer-insight-skill"


def load_examples() -> tuple[dict[str, str], list[dict]]:
    """返回 (reviews: {review_id: text}, outputs: 金标准 JSON 列表)。"""
    import csv

    reviews: dict[str, str] = {}
    with open(SKILL_DIR / "examples" / "reviews_input.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            if rid:
                reviews[rid] = row.get("text") or ""

    outputs = json.loads(
        (SKILL_DIR / "examples" / "expected_outputs.json").read_text(encoding="utf-8")
    )
    return reviews, outputs


def load_schema() -> dict:
    """返回 schema.json 的字典形式。"""
    return json.loads((SKILL_DIR / "schema.json").read_text(encoding="utf-8"))
