# -*- coding: utf-8 -*-
"""营销数据校验与分析核心模块（实验1 · v0.1）

职责边界（与课程规范一致）：
- 本模块只做「程序计算」：字段校验、类型转换、分组聚合、占比与排名。
- 不包含任何大模型调用；所有数值均由 pandas 计算得出，可复算。

设计要点：
1. validate_columns / coerce_numeric / check_missing 分离，保证错误信息可定位。
2. 原始 DataFrame 全程只读，筛选与聚合都返回副本，绝不原地修改。
3. 所有聚合结果附带记录数（n），避免出现没有分母的百分比。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# 常量：字段契约
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS: tuple[str, ...] = ("brand", "price", "rating")
OPTIONAL_COLUMNS: tuple[str, ...] = ("product", "sales")
NUMERIC_COLUMNS: tuple[str, ...] = ("price", "rating", "sales")

COLUMN_LABELS: dict[str, str] = {
    "brand": "品牌",
    "product": "产品",
    "price": "价格",
    "rating": "评分",
    "sales": "销量",
}

# 业务合理区间，用于异常值提示（不删数据，只提示）
VALID_RANGES: dict[str, tuple[float, float]] = {
    "price": (0.0, 100000.0),
    "rating": (0.0, 5.0),
    "sales": (0.0, 1e9),
}


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """字段校验结果。"""

    ok: bool = True
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    """数据质量报告（供页面展示与实验文档引用）。"""

    n_rows: int = 0
    n_cols: int = 0
    missing_by_column: dict[str, int] = field(default_factory=dict)
    duplicate_rows: int = 0
    out_of_range: dict[str, int] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 读取与校验
# ---------------------------------------------------------------------------


def _normalize_column_name(name: str) -> str:
    """列名标准化：去空格、转小写，兼容 'Price' / ' price ' 这类写法。"""
    return str(name).strip().lower()


def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    """从上传的字节流读取 CSV。

    - 自动尝试 utf-8 / utf-8-sig / gbk，兼容 Excel 导出的中文 CSV。
    - 读入后标准化列名并删除完全空白的列，但不修改任何单元格的值。
    """
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            df = pd.read_csv(pd.io.common.BytesIO(raw), encoding=encoding)
            break
        except UnicodeDecodeError as exc:  # 编码不匹配，换下一个
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise ValueError("CSV 文件为空，没有可解析的内容。") from exc
        except pd.errors.ParserError as exc:
            raise ValueError(
                "CSV 解析失败：行内分隔符数量不一致，请检查是否有未闭合的引号或多余逗号。"
            ) from exc
    else:
        raise ValueError(f"CSV 编码无法识别（已尝试 utf-8 / gbk）：{last_error}")

    if df.empty:
        raise ValueError("CSV 只有表头没有数据行，无法进行品牌分析。")

    df = df.rename(columns={c: _normalize_column_name(c) for c in df.columns})
    df = df.dropna(axis=1, how="all")
    return df


def validate_columns(df: pd.DataFrame, required: Iterable[str] = REQUIRED_COLUMNS) -> ValidationResult:
    """校验必要字段是否齐全，并给出可读的中文提示。"""
    required = list(required)
    present = list(df.columns)
    missing = [c for c in required if c not in present]
    extra = [c for c in present if c not in set(required) | set(OPTIONAL_COLUMNS)]

    result = ValidationResult(ok=not missing, missing_columns=missing, extra_columns=extra)

    if missing:
        readable = "、".join(f"{c}（{COLUMN_LABELS.get(c, c)}）" for c in missing)
        result.messages.append(f"缺少必要字段：{readable}。")
        result.messages.append(f"当前文件实际包含字段：{'、'.join(present) if present else '（无）'}。")
        result.messages.append(
            "请在 CSV 表头中补齐上述字段后重新上传；字段名不区分大小写与首尾空格。"
        )
    else:
        result.messages.append("必要字段校验通过：brand、price、rating 均存在。")

    if extra:
        result.messages.append(
            f"检测到未定义字段：{'、'.join(extra)}。这些字段会被保留但不参与计算。"
        )

    return result


def coerce_numeric(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """将数值字段转为数值型（不修改入参）。

    处理常见脏数据：'￥32.00'、'1,200'、'4.5分'、全角空格等。
    返回 (新DataFrame, {列名: 转换失败条数})。
    """
    out = df.copy()
    failed: dict[str, int] = {}

    for col in NUMERIC_COLUMNS:
        if col not in out.columns:
            continue
        original_non_null = out[col].notna().sum()
        series = out[col]
        if series.dtype == object:
            series = (
                series.astype("string")
                .str.replace(r"[,\s￥¥$元分]", "", regex=True)
                .str.strip()
            )
        converted = pd.to_numeric(series, errors="coerce")
        # 原本非空、转换后变空 => 该条转换失败
        failed[col] = int(original_non_null - converted.notna().sum())
        out[col] = converted

    return out, failed


def check_missing(df: pd.DataFrame) -> dict[str, int]:
    """统计必要字段的空值数量。"""
    return {c: int(df[c].isna().sum()) for c in REQUIRED_COLUMNS if c in df.columns}


def quality_report(df: pd.DataFrame) -> QualityReport:
    """生成数据质量报告：空值、重复行、越界值。"""
    report = QualityReport(n_rows=int(df.shape[0]), n_cols=int(df.shape[1]))
    report.missing_by_column = {c: int(df[c].isna().sum()) for c in df.columns}
    report.duplicate_rows = int(df.duplicated().sum())

    for col, (low, high) in VALID_RANGES.items():
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        mask = s.notna() & ((s < low) | (s > high))
        if int(mask.sum()) > 0:
            report.out_of_range[col] = int(mask.sum())

    total_missing = sum(report.missing_by_column.get(c, 0) for c in REQUIRED_COLUMNS)
    if total_missing:
        report.messages.append(
            f"必要字段存在 {total_missing} 个空值，对应记录将不参与该字段的平均值计算"
            "（pandas 默认 skipna），但仍在原始数据中保留。"
        )
    if report.duplicate_rows:
        report.messages.append(f"检测到 {report.duplicate_rows} 行完全重复记录，建议在实验3清洗阶段处理。")
    if report.out_of_range:
        detail = "、".join(
            f"{COLUMN_LABELS.get(k, k)} {v} 条" for k, v in report.out_of_range.items()
        )
        report.messages.append(f"存在超出业务合理区间的值：{detail}（仅提示，不自动删除）。")

    return report


# ---------------------------------------------------------------------------
# 筛选（只读，不修改原始数据）
# ---------------------------------------------------------------------------


def list_brands(df: pd.DataFrame) -> list[str]:
    """返回去重后的品牌列表（按字母序，空值剔除）。"""
    if "brand" not in df.columns:
        return []
    brands = df["brand"].dropna().astype(str).str.strip()
    return sorted(b for b in brands.unique() if b)


def filter_by_brand(df: pd.DataFrame, brands: Iterable[str]) -> pd.DataFrame:
    """按品牌筛选，返回副本。传空列表视为不筛选。"""
    selected = [b for b in brands if b]
    if not selected:
        return df.copy()
    brand_series = df["brand"].astype(str).str.strip()
    return df.loc[brand_series.isin(selected)].copy()


# ---------------------------------------------------------------------------
# 聚合计算（唯一允许产生"平均值/占比/排名"的地方）
# ---------------------------------------------------------------------------


def brand_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按品牌计算平均价格、平均评分、记录数与销量合计。

    说明：
    - 均值用 pandas mean()（默认 skipna），并同时输出各指标的样本量 n_*，
      保证任何平均值都能找到分母。
    - 排序按 avg_price 降序，排名 rank_price / rank_rating 为并列最小排名法。
    """
    result_cols = [
        "brand",
        "n_records",
        "avg_price",
        "avg_rating",
        "n_price",
        "n_rating",
        "total_sales",
        "sales_share",
        "rank_price",
        "rank_rating",
    ]
    if "brand" not in df.columns:
        return pd.DataFrame(columns=result_cols)

    work = df.copy()
    work["brand"] = work["brand"].astype(str).str.strip()
    work = work[work["brand"].ne("") & work["brand"].ne("nan")]

    for col in ("price", "rating", "sales"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    has_sales = "sales" in work.columns

    grouped = work.groupby("brand", dropna=False)
    if has_sales:
        summary = grouped.agg(
            n_records=("brand", "size"),
            avg_price=("price", "mean"),
            avg_rating=("rating", "mean"),
            n_price=("price", "count"),
            n_rating=("rating", "count"),
            total_sales=("sales", "sum"),
        ).reset_index()
    else:
        summary = grouped.agg(
            n_records=("brand", "size"),
            avg_price=("price", "mean"),
            avg_rating=("rating", "mean"),
            n_price=("price", "count"),
            n_rating=("rating", "count"),
        ).reset_index()

    # 四舍五入放在展示层用 round 控制，这里保留原始精度，避免二次舍入误差
    if has_sales:
        grand_sales = float(summary["total_sales"].sum())
        summary["sales_share"] = (
            (summary["total_sales"] / grand_sales * 100).round(2) if grand_sales else 0.0
        )
    else:
        # 无 sales 字段时该列留空，保证列契约稳定（下游 v0.2+ 可直接按列名取值）
        summary["total_sales"] = pd.NA
        summary["sales_share"] = pd.NA
    summary["rank_price"] = summary["avg_price"].rank(ascending=False, method="min").astype("Int64")
    summary["rank_rating"] = summary["avg_rating"].rank(ascending=False, method="min").astype("Int64")

    summary = summary.sort_values(
        by=["avg_price", "brand"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)

    return summary[result_cols]


def overall_metrics(df: pd.DataFrame) -> dict[str, float | int | None]:
    """整体概览指标（用于顶部 KPI 卡片）。"""
    price = pd.to_numeric(df.get("price"), errors="coerce") if "price" in df.columns else None
    rating = pd.to_numeric(df.get("rating"), errors="coerce") if "rating" in df.columns else None
    sales = pd.to_numeric(df.get("sales"), errors="coerce") if "sales" in df.columns else None

    return {
        "n_records": int(df.shape[0]),
        "n_brands": int(df["brand"].dropna().nunique()) if "brand" in df.columns else 0,
        "avg_price": round(float(price.mean()), 2) if price is not None and price.notna().any() else None,
        "avg_rating": round(float(rating.mean()), 2) if rating is not None and rating.notna().any() else None,
        "total_sales": float(sales.sum()) if sales is not None and sales.notna().any() else None,
    }


def format_summary_for_display(summary: pd.DataFrame) -> pd.DataFrame:
    """生成用于页面展示的表格副本（两位小数、中文列名）。不修改入参。"""
    display = summary.copy()
    rename = {
        "brand": "品牌",
        "n_records": "产品数",
        "avg_price": "平均价格",
        "avg_rating": "平均评分",
        "n_price": "价格样本量",
        "n_rating": "评分样本量",
        "total_sales": "销量合计",
        "sales_share": "销量占比(%)",
        "rank_price": "价格排名",
        "rank_rating": "评分排名",
    }
    if "avg_price" in display.columns:
        display["avg_price"] = display["avg_price"].round(2)
    if "avg_rating" in display.columns:
        display["avg_rating"] = display["avg_rating"].round(2)
    if "total_sales" in display.columns:
        display["total_sales"] = display["total_sales"].round(0)
    return display.rename(columns=rename)
