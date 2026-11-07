# -*- coding: utf-8 -*-
"""图表模块（实验1 · v0.1）

只负责把已经算好的聚合表画成图，不做任何计算。
所有图表数据来源均为 brand_summary() 的输出，便于复核。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 无界面后端，兼容服务器环境

import matplotlib.pyplot as plt
import pandas as pd

# 中文字体候选（按优先级），找不到则回退为默认字体并关闭负号告警
_CJK_FONT_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Microsoft YaHei",
    "SimHei",
    "PingFang SC",
    "Heiti SC",
]


def setup_matplotlib() -> str:
    """配置中文字体，返回实际使用的字体名（用于日志与文档）。"""
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((f for f in _CJK_FONT_CANDIDATES if f in available), None)

    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen] + _CJK_FONT_CANDIDATES
    else:
        plt.rcParams["font.sans-serif"] = _CJK_FONT_CANDIDATES

    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    return chosen or "DejaVu Sans (CJK 缺失，中文可能显示为方框)"


def _empty_figure(message: str) -> plt.Figure:
    """生成一张只有提示文字的占位图。"""
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12, color="#666666", wrap=True)
    fig.tight_layout()
    return fig


def plot_avg_price(summary: pd.DataFrame) -> plt.Figure:
    """品牌平均价格柱状图（降序）。"""
    if summary.empty or "avg_price" not in summary.columns:
        return _empty_figure("暂无价格数据可绘图")

    data = summary.dropna(subset=["avg_price"]).sort_values("avg_price", ascending=False)
    if data.empty:
        return _empty_figure("暂无有效价格数据可绘图")

    fig, ax = plt.subplots(figsize=(8, 4.2))
    bars = ax.bar(data["brand"], data["avg_price"], color="#2F6FED", width=0.6)
    ax.set_title("各品牌平均价格（元）", fontsize=13, pad=12)
    ax.set_xlabel("")
    ax.set_ylabel("平均价格（元）")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    for bar, value in zip(bars, data["avg_price"]):
        ax.annotate(
            f"{value:.2f}",
            xy=(bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )

    fig.tight_layout()
    return fig


def plot_avg_rating(summary: pd.DataFrame) -> plt.Figure:
    """品牌平均评分柱状图（降序，纵轴固定 0—5 便于横向比较）。"""
    if summary.empty or "avg_rating" not in summary.columns:
        return _empty_figure("暂无评分数据可绘图")

    data = summary.dropna(subset=["avg_rating"]).sort_values("avg_rating", ascending=False)
    if data.empty:
        return _empty_figure("暂无有效评分数据可绘图")

    fig, ax = plt.subplots(figsize=(8, 4.2))
    bars = ax.bar(data["brand"], data["avg_rating"], color="#12A088", width=0.6)
    ax.set_title("各品牌平均评分（满分 5 分）", fontsize=13, pad=12)
    ax.set_ylabel("平均评分")
    ax.set_ylim(0, 5.2)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")

    for bar, value in zip(bars, data["avg_rating"]):
        ax.annotate(
            f"{value:.2f}",
            xy=(bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )

    fig.tight_layout()
    return fig


def plot_price_vs_rating(summary: pd.DataFrame) -> plt.Figure:
    """均价—评分散点图，气泡大小为产品数。用于快速定位「高价低分」象限。"""
    data = summary.dropna(subset=["avg_price", "avg_rating"])
    if data.empty:
        return _empty_figure("暂无足够数据绘制价格—评分分布")

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    sizes = (data["n_records"] * 60).clip(lower=80)
    ax.scatter(data["avg_price"], data["avg_rating"], s=sizes, color="#F2994A", alpha=0.75, edgecolor="white")

    for _, row in data.iterrows():
        ax.annotate(
            row["brand"],
            xy=(row["avg_price"], row["avg_rating"]),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=9,
        )

    ax.axvline(data["avg_price"].mean(), color="#999999", linestyle=":", linewidth=1)
    ax.axhline(data["avg_rating"].mean(), color="#999999", linestyle=":", linewidth=1)
    ax.set_xlabel("平均价格（元）")
    ax.set_ylabel("平均评分")
    ax.set_title("品牌价格—评分分布（虚线为筛选范围内均值）", fontsize=12, pad=12)
    ax.grid(linestyle="--", alpha=0.3)

    fig.tight_layout()
    return fig
