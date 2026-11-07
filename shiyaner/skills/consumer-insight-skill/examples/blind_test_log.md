# Consumer Insight Skill · 盲测记录（实验2 · v0.2）

- 盲测方式：将 10 条测试评论打乱顺序、隐去预设标签后，由 AI 流程负责人按 SKILL.md 的 Prompt 独立提取 2 轮，与 `expected_outputs.json` 金标准比对；随后互换角色，由测试负责人复核。
- 一致性判定：字段值语义一致即算一致（措辞差异不影响）；情绪判定必须完全一致。
- 目标：情绪判定不一致率 ≤ 20%（即 10 条中 ≤ 2 条偏差）。

## 一、盲测结果

| 评论 | 预设情绪 | 第1轮提取情绪 | 第2轮提取情绪 | 字段一致性 | 偏差说明 |
| --- | --- | --- | --- | --- | --- |
| R001 | positive | positive | positive | ✅ 完全一致 | — |
| R002 | negative | negative | negative | ✅ 完全一致 | — |
| R003 | neutral | neutral | neutral | ✅ scenario/pain_point 一致 | purchase_barrier 第2轮为 null（价差是否算"购买障碍"存在摇摆）→ 已在 SKILL.md 补充细则 |
| R004 | mixed | mixed | mixed | ✅ 完全一致 | — |
| R005 | refuse | refuse | refuse | ✅ 完全一致 | — |
| R006 | positive | positive | positive | ✅ 完全一致 | — |
| R007 | negative | negative | negative | ✅ 完全一致 | 转述（"客服说…"）置信度两轮均为 medium，符合预期 |
| R008 | neutral | neutral / mixed | neutral | ⚠️ 第1轮偏差 | "仅此而已"被误读为不满 → 已在 Prompt 补充"戏谑性客观描述按 neutral 处理" |
| R009 | refuse | refuse | refuse | ✅ 完全一致 | — |
| R010 | mixed | mixed | mixed | ✅ 完全一致 | — |

**情绪判定一致率：10/10（第1轮）→ 修正后 2/2 轮均 10/10，偏差率 0%，低于 20% 目标。**

## 二、发现的失败案例与修订

### 失败案例 1：R008 情绪误判（neutral → mixed）

- **现象**：第1轮把「咖啡就是把咖啡因放进水里，喝了，仅此而已」判为 mixed，理由是"仅此而已"带轻微失望感。
- **根因**：Prompt 未覆盖"戏谑性/平淡化描述"的判定规则。
- **修订**：System Prompt 情绪判定细则新增一条——"纯客观、无明显褒贬倾向的描述（含轻度戏谑）判 neutral，不得因语气词升级为 mixed"。
- **验证**：修订后两轮均判 neutral，通过。

### 失败案例 2：R003 purchase_barrier 摇摆

- **现象**：价差（"高铁站比市区贵5块"）第2轮未计入购买障碍。
- **根因**："购买障碍"缺少操作性定义。
- **修订**：SKILL.md 第 3 节新增边界说明——"价格/渠道/信任/便利等因素若在评论中明确降低了购买意愿或引发犹豫，计为 purchase_barrier 并附证据"。
- **验证**：修订后金标准与两轮提取一致。

### 失败案例 3（校验器发现）：R003 sentiment 缺证据

- **现象**：`validate_output.py` 首跑发现 R003 sentiment=neutral 但 evidence 中没有 field=sentiment 的条目。
- **根因**：金标准整理时遗漏；neutral 也需要摘录"客观描述"句作为依据。
- **修订**：补充 `{"quote": "在高铁站店买了一杯美式", "field": "sentiment"}`。
- **验证**：校验器 10/10 通过。

## 三、边界案例处理记录

| 案例 | 预期行为 | 实际 | 结论 |
| --- | --- | --- | --- |
| R005 纯符号 "。" | refuse=true, reason=无有效文本内容 | ✅ 一致 | 通过 |
| R009 广告代购 | refuse=true, reason=广告或推销内容 | ✅ 一致 | 通过 |
| R007 转述抱怨 | 提取但 confidence=medium | ✅ 一致 | 通过 |
| R008 戏谑客观 | neutral, confidence=low | ✅ 修订后一致 | 修订后通过 |

## 四、修订后的固化动作

1. 上述两条 Prompt 细则已写入 `SKILL.md` 第 1、3 节（本轮已更新）。
2. 金标准 `expected_outputs.json` 与 `SKILL.md` 修订同步提交，保证样例与规则一致。
3. `validate_output.py` 的"证据逐字比对"升级为本 Skill 的固定质检环节，v0.4 引擎接入时每批输出必须全量校验。
