# -*- coding: utf-8 -*-
"""实验3：公开数据集获取适配器（v0.3 · 通道 B）

================================ 为什么需要这个脚本 ================================
课程实验3 的要求是「模拟生成 **或** 获取」原始数据。只有生成器时，「获取」这一环没有落点，
答辩时容易被问"你的数据到底怎么来的"。

本脚本提供**第二条合规的数据获取通道**：
    从 HuggingFace 公开数据集（datasets-server HTTP API）拉取真实的
    电子产品评论切片，映射到项目统一的 8 字段 schema，落盘为
    data/raw/public_slice.csv，供与模拟数据做对照（或直接作为输入）。

================================ 合规边界（重要）================================
1. **只读公开接口**：使用 HuggingFace 官方 datasets-server API，无需登录、无 token、
   不绕过任何验证码 / 付费墙 / 访问限制。
2. **记录来源与许可**：每次运行都把 dataset id、URL、license、行数写入
   data/raw/public_slice.meta.json，可追溯。
3. **不落库原文全文**（可配置）：默认只保留前 200 字，避免大段版权文本进入仓库。
4. **不推断个人信息**：只取 text / label 两个字段，数据集本身不含用户 ID 等 PII。
5. **失败即降级**：网络不可用 / 数据集变更 / API 限流时，脚本不抛异常中断主流程，
   而是输出明确提示并返回空结果——主线仍以 generate_raw_data.py 为准。

================================ 字段映射 ================================
公开数据集字段           →  本项目字段        说明
text                    →  review_text      评论文本（截断到 MAX_TEXT_LEN）
labels (0/1/2)          →  rating           映射为 3.0 / 4.0 / 5.0（粗粒度，见下）
（数据集无）            →  brand/product    统一标注为 "公开数据集/电子产品评论"，不编造品牌
（数据集无）            →  price             置空（原始数据缺失是真实情况，交 C7 处理）
（数据集无）            →  date              置空（交 C7 处理）
（数据集无）            →  interaction_count 置空（交 C7 处理）
新增                    →  source            标记来源 "public:huggingface"，便于与模拟数据区分

设计原则：**缺失就留空，不编造**。公开数据集没有的字段一律置空，由 C7 规则统一处理，
而不是用随机数填一个"看起来完整"的值——那不叫获取数据，叫伪造数据。

运行：
    python src/fetch_public_data.py                 # 默认拉 100 条
    python src/fetch_public_data.py --limit 200
    python src/fetch_public_data.py --offline-check  # 只检查可达性，不落盘
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "data" / "raw" / "public_slice.csv"
META_OUT = PROJECT_ROOT / "data" / "raw" / "public_slice.meta.json"

# 公开数据集配置（HuggingFace datasets-server，公开只读）
DATASET_ID = "gyoungjr/amazon-electronics-reviews"
DATASET_CONFIG = "default"
DATASET_SPLIT = "train"
DATASET_URL = f"https://huggingface.co/datasets/{DATASET_ID}"
API_BASE = "https://datasets-server.huggingface.co/rows"

# 许可与来源声明（写入 meta.json，随仓库一起留档）
LICENSE_NOTE = (
    "HuggingFace 公开数据集，经 datasets-server 只读 API 访问；"
    "原始数据为 Amazon Electronics 评论的公开研究用抽样。"
    "本项目仅用于课程教学，不进行再分发，且只保留文本片段用于字段映射演示。"
)

MAX_TEXT_LEN = 200       # 单条评论最多保留字符数（避免版权长文本入库）
REQUEST_TIMEOUT = 30     # 单次请求超时（秒）
PAGE_SIZE = 100          # datasets-server 单页上限

# 标签 → 评分映射（该数据集 labels 为 0/1/2 三档情感，非真实星级）
LABEL_TO_RATING = {0: 3.0, 1: 4.0, 2: 5.0}


def _fetch_page(offset: int, length: int) -> list[dict]:
    """拉取一页数据。失败返回空列表并打印原因（不抛异常）。"""
    url = (f"{API_BASE}?dataset={urllib.parse.quote(DATASET_ID, safe='')}"
           f"&config={DATASET_CONFIG}&split={DATASET_SPLIT}"
           f"&offset={offset}&length={min(length, PAGE_SIZE)}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "marketing-os-teamXX/0.3 (course project; read-only)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"  [警告] 拉取失败（offset={offset}）：{type(exc).__name__}: {exc}")
        return []
    except json.JSONDecodeError as exc:
        print(f"  [警告] 响应不是合法 JSON（offset={offset}）：{exc}")
        return []

    rows = payload.get("rows", [])
    return [r.get("row", {}) for r in rows]


def fetch(limit: int = 100) -> list[dict]:
    """分页拉取并映射为项目 schema。"""
    records: list[dict] = []
    offset = 0
    while len(records) < limit:
        need = limit - len(records)
        page = _fetch_page(offset, need)
        if not page:
            break
        for row in page:
            text = str(row.get("text", "") or "").strip()
            if not text:
                continue
            label = row.get("labels")
            rating = LABEL_TO_RATING.get(label) if isinstance(label, int) else None
            records.append({
                "review_id": f"P{len(records) + 1:04d}",
                "brand": "公开数据集",
                "product": "电子产品评论",
                "price": None,            # 数据集无此字段 → 留空，不编造
                "rating": rating,
                "review_text": text[:MAX_TEXT_LEN],
                "date": None,             # 同上
                "interaction_count": None,
                "source": f"public:huggingface/{DATASET_ID}",
            })
            if len(records) >= limit:
                break
        offset += len(page)

    print(f"  实际获取 {len(records)} 条（目标 {limit} 条）")
    return records


def write_csv(records: list[dict], out: Path) -> None:
    """写 CSV（含 source 列，便于与模拟数据区分）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    header = ["review_id", "brand", "product", "price", "rating",
              "review_text", "date", "interaction_count", "source"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(header) + "\n")
        for rec in records:
            cells = []
            for col in header:
                v = rec.get(col)
                if v is None:
                    cells.append("")
                    continue
                s = str(v)
                if "," in s or '"' in s or "\n" in s:
                    s = '"' + s.replace('"', '""') + '"'
                cells.append(s)
            f.write(",".join(cells) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="公开数据集获取适配器（实验3 通道 B）")
    parser.add_argument("--limit", type=int, default=100, help="获取条数（默认 100）")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    parser.add_argument("--offline-check", action="store_true",
                        help="只检查数据源可达性，不落盘")
    args = parser.parse_args()

    print(f"数据源：{DATASET_URL}")
    print(f"用途：课程实验3 数据获取通道（只读公开 API，无需登录）")

    if args.offline_check:
        probe = _fetch_page(0, 1)
        ok = bool(probe)
        print(f"可达性检查：{'✅ 可访问' if ok else '❌ 不可访问（将自动降级为纯模拟通道）'}")
        return 0 if ok else 1

    records = fetch(limit=args.limit)
    if not records:
        print("\n[降级] 公开数据源不可用，本次不落盘。")
        print("       主线不受影响：请使用 `python src/generate_raw_data.py` 生成模拟数据。")
        return 1

    out = Path(args.out)
    write_csv(records, out)

    meta = {
        "dataset_id": DATASET_ID,
        "dataset_url": DATASET_URL,
        "api": API_BASE,
        "config": DATASET_CONFIG,
        "split": DATASET_SPLIT,
        "rows": len(records),
        "fields_mapped": {
            "text": "review_text（截断 %d 字）" % MAX_TEXT_LEN,
            "labels": "rating（0/1/2 → 3.0/4.0/5.0，粗粒度映射）",
            "—": "brand/product 统一标注「公开数据集/电子产品评论」，不编造品牌",
            "—": "price/date/interaction_count 数据集缺失，一律留空，交 C7 处理",
        },
        "license_note": LICENSE_NOTE,
        "compliance": [
            "只访问公开只读 API，无需登录、无 token",
            "不绕过验证码 / 付费墙 / 访问限制",
            "不采集个人信息（数据集仅含 text + label）",
            "只保留文本片段（≤%d 字），不整段转载" % MAX_TEXT_LEN,
        ],
        "note": "本文件为审计留档，随仓库提交；public_slice.csv 为可复现的派生切片。",
    }
    META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n已写入 {len(records)} 条 -> {out}")
    print(f"来源与合规声明 -> {META_OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
