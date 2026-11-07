# 实验2：Consumer Insight Skill 设计（v0.2）

> 组别：teamXX　｜　周期：第 3—4 周　｜　版本：v0.2　｜　复用：实验1 全部成果

## 1. 本实验解决的营销问题

实验1 只能回答"卖得怎么样"（价格/评分/销量），回答不了"**消费者为什么买、为什么不买**"。本实验把「消费者评论分析」沉淀为一个**标准可复用的语义提取 Skill**：输入任意一条评论，稳定输出结构化的情绪、需求、痛点、场景、购买障碍——它是后续实验4 消费者洞察引擎的"语义传感器"。

## 2. 复用上一实验的成果

| 复用项 | 来自 | 用途 |
| --- | --- | --- |
| 项目目录规范与 Git 流程 | 实验1 | 直接在 v0.1 仓库上增量开发 |
| 数据读取与校验层 `src/data_utils.py` | 实验1 | reviews CSV 的读取、编码识别、review_id 完整性检查 |
| 上传组件与页面框架 `app.py` | 实验1 | 实验4 引擎界面将复用同一套上传/校验流程 |

本实验**新增代码不修改任何 v0.1 文件**（回归测试通过：20 项旧测试全绿、app 可正常启动）。

## 3. 输入数据、来源与字段

- 输入：单条评论 `{review_id, text}`；批量形式为 `reviews_input.csv`。
- 样例：`skills/consumer-insight-skill/examples/reviews_input.csv`，10 条**人工构造的模拟评论**（合规：无真实个人信息），覆盖正面×2、负面×2、中立×2、混合×2、无效噪音×2。

## 4. 新增功能、Skill 或 Workflow

```
skills/consumer-insight-skill/
├── SKILL.md                      # System Prompt + 6步SOP + 8类边界/拒答规则
├── schema.json                   # JSON Schema（11个必填字段，含 if/then 条件约束）
├── examples/
│   ├── reviews_input.csv         # 10 条测试评论
│   ├── expected_outputs.json     # 10 条金标准输出
│   └── blind_test_log.md         # 盲测记录与修订说明
└── tools/
    └── validate_output.py        # 三级校验器（Schema→证据逐字比对→证据绑定）
```

**字段契约**（7 个核心字段 + 4 个治理字段）：
`sentiment`(5枚举) · `need` · `pain_point` · `scenario` · `purchase_barrier` · `evidence`(逐字摘录数组) · `confidence`(3级) · 外加 `review_id`/`refuse`/`refuse_reason`/`unjudged_fields` 保证拒答与不可判断显式化。

## 5. 程序计算与 AI 判断的分工

| 环节 | 负责方 | 位置 |
| --- | --- | --- |
| 语义提取（情绪/需求/痛点/场景/障碍） | AI（按 SKILL.md Prompt） | 本 Skill |
| JSON 结构合法性 | **程序**（jsonschema + 内置等价校验） | `tools/validate_output.py` |
| 证据逐字比对（防编造红线） | **程序**（子串精确匹配） | 同上 |
| 统计、占比、排名 | **程序**（pandas） | v0.4 引擎实现，本 Skill 明确禁止输出统计量 |

> 设计要点：AI 的输出**必须**经过程序校验才能进入下游——Skill 产出的不是"答案"，而是"待检材料"。

## 6. 测试用例、结果与 Debug 记录

### 6.1 测试结果

| 测试 | 结果 |
| --- | --- |
| `tests/test_skill.py`（13 项：金标准校验、伪造证据拦截、改写摘录拦截、无证据绑定拦截、拒答格式、字段契约、5 类情绪覆盖） | ✅ 13/13 |
| `tests/test_data_utils.py`（实验1 回归） | ✅ 20/20 |
| `validate_output.py` 校验金标准 | ✅ 10/10 |
| 官方 jsonschema（Draft 2020-12）独立复核 | ✅ 10/10 |
| Streamlit 回归启动 | ✅ HTTP 200 |

### 6.2 Debug 记录（真实问题 3 条）

| # | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | 校验器首跑 R003 失败：sentiment=neutral 无对应证据 | 金标准整理遗漏 neutral 的"客观描述"证据句 | 补 `{"quote": "在高铁站店买了一杯美式", "field": "sentiment"}`；确立"非 unknown 的 sentiment 必须绑证据"规则 |
| 2 | 盲测 R008「仅此而已」被第1轮误判 mixed | Prompt 未定义戏谑性客观描述的判定 | SKILL.md 情绪细则新增"轻度戏谑按 neutral，不得因语气词升级" |
| 3 | 盲测 R003 价差是否算 purchase_barrier 两轮摇摆 | "购买障碍"缺操作性定义 | SKILL.md 边界节新增："明确降低购买意愿或引发犹豫的价格/渠道/信任/便利因素计为 purchase_barrier" |

## 7. 证据追溯示例

> **评论** R002：「第三次喝了，这次比上次甜好多，齁得慌，而且等了25分钟才做好，太慢了。」
> **输出**：sentiment=negative；pain_point=「产品变甜口感变差，且出餐等待时间过长」；
> **证据**：`"这次比上次甜好多，齁得慌"`（field=pain_point）、`"等了25分钟才做好，太慢了"`（field=pain_point）——两条均为原文逐字摘录，可用校验器自动复核：
> `python skills/consumer-insight-skill/tools/validate_output.py --input ... --outputs ...`

**无法判断的处理实例**：R007「客服说漏发会补，结果一周都没消息」中 `need=null` 并列入 `unjudged_fields`——评论只谈售后，未表达任何需求，按规则留空而非编造。

## 8. 已知限制与合规说明

1. 当前金标准为人工/AI 协作标注的**示范样例**；接入真实大模型 API 属于实验4（v0.4），届时用本 Skill 的 Prompt + 校验器做批量提取与全量质检。
2. 情绪为整体判定，一条评论内多品类的情绪细分（如"好喝但包装差"拆两条）留给 v0.4 的字段扩展。
3. 证据比对基于精确子串匹配；若上游对评论做过全角/半角转换，摘录可能误报——因此规定**读入原文不清洗不转码**。
4. 合规：样例评论全部为人工构造模拟数据；Skill 不采集、不存储任何个人信息。

## 9. 版本号与运行方式

- 版本：**v0.2**（Tag：`v0.2`）
- 校验金标准：`python skills/consumer-insight-skill/tools/validate_output.py --input skills/consumer-insight-skill/examples/reviews_input.csv --outputs skills/consumer-insight-skill/examples/expected_outputs.json`
- 全部测试：`python tests/test_skill.py && python tests/test_data_utils.py`
- 应用（含实验1功能）：`streamlit run app.py`

## 10. 小组成员贡献

| 成员 | 角色 | 本次贡献 | 占比 |
| --- | --- | --- | --- |
| （填写） | 营销负责人 | 标签字典、5类情绪口径、验收标准 | — |
| （填写） | 数据负责人 | 10条测试评论设计与覆盖矩阵 | — |
| （填写） | AI流程负责人 | SKILL.md Prompt、边界规则、盲测 | — |
| （填写） | 产品负责人 | schema.json、校验器、目录规范 | — |
| （填写） | 测试负责人 | 13项单测、回归验证、盲测复核 | — |
