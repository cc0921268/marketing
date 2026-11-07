# AI Marketing OS（v0.3）

> 营销综合实训 · 递进式课程项目（实验1—8，v0.1 → v1.0）
> 当前版本 **v0.3**：实验1 Analyzer + 实验2 Skill + **实验3 数据清洗管线**。
> **业务品类：蓝牙耳机（TWS 真无线 + 头戴式）**，6 品牌 23 型号。
> **职责红线**：所有统计量（均值/占比/排名）由 Python/Pandas 计算；AI 仅做结构化语义提取与证据追溯，输出必须经过程序校验。

## 一、本版本解决了什么营销问题

小米（焦点品牌）要在蓝牙耳机市场守住并扩大份额，团队按顺序回答四个问题。**当前停留在第 3 步**——先确保数据可信，后面的洞察才站得住：

| 阶段 | 问题 | 对应实验 | 输出 | 状态 |
| --- | --- | --- | --- | --- |
| 基础盘 | 各品牌均价、均分、销量占比处于什么水平？谁"高价低分"？ | 实验1（v0.1） | 上传 CSV → 聚合表 + 柱状图 | ✅ 已完成 |
| 单条理解 | 一条评论里的情绪、需求、痛点、场景、购买障碍能否结构化？ | 实验2（v0.2） | Skill + JSON Schema + 三级校验 | ✅ 已完成 |
| **数据底座** | **数据从哪来、脏在哪、怎么洗、洗完什么质量？** | **实验3（v0.3）** | **300 → 282 条，完整率 97.82%** | **✅ 本版本** |
| 用户洞察 | 评论里最痛的痛点是什么？情绪结构如何？ | 实验4（v0.4） | 痛点排行 + 情绪分布 + 证据追溯 | ⏳ 待做 |
| 竞争判断 | 主要竞争者是谁？市场空白在哪？ | 实验5（v0.5） | 威胁指数排行 + 雷达图 | ⏳ 待做 |

## 二、快速开始

```bash
# 1. 克隆仓库后进入项目根目录
cd marketing-os-teamXX

# 2.（建议）创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 生成 + 清洗数据（可复现，seed=42）
python3 src/generate_raw_data.py
python3 src/data_cleaning.py

# 5. 运行测试（88 项）
python3 tests/test_cleaning.py

# 6. 启动看板（实验1 页面）
python3 -m streamlit run app.py
# 浏览器自动打开 http://localhost:8501
```

## 三、项目结构

```
marketing-os-teamXX/
├── app.py                                  # Streamlit 主应用（实验1 页面）
├── requirements.txt                        # 依赖清单（Python >= 3.9）
├── README.md
├── data/
│   ├── raw/
│   │   ├── raw_data.csv                    # 300 条原始耳机评论（只读，md5 保护）
│   │   ├── public_slice.csv                # 公开数据切片（通道B，60 条，可选）
│   │   └── public_slice.meta.json          # 公开数据来源与许可留档
│   ├── processed/
│   │   ├── clean_data.csv                  # 282 条清洗结果（10 列）
│   │   ├── cleaning_log.csv                # 731 行逐条清洗日志（审计链）
│   │   └── quality_report.json             # 质量统计报告
│   └── sample/
│       ├── marketing_data.csv              # ✅ 正常样例（15 条，通用字段演示）
│       ├── marketing_data_missing_rating.csv   # ❌ 缺字段样例（缺 rating）
│       └── marketing_data_with_nulls.csv       # ⚠️ 含空值样例（price 4 处 / rating 3 处）
├── skills/
│   └── consumer-insight-skill/             # 实验2：消费者评论语义提取 Skill
│       ├── SKILL.md                        # System Prompt + SOP + 边界/拒答规则
│       ├── schema.json                     # 输出 JSON Schema（校验唯一标准）
│       ├── examples/                       # 10条测试评论 + 金标准输出 + 盲测记录
│       └── tools/validate_output.py        # 三级校验器（Schema/逐字证据/绑定）
├── src/
│   ├── __init__.py
│   ├── data_utils.py                       # 校验 / 清洗 / 聚合 / 筛选（实验1 计算层）
│   ├── charts.py                           # 绘图层（只画图，不算数）
│   ├── generate_raw_data.py                # 实验3：模拟数据生成器（seed=42，N1—N10）
│   ├── data_cleaning.py                    # 实验3：C1—C10 清洗管线
│   └── fetch_public_data.py                # 实验3：公开数据适配器（通道B，可降级）
├── outputs/
│   └── cleaning_summary.txt                # 清洗摘要（人类可读）
├── tests/                                  # 三份测试，共 121 项
│   ├── test_data_utils.py                  # 20 项
│   ├── test_skill.py                       # 13 项
│   └── test_cleaning.py                    # 88 项
└── docs/
    ├── experiment01.md                     # 实验1 文档
    ├── experiment02.md                     # 实验2 文档
    ├── experiment03.md                     # 实验3 文档 ⭐ 本版本重点
    ├── data_dictionary.md                  # 数据字典（10类噪声 + C1—C10 + 别名表）
    └── ethics_checklist.md                 # 伦理自查表（20 项 + 敏感信息扫描）
```

## 四、核心结论速览（v0.3，耳机数据集）

| 维度 | 结果 | 分母 |
| --- | --- | --- |
| 数据量 | 原始 **300** → 清洗后 **282** 条（剔除 9 行整行重复 + 9 行 ID 重复） | — |
| 数据质量 | 整体字段完整率 **97.82%**（达标线 90% ✅） | — |
| 品牌收敛 | 243 条别名 → **6 个规范品牌**（Apple/华为/小米/漫步者/OPPO/索尼） | 282 |
| 价格处理 | 201 条脏格式解析成功（失败 0），2 条 ×10 异常截断 | 282 |
| 日期归一 | 184 条格式转换，2 条未来日期置空 | 282 |
| 有效评论 | 有效 **267** / 无效 15（只打标不删） | 282 |
| 一致性 | 品牌型号匹配 **275** / 待复核 7（只打标不删） | 282 |
| 测试 | **88/88** 通过 | — |

**清洗规则命中详情**：C1=243、C2=9、C3=9、C4=184（置空2）、C5=201、C6=2、C7=（填0 14 / price置空 13 / rating置空 28）、C8=15、C9=36、C10=（折算8 / 标记7）

## 五、程序计算与 AI 判断的分工（课程红线）

| 环节 | 负责方 | 实现位置 |
| --- | --- | --- |
| 字段校验、类型转换 | 程序（pandas） | `src/data_utils.py` |
| 平均价格 / 平均评分 / 占比 / 排名 | 程序（pandas） | `src/data_utils.py::brand_summary` |
| 噪声注入（N1—N10） | 程序（`random.Random(seed=42)`） | `src/generate_raw_data.py` |
| 清洗决策 C1—C10 | 程序（规则表 + 日志） | `src/data_cleaning.py` |
| 图表绘制 | 程序（matplotlib） | `src/charts.py` |
| 噪声体系设计（脏在哪、脏多少） | **人**（业务判断） | — |
| 规则边界拍板（短评算不算噪音等） | **人** | — |
| 代码实现 / Bug 定位 | AI 写 + 人审 + 测试断言把关 | `tests/test_cleaning.py` |
| 语义编码（情绪/需求/痛点） | AI（实验2 Skill 口径） | `skills/consumer-insight-skill/` |
| 大模型 API | **尚未调用**（后续实验接入） | — |

**可追溯红线**：任何一条清洗结果都能通过 `review_id` 反查 `cleaning_log.csv` 的 `before → after`；原始文件全程只读，md5 校验保护（有测试强制）。

## 六、测试

```bash
python3 tests/test_cleaning.py       # 88 项（本版本重点）
python3 tests/test_data_utils.py     # 20 项
python3 tests/test_skill.py          # 13 项
# 或用 pytest 统一跑
python -m pytest tests/ -v
```

| 测试文件 | 项数 | 覆盖 |
| --- | --- | --- |
| `test_data_utils.py` | 20 | 三类数据场景（正常/缺字段/空值）、均值手算、筛选不改原表 |
| `test_skill.py` | 13 | Schema 校验、逐字证据、拒答条件 |
| `test_cleaning.py` | **88** | 可复现、300 条、N1—N10 逐类验证、C1—C10 逐规则边界、raw 保护、幂等、完整率≥90% |
| **合计** | **121** | ✅ 全部通过 |

## 七、版本记录

| 版本 | Tag | 内容 |
| --- | --- | --- |
| v0.1 | `v0.1` | 实验1：Marketing Analyzer（上传 / 校验 / 聚合 / 图表 / 筛选 / 导出） |
| v0.2 | `v0.2` | 实验2：Consumer Insight Skill（SKILL.md + JSON Schema + 10条金标准 + 三级校验器 + 盲测记录） |
| **v0.3** | **`v0.3`** | **实验3：数据获取与清洗（蓝牙耳机品类）——300条生成器含 N1—N10 十类噪声 + C1—C10 十条清洗规则 + 完整率 97.82% + 双通道数据源 + 88 项测试 + 数据字典/伦理自查表** |

> v0.4 及以后待课程进度推进。此前曾存在 v0.4/v0.5 的实现，因数据底座重做（咖啡→蓝牙耳机）已回退，备份保留在 Git 分支 `backup-v0.5.1-20261106`。

## 八、已知限制

1. **数据是合成的**：评论由模板拼接，语言多样性远低于真实评论；后续做文本聚类/主题模型时，真实数据上效果可能下降。
2. **品牌/型号名真实、评论虚构**：容易被误读为真实口碑，对外引用必须先说明"模拟数据"。
3. **公开切片仅 60 条且不参与统计**：只验证字段映射跑得通，不能声称"在真实数据上验证了清洗效果"。
4. **无时间序列深度**：6 个月、300 条，做不了季节性/趋势分析。
5. **无用户维度**：没有用户 ID、复购、会员等级，做不了用户分群、LTV。
6. **C6 价格上限靠人工设定**：真实数据需重新校准，否则截断可能误伤。
7. **繁简转换表非完备**：`TRAD_TO_SIMPLE` 收录 45 组高频词条，非完整繁简表；已加 `test_c9_trad_map_covers` 做样本级防护。
8. **单次处理数据量设计上限约 10 万行**（更大规模需分块清洗）。
9. `marketing_data.csv` 的 15 条样例为通用字段演示（v0.1 保留原样），与耳机业务数据不混用。
10. 沙箱/部分 Linux 服务器若无中文字体，图表标题可能显示为方框；本地 Windows/macOS 正常。

## 九、合规说明

- 全部数据为**程序合成的模拟数据**（`seed=42`），不含任何真实个人信息，可公开传播。
- 品牌名与产品型号为公开市场信息，评论内容为模板合成、非真实用户言论，**不代表任何真实品牌的实际表现或产品质量**。
- 公开数据集切片（`gyoungjr/amazon-electronics-reviews`）经 HuggingFace `datasets-server` 公开只读 API 访问，单条截断 ≤200 字，仅课程教学使用、不再分发；来源与许可记录于 `data/raw/public_slice.meta.json`。
- 敏感信息扫描：手机号/身份证/邮箱/银行卡 **0 命中**；仅有 1 处刻意注入的广告占位符（已由 C8 打标）。
- 详见 `docs/ethics_checklist.md`（20 项合规自查 + 风险登记表）。
