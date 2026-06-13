# 资产协议

`library.py register` 接收一个 UTF-8 JSON 文件。只有用户审阅并确认后的内容才能进入 payload。

## 最小示例

```json
{
  "confirmed": true,
  "session": {
    "id": "2026-06-13-client-choice",
    "date": "2026-06-13",
    "mode": "deep-interviewer",
    "summary": "用户讲述了为什么主动拒绝一个大客户。",
    "themes": ["客户选择", "业务判断"]
  },
  "quotes": [
    {
      "id": "q-20260613-01",
      "text": "不是所有给钱多的客户都值得接。",
      "source_turn": "user-4",
      "theme": "客户选择",
      "story_or_decision": true
    }
  ],
  "topics": [
    {
      "id": "topic-client-choice",
      "title": "为什么我主动拒绝一个大客户",
      "fact_core": "用户发现该客户会持续改变交付边界，最终主动拒绝。",
      "tension": "短期收入与长期交付质量之间的冲突。",
      "audience": "正在接单的服务型创业者",
      "angles": ["什么样的大客户反而不该接", "拒绝前看哪三个信号"],
      "theme": "客户选择",
      "status": "unfilmed",
      "quote_ids": ["q-20260613-01"]
    }
  ],
  "signals": [
    {
      "id": "signal-boundary-over-revenue",
      "type": "value",
      "claim": "相比短期收入，用户更重视可控的交付边界。",
      "status": "tentative",
      "confidence": 0.45,
      "evidence_quote_ids": ["q-20260613-01"],
      "theme": "客户选择"
    }
  ],
  "next_threads": ["拒绝客户后，团队和收入发生了什么变化？"]
}
```

## 顶层字段

| 字段 | 必需 | 说明 |
|---|---|---|
| `confirmed` | 是 | 必须为 `true`，否则脚本拒绝登记 |
| `session` | 是 | 本次已确认素材的会话元数据 |
| `quotes` | 是 | 精选原话，不是完整聊天记录 |
| `topics` | 否 | 1–3 张轻量选题卡 |
| `signals` | 否 | 证据化画像信号 |
| `next_threads` | 否 | 下次可继续的具体话头 |
| `update_default_mode` | 否 | 只有用户明确要求以后都切换时才设为 `true` |
| `business_changed` | 否 | 用户明确确认业务发生重大变化时设为 `true` |
| `persona_generation` | 否 | 用户确认生成 Persona 后登记 |

## 信号状态

固定状态：

- `tentative`：单次或证据不足的暂定观察。
- `recurring`：至少跨 3 次会话重复出现。脚本会检查证据门槛。
- `confirmed`：用户明确认领的价值观或立场，需设置 `user_confirmed: true`。
- `contradicted`：与已有信号冲突，使用 `contradicts: "<signal-id>"` 保留两边。
- `retired`：用户确认已不再适用，需设置 `user_confirmed: true`。

信号类型：

- `voice`：表达习惯、句式、常用比喻或叙事方式。
- `value`：价值排序。
- `stance`：对业务、行业或生活问题的明确立场。
- `boundary`：不愿表达、不能编造或不希望公开的边界。
- `tension`：用户自身长期存在的矛盾与张力。
- `business`：业务定位、服务对象或工作方式。

## Persona 生成登记

```json
{
  "persona_generation": {
    "user_confirmed": true,
    "path": "generated/jia-run-persona/SKILL.md",
    "generated_at": "2026-06-13T12:00:00+08:00"
  }
}
```

登记后，`status` 会从当时的原话数量开始计算新增语料，并在新增 15 条或出现重大变化时建议更新。

## 数据原则

- `state.json` 只保存索引、状态、证据引用和统计，不保存原话正文或画像判断正文。
- 原话正文只存在于会话 Markdown 文件中。
- 选题和信号必须引用真实原话 ID。
- 同一信号增加证据时复用相同 `signal.id`；不要创建多个近义信号来虚增重复模式。

