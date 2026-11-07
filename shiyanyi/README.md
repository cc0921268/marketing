# AI Marketing OS · Marketing Analyzer（v0.1）

> 营销综合实训 · 实验1：Codex 协作开发与 Debug（第 1—2 周）
> 轻量级、模块化的营销分析系统原型。**本版本不调用任何大模型 API，所有均值、占比、排名均由 Python（pandas）计算。**

## 一、本版本解决了什么营销问题

多品牌咖啡产品上市前，团队需要快速回答三个基础问题：

1. 各品牌的**平均定价与平均口碑**处于什么水平？
2. 哪些品牌呈现「**高价低分**」特征（价格—评分象限）？
3. 在指定品牌范围内，各品牌的**销量占比**与排名如何？

本工具用一份 CSV 即可完成上述对比，且每个数字都可复算、每张图都可下载留档。

## 二、快速开始

```bash
# 1. 克隆仓库后进入项目根目录
cd marketing-os-teamXX

# 2.（建议）创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动
streamlit run app.py
# 浏览器自动打开 http://localhost:8501
```

## 三、项目结构

```
marketing-os-teamXX/
├── app.py                                  # Streamlit 主应用（入口）
├── requirements.txt                        # 依赖清单（Python >= 3.9）
├── README.md
├── data/
│   ├── raw/                                # 原始数据（实验3启用，禁止覆盖）
│   ├── processed/                          # 清洗数据（实验3启用）
│   └── sample/
│       ├── marketing_data.csv              # ✅ 正常样例（15 条）
│       ├── marketing_data_missing_rating.csv   # ❌ 缺字段样例（缺 rating）
│       └── marketing_data_with_nulls.csv       # ⚠️ 含空值样例（price 4 处 / rating 3 处）
├── skills/                                 # Skill 目录（实验2启用）
├── src/
│   ├── __init__.py
│   ├── data_utils.py                       # 校验 / 清洗 / 聚合 / 筛选（核心计算层）
│   └── charts.py                           # 绘图层（只画图，不算数）
├── outputs/                                # 运行结果导出目录
├── tests/
│   └── test_data_utils.py                  # 20 项单元测试（含手算复核）
└── docs/
    └── experiment01.md                     # 实验1统一提交文档
```

## 四、功能清单

| 功能 | 说明 | 验收状态 |
| --- | --- | --- |
| CSV 上传 / 示例数据 | 支持 utf-8 / utf-8-sig / gbk 自动编码识别 | ✅ |
| 必要字段校验 | 缺 `brand`/`price`/`rating` 时给出中文错误提示 + 排查步骤 | ✅ |
| 按品牌聚合 | 平均价格、平均评分保留两位小数；同时输出样本量（分母） | ✅ 手算复核一致 |
| 柱状图 | 品牌均价、均分柱状图，评分轴固定 0—5 便于比较 | ✅ |
| 品牌筛选 | 多选 / 单选 / 全选；返回 DataFrame 副本，**不修改原始数据** | ✅ 单测覆盖 |
| 空值容错 | `￥32.00`、`1,200`、`4.5分` 可自动解析；无法解析按缺失处理并提示 | ✅ |
| 导出 | 汇总表 CSV、图表 PNG、结果 + 输入快照到 `outputs/` | ✅ |
| Debug 面板 | 页面内展示校验结果、转换失败计数、行数自检 | ✅ |

## 五、程序计算与 AI 判断的分工（课程红线）

| 环节 | 负责方 | 实现位置 |
| --- | --- | --- |
| 字段校验、类型转换 | 程序（pandas） | `src/data_utils.py` |
| 平均价格 / 平均评分 / 占比 / 排名 | 程序（pandas） | `src/data_utils.py::brand_summary` |
| 图表绘制 | 程序（matplotlib） | `src/charts.py` |
| 大模型调用 | **本版本无**（v0.4 起才引入，且仅做语义提取，不替算） | — |

## 六、测试

```bash
# 推荐：pytest
python -m pytest tests/ -v

# 无 pytest 时直接运行
python tests/test_data_utils.py
```

覆盖三类数据场景（正常 / 缺字段 / 空值）共 **20 项断言**，全部通过；均值与手算抽查一致（如 Starbucks 均价 = (32+36+30)/3 = **32.67**）。

## 七、版本记录

| 版本 | Tag | 内容 |
| --- | --- | --- |
| v0.1 | `v0.1` | 实验1：Marketing Analyzer（上传 / 校验 / 聚合 / 图表 / 筛选 / 导出） |

## 八、已知限制

1. 单次处理数据量设计上限约 10 万行（更大规模在实验3引入分块清洗）。
2. 品牌名前后空格会做 strip，但「瑞幸」与「Luckin Coffee」这类别名归一留待实验3。
3. 评分轴按 0—5 满分设计；如换用 10 分制需调整 `VALID_RANGES`。
4. 沙箱/部分 Linux 服务器若无中文字体，图表标题可能显示为方框；本地 Windows/macOS 正常。

## 九、合规说明

- 示例数据为**人工构造的模拟数据**，不含任何真实个人信息，可公开传播。
- 上传的数据仅保存在浏览器会话与本地 `outputs/`，不上传任何服务器。
