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
from src.consumer_insight_engine import (  # noqa: E402
    PAIN_DIMENSIONS,
    build_insight_report,
    encode_batch,
    filter_valid,
    fmt_ratio,
    load_clean,
    pain_ranking,
    sentiment_distribution,
    brand_sentiment_stats,
    brand_pain_cross,
    run_engine,
    top_evidence,
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
CLEAN_PATH = PROJECT_ROOT / "data" / "processed" / "clean_data.csv"

st.set_page_config(
    page_title="AI Marketing OS",
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


def page_analyzer() -> None:
    """实验1 页面：Marketing Analyzer。"""
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




# ---------------------------------------------------------------------------
# 实验4：消费者洞察引擎
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="正在运行消费者洞察引擎…")
def run_insight(clean_mtime: float, clean_path_str: str) -> dict:
    """按 clean_data.csv 的修改时间缓存引擎结果。"""
    result = run_engine(Path(clean_path_str))
    return {
        "enc": result.enc,
        "stats": result.stats,
        "report": result.report,
        "meta": {k: v for k, v in result.meta.items() if k != "enc_all"},
    }


def _kpi(enc_all: pd.DataFrame, df: pd.DataFrame) -> None:
    total_raw = len(enc_all)
    total_valid = len(df)
    n_refuse = int(enc_all["refuse"].sum())
    n_neg = int(((enc_all["sentiment"] == "negative") & (~enc_all["refuse"])).sum())
    cols = st.columns(4)
    cols[0].metric("原始评论", f"{total_raw}", help="clean_data.csv 全部记录")
    cols[1].metric("有效评论", f"{total_valid}", help="已剔除噪音与品牌型号不一致")
    cols[2].metric("拒答（噪音）", f"{n_refuse}",
                   help=f"{fmt_ratio(n_refuse, total_raw)}")
    cols[3].metric("负面情绪", f"{n_neg}",
                   delta=f"{fmt_ratio(n_neg, total_raw)}", delta_color="off")


def _tab_pain(enc: pd.DataFrame, df: pd.DataFrame) -> None:
    st.subheader("① 痛点排行")
    rk = pain_ranking(enc, df)
    st.caption(
        f"分母 = **{len(df)} 条有效评论**；一条评论若同时抱怨多个维度，"
        "每个维度各计 1 次（多选题口径），因此各维度条数之和大于分母属正常。"
    )
    if rk.empty:
        st.warning("未识别到任何痛点。")
        return

    show = rk[["排名", "痛点维度", "提及条数", "占比", "占提及评论",
               "平均评分", "涉及品牌数"]].copy()
    st.dataframe(show, use_container_width=True, hide_index=True)

    # 条形图
    top = rk.head(8)
    chart_df = top.set_index("痛点维度")["提及条数"]
    st.bar_chart(chart_df.sort_values(ascending=False), height=280)
    st.caption("条形图按提及条数排序，数据与上表一致，可对照复核。")


def _tab_sentiment(enc: pd.DataFrame, df: pd.DataFrame, enc_all: pd.DataFrame) -> None:
    st.subheader("② 情绪分布")
    senti = sentiment_distribution(enc_all, enc_all)
    st.caption(
        f"分母 = **{len(enc_all)} 条全部编码记录**（含拒答）；"
        "五类情绪 + 拒答之和恰好等于分母，不重不漏。"
    )
    c1, c2 = st.columns([1, 1])
    with c1:
        st.dataframe(senti[["情绪", "条数", "占比"]],
                     use_container_width=True, hide_index=True)
    with c2:
        pie_df = senti[~senti["编码值"].isin(["unknown"])].set_index("情绪")["条数"]
        st.bar_chart(pie_df, height=280)
        st.caption("已排除「无法判断」，便于看清主流情绪结构。")


def _tab_brand(enc: pd.DataFrame, df: pd.DataFrame) -> None:
    st.subheader("③ 品牌交叉统计")

    st.markdown("**品牌 × 情绪**")
    bs = brand_sentiment_stats(enc, df)
    st.dataframe(bs, use_container_width=True, hide_index=True)
    st.caption("每格格式为 `n/该品牌评论数（占比）`，分母随品牌变化。")

    st.markdown("**品牌 × 痛点（提及条数）**")
    cross = brand_pain_cross(enc, df)
    st.dataframe(cross, use_container_width=True, hide_index=True)
    st.caption("对角线读数：某品牌某维度提及越多，说明该品牌在此维度越需改进。")

    if not cross.empty:
        dims = [c for c in cross.columns if c not in ("品牌", "评论数", "痛点总数")]
        heat = cross.set_index("品牌")[dims]
        st.markdown("**热力对照（同一维度跨品牌比较）**")
        st.dataframe(
            heat.style.background_gradient(cmap="Reds", axis=None),
            use_container_width=True,
        )
        st.caption("颜色越深 = 该品牌该维度被抱怨越多。")


def _tab_report(report: str) -> None:
    st.subheader("④ 洞察报告（事实 / 推断 / 建议三段分离）")
    st.caption(
        "报告只接收统计表，不接触原始零散文本；"
        "每个数字均可在上方表格中复算。"
    )
    st.markdown(report)
    st.download_button(
        "⬇️ 下载洞察报告（Markdown）",
        data=report.encode("utf-8"),
        file_name="insight_report.md",
        mime="text/markdown",
    )


def _tab_evidence(enc: pd.DataFrame, df: pd.DataFrame) -> None:
    st.subheader("⑤ 证据追溯")
    st.caption(
        "每个核心痛点绑定 ≥3 条原始评论，`review_id` 可回查 "
        "`data/processed/clean_data.csv` 与 `cleaning_log.csv`。"
    )
    rk = pain_ranking(enc, df)
    if rk.empty:
        st.warning("无可用证据。")
        return

    for _, r in rk.iterrows():
        dim = r["痛点维度"]
        evs = top_evidence(enc, df, dim, k=3)
        if not evs:
            continue
        with st.expander(
            f"{r['排名']}. {dim} — {r['提及条数']} 条提及（{r['占比']}）",
            expanded=False,
        ):
            for i, e in enumerate(evs, 1):
                rating = "—" if e["rating"] is None else e["rating"]
                inter = "—" if e["interaction_count"] is None else e["interaction_count"]
                st.markdown(
                    f"**{i}. `{e['review_id']}`**　{e['brand']} · {e['product']}　"
                    f"评分 {rating}｜互动 {inter}"
                )
                st.markdown(f"> 原文：{e['review_text']}")
                st.markdown(f"> 证据片段：**{e['quote']}**")
                if i < len(evs):
                    st.divider()


def page_insight() -> None:
    """实验4 页面：消费者洞察引擎。"""
    st.title("🧠 消费者洞察引擎　`v0.4`")
    st.caption(
        "实验4 · AI + Python ｜ 编码由规则引擎完成，统计由 pandas 完成，"
        "所有占比均标注分母 ｜ 数据源 data/processed/clean_data.csv"
    )

    if not CLEAN_PATH.exists():
        st.error(f"未找到 {CLEAN_PATH.relative_to(PROJECT_ROOT)}，请先运行实验3 的清洗管线。")
        st.code("python3 src/generate_raw_data.py\npython3 src/data_cleaning.py")
        return

    mtime = CLEAN_PATH.stat().st_mtime
    payload = run_insight(mtime, str(CLEAN_PATH))
    enc, df = payload["enc"], filter_valid(load_clean(CLEAN_PATH))
    enc_all = encode_batch(load_clean(CLEAN_PATH))
    stats, report = payload["stats"], payload["report"]

    _kpi(enc_all, df)
    st.divider()

    tabs = st.tabs(["🔥 痛点排行", "😊 情绪分布", "🏷️ 品牌交叉",
                    "📝 洞察报告", "🔍 证据追溯"])
    with tabs[0]:
        _tab_pain(enc, df)
    with tabs[1]:
        _tab_sentiment(enc, df, enc_all)
    with tabs[2]:
        _tab_brand(enc, df)
    with tabs[3]:
        _tab_report(report)
    with tabs[4]:
        _tab_evidence(enc, df)

    st.divider()
    st.caption(
        "数据为**程序合成的模拟数据**，结论仅用于方法演示，"
        "不代表任何真实品牌的市场表现。"
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    st.sidebar.title("AI Marketing OS")
    page = st.sidebar.radio(
        "选择模块",
        ["📊 营销数据分析（实验1）", "🧠 消费者洞察引擎（实验4）"],
        label_visibility="collapsed",
    )
    st.sidebar.caption(f"版本 v{__version__}")

    if page.startswith("📊"):
        page_analyzer()
    else:
        page_insight()


if __name__ == "__main__":
    setup_matplotlib()
    main()
