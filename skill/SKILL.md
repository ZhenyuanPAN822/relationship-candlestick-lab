---
name: rcl-score
description: |
  Convert a two-person chat history into a relationship K-line chart.
  When invoked, walk the user through providing a chat file, run the local
  preprocessing pipeline, score every "turn" (consecutive same-sender block)
  with v3.1 semantic deltas, expand back to message-level scored.jsonl, and
  hand off to the local web frontend for visualization.
---

# Relationship Candlestick Lab · Scoring Skill (v3.1)

This skill has TWO operating modes. Detect which one you're in by looking
at the first user message:

- **Entry Mode** — user just typed `/rcl-score` (or asked you to "score
  my chat / 画 K 线") with no input file yet. Run the **Entry Protocol**
  below.
- **Batch Scoring Mode** — your user message starts with "Score each TURN
  below" or contains a `=== TURNS ===` block (this is how the API pipeline
  invokes you). Skip the Entry Protocol and jump directly to the
  **Scoring Rules** section, output JSONL only.

---

## ⓪ Entry Protocol（仅当用户直接调用 skill 时）

### 对用户说的话（仅这一段对外输出，Step 1–4 不要复述给用户）

回复用户（中文，简洁，5–8 行以内）：

> 我会把你的聊天记录画成 K 线图，每根 K 线代表一段时间的关系强度变化。
>
> **请准备一个聊天导出文件**（任选其一）：
> - 微信导出 CSV（推荐，pywxdump / Memotrace 都可以）
> - 或 JSON / 纯文本（每行 `YYYY-MM-DD HH:MM[:SS] sender: message`）
>
> **把文件的绝对路径粘贴给我。**
>
> ⚠️ **模型 / effort 推荐**：
> - **Claude**：`Sonnet 4.6` + effort `low`
> - **GPT 系列**：`GPT-5 / 5.4 / 5.5` + effort `low`
>
> ⏱ **耗时预估**：每 1000 条消息约 **7 分钟**（取决于模型 / effort）。
>
> 全程在本地处理，聊天数据不上传云端。

等用户回复文件路径再继续。

### Step 1–4（你内部按顺序执行，不需要把命令贴给用户）

**Step 1 — CSV → messages.jsonl**

`<job_name>` 用源文件名（去后缀）。

```bash
python scripts/wechat_to_standard.py \
    --input "<用户给的路径>" \
    --output "output/_jobs/<job_name>/messages_standard.csv" \
    --me me --them other
```

然后 Python 把标准 CSV 转 messages.jsonl（每行带 `i` 索引）。
如果用户给的是 JSON/TXT，改用 `python -m relationship_candlestick.cli prepare ...`。

**Step 2 — 预处理：剔单字 + 聚合 turns**

```bash
python scripts/preprocess_turns.py \
    --input  output/_jobs/<job_name>/messages.jsonl \
    --out-dir output/_jobs/<job_name>/ \
    --gap-min 10
```

**Step 3 — 评分：你（LLM）按下面的 Scoring Rules 给每个 turn 打分**

读取 `output/_jobs/<job_name>/turns.jsonl`，每次取 30–60 个 turn 一批
（effort low → 60 / medium → 40 / high → 20），按 **Scoring Rules** 输出
JSONL，append 到 `output/_jobs/<job_name>/turns_scored.jsonl`。

**Step 4 — 反扩展回 i 级**

```bash
python scripts/expand_turns.py \
    --turns        output/_jobs/<job_name>/turns.jsonl \
    --turns-scored output/_jobs/<job_name>/turns_scored.jsonl \
    --auto         output/_jobs/<job_name>/auto_scored.jsonl \
    --messages     output/_jobs/<job_name>/messages.jsonl \
    --out          output/_jobs/<job_name>/scored.jsonl
```

### 完成后对用户说的话（仅这一段对外输出）

> ✅ 评分完成！scored.jsonl 路径：
>
> `<绝对路径，例如 E:/.../output/_jobs/myjob/scored.jsonl>`
>
> **下一步**：打开 K 线网页（如果服务还没起，请运行 `python -m relationship_candlestick.cli serve`）
>
> 1. 浏览器访问 http://127.0.0.1:7000
> 2. 选 **"已有 scored.jsonl"** 流程
> 3. 把上面路径粘贴到 **scored.jsonl 绝对路径** 输入框
> 4. 点 **"▶ 加载并显示 K 线"**

完成 Entry Protocol 后退出，**不要继续按规则给消息打分** — 评分由后续的
Batch Scoring Mode 负责。

> 注：API 模式用户**不走 skill** — 他们直接在前端 ingest CSV 走 server
> 自动调用外部 API。Skill 只服务 Claude Code / Codex / GPT 这类 IDE 用户。

---

# Scoring Rules · v3.1（适用于 Batch Scoring Mode）

You are the **semantic scorer** of a relationship-K-line system. Your job is
to read messages **in order, in context** and emit two **relative deltas** per
message — never absolute scores. The framework does all arithmetic, recurrence,
and time decay.

The whole point of using Claude here is **contextual judgment**. Sarcasm,
callbacks, awkward silences, and inside jokes are exactly what you must read.

---

## 🚨 Most important principle: every message moves the needle

**No two consecutive messages are exactly the same temperature.** Even when
the topic and mood feel "identical", real conversations have constant
micro-variation:

- A reply is slightly warmer or cooler than the message it answers
- A continuation message is slightly weaker than the original (loss of momentum)
- An emoji-only reply is slightly lighter than a text reply
- A "嗯" after substance is a small cooling
- A "哈哈" after partner's joke is a small acknowledgment lift

**Default to small nonzero deltas (±0.2 ~ ±0.5), not 0.**

`0, 0` is a strong claim that means "this message contributes literally nothing —
identical temperature to prior AND to atmosphere". This should be **rare**,
reserved for cases like:
- A message inside an opaque sub-thread (file path, link, phone number)
- A literal repeat ("嗯" "嗯" "嗯" — even then the third is -0.2, not 0)

If you find yourself outputting `0, 0` for more than ~15% of messages,
**you are under-scoring**. Real chats have constant ebb and flow.

---

## Core principle: relative, not absolute

You **do not** score "this message has affection 5". There's no objective
anchor for that.

You **do** score "this message is +1 warmer than the prior message" and
"this message is +0.5 vs the recent atmosphere". Both are relative
comparisons you can actually make confidently.

Two reference frames:

- `delta_vs_prior` — change vs the **immediately previous** message
- `delta_vs_atmosphere` — change vs the **mean of recent messages**

The framework blends both: `delta_blend = 0.5 * vs_prior + 0.5 * vs_atmosphere`.

---

## Input

Per API call you receive:

```json
{
  "previous_relationship_index": 67.4,
  "atmosphere": {
    "recent_avg_index":  65.0,
    "recent_avg_delta":  0.3,
    "window_size":       20
  },
  "context_already_scored": [
    {"i":..., "ts":..., "sender":..., "text":...,
     "delta_vs_prior":..., "delta_vs_atmosphere":..., "primary_dim":..., "idx":...},
    ...
  ],
  "new_messages_to_score": [ {"i":..., "ts":..., "sender":..., "text":...}, ... ]
}
```

Time gaps matter: the framework decays the index based on real time between
messages, so don't manually penalize "long silence" — score the **content** only.

---

## Output (one line per input message, same order)

```json
{
  "i": 42,
  "delta_vs_prior":      +1.5,
  "delta_vs_atmosphere": +0.8,
  "primary_dim": "affection",
  "tags": ["intimacy","care"],
  "rationale": "比上条暖一点；vs 整体氛围也是小升"
}
```

`primary_dim` and `tags` are for display/explanation — they do NOT enter the math.

---

## Delta scale (with explicit micro-fluctuation guidance)

| Magnitude | Meaning | Frequency in real chat |
|---|---|---|
| `±0.2 ~ ±0.5` | **MICRO-FLUCTUATION** — natural ebb/flow | **MOST messages live here** |
| `±0.5 ~ ±1.5` | Subtle but clear shift | ~25% |
| `±2 ~ ±4` | Clearly noticeable change | ~10% |
| `±5 ~ ±8` | Big move (probe / invitation / repair / conflict) | ~3% |
| `±9 ~ ±15` | Rare landmark events (告白 / 分手) | < 1% |
| `0, 0` | Literally no change — use sparingly | **< 15%** |

**Distribution check**: In a healthy 100-message scoring batch, you should
have roughly:
- ~15 messages with `0, 0`
- ~60 messages with `±0.2 ~ ±0.5` (micro-fluctuations)
- ~20 messages with `±0.5 ~ ±2`
- ~5 messages with `±2+`

If your output is mostly 0,0, you're flattening reality.

---

## Continuation heuristics (give you concrete starting points)

For messages that don't represent a clear "event", use these defaults
then adjust based on context:

| Pattern | vs_prior default | vs_atmosphere default |
|---|---|---|
| Filler "嗯/哦/好/okok/豪德/对/yes" after substance | **-0.3 ~ -0.5** | depends on atmosphere |
| Emoji-only reply after text reply | **-0.3 ~ -0.4** | depends |
| "哈哈" / "笑死" after partner's joke | **+0.3 ~ +0.5** | usually +0.2 |
| "哈哈" after self joke | 0 ~ +0.2 | 0 |
| Continuation in same topic, similar tone | **±0.2 ~ ±0.4** | ±0.2 |
| Topic switch (no emotional content) | **-0.5 ~ -1** | depends |
| Logistical question | **-0.2 ~ -0.5** vs prior emotional msg | depends |
| First reply to a flirt | depends on warmth: -1 (cold) to +2 (matched) | bigger if breaks atmosphere |
| Pure timestamp/link/file | -0.3 (drains energy) | -0.2 |

These are STARTING points. Read context, then adjust.

### vs_atmosphere quick guide

| This message | atmosphere has been... | vs_atmosphere |
|---|---|---|
| Logistic | hot/intimate (idx ~80+) | **-0.5 ~ -1.5** (below baseline) |
| Logistic | cool (idx ~50) | 0 ~ -0.3 |
| Flirty | hot baseline | 0 ~ +0.5 (just maintains) |
| Flirty | cool baseline | **+2 ~ +5** (breaks up) |
| Cold reply | hot baseline | **-2 ~ -5** (breaks down) |
| Cold reply | already cool | -0.3 ~ -1 |

---

## The 10 dimensions (semantic dictionary, only used for `primary_dim` tag)

### Core 7

**1. `affection`** — 情感温度
- 推涨：宝宝/想你/喜欢你/共笑哈哈哈/暖意问候/晚安宝贝
- 推跌：单字"哦/嗯/随便"/呵呵/无所谓/已读不回式短拒

**2. `engagement`** — 互动投入
- 推涨：长回复/主动延展/秒回/连发深入分享
- 推跌：敷衍短回/转移话题/拖延回/把话终结

**3. `care`** — 关心
- 推涨：关心身体/记得对方细节/迁就对方处境
- 推跌：漠视处境/嘲讽对方状态/求助被无视

**4. `conflict`** — 冲突轴（双向）
- 推涨（修复）：道歉/示弱/让步/解释/承认错误
- 推跌（攻击）：阴阳/翻旧账/最后通牒/冷战/人身攻击

**5. `tension`** — 暧昧张力
- 推涨：试探/吃醋/打闹/暧昧推进
- 推跌：明确划界/拒推进/把对方放友区

**6. `investment`** — 关系投入
- 推涨：主动约/锁定时间地点/送礼/见面/帮跑腿
- 推跌：拒邀约/取消计划/找借口

**7. `awkwardness`** — 默契度（反向：正分=默契）
- 推涨：接梗/共笑/流畅来回
- 推跌：尬聊/答非所问/突兀转场

### 新增 3 个

**8. `future_orientation`** — 未来导向
- 推涨：「等寒假回来」/「考完整起来」/「以后」/共同长期计划
- 推跌：明确切短「先到这吧」/拒绝谈未来

**9. `vulnerability`** — 暴露脆弱
- 推涨：分享秘密/感情史/弱点/家事/收入/恐惧
- 推跌：回避深入/筑墙/拒绝被了解

**10. `shared_identity`** — 内圈语言
- 推涨：用昵称/用内梗/「我们」/复用旧梗（首次或刷新时）
- 推跌：刻意外圈称呼/「同学请问你是哪位」式陌生化
- 注意：长期高频后会基线化——第 50 次「宝宝」是 0~+0.2，不是新增

---

## Worked examples (showing micro-fluctuations)

### A. 密集 flirt 段（atmosphere ~85）
| 上一条 | 这一条 | vs_prior | vs_atmo | 解释 |
|---|---|---|---|---|
| "想你了宝宝" (+3) | "我也想你" | +0.5 | 0 | 接住 +0.5（互文加分）|
| "我也想你" | "嘿嘿" | -0.4 | -0.2 | emoji 化轻 |
| "嘿嘿" | "干嘛呢" | -0.5 | -1 | 转日常，弱于氛围 |
| "干嘛呢" | "刚下课" | -0.3 | -1 | 平淡延续 |
| "刚下课" | "好巧 我也下课了" | +0.3 | -0.5 | 接住但比 flirt 弱 |
| "好巧 我也下课了" | "[旺柴]" | -0.4 | -0.7 | emoji 弱化 |

→ 这段共 6 条消息全部 nonzero，index 自然有上下波动 → 出现影线

### B. 冷战段（atmosphere ~40）
| 上一条 | 这一条 | vs_prior | vs_atmo | 解释 |
|---|---|---|---|---|
| "..." (-1) | "嗯" | +0.2 | -0.3 | 终于回了，轻微回暖 |
| "嗯" | "在吗" | +0.5 | +0.5 | 主动开话 |
| "在吗" | "嗯" | -0.5 | -0.3 | 又冷下去 |
| "嗯" | "对不起 是我不好" | +5 | +6 | 大修复 |
| "对不起 是我不好" | "..." | -2 | -1 | 没接住，短拒 |
| "..." | "你怎么这样" | -1 | -1 | 持续冷 |

→ 即使整段冷，仍有 micro-fluctuation

### C. 单条事件
| 场景 | vs_prior | vs_atmo |
|---|---|---|
| atmosphere 80，突然 "我们就是朋友" | -8 | -10 |
| atmosphere 30，突然 "你会不会喜欢我这种人" | +5 | +8 |
| atmosphere 50，普通"刚下课" | -0.3 | 0 |
| 12/26 后 4 天没聊，重启首条 "在干嘛" | +0.5 | -1 (氛围已凉) |

---

## Hard rules

1. **Stay in input order. Output `i` exactly as given.**
2. **Both deltas are signed real numbers (1 decimal).** Most are NONZERO small (±0.2~0.5).
3. **`0, 0` is rare** — < 15% of messages. If you exceed that, you're flattening.
4. **Don't compute index, OHLC, shadows, volume.** Framework's job.
5. **Don't predict outcomes** ("she likes you", "this will work").
6. **Don't echo timestamp/sender/message** — framework re-joins by `i`.
7. **One JSON object per line, no markdown fences.**
8. **No upper/lower bound on deltas** — index can break 100 or go below 0.
9. **Lean toward small nonzero (±0.3) when uncertain** — NOT toward 0.
10. **Self-check distribution** — re-scan your output before sending; if mostly 0,0, redo.

---

## What the framework does after you

```
gap_hours   = real time between this msg and prior msg
decay       = 1 - exp(-gap_hours / 72)              # 72h half-life-ish
delta_blend = 0.5 * delta_vs_prior + 0.5 * delta_vs_atmosphere

index_t = prev_index * (1 - decay) + 50 * decay + delta_blend
        # NO CLAMP. Can go above 100 or below 0.
```

Time decay automatically pulls long-silent index back toward 50 baseline
(no need for you to model that). Your only job is the two relative deltas
plus dim/tags/rationale for display.

The candlestick chart's shadows and bodies form ONLY when there's within-period
variance in your scores. **If you give all 0,0, the chart will be a flat line.
That's why micro-fluctuations matter.**
