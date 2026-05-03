# Relationship Candlestick Lab · 后端架构归档

定稿版本，下次修改前请确认是否真的需要动核心逻辑。

---

## 1. 数据流总览（API 与 Skill 完全一致）

```
        ┌─────────────────────────────────────────────────┐
        │                源数据 (CSV/JSON/TXT)             │
        │     微信导出 / pywxdump / 自己整理的纯文本        │
        └────────────────────────┬────────────────────────┘
                                 │
                       wechat_to_standard.py
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │ messages.jsonl  ← 标准化输入                     │
        │ {i, timestamp, sender, message}                  │
        └────────────────────────┬────────────────────────┘
                                 │
                  ╔══════════════╧══════════════╗
                  ║   preprocess_turns.py       ║
                  ║   (Step 1) 同 sender 聚合    ║
                  ╠═════════════════════════════╣
                  ║ - 单字 / URL / empty         ║
                  ║   → auto_scored.jsonl       ║
                  ║   (-0.2/-0.2/engagement)    ║
                  ║ - 其余消息按 sender 切换聚合 ║
                  ║   gap ≤ 10min → turns.jsonl ║
                  ╚══════════════╤══════════════╝
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │ turns.jsonl                                      │
        │ {turn_id, sender, ts_first, ts_last, n_msgs,    │
        │  original_is, text}                              │
        └────────────────────────┬────────────────────────┘
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
       (Step 2a) API 模式               (Step 2b) Skill 模式
       score_turns_api.py               LLM (Claude / GPT) 通过
       score_turns_deepseek.py          skill/SKILL.md 规则评分
                │                                 │
                │  并发批量调用 LLM                 │  人 / Claude Code
                │  按 SKILL.md 规则评分             │  在 IDE 里逐批评分
                │                                 │
                └────────────────┬────────────────┘
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │ turns_scored.jsonl ← 同样的 schema               │
        │ {turn_id, delta_vs_prior, delta_vs_atmosphere,   │
        │  primary_dim, tags, rationale}                   │
        └────────────────────────┬────────────────────────┘
                                 ▼
                       expand_turns.py
                       (Step 3) 反扩展到 i 级
                                 │
        ┌────────────────────────┴────────────────────────┐
        │ scored.jsonl  ← K 线系统输入                     │
        │ {i, delta_vs_prior, delta_vs_atmosphere,         │
        │  primary_dim, tags, rationale}  全 9322 / 1170 条 │
        │ (turn 首条带 delta，其余给 0/0)                  │
        └────────────────────────┬────────────────────────┘
                                 ▼
                     POST /api/ingest
                     (server.py)
                                 │
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │  K 线 / 成交量 / 主导维度 / 关键时刻             │
        │  http://127.0.0.1:7000                          │
        └─────────────────────────────────────────────────┘
```

---

## 2. API 路径 vs Skill 路径并列对比

| 阶段 | API 路径（前端用户） | Skill 路径（IDE 用户） |
|---|---|---|
| **入口** | 浏览器打开 `http://127.0.0.1:7000`，前端 ingest CSV → 后端自动调外部 API | 在 Claude Code / Codex 里输入 `/rcl-score` |
| **CSV → messages.jsonl** | server 后台调 `wechat_to_standard.py` | LLM 通过 Bash 调 `wechat_to_standard.py` |
| **预处理（剔单字 + 聚合 turns）** | server 后台调 `preprocess_turns.py` | LLM 通过 Bash 调 `preprocess_turns.py` |
| **打分** | server 调 `score_turns_api.py` / `score_turns_deepseek.py` 并发 LLM API | LLM 自己按 SKILL.md 规则给每批 turns 打分 |
| **扩展回 i 级** | server 调 `expand_turns.py` | LLM 通过 Bash 调 `expand_turns.py` |
| **可视化** | 同一前端自动跳转到 K 线页 | LLM 把 scored.jsonl 路径告诉用户，让用户在前端 ingest |

> **注**：API 用户**不走 CLI**，全部交互都在浏览器前端完成。Skill 路径
> 服务希望在 IDE（Claude Code / Codex / GPT 客户端）里直接对话评分的用户。

### 共享的核心 Spec（**两条路径必须一模一样**）

1. **预处理规则** (`scripts/preprocess_turns.py`)
   - 单字 / 纯 URL / 空消息 → auto_scored，固定打 `-0.2/-0.2/engagement/[]/""`
   - 其余消息按 sender 切换聚合，相邻间隔 ≤ 10 分钟才合一个 turn
   - 聚合用 `\n` 拼接 message 文本

2. **评分 schema** (`skill/SKILL.md` v3.1)
   ```json
   {
     "turn_id": int,
     "delta_vs_prior":      float,    // ±0.2~0.5 微波动 / ±5~8 大事件
     "delta_vs_atmosphere": float,    // 同上
     "primary_dim": "engagement" | "affection" | "care" | "conflict" |
                    "tension" | "investment" | "awkwardness" |
                    "future_orientation" | "vulnerability" | "shared_identity",
     "tags": [str],                   // 自由附加标签
     "rationale": str                 // ≤ 8 中文字符；琐碎留空 ""
   }
   ```

3. **扩展回 i 级规则** (`scripts/expand_turns.py`)
   - turn 内**首条** original_i → 拿到完整 delta + dim + tags + rationale
   - 其他 original_i → 0/0/engagement/[]/""（不再贡献 K 线）
   - auto_scored 的 trivial 消息保留 -0.2/-0.2

4. **K 线计算** (`relationship_candlestick/ohlc.py`)
   - 每 message_i 通过时间衰减递推到 `relationship_index`
   - OHLC 按 timeframe 聚合：`open=首条 idx, close=末条 idx, high=max, low=min`
   - calendar 模式 silent 周期 flat carry-forward (O=H=L=C=prev)

5. **技术指标** (`relationship_candlestick/indicators.py`)
   - 纯 numpy/pandas 算 MA / EMA / BBands / MACD / RSI / KDJ
   - 完全本地，永远不调 LLM

---

## 3. 文件清单（按职责分组）

### 核心 Spec（两路径共享）
```
skill/SKILL.md                         # v3.1 评分规则 + Skill 入口
config/default_weights.yaml            # 数值参数（threshold / volume）
```

### 流水线脚本（两路径共享）
```
scripts/wechat_to_standard.py          # 微信 CSV → 标准 CSV
scripts/preprocess_turns.py            # 标准 CSV → turns.jsonl + auto_scored.jsonl
scripts/score_turns_api.py             # API 模式（Anthropic）
scripts/score_turns_deepseek.py        # API 模式（DeepSeek，OpenAI 兼容）
scripts/score_turns_dispatch.py        # Subagent 模式：切批文件给 CC fan-out
scripts/expand_turns.py                # turn 级 → i 级
scripts/pipeline_turns.py              # API 模式 一键编排
```

### 计算 / 渲染层
```
relationship_candlestick/
├── ai_scorer.py        # 旧 v3 接口（少用）
├── api_scorer.py       # 旧串行 API scorer（少用，新代码用 scripts/score_turns_*）
├── ohlc.py             # K 线聚合 + per-bar attribution（top_dims/top_events）
├── indicators.py       # MA/BB/MACD/RSI/KDJ
├── volume.py           # 成交量公式
├── parser.py           # CSV/JSON/TXT 解析
├── server.py           # FastAPI 后端 (port 7000)
└── cli.py              # rcl analyze/ingest/serve 命令
frontend/
├── index.html          # 单页应用
├── app.js              # 图表逻辑（lightweight-charts v5）
└── style.css
```

---

## 4. 关键决策记录

| 决策 | 理由 |
|---|---|
| **聚合 turns** 而不是逐条评分 | 节省 60%+ LLM 调用；金融数据"一句话一个事件"语义更合理 |
| **单字消息独立 auto_scored** 不进 turns | 单字本质是噪声，统一打低分避免 LLM 浪费 token |
| **scored.jsonl turn 首条带 delta，其余 0/0** | K 线"事件点"语义；累积 index 不会被同一 turn 重复影响 |
| **fake time mapping**（前端） | active-only 模式 bar 时间戳间隔不均，lightweight-charts 默认按真实时间画间距 → 大空白。改用 1 day step fake time 强制等距 |
| **lightweight-charts v5** 而非 v4 | v5 原生支持 multi-pane（MACD/RSI/KDJ）+ 共享时间轴，省掉 v4 时代手撸 sync 的所有 bug |
| **本地 indicators.py** 而非 LLM 算 | 数学可重复 / 零成本 / 即时响应 |
| **active-only 默认** 而非 calendar | 聊天数据天然稀疏，silent 天画衰减细线干扰多于信息；用户可手动切 calendar |

---

## 5. 一致性保证：用 API 和用 Skill 评出来的结果应当**完全等价**

只要：
- 输入相同（同一 CSV）
- 都走 `preprocess_turns.py`（保证 turns.jsonl 完全相同）
- LLM 都按 `skill/SKILL.md` v3.1 规则评分
- 都走 `expand_turns.py`

→ 输出 `scored.jsonl` 应当**逐条等价**（仅 LLM 主观判断的微小差异）。

差异来源**只能是**：
1. LLM 模型不同（Sonnet vs DeepSeek vs GPT-5）→ rationale 措辞和 delta 大小有 ±0.1 的合理浮动
2. LLM 温度 / batch context 不同 → 同一条消息可能被不同模型评出 +0.3 vs +0.5
3. Skill 模式人工干预 → 用户可能手动调整某些 turn 的 delta

不应当出现的差异：
- ❌ 维度名错了（必须是 10 个之一）
- ❌ schema 字段错了
- ❌ 单字消息没被剔除
- ❌ turn 聚合阈值跟脚本不一样

---

## 6. Server API 接口

```
POST /api/ingest       body: {scored_path, calendar_mode, initial_index}
                       返回 {id, status, ...}

POST /api/jobs         body: 完整分析 job（API 内部模式，少用）

GET  /api/jobs/{jid}                    job 状态
GET  /api/jobs/{jid}/ohlc?tf=...        K 线数据 + per-bar top_dims/top_events
GET  /api/jobs/{jid}/events             所有打分事件
GET  /api/jobs/{jid}/indicators?tf=&spec=...   技术指标
GET  /api/jobs/{jid}/timeframes         可用时间框列表
```

---

## 7. 多厂商 API 集成清单

前端 `PROVIDER_CONFIG` 已暴露下面所有厂商。后端 `score_turns_*.py`
当前只实现了 Anthropic 和 OpenAI 兼容两种协议；接入新厂商时只需要把
对应 `base_url` 传给 OpenAI client 即可。

| 厂商 (provider) | 协议 (api_format) | base_url | SDK / 调用方式 | 鉴权 header |
|---|---|---|---|---|
| **anthropic** | `anthropic` | （SDK 内置）`https://api.anthropic.com` | `anthropic.AsyncAnthropic` `client.messages.create()` | `x-api-key: <KEY>` + `anthropic-version: 2023-06-01` |
| **openai** | `openai` | `https://api.openai.com/v1` | `openai.AsyncOpenAI` `client.chat.completions.create()` | `Authorization: Bearer <KEY>` |
| **deepseek** | `openai` | `https://api.deepseek.com/v1` | 同 OpenAI SDK，换 `base_url` | 同 OpenAI |
| **google** (Gemini) | `openai` | `https://generativelanguage.googleapis.com/v1beta/openai` | 同 OpenAI SDK + 兼容端点 | `Authorization: Bearer <GOOGLE_API_KEY>` |
| **xai** (Grok) | `openai` | `https://api.x.ai/v1` | 同 OpenAI SDK | 同 OpenAI |
| **moonshot** (Kimi) | `openai` | `https://api.moonshot.cn/v1` | 同 OpenAI SDK | 同 OpenAI |
| **qwen** (通义千问) | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 同 OpenAI SDK | 同 OpenAI |
| **zhipu** (智谱 GLM) | `openai` | `https://open.bigmodel.cn/api/paas/v4` | 同 OpenAI SDK | 同 OpenAI |
| **doubao** (字节豆包) | `openai` | `https://ark.cn-beijing.volces.com/api/v3` | 同 OpenAI SDK | 同 OpenAI |
| **ernie** (百度文心) | `openai` | `https://qianfan.baidubce.com/v2` | 同 OpenAI SDK（千帆 v2 兼容端点） | 同 OpenAI |
| **custom** | `openai` | 用户填 | 同 OpenAI SDK | 同 OpenAI |

### 后端最小集成代码（后续要做）

```python
# server.py 拓展 JobRequest:
class JobRequest(BaseModel):
    ...
    provider:   str = "anthropic"
    api_format: str = "anthropic"   # "anthropic" | "openai"
    base_url:   Optional[str] = None
    model:      str = "claude-sonnet-4-6"

# _run_job 分流：
if req.api_format == "anthropic":
    score_with_api(...)              # 走 score_turns_api.py
else:  # "openai"
    score_with_openai_compat(
        base_url=req.base_url,
        model=req.model,
        api_key=req.api_key,
    )                                # 走 score_turns_deepseek.py 同款逻辑
```

### 关键差异点

- **Anthropic Messages API**：`system` 参数独立于 `messages` 列表，`role` 只能是 `user/assistant`。
- **OpenAI Chat Completions API**：`system` 是 `messages` 列表里的第一条。
- **Gemini OpenAI 兼容端点**：`max_tokens` 字段名仍是 OpenAI 风格；某些参数 (e.g. `temperature`) 行为略不同。
- **百度千帆 v2**：自 2024 末统一到 OpenAI 兼容；以前的 v1 endpoint 已废弃。
- **DashScope (Qwen)**：用 `compatible-mode` 子路径才是 OpenAI 兼容；`/v1` 是阿里原生协议。

### 模型默认列表更新策略

`PROVIDER_CONFIG` 在 `frontend/app.js` 里写死。新模型出来时直接改这个
对象的 `models` 数组即可（不需要后端改动），用户也可以在 UI 上选
"自定义模型 ID" 临时填任意 model id 而不用动代码。

---

## 8. 历史包袱（保留但少用）

```
relationship_candlestick/api_scorer.py    # 旧串行 API scorer
relationship_candlestick/ai_scorer.py     # 旧 v3 evaluator
scripts/score_b*.py                        # 早期单批评分脚本（已被 score_turns_*.py 取代）
```

新代码请使用 `scripts/score_turns_*.py` + `scripts/expand_turns.py`。

---

**最后更新**：2026-05-03
**状态**：后端定稿，下面进入前端开发阶段。
