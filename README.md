> 把两个人的聊天记录，压缩成一张 K 线走势图。

**像读股票 K 线一样，读一段关系的变化。**

系统先对聊天记录里的**每一条消息**进行量化：
一条冷淡回复会让关系价格下跌，一句暧昧称呼会让价格上涨，一次吵架会形成下探，一次解释和修复会把价格重新拉回。

当每条消息都被转化成带时间戳的关系指数后，系统再把这些指数按 5 分钟、1 小时、日线、周线等周期压缩成 K 线蜡烛图：

- **Open**：这个周期开始时的关系指数
- **High**：这个周期内关系最热的时刻
- **Low**：这个周期内关系最冷的时刻
- **Close**：这个周期结束时的关系指数
- **Volume**：这段时间的互动密度和情绪强度

所以，一根关系 K 线不是模型主观生成的，而是由消息级指数路径自然聚合出来的。
上影线代表关系曾经冲高但回落，下影线代表关系曾经下探但被修复。

---

## 它能给你什么

- **K 线 + 成交量**：每根 bar 看那段时间的关系强度变化、互动密度
- **MA / 布林带 / MACD / RSI / KDJ**：你熟悉的技术指标，本地计算，零等待
- **每根 K 线的事件归因**：鼠标悬停 → 「这天主要是 *亲昵 +1.4 / 互动 -1.15* 在拉动」+ 4 条最有代表性的关键消息
- **多个时间周期**：5m / 15m / 30m / 1h / 2h / 4h / 日 / 周 / 月 / 季 / 年
- **历史分析记录**：每次跑过的任务都留在本机，随时回看

---

## 一键启动

下载本仓库后，按你的系统**双击**对应文件就行：

| 系统 | 双击 | 它会做什么 |
|---|---|---|
| **Windows** | `start.bat` | 找到 Python → 自动装缺的依赖 → 启动后端 → 自动开浏览器 |
| **macOS / Linux** | `start.sh` | 同上（首次需 `chmod +x start.sh`） |
| 任何系统 | 命令行跑 `python start.py` | 同上 |

> 前提：你电脑上有 **Python 3.9+**。
> 没有的话去 [python.org/downloads](https://www.python.org/downloads/) 装一个，
> Windows 安装时记得勾上 *Add Python to PATH*。

启动后浏览器自动打开 `http://127.0.0.1:7000`，会让你二选一：

| | 适合谁 |
|---|---|
| **本地分析（Skills 模式）** | 你已经在用 Claude Code / Codex 等 IDE，希望聊天数据完全不出本机 |
| **在线分析（API 模式）**   | 想直接图形化操作，愿意把聊天发给所选模型厂商 |

---

### 如果你想手动来

也行，传统三步：

```bash
git clone https://github.com/ZhenyuanPAN822/relationship-candlestick-lab.git
cd relationship-candlestick-lab
pip install -r requirements.txt

# 选装一个 LLM SDK（按你要走的厂商）
pip install anthropic              # 走 Claude
pip install "openai>=1.30"          # 走 GPT / DeepSeek / Gemini / 国产八家

# 启动
python -m relationship_candlestick.cli serve
# → 浏览器打开 http://127.0.0.1:7000
```

---

## 两条工作流

### 路线一 · 本地分析（Skills 模式）

聊天记录全程不出本机。**适合敏感对话**。

1. 在你常用的 IDE（Claude Code / Codex / GPT 桌面端…）里把本仓库的 `skill/SKILL.md` 注册为 Skill
2. 在 IDE 中输入 `/rcl-score`
3. Skill 会引导你粘聊天文件路径，然后自动跑：拆单字 → 聚合连发 → 逐条评分 → 反扩展回消息级
4. 跑完会给你一份本机评分文件的路径
5. **双击 `start.bat`（Windows）或 `start.sh`（macOS / Linux）启动网页**
6. 浏览器自动打开后选「导入本地文件」，把刚才的路径粘进去

> 推荐：Claude Sonnet 4.6 + effort `low`，或 GPT-5 系列 + effort `low`。
> 1000 条消息约 7 分钟。

### 路线二 · 在线分析（API 模式）

让网页端直接调外部模型 API 跑。

1. **双击 `start.bat`（Windows）或 `start.sh`（macOS / Linux）启动网页**
2. 浏览器自动打开 `http://127.0.0.1:7000`，选「在线分析」
3. 选厂商 + 模型，填 API Key，给聊天文件路径
4. 进度跑完自动跳到 K 线页

支持的厂商（每家都内置最新主流型号，也能自定义模型 ID）：

| 厂商 | 协议 |
|---|---|
| Anthropic（Claude） | Anthropic SDK |
| OpenAI（GPT） · DeepSeek · Google Gemini · xAI（Grok） · Moonshot（Kimi） · 通义千问 · 智谱 GLM · 字节豆包 · 百度文心 ERNIE · 任意 OpenAI 兼容端点 | OpenAI 兼容 |

---

## 输入格式

支持 **CSV / JSON / TXT**：

- **CSV**（推荐）：微信导出 CSV、pywxdump、Memotrace 等都能识别
- **JSON**：数组，每条 `{timestamp, sender, message}`
- **TXT**：每行 `YYYY-MM-DD HH:MM[:SS] sender: message`

`examples/` 下有三种格式的合成示例可参考。

---

## 项目结构

```
relationship-candlestick-lab/
├── relationship_candlestick/   ← Python 后端模块
│   ├── pipeline.py             核心：预处理 + 评分 + 反扩展
│   ├── server.py               FastAPI Web 后端
│   ├── ohlc.py                 K 线聚合 + 每根 bar 的归因
│   ├── indicators.py           MA / 布林带 / MACD / RSI / KDJ（纯本地）
│   ├── parser.py               CSV / JSON / TXT 解析
│   └── cli.py                  命令行入口
├── frontend/                   ← 前端单页应用
├── scripts/                    ← 流水线 CLI 脚本
├── skill/SKILL.md              ← Claude Code Skill 入口 + v3.1 评分规则
├── config/default_weights.yaml ← 数值参数
├── examples/                   ← 合成示例数据
├── tests/                      ← 39 个 pytest 单元测试
├── ARCHITECTURE.md             ← 架构 + 多厂商 API 接入清单
└── README.md
```

---

## 评分规则（v3.1）

10 个语义维度：

| 维度 | 含义 |
|---|---|
| affection | 亲昵 / 喜欢 |
| engagement | 普通互动 |
| care | 关心 / 操心 |
| investment | 投入精力 / 时间 |
| vulnerability | 暴露脆弱 / 自我剖白 |
| shared_identity | 共同身份 / 默契 |
| future_orientation | 未来导向 |
| tension | 暧昧紧张 |
| conflict | 冲突 |
| awkwardness | 尴尬 |

每条消息 LLM 给两个相对 delta（vs 上一条 + vs 整体气氛）+ 一个主导维度 + 标签 + 简短理由。
本地 Python 用时间衰减递推算出 `relationship_index`，再聚合成 OHLC。

完整规则见 [`skill/SKILL.md`](skill/SKILL.md)，架构细节见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

---

## 隐私

- **本地分析**：聊天数据全程不出本机
- **在线分析**：聊天文本会发送给你选的厂商。敏感对话请走本地分析
- API Key 只在浏览器本会话使用，**不写入** localStorage
- 文件路径**不写入** localStorage（早期版本会写，从 v6 起严格不写）
- `.gitignore` 默认排除 `output/`，分析结果不会被误推到仓库
- 本仓库不收集任何遥测，不上报使用数据

---

## 它**不**能干的事

- 不预测对方真实想法、不预测关系结果
- 不做"TA 喜不喜欢你"这种主观判断
- 它只读你能在聊天里看见的信号，给一个走势图

如果你想用它来做决定，请先意识到这只是一种**事后视角的可视化**。

---

## License

MIT — 详见 [`LICENSE`](LICENSE)。
图表库 lightweight-charts 是 Apache 2.0。
