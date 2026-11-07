# -*- coding: utf-8 -*-
"""实验3：原始营销数据模拟生成器（v0.3 · 蓝牙耳机品类）

场景：蓝牙耳机（TWS 真无线 + 头戴式）消费者评论。

设计目标：生成 300 条「具有真实噪声」的原始数据。噪声类型对齐真实电商平台
（京东 / 天猫 / 拼多多）评论导出文件中的典型脏数据，供 data_cleaning.py 的
C1—C10 清洗规则逐条消除。

================================ 噪声清单（10 类） ================================
N1  品牌别名混用       Apple AirPods / airpods / 苹果耳机 指同一品牌
N2  价格脏格式         '￥499'、'1,299.00'、'699元'、'19,90'（欧式小数）、纯数字
N3  价格录入异常       约 2% 记录价格放大 10 倍（人工录入多打一个 0）
N4  日期多格式         2024-06-01 / 2024/6/1 / 20240601 / 2024年6月1日 / 缺年份 6/1
N5  字段缺失           price / rating / interaction_count 随机缺失
N6  整行完全重复       约 3% 概率整行重复（导出时重复执行）
N7  review_id 重复     约 1% 概率 ID 重复但内容不同（用户二次提交）
N8  无效评论           纯符号 / 纯数字 / 广告引流 / 无关闲聊 / 极短无信息
N9  文字形态脏数据     繁体字混用（「續航」「連線」）、异体字（「藍牙」）、emoji、全角标点
N10 逻辑矛盾数据       rating 超出 1—5 范围（8.7 实为 10 分制）、日期落在未来、
                      product 与 brand 张冠李戴（AirPods Pro 2 挂在华为名下）

合规声明：全部数据由程序随机合成，不含任何真实个人信息、不含真实用户言论。
可复现：固定 random.seed(42)，同 seed 重跑生成的文件逐字节一致。

用法：
    python src/generate_raw_data.py                  # 默认 300 条，seed=42
    python src/generate_raw_data.py --n 300 --seed 42
    python src/generate_raw_data.py --out data/raw/raw_data.csv
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "data" / "raw" / "raw_data.csv"

SEED = 42
N_DEFAULT = 300

# ---------------------------------------------------------------------------
# 品牌池：规范名 → 别名列表（N1 噪声源）
# 别名覆盖：英文大小写、英文简称、中文全称、渠道俗称
# ---------------------------------------------------------------------------
BRAND_ALIASES: dict[str, list[str]] = {
    "Apple": ["Apple", "AirPods", "airpods", "苹果耳机", "Apple AirPods", "APPLE"],
    "华为": ["华为", "Huawei", "HUAWEI", "FreeBuds", "华为耳机", "華為"],
    "小米": ["小米", "Xiaomi", "XIAOMI", "MI", "Redmi", "红米耳机"],
    "漫步者": ["漫步者", "Edifier", "edifier", "EDIFIER", "漫步者耳机"],
    "OPPO": ["OPPO", "oppo", "Enco", "OPPO耳机", "欧珀"],
    "索尼": ["索尼", "Sony", "SONY", "sony", "索尼耳机", "新力"],
}

# 各品牌抽样权重（模拟声量份额，仅用于造数据，非真实市场份额）
BRAND_WEIGHTS: dict[str, float] = {
    "Apple": 0.20, "华为": 0.22, "小米": 0.24,
    "漫步者": 0.16, "OPPO": 0.12, "索尼": 0.06,
}

# ---------------------------------------------------------------------------
# 产品池：规范品牌 → [(型号, 价格下限, 价格上限), ...]
# 覆盖入门 TWS 到旗舰头戴，价格跨度 99—2399 元
# ---------------------------------------------------------------------------
PRODUCTS: dict[str, list[tuple[str, float, float]]] = {
    "Apple": [
        ("AirPods 4", 999, 1399),
        ("AirPods Pro 2", 1499, 1899),
        ("AirPods 3", 999, 1299),
    ],
    "华为": [
        ("FreeBuds Pro 3", 1099, 1499),
        ("FreeBuds 6i", 499, 699),
        ("FreeBuds SE 3", 199, 299),
        ("FreeBuds Lipstick", 1299, 1699),
    ],
    "小米": [
        ("Xiaomi Buds 5", 599, 799),
        ("Redmi Buds 6", 149, 229),
        ("Xiaomi Buds 4 Pro", 799, 999),
        ("Redmi Buds 6 Pro", 279, 399),
    ],
    "漫步者": [
        ("LolliPods Pro", 199, 299),
        ("NeoBuds Pro 2", 699, 999),
        ("W820NB 头戴", 299, 449),
        ("声迈 X5", 99, 159),
    ],
    "OPPO": [
        ("Enco X3", 899, 1199),
        ("Enco Air4", 199, 299),
        ("Enco Air4 Pro", 399, 499),
        ("Enco Free4", 599, 799),
    ],
    "索尼": [
        ("WF-1000XM5", 1899, 2399),
        ("WF-C700N", 699, 899),
        ("LinkBuds S", 899, 1199),
        ("WF-C510", 399, 549),
    ],
}

# 全部型号清单，用于 N10「张冠李戴」噪声（把 A 品牌的产品挂到 B 品牌名下）
ALL_PRODUCTS: list[str] = [p[0] for plist in PRODUCTS.values() for p in plist]

# ---------------------------------------------------------------------------
# 评论模板池：按耳机评价维度组织
# ---------------------------------------------------------------------------
POSITIVE = [
    "{prod}音质很惊喜，低频有质感，听流行很带感。",
    "降噪开启后地铁里几乎听不见报站，{prod}这个价位太值了。",
    "续航扎实，{scene}全程戴着{prod}，一天下来还有40%。",
    "佩戴很轻，{prod}戴两小时耳朵不胀。",
    "连接很快，{prod}开盖就连上，双设备切换顺畅。",
    "{scene}用{prod}打电话，对方说听得很清楚。",
    "颜值高，{prod}做工细腻，开合手感踏实。",
    "延迟低，{scene}打游戏音画同步，{prod}性价比拉满。",
]
NEGATIVE_SOUND = [
    "{prod}中高频发刺，听人声有点刮耳。",
    "{prod}低音轰头但糊，鼓点全糊成一片。",
    "{prod}左右耳音量不一致，右耳明显偏小。",
]
NEGATIVE_ANC = [
    "{prod}降噪名不副实，开了和没开差不多，地铁上照样吵。",
    "{prod}降噪一开就有耳压感，坐一会儿就头晕。",
]
NEGATIVE_BATTERY = [
    "{prod}续航虚标，标称8小时实际4小时就没电。",
    "买了三个月{prod}电池健康掉得快，现在一天两充。",
]
NEGATIVE_UNCOMFORT = [
    "{prod}戴久了耳朵疼，耳塞偏硬。",
    "{prod}腔体太大，我的耳朵塞不进去，总是掉。",
]
NEGATIVE_CONNECT = [
    "{prod}断连很频繁，{scene}走路都会断一下。",
    "{prod}蓝牙配对折腾半天，两台设备切换总失败。",
]
NEGATIVE_CALL = [
    "{prod}通话风噪严重，{scene}对方说听不清。",
    "{prod}麦克风收音闷，开会议像在桶里说话。",
]
NEGATIVE_SERVICE = [
    "{prod}用了一个月右耳没声音，客服让寄回但两周没消息。",
    "买的{prod}拆封有划痕，申请换货被拒。",
    "保修期内{prod}出问题，售后要求自费检测，体验很差。",
]
NEGATIVE_PRICE = [
    "{prod}刚买就降价{diff}块，价格保护形同虚设。",
    "{prod}卖{price}元，这个配置实在有点贵。",
]
NEUTRAL = [
    "{scene}在官方店买了{prod}，{price}元，正常水平。",
    "{prod}就是普通TWS耳机，能用，没有特别印象。",
    "办公室同事都在用{prod}，我也跟风买了一个。",
]
MIXED = [
    "{prod}音质和降噪都不错，但{scene}戴一会儿耳朵就疼。",
    "降噪给力，可惜{prod}续航一般，出差得带充电仓。",
    "{prod}做工漂亮，价格{price}元实在肉疼。",
    "音质没得说，就是{prod}连接偶尔抽风，要重新配对。",
]

SCENE_POOL = ["地铁通勤", "健身房", "办公室", "跑步", "开车",
              "宿舍", "高铁", "图书馆", "打游戏", "视频会议"]

# ---------------------------------------------------------------------------
# N8 无效评论池（3 个亚型，便于清洗阶段按模式识别）
# ---------------------------------------------------------------------------
NOISE_SYMBOL = ["。。。。。", "？？？", "……", "!!!", "。。。", "。。。。"]
NOISE_NUMBER = ["666666", "111", "000", "233333"]
NOISE_AD = ["加我微信代购耳机5折", "转发抽奖", "低价出全新未拆封耳机", "私聊有优惠"]
NOISE_IRRELEVANT = ["今日天气不错", "祝商家生意兴隆", "评价方未及时评价，系统默认好评", "路过看看"]
SHORT_NO_INFO = ["一般", "还行吧", "退货了", "到了"]

# ---------------------------------------------------------------------------
# N9 文字形态脏数据：繁体 / 异体字替换表
# 清洗阶段用同一张表做归一（generate 与 cleaning 共享语义，但各自维护，避免耦合）
# ---------------------------------------------------------------------------
TRAD_TO_SIMPLE: dict[str, str] = {
    "續航": "续航", "連線": "连接", "連接": "连接", "藍牙": "蓝牙",
    "降噪": "降噪", "音質": "音质", "耳機": "耳机", "電池": "电池",
    "耳壓": "耳压", "斷連": "断连", "通話": "通话", "麥克風": "麦克风",
    "外觀": "外观", "價格": "价格", "佩戴": "佩戴", "會": "会",
    "買": "买", "個": "个", "說": "说", "聽": "听", "覺": "觉",
    "這": "这", "麼": "么", "開": "开", "關": "关", "沒": "没",
    "現": "现", "兩": "两", "點": "点", "還": "还", "產": "产",
}

# 全角标点 → 半角（用于制造 N9 噪声，也用于清洗还原）
FULLWIDTH_PUNCT: dict[str, str] = {
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":",
    "（": "(", "）": ")", "、": ",",
}

EMOJI_POOL = ["😂", "👍", "🔥", "😭", "🙏", "❤️", "💯", "🤔"]


# ---------------------------------------------------------------------------
# 噪声注入工具
# ---------------------------------------------------------------------------


def _messy_price(rng: random.Random, price: float) -> str:
    """N2：把干净价格弄脏成真实录入风格。

    耳机价格多为整数，但也有保留两位小数的场景，因此保留 4 种格式 + 欧式小数。
    """
    style = rng.random()
    if style < 0.22:
        return f"￥{price:.2f}"                     # ￥1299.00
    if style < 0.38:
        return f"{price:.0f}元"                     # 1299元
    if style < 0.50:
        return f"{price:,.2f}"                      # 1,299.00（千分位）
    if style < 0.58 and price < 1000:
        return f"{price:.0f}".replace(".", ",")     # 899 → 899（无逗号，占位）
    if style < 0.66:
        return f"{price:.2f}".replace(".", ",")     # 19,90 欧式小数
    if style < 0.80:
        return f"{price:.2f}"                       # 1299.00 纯数字带小数
    return str(int(price))                          # 1299 整数


def _messy_date(rng: random.Random, d: date) -> str:
    """N4：5 种日期格式。"""
    style = rng.random()
    if style < 0.32:
        return d.isoformat()                        # 2024-06-01
    if style < 0.52:
        return f"{d.year}/{d.month}/{d.day}"        # 2024/6/1
    if style < 0.68:
        return f"{d.year}{d.month:02d}{d.day:02d}"  # 20240601
    if style < 0.84:
        return f"{d.year}年{d.month}月{d.day}日"     # 2024年6月1日
    return f"{d.month}/{d.day}"                     # 6/1（缺年份）


def _traditionalize(rng: random.Random, text: str, prob: float = 0.45) -> str:
    """N9：按概率把简体词替换为繁体/异体字。

    注意 TRAD_TO_SIMPLE 的 key 是**繁体**、value 是简体，这里反向使用，
    因此遍历时是 (trad, simp)，替换方向 simp → trad。
    （初版把方向写反，导致繁体噪声完全没注入，C9 的繁简规则永远命中 0 条。）
    """
    out = text
    for trad, simp in TRAD_TO_SIMPLE.items():
        if simp in out and rng.random() < prob:
            out = out.replace(simp, trad, 1)
    return out


def _add_emoji(rng: random.Random, text: str) -> str:
    """N9：在句尾追加 1—2 个 emoji，并随机把部分标点转全角。"""
    n = rng.randint(1, 2)
    tail = "".join(rng.choice(EMOJI_POOL) for _ in range(n))
    out = text + tail
    if rng.random() < 0.5:
        out = out.replace(",", "，").replace(".", "。")
    return out


def _fake_review(rng: random.Random, product: str, price: float) -> str:
    """生成一条评论文本（含 N8 无效评论与 N9 文字形态噪声）。"""
    r = rng.random()
    scene = rng.choice(SCENE_POOL)
    diff = rng.choice([50, 100, 150, 200, 300])
    price_str = f"{price:.0f}"

    # N8 无效评论：约 7%
    if r < 0.025:
        return rng.choice(NOISE_SYMBOL)
    if r < 0.040:
        return rng.choice(NOISE_NUMBER)
    if r < 0.055:
        return rng.choice(NOISE_AD)
    if r < 0.070:
        return rng.choice(NOISE_IRRELEVANT)

    # 正常评论：按维度分配
    if r < 0.29:
        text = rng.choice(POSITIVE).format(prod=product, scene=scene)
    elif r < 0.45:
        text = rng.choice(NEGATIVE_SOUND + NEGATIVE_ANC).format(prod=product)
    elif r < 0.57:
        text = rng.choice(NEGATIVE_BATTERY + NEGATIVE_UNCOMFORT).format(prod=product)
    elif r < 0.69:
        text = rng.choice(NEGATIVE_CONNECT + NEGATIVE_CALL).format(prod=product, scene=scene)
    elif r < 0.77:
        text = rng.choice(NEGATIVE_SERVICE).format(prod=product)
    elif r < 0.85:
        text = rng.choice(NEGATIVE_PRICE).format(prod=product, price=price_str, diff=diff)
    elif r < 0.94:
        text = rng.choice(NEUTRAL).format(prod=product, scene=scene, price=price_str)
    else:
        text = rng.choice(MIXED).format(prod=product, scene=scene, price=price_str)

    # N9 文字形态：约 15% 繁体化，约 8% 加 emoji
    if rng.random() < 0.15:
        text = _traditionalize(rng, text)
    if rng.random() < 0.08:
        text = _add_emoji(rng, text)

    # 极短无信息评论
    if rng.random() < 0.03:
        text = rng.choice(SHORT_NO_INFO)
    return text


# ---------------------------------------------------------------------------
# 主生成逻辑
# ---------------------------------------------------------------------------


def _build_one(rng: random.Random, rid: str, start: date, n_days: int) -> dict:
    """构造一条记录（含 N1—N5、N9、N10 噪声）。"""
    brand = rng.choices(list(BRAND_WEIGHTS), weights=list(BRAND_WEIGHTS.values()), k=1)[0]
    alias = rng.choice(BRAND_ALIASES[brand])
    product, low, high = rng.choice(PRODUCTS[brand])
    price = round(rng.uniform(low, high), 2)

    # N10：product 与 brand 张冠李戴（约 4.5%）——把产品换成「其他品牌」的型号
    # 注意：必须按规范品牌取「不属于自己的型号」，否则可能随机取到自家产品，
    # 噪声注入失败（这是初版只命中 1 条的根因）。
    if rng.random() < 0.045:
        own = {p[0] for p in PRODUCTS[brand]}
        foreign = [p for p in ALL_PRODUCTS if p not in own]
        if foreign:
            product = rng.choice(foreign)

    # N3：价格放大 10 倍（录入多打一个 0）
    if rng.random() < 0.02:
        price = round(price * 10, 2)

    # N5：字段缺失
    rating: float | None = round(rng.uniform(3.0, 5.0), 1) if rng.random() > 0.08 else None
    price_cell: str | None = _messy_price(rng, price) if rng.random() > 0.05 else None
    interaction: int | None = rng.randint(0, 800) if rng.random() > 0.06 else None

    # N10：rating 超出 1—5（实为 10 分制混入）
    if rating is not None and rng.random() < 0.03:
        rating = round(rng.uniform(7.0, 9.5), 1)

    # 日期：N4 多格式 + N10 未来日期
    d = start + timedelta(days=rng.randint(0, n_days))
    if rng.random() < 0.02:
        d = date(2025, rng.randint(1, 12), rng.randint(1, 28))  # 未来日期

    return {
        "review_id": rid,
        "brand": alias,
        "product": product,
        "price": price_cell,
        "rating": rating,
        "review_text": _fake_review(rng, product, price),
        "date": _messy_date(rng, d),
        "interaction_count": interaction,
    }


def generate(n: int = N_DEFAULT, seed: int = SEED) -> list[dict]:
    """生成 n 条原始噪声记录。

    ============================ 注入策略（两阶段） ============================
    阶段 A：先造主体记录（n 条基础行，含 N1—N5、N9、N10 的字段级噪声）
    阶段 B：再注入两类"结构性重复"，且**互不干扰**：
        N6 整行完全重复：从已有行随机复制一条追加（review_id 也重复）
        N7 ID 重复内容不同：复制一条已有行，改 review_id + 改一个字段值

    为什么必须分两阶段：
      初版在同一次循环里交替掷骰子注入 N6/N7，导致 N7 造出的行会被后续的
      N6 整行复制覆盖；而清洗阶段 C2（整行去重）永远先于 C3（ID 去重）执行，
      于是 C3 恒为 0 条，两类重复退化成一类，规则验证失去意义。
      分阶段后两类噪声各自独立可辨：C2 只吃 N6、C3 只吃 N7。
    """
    rng = random.Random(seed)
    start = date(2024, 1, 1)
    end_offset = 181  # 2024-01-01 起 181 天 → 2024-06-30

    # 先算好两类重复各占多少条，剩余的才是基础行——保证最终恰好 n 条
    n_dup_id = max(3, int(n * 0.03))     # N7：ID 重复、内容不同
    n_dup_full = max(3, int(n * 0.03))   # N6：整行完全重复
    n_base = n - n_dup_id - n_dup_full

    # ---------------- 阶段 A：主体记录 ----------------
    base: list[dict] = []
    i = 0
    while len(base) < n_base:
        i += 1
        base.append(_build_one(rng, f"R{i:04d}", start, end_offset))

    records = list(base)

    # ---------------- 阶段 B：结构性重复 ----------------
    # 先注入 N7（ID 重复、内容不同）——复制基础行、**沿用原 review_id**，
    # 只改评分与互动量。这是真实场景里最常见的"二次提交"：
    # 同一条评论被提交两次，ID 落库相同，但评分/互动量被后续修改过。
    for _ in range(n_dup_id):
        src = dict(rng.choice(base))   # 沿用原 review_id，制造 ID 重复
        old_rating = src["rating"]
        new_rating = round(rng.uniform(3.0, 5.0), 1)
        while new_rating == old_rating:      # 强制改出不同的值
            new_rating = round(rng.uniform(3.0, 5.0), 1)
        src["rating"] = new_rating
        src["interaction_count"] = int(src["interaction_count"] or 0) + rng.randint(1, 200)
        records.append(src)

    # 再注入 N6（整行完全重复，连 review_id 一起重复）
    for _ in range(n_dup_full):
        records.append(dict(rng.choice(base)))

    # 打乱顺序（模拟导出文件的自然行序，避免重复行扎堆在末尾）
    rng.shuffle(records)
    return records[:n]


def write_csv(records: list[dict], out: Path) -> None:
    """写 CSV（手动实现，避免 pandas 对空值/引号的隐式处理）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    header = ["review_id", "brand", "product", "price", "rating", "review_text",
              "date", "interaction_count"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(header) + "\n")
        for rec in records:
            cells = []
            for col in header:
                v = rec[col]
                if v is None:
                    cells.append("")
                    continue
                s = str(v)
                if "," in s or '"' in s or "\n" in s:
                    s = '"' + s.replace('"', '""') + '"'
                cells.append(s)
            f.write(",".join(cells) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成模拟原始营销数据（蓝牙耳机，10 类噪声）")
    parser.add_argument("--n", type=int, default=N_DEFAULT, help="记录条数（默认 300）")
    parser.add_argument("--seed", type=int, default=SEED, help="随机种子（默认 42）")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT), help="输出路径")
    args = parser.parse_args()

    records = generate(n=args.n, seed=args.seed)
    out = Path(args.out)
    write_csv(records, out)

    print(f"已生成 {len(records)} 条原始数据 -> {out}")
    print(f"seed={args.seed}（固定种子，重跑结果逐字节一致，保证可复现）")
    print("注入噪声：N1 品牌别名 / N2 价格脏格式 / N3 价格×10 / N4 日期多格式 / N5 字段缺失")
    print("          N6 整行重复 / N7 ID重复 / N8 无效评论 / N9 繁简混用+emoji / N10 逻辑矛盾")


if __name__ == "__main__":
    main()
