# -*- coding: utf-8 -*-
"""实验1 单元测试（v0.1）

覆盖：
1. 正常数据：字段校验、均值计算、两位小数、品牌筛选不改原表
2. 缺字段数据：给出缺失字段列表与提示
3. 空值数据：均值跳过空值，样本量正确
4. 脏数据：货币符号、千分位分隔符可解析
5. 汇总表口径：占比合计 100%、排名并列规则

运行：
    python -m pytest tests/ -v
    # 或（无 pytest 时）
    python tests/test_data_utils.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_utils import (  # noqa: E402
    REQUIRED_COLUMNS,
    brand_summary,
    check_missing,
    coerce_numeric,
    filter_by_brand,
    format_summary_for_display,
    list_brands,
    overall_metrics,
    quality_report,
    read_csv_bytes,
    validate_columns,
)

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"
NORMAL_CSV = SAMPLE_DIR / "marketing_data.csv"
MISSING_CSV = SAMPLE_DIR / "marketing_data_missing_rating.csv"
NULL_CSV = SAMPLE_DIR / "marketing_data_with_nulls.csv"


def _read(path: Path) -> pd.DataFrame:
    return read_csv_bytes(path.read_bytes())


# ---------------------------------------------------------------------------
# 1. 正常数据
# ---------------------------------------------------------------------------


def test_normal_csv_row_count_is_15():
    df = _read(NORMAL_CSV)
    assert len(df) == 15, f"示例数据应为 15 条，实际 {len(df)}"


def test_required_columns_exist():
    df = _read(NORMAL_CSV)
    result = validate_columns(df)
    assert result.ok is True
    assert result.missing_columns == []


def test_avg_price_matches_manual_calculation():
    """手算校验：Starbucks 三条记录均价 = (32 + 36 + 30) / 3 = 32.67。"""
    df = _read(NORMAL_CSV)
    summary = brand_summary(df).set_index("brand")

    assert round(summary.loc["Starbucks", "avg_price"], 2) == 32.67
    assert summary.loc["Starbucks", "n_price"] == 3

    # Manner = (15 + 22 + 28) / 3 = 21.67
    assert round(summary.loc["Manner Coffee", "avg_price"], 2) == 21.67
    # Luckin = (19.9 + 16 + 21) / 3 = 18.97
    assert round(summary.loc["Luckin Coffee", "avg_price"], 2) == 18.97


def test_avg_rating_matches_manual_calculation():
    """手算校验：Starbucks 均分 = (4.5 + 4.3 + 4.1) / 3 = 4.30。"""
    df = _read(NORMAL_CSV)
    summary = brand_summary(df).set_index("brand")
    assert round(summary.loc["Starbucks", "avg_rating"], 2) == 4.30
    assert summary.loc["Cotti Coffee", "n_rating"] == 2


def test_sales_share_sums_to_100_percent():
    df = _read(NORMAL_CSV)
    summary = brand_summary(df)
    total = summary["sales_share"].sum()
    assert abs(total - 100.0) < 0.05, f"销量占比合计应约为 100%，实际 {total}"


def test_filter_does_not_mutate_original():
    df = _read(NORMAL_CSV)
    before_shape = df.shape
    before_brands = sorted(df["brand"].unique())

    filtered = filter_by_brand(df, ["Starbucks"])

    assert df.shape == before_shape, "筛选后原始 DataFrame 行数发生变化"
    assert sorted(df["brand"].unique()) == before_brands, "筛选后原始品牌集合发生变化"
    assert set(filtered["brand"].unique()) == {"Starbucks"}
    assert filtered is not df


def test_empty_filter_returns_full_copy():
    df = _read(NORMAL_CSV)
    filtered = filter_by_brand(df, [])
    assert len(filtered) == len(df)
    assert filtered is not df


def test_display_rounds_to_two_decimals():
    df = _read(NORMAL_CSV)
    display = format_summary_for_display(brand_summary(df))
    for value in display["平均价格"].dropna():
        assert round(float(value), 2) == float(value)
    assert "品牌" in display.columns


# ---------------------------------------------------------------------------
# 2. 缺字段数据
# ---------------------------------------------------------------------------


def test_missing_rating_column_detected():
    df = _read(MISSING_CSV)
    result = validate_columns(df)
    assert result.ok is False
    assert result.missing_columns == ["rating"]
    assert any("缺少必要字段" in m for m in result.messages)
    assert any("评分" in m for m in result.messages), "错误提示应包含中文字段名，便于非技术同学理解"


def test_missing_brand_and_price_detected():
    df = pd.DataFrame({"product": ["A"], "rating": [4.5]})
    result = validate_columns(df)
    assert result.ok is False
    assert set(result.missing_columns) == {"brand", "price"}


def test_column_name_case_and_space_insensitive():
    raw = "Brand , Price , Rating\nA, 10, 4.0\n".encode("utf-8")
    df = read_csv_bytes(raw)
    assert validate_columns(df).ok is True


# ---------------------------------------------------------------------------
# 3. 空值数据
# ---------------------------------------------------------------------------


def test_null_csv_missing_counts():
    df = _read(NULL_CSV)
    counts = check_missing(df)
    assert counts["price"] == 4
    assert counts["rating"] == 3


def test_null_values_are_skipped_not_dropped():
    df = _read(NULL_CSV)
    summary = brand_summary(df).set_index("brand")

    # Starbucks 价格：32, NaN, 30 -> 均值 31.0，样本量 2
    assert round(summary.loc["Starbucks", "avg_price"], 2) == 31.00
    assert summary.loc["Starbucks", "n_price"] == 2
    # Starbucks 评分：4.5, 4.3, NaN -> 4.40
    assert round(summary.loc["Starbucks", "avg_rating"], 2) == 4.40

    # 原始记录数不变
    assert len(df) == 12
    assert summary["n_records"].sum() == 12


def test_quality_report_flags_nulls():
    df = _read(NULL_CSV)
    report = quality_report(df)
    assert report.n_rows == 12
    assert "price" in report.out_of_range or report.out_of_range.get("rating", 0) == 0
    assert any("空值" in m for m in report.messages)


# ---------------------------------------------------------------------------
# 4. 脏数据解析
# ---------------------------------------------------------------------------


def test_currency_and_thousand_separator_parsed():
    df = pd.DataFrame({"brand": ["A"] * 3, "price": ["￥32.00", "1,200", "4.5分"], "rating": [4, 4, 4]})
    cleaned, failed = coerce_numeric(df)
    assert failed["price"] == 0
    assert list(cleaned["price"]) == [32.0, 1200.0, 4.5]


def test_unparseable_values_counted_as_failed():
    df = pd.DataFrame({"brand": ["A", "A"], "price": ["约三十元", "20"], "rating": [4, 4]})
    _, failed = coerce_numeric(df)
    assert failed["price"] == 1


# ---------------------------------------------------------------------------
# 5. 汇总表口径
# ---------------------------------------------------------------------------


def test_overall_metrics_keys():
    df = _read(NORMAL_CSV)
    metrics = overall_metrics(df)
    assert metrics["n_records"] == 15
    assert metrics["n_brands"] == 6
    assert metrics["avg_price"] is not None


def test_brand_list_sorted_and_clean():
    df = _read(NORMAL_CSV)
    brands = list_brands(df)
    assert brands == sorted(brands)
    assert all(b.strip() == b for b in brands)


def test_rank_method_min_for_ties():
    df = pd.DataFrame(
        {
            "brand": ["A", "B", "C"],
            "price": [10, 10, 20],
            "rating": [4.0, 4.0, 4.0],
        }
    )
    summary = brand_summary(df).set_index("brand")
    # C 最贵 rank=1，A/B 并列 rank=2
    assert summary.loc["C", "rank_price"] == 1
    assert summary.loc["A", "rank_price"] == 2
    assert summary.loc["B", "rank_price"] == 2
    # 评分全部并列第一
    assert set(summary["rank_rating"]) == {1}


def test_required_columns_constant():
    assert REQUIRED_COLUMNS == ("brand", "price", "rating")


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
            failed.append((name, str(exc)))
            print(f"[FAIL] {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[PASS] {name}")
    print(f"\n合计 {len(tests)} 项，通过 {passed} 项，失败 {len(failed)} 项。")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
