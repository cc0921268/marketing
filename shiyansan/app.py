# -*- coding: utf-8 -*-
"""AI Marketing OS · Marketing Analyzer (v0.1)

实验1：Codex 协作开发与 Debug
- 本地运行的 Streamlit 营销数据分析小工具
- 不调用任何大模型 API，所有数值均由 pandas 计算

启动方式：
    streamlit run app.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# 允许直接 `streamlit run app.py` 时导入 src 包
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import __version__  # noqa: E402
from src.charts import (  # noqa: E402
    plot_avg_price,
    plot_avg_rating,
    plot_price_vs_rating,
    setup_matplotlib,
)
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
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DEFAULT_SAMPLE = SAMPLE_DIR / "marketing_data.csv"

st.set_page_config(
    page_title="Marketing Analyzer v0.1",
    page_icon="📊",
    layout="wide",
)


# ---------------------------------------------------------------------------
# 缓存与工具
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def load_sample(path_str: str) -> tuple[pd.DataFrame, bytes]:
    """读取仓库内示例数据，返回 (DataFrame, 原始字节)。"""
    raw = Path(path_str).read_bytes()
    return read_csv_bytes(raw), raw


@st.cache_data(show_spinner=False)
def compute_summary(df: pd.DataFrame) -> pd.DataFrame:
    """聚合结果按数据内容缓存，避免每次交互重算。"""
    return brand_summary(df)


def fig_to_png_bytes(fig: plt.Figure) -> bytes:
    """图表导出为 PNG 字节流，供下载按钮使用。"""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", dpi=150)
    return buffer.getvalue()


def render_error_block(title: str, messages: list[str], expander_label: str = "查看排查步骤") -> None:
    """统一的友好错误提示。"""
    st.error(f"**{title}**")
    for msg in messages:
        st.write(f"- {msg}")
    with st.expander(expander_label, expanded=False):
        st.markdown(
            """
1. 下载 `data/sample/marketing_data.csv` 作为模板，确认表头为
   `brand,product,price,rating,sales`。
2. 字段名不区分大小写，但不要写成 `品牌`、`price(元)` 这类带修饰的名字。
3. 数值列不要混入单位符号以外的文字（`￥32.00`、`1,200` 会被自动清洗，
   `约三十元` 会被判为缺失）。
4. 若用 Excel 另存为 CSV，请选择「CSV UTF-8（逗号分隔）」。
"""
        )


# ---------------------------------------------------------------------------
# 侧边栏：数据来源
# ---------------------------------------------------------------------------


def sidebar_data_source() -> tuple[pd.DataFrame | None, str, bytes | None]:
    st.sidebar.header("① 数据来源")

    source_mode = st.sidebar.radio(
        "选择数据方式",
        options=["使用仓库示例数据", "上传本地 CSV"],
        index=0,
        help="示例数据位于 data/sample/marketing_data.csv，共 15 条记录。",
    )

    df: pd.DataFrame | None = None
    source_label = ""
    raw_bytes: bytes | None = None

    if source_mode == "使用仓库示例数据":
        sample_files = sorted(p.name for p in SAMPLE_DIR.glob("*.csv")) if SAMPLE_DIR.exists() else []
        if not sample_files:
            st.sidebar.error("未找到 data/sample 下的示例文件。")
            return None, "", None

        chosen = st.sidebar.selectbox(
            "示例文件",
            options=sample_files,
            index=sample_files.index(DEFAULT_SAMPLE.name) if DEFAULT_SAMPLE.name in sample_files else 0,
        )
        try:
            df, raw_bytes = load_sample(str(SAMPLE_DIR / chosen))
            source_label = f"示例数据 · {chosen}"
        except (ValueError, OSError) as exc:
            st.sidebar.error(f"示例文件读取失败：{exc}")
            return None, "", None
    else:
        uploaded = st.sidebar.file_uploader(
            "上传营销数据 CSV",
            type=["csv"],
            help="必须包含 brand、price、rating 三个字段。",
        )
        if uploaded is None:
            st.sidebar.info("请在下方上传 CSV 文件，或切换回示例数据。")
            return None, "", None
        try:
            raw_bytes = uploaded.getvalue()
            df = read_csv_bytes(raw_bytes)
            source_label = f"上传文件 · {uploaded.name}"
        except ValueError as exc:
            render_error_block("文件读取失败", [str(exc)])
            return None, "", None

    return df, source_label, raw_bytes


# ---------------------------------------------------------------------------
# 页面区块
# ---------------------------------------------------------------------------


def section_kpi(metrics: dict) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("记录数", f"{metrics['n_records']:,}")
    c2.metric("品牌数", f"{metrics['n_brands']}")
    c3.metric("整体均价", "—" if metrics["avg_price"] is None else f"¥{metrics['avg_price']:.2f}")
    c4.metric("整体均分", "—" if metrics["avg_rating"] is None else f"{metrics['avg_rating']:.2f} / 5")
    c5.metric(
        "销量合计",
        "—" if metrics["total_sales"] is None else f"{metrics['total_sales']:,.0f}",
    )


def section_quality(df: pd.DataFrame) -> None:
    report = quality_report(df)
    missing_map = check_missing(df)

    with st.expander("② 数据质量体检（只提示，不修改原始数据）", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.write(f"**行数 / 列数**：{report.n_rows} / {report.n_cols}")
        c2.write(f"**完全重复行**：{report.duplicate_rows}")
        total_missing = sum(missing_map.values())
        c3.write(f"**必要字段空值合计**：{total_missing}")

        detail = pd.DataFrame(
            {"字段": list(report.missing_by_column.keys()),
             "空值数": list(report.missing_by_column.values())}
        )
        st.dataframe(detail, hide_index=True, use_container_width=True)

        if report.messages:
            for msg in report.messages:
                st.warning(msg, icon="⚠️")
        else:
            st.success("未发现空值、重复行或越界值。", icon="✅")


def section_filter(df: pd.DataFrame) -> list[str]:
    st.sidebar.header("③ 品牌筛选")
    brands = list_brands(df)
    if not brands:
        st.sidebar.warning("数据中未找到有效品牌名称。")
        return []

    select_all = st.sidebar.checkbox("全选品牌", value=True)
    selected = st.sidebar.multiselect(
        "选择要对比的品牌",
        options=brands,
        default=brands if select_all else brands[:1],
        help="多选可做品牌间对比；清空则视为不筛选（显示全部）。",
    )
    return selected


def section_charts(summary: pd.DataFrame, subset_label: str) -> None:
    st.subheader("④ 品牌维度图表")
    st.caption(f"当前范围：{subset_label}；图表数据来自同一张聚合表，可与下方表格逐项核对。")

    left, right = st.columns(2)
    with left:
        fig_price = plot_avg_price(summary)
        st.pyplot(fig_price, use_container_width=True)
        st.download_button(
            "下载均价图 PNG",
            data=fig_to_png_bytes(fig_price),
            file_name="avg_price_by_brand.png",
            mime="image/png",
            key="dl_price",
        )
        plt.close(fig_price)

    with right:
        fig_rating = plot_avg_rating(summary)
        st.pyplot(fig_rating, use_container_width=True)
        st.download_button(
            "下载评分图 PNG",
            data=fig_to_png_bytes(fig_rating),
            file_name="avg_rating_by_brand.png",
            mime="image/png",
            key="dl_rating",
        )
        plt.close(fig_rating)

    with st.expander("进阶视图：价格—评分象限分布", expanded=False):
        fig_scatter = plot_price_vs_rating(summary)
        st.pyplot(fig_scatter, use_container_width=True)
        plt.close(fig_scatter)


def section_table(summary: pd.DataFrame) -> None:
    st.subheader("⑤ 品牌汇总表（Python 计算，可复算）")
    if summary.empty:
        st.info("当前筛选范围内没有可汇总的数据。")
        return

    display = format_summary_for_display(summary)
    st.dataframe(display, hide_index=True, use_container_width=True)

    st.download_button(
        "下载汇总表 CSV",
        data=summary.to_csv(index=False).encode("utf-8-sig"),
        file_name="brand_summary.csv",
        mime="text/csv",
    )

    with st.expander("查看计算口径", expanded=False):
        st.markdown(
            """
| 指标 | 计算方式 |
| --- | --- |
| 平均价格 | `groupby('brand')['price'].mean()`，跳过空值，展示时保留两位小数 |
| 平均评分 | `groupby('brand')['rating'].mean()`，跳过空值，展示时保留两位小数 |
| 价格样本量 / 评分样本量 | `count()`，即该平均值的分母 |
| 销量合计 | `sum()`（仅在存在 `sales` 字段时计算） |
| 销量占比 | 该品牌销量 ÷ 当前范围销量合计 × 100，保留两位小数 |
| 价格排名 / 评分排名 | `rank(ascending=False, method='min')`，并列取最小名次 |

数据为空值时不参与该项均值计算，但原始记录不会被删除。
"""
        )


def section_raw_data(df: pd.DataFrame, filtered: pd.DataFrame) -> None:
    with st.expander("⑥ 原始数据只读预览（筛选不修改原始 DataFrame）", expanded=False):
        st.caption(f"原始行数：{len(df)}　当前筛选后行数：{len(filtered)}")
        tab_raw, tab_filtered = st.tabs(["原始数据", "筛选结果"])
        with tab_raw:
            st.dataframe(df, use_container_width=True, height=320)
        with tab_filtered:
            st.dataframe(filtered, use_container_width=True, height=320)


def section_debug(df: pd.DataFrame) -> None:
    with st.expander("⑦ Debug 面板（验收时用于核对）", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.write("**字段校验结果**")
            result = validate_columns(df)
            st.write({"ok": result.ok, "missing": result.missing_columns, "extra": result.extra_columns})
            for msg in result.messages:
                st.caption(f"· {msg}")
        with c2:
            st.write("**数值类型转换**")
            _, failed = coerce_numeric(df)
            st.write(failed)
            st.caption("转换失败条数 = 原本非空但无法解析为数值的单元格数量。")

        st.write("**DataFrame 完整性自检**")
        before_rows = st.session_state.get("raw_row_count", len(df))
        st.write({"raw_rows": before_rows, "current_rows": len(df),
                  "columns": list(df.columns)})


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> None:
    st.title("📊 Marketing Analyzer　`v0.1`")
    st.caption(
        "实验1 · Codex 协作开发与 Debug ｜ 本地运行 · 不调用大模型 API ｜ "
        "所有均值、占比、排名均由 Python（pandas）计算"
    )

    df, source_label, raw_bytes = sidebar_data_source()

    if df is None:
        st.info(
            "👈 请在左侧选择数据来源。首次使用建议直接使用仓库示例数据 "
            "`data/sample/marketing_data.csv`（15 条记录）。",
            icon="💡",
        )
        with st.expander("支持的 CSV 字段说明", expanded=True):
            st.markdown(
                """
| 字段 | 是否必需 | 类型 | 说明 |
| --- | --- | --- | --- |
| `brand` | ✅ 必需 | 文本 | 品牌名称，用于分组 |
| `price` | ✅ 必需 | 数值 | 单价，单位元 |
| `rating` | ✅ 必需 | 数值 | 评分，0—5 |
| `product` | ⭕ 可选 | 文本 | 产品名称 |
| `sales` | ⭕ 可选 | 数值 | 销量，用于销量合计与占比 |
"""
            )
        return

    # 1) 字段校验
    validation = validate_columns(df)
    if not validation.ok:
        render_error_block(
            "必要字段缺失，无法继续分析",
            validation.messages,
        )
        with st.expander("当前文件实际字段（前 5 行预览）", expanded=True):
            st.dataframe(df.head(), use_container_width=True)
        st.stop()

    # 2) 数值转换
    df_numeric, failed = coerce_numeric(df)
    if failed:
        bad = {k: v for k, v in failed.items() if v}
        if bad:
            st.warning(
                f"以下字段存在无法解析为数值的单元格（已按缺失处理）：{bad}。"
                "这些单元格不参与均值计算。",
                icon="⚠️",
            )

    st.session_state.setdefault("raw_row_count", len(df_numeric))

    # 3) 概览
    st.success(f"数据加载成功：{source_label}", icon="✅")
    st.subheader("① 整体概览")
    section_kpi(overall_metrics(df_numeric))

    # 4) 质量体检
    section_quality(df_numeric)

    # 5) 筛选（返回副本）
    selected_brands = section_filter(df_numeric)
    filtered = filter_by_brand(df_numeric, selected_brands)

    subset_label = "全部品牌" if not selected_brands else f"{len(selected_brands)} 个品牌：" + "、".join(selected_brands)
    st.caption(f"筛选范围 → {subset_label}｜记录数 {len(filtered)} / {len(df_numeric)}")

    if filtered.empty:
        st.warning("筛选结果为空，请至少勾选一个品牌。")
        st.stop()

    # 6) 聚合 + 图表
    summary = compute_summary(filtered)
    section_charts(summary, subset_label)

    # 7) 表格
    section_table(summary)

    # 8) 原始数据
    section_raw_data(df_numeric, filtered)

    # 9) Debug
    section_debug(df_numeric)

    # 10) 导出
    st.divider()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("导出本次结果到 outputs/", type="primary"):
            ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            summary_path = OUTPUT_DIR / f"brand_summary_{ts}.csv"
            summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
            if raw_bytes is not None:
                (OUTPUT_DIR / f"input_snapshot_{ts}.csv").write_bytes(raw_bytes)
            st.success(f"已保存：{summary_path.name}")
    with col_b:
        st.caption("导出文件包含聚合结果与本次输入的原始快照，便于实验文档中的结果复现。")

    st.divider()
    st.caption(
        f"AI Marketing OS · v{__version__} · 实验1（第1—2周）｜"
        " 计算全部由 pandas 完成，本工具不含任何大模型调用。"
    )


if __name__ == "__main__":
    setup_matplotlib()
    main()
