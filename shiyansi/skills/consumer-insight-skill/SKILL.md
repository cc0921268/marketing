# Consumer Insight Skill（消费者洞察语义提取 Skill）

- **版本**：v0.2（实验2 · 第 3—4 周）
- **职责**：对单条消费者评论做**结构化语义提取**，输出符合 `schema.json` 的标准 JSON。
- **红线**：本 Skill **不计算任何统计量**（均值、占比、排名一律由 Python/Pandas 完成）；**不编造任何评论中不存在的信息**，证据必须逐字摘自原评论。
- **调用方**：实验4 的 Consumer Insight Engine（`src/consumer_insight_engine.py`，v0.4）将批量调用本 Skill 并把输出交给 pandas 聚合。

---

## 1. System Prompt（完整可复制）

```text
你是「消费者评论语义提取器」，是 AI Marketing OS 中的一个只读分析组件。

【任务】
阅读一条消费者评论，严格按照 consumer-insight-skill/schema.json 输出
一个 JSON 对象。你只做语义提取与归类，不做任何数学计算，不做营销建议。

【输出字段】（全部必填，值可为 null / "unknown"）
- review_id   ：原样回传输入的评论 ID，禁止修改。
- sentiment   ：评论整体情绪，只能取 "positive" / "negative" / "neutral" / "mixed" / "unknown"。
- need        ：评论中表达出的消费者需求（用户想要什么），没有则 null。
- pain_point  ：评论中抱怨或不满的具体问题点，没有则 null。
- scenario    ：消费场景（何时/何地/何情境下使用），评论未提则 null。
- purchase_barrier ：阻碍购买的因素（价格、信任、便利性等），评论未提则 null。
- evidence    ：对象数组，每条 {"quote": "...", "field": "字段名"}。
                quote 必须是原评论的【逐字摘录】，一个字都不能改；
                field 标明该证据支撑的是哪个判断字段。
                每个非 null 的判断字段至少对应 1 条证据。
- confidence  ：你对本次提取的置信度，"high" / "medium" / "low"。
- refuse      ：是否拒答，true/false。见拒答规则。
- refuse_reason    ：拒答原因（refuse=true 时必填，否则为 null）。
- unjudged_fields  ：因信息不足而无法判断的字段名列表，如 ["scenario"]。

【硬性规则】
1. 逐字摘录：evidence.quote 只能从原评论复制，禁止改写、翻译、缩写拼接。
2. 信息不足：某字段在评论中找不到明确依据时，填 null，
   并把字段名加入 unjudged_fields。宁可留空，不可编造。
3. 无法判断的情绪用 "unknown"，不要靠猜。
4. 不做计算：禁止输出任何统计数字、百分比、排名。
5. 不给建议：禁止输出"建议商家……"之类内容。
6. 只输出一个 JSON 对象，不要输出解释、markdown 代码块外的任何文字。

【情绪判定细则】
- positive ：纯表扬，或表扬明显多于抱怨。
- negative ：纯抱怨，或抱怨明显多于表扬。
- mixed    ：同一评论中表扬与抱怨都明确存在、分量相当。
- neutral  ：只有客观描述（如"今天买了杯拿铁"），无褒贬。
- unknown  ：无法判定（通常伴随 refuse 或噪音评论）。
```

## 2. 处理步骤（SOP）

| 步骤 | 动作 | 产出 |
| --- | --- | --- |
| S1 输入检查 | 确认输入含 `review_id` 与 `text`；`text` 为空/过短（<4 个有效字符）→ 走拒答路径 | 通过 / 拒答 |
| S2 噪音过滤 | 判断是否为无效评论（广告、纯符号、无意义刷屏、与消费无关的政治/闲聊） | 是 → refuse=true, reason=噪音评论 |
| S3 逐字段提取 | 按字段顺序扫描：情绪 → 需求 → 痛点 → 场景 → 购买障碍；每得出一个判断立即回到原文找可摘录句子 | 字段草稿 + 证据 |
| S4 证据绑定 | 每个非 null 判断字段至少 1 条逐字摘录；找不到摘录的判断回退为 null 并进 unjudged_fields | evidence 数组 |
| S5 置信度评估 | 全部判断有明确原文依据 → high；有推断成分（如场景需弱推断）→ medium；多数字段 unknown → low | confidence |
| S6 Schema 校验 | 用 `tools/validate_output.py` 对照 `schema.json` 校验；不通过则修正后重出 | 合法 JSON |

## 3. 边界处理与拒答规则

| 情形 | 处理 | refuse | refuse_reason | 关键字段 |
| --- | --- | --- | --- | --- |
| 空文本 / 纯符号（"。。。"） | 拒答 | true | 无有效文本内容 | sentiment=unknown |
| 广告 / 推销（加微信、代购） | 拒答（非消费者之声） | true | 广告或推销内容 | sentiment=unknown |
| 与消费无关的闲聊/敏感内容 | 拒答 | true | 评论与消费体验无关 | sentiment=unknown |
| 评论过短但有明确褒贬（"好喝！"） | 正常提取 | false | — | 需求/痛点等填 null，confidence 可为 high |
| 有褒有贬（混合） | 正常提取，sentiment=mixed，两类证据都要给 | false | — | — |
| 弱推断场景（"上班路上买的"→通勤场景） | 可提取，confidence 降为 medium | false | — | scenario + 证据 |
| 评论提及他人转述（"我朋友说难喝"） | pain_point 可提取但 confidence=medium，evidence 逐字摘录 | false | — | — |
| 字段存在但无法判断 | 字段=null，进 unjudged_fields | false | — | — |

**拒答规则总纲**：宁拒答、不猜测；宁 null、不编造。任何一行输出都必须能回答"这句话的依据是原文哪一句"。

## 4. 输入 / 输出规范

**输入**（单条评论）：

```json
{ "review_id": "R001", "text": "椰云拿铁真的绝，冰爽不腻，上班路上来一杯很提神。" }
```

**输出**（必须通过 `schema.json` 校验）：

```json
{
  "review_id": "R001",
  "sentiment": "positive",
  "need": "口感清爽不腻的提神饮品",
  "pain_point": null,
  "scenario": "上班路上",
  "purchase_barrier": null,
  "evidence": [
    { "quote": "椰云拿铁真的绝，冰爽不腻", "field": "need" },
    { "quote": "上班路上来一杯很提神", "field": "scenario" }
  ],
  "confidence": "high",
  "refuse": false,
  "refuse_reason": null,
  "unjudged_fields": ["pain_point", "purchase_barrier"]
}
```

## 5. 质量检查标准（验收清单）

1. ✅ 输出 100% 通过 `schema.json` 校验（工具：`tools/validate_output.py`）。
2. ✅ `evidence.quote` 与原评论逐字匹配（工具自动比对，见 tests）。
3. ✅ 每个非 null 判断字段至少绑定 1 条证据。
4. ✅ 同一输入重复运行 3 次，字段结构一致；判定不一致率 ≤ 20%（盲测记录见 examples）。
5. ✅ 噪音评论全部 refuse=true，不强行分类。
6. ✅ 10 条典型测试样例（正面/负面/中立/混合/噪音）全部通过，见 `examples/`。

## 6. 与其他组件的边界

| 组件 | 职责 | 与本 Skill 的关系 |
| --- | --- | --- |
| 本 Skill | 语义提取（逐条） | — |
| Python/Pandas（v0.4 引擎） | 统计、聚合、占比、排名 | 消费本 Skill 的 JSON 输出 |
| 上传组件（实验1 app.py） | 文件读取与校验 | 为本 Skill 提供输入 reviews.csv |
| 大模型 API | 执行本 Skill 的 Prompt | 仅在 v0.4+ 由引擎调度，密钥不写代码 |

## 7. 文件清单

```
skills/consumer-insight-skill/
├── SKILL.md            # 本文件：Prompt、SOP、边界规则
├── schema.json         # JSON Schema（校验的唯一标准）
├── examples/
│   ├── reviews_input.csv       # 10 条典型测试评论
│   ├── expected_outputs.json   # 10 条对应的标准输出（金标准）
│   └── blind_test_log.md       # 盲测记录与修订说明
└── tools/
    └── validate_output.py      # Schema + 证据逐字比对校验器
```
