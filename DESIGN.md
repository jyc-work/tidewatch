# tidewatch（观潮）· A 股市场图谱 设计方案 v1.0

> 状态：**P0 + P1 完成，P2 完成**；站点内网上线（`http://100.70.84.18:8080/`，864 页）
> 目标：复刻 `https://openbit.trade/` 的产品形态，改为适配中国 A 股，部署在 NAS，**对外公开发布（海外+国内）**。
> 硬约束：**不依赖 Windows 常开，不依赖 QMT 常在线。**
>
> **v0.2**：数据源改为**东财/同花顺/腾讯直连**（免 key，已实测）。
> **v0.3**：确认 **中英双语** + **公网对外发布**。
> **v0.4**：确认 **海外+国内双发布**、概念板块 **Top 100**、英文公司名策略。
> **v0.5**：按评审意见收紧数据可信度（命名冻结/运行账本/溯源字段/证据分层/验收合同）。
> **v0.6**：**P0 交付**（数据层 + SQLite + 板块管道）。
> **v0.7**：**P1 交付**（静态渲染 + 中英双语 + 发布守门 + nginx 托管）。
> **v0.8**：**板块全量**（90 行业 + 98 概念）+ **P2 游资**（龙虎榜 838 记录/240 席位）。
> **v0.9**：**席位映射回填**（`operatedept_code` 0/33 → 27/33），游资页显示社区别名；修复 4 个实战 bug。
> **v1.0（2026-10-05）**：**P2 完成**——**资金雷达**（涨停/炸板/跌停/强势池，272 条 + 连板梯队），
> 站点 **864 页**，**31 单测全绿**，代码 2499 行。

---

## 0. 文档目的

本文档只回答四件事：

1. openbit 有哪些模块，A 股能不能换、换成什么
2. 数据从哪来（结论：**改用同花顺 HTTP API，QMT 降级为可选**）
3. 系统怎么搭、跑在哪（结论：**NAS 单机全流程**）
4. 复用哪些现成代码，分几期做

评审通过后再动手。**未通过前不写业务代码。**

### 0.1 命名冻结（评审点 1）

文档曾同时出现 `tidewatch` / `atlas` / `src/atlas` / `atlas run`，现冻结：

```text
仓库/项目：tidewatch
Python 包：tidewatch          →  src/tidewatch/
CLI：     tidewatch            →  tidewatch run --stage sectors
产品中文名：观潮
域名：   可与项目名不同（如 stockatlas.cn，§7.5）
```

> 三者不一致会在开工后造成命令、模块、部署目录到处混用，因此**任何新代码不得再出现 `atlas` 作为包名/CLI**。

---

## 1. 目标与非目标

### 目标

- 复刻 openbit 的核心信息架构：**板块图谱 + 聪明钱 + 个股研究 + 追踪 + 雷达**
- 「人物持仓」替换为 A 股口径：**游资 / 基金经理 / 机构**
- 每交易日收盘后自动出数，产出静态页面
- 全部运行在 NAS，**Windows 可以一直关机**
- **对外公开发布**：中英双语静态站，托管在公网 CDN（§7.3）

### 非目标（明确砍掉）

| 砍掉 | 原因 |
|---|---|
| 期权雷达 `/tools/options-radar` | 用户明确不要；且国内场内期权标的太窄 |
| Polymarket 预测市场 `/tools/polymarket` | 国内无对应物，且涉合规灰区 |
| 实盘交易 / 下单 | 本项目定位是研究展示，不做交易通道 |
| 分钟级 / Tick 实时行情 | 数据源不提供，且与"收盘后更新"的产品模式冲突 |
| 社区运营功能（发帖/IM） | 本期只做只读展示，社区留占位页 |

---

## 2. 参考对象拆解：openbit.trade 全站模块

以下为 2026-10-05 实际抓取 `sitemap.xml` + 各页 meta 得到的**完整**结构，共 19 个静态页 + 4 类动态页。

### 2.1 页面清单

| # | 路径 | 模块名 | 页面描述（原文摘要） |
|---|---|---|---|
| 1 | `/` | 首页 | 挑 5 只股票交给引擎，看它现在怎么判、依据是什么 |
| 2 | `/ask` | 开问 ASK | 从覆盖的板块/逻辑/机构说法里抽因果子图，只用抽出来的数据写结论 |
| 3 | `/market/sectors` | 板块图谱 SECTORS | 行业与概念板块的当日/5 日/20 日表现与强弱四段 |
| 4 | `/market/sectors/{code}` | 板块详情 | 成分股 + 引擎逻辑 + 谁在买 |
| 5 | `/stocks` | 股票研究 | 搜索一只股票，看核心叙事、驱动关系、反证、下一验证点 |
| 6 | `/stocks/{ticker}` | 个股研究页 | 同上，单标的 |
| 7 | `/stocks/dossier` | 档案 DOSSIER | 一个对象的全部判断、改写记录、下一个可验证事件 |
| 8 | `/people` | 聪明钱 FILINGS | 按人物或机构查看已披露持仓（13F / 13D / PTR / 日度） |
| 9 | `/people/{slug}` | 人物详情 | 申报主体、披露口径、涉及证券、已披露交易记录 |
| 10 | `/monitor` | 追踪 MONITOR | 库内可追踪的人/板块/逻辑/标的，各带最近记录 |
| 11 | `/monitor/list` | 叙事追踪 | 最多 5 只股票，只在核心逻辑强化/削弱/分歧/证伪时更新 |
| 12 | `/tools/market-radar` | 市场雷达 | 全市场涨跌分布、52 周新高新低、板块多窗口动量与领涨股 |
| 13 | `/tools/flow-radar` | 主力资金雷达 | 四层资金流与筹码结构：吸筹/出货/背离/筹码异动四榜 |
| 14 | `/tools/insider` | 高管异动 | Form 4 个人级增减持，单笔大额 + 同期多人同向 |
| 15 | `/tools/portfolio-checkup` | 持仓体检 | 上传持仓截图，测算共同驱动暴露，截图不落盘 |
| 16 | `/community` | 社区 | 社群入口、工具清单与运行状态 |
| 17 | `/lab` | 实验室 | 尚在验证的能力：是什么、依据、状态与限制 |
| 18 | `/insights` | 洞察 | 教程/方法论文章 |
| 19 | `/insights/{slug}` | 洞察详情 | 如「form-4-transaction-codes」「how-to-read-13f-filing」 |

### 2.2 关键技术特征（必须继承）

1. **离线批处理 + 静态页**：HTML 里直接内嵌数据，页面明确标注"快照日期"（如 `交易日：2026-10-02`）。**不是实时行情站。**
2. **SEO 优先**：`sitemap.xml` 分 4 个子图（pages/stocks/sectors/people），多语言 `hreflang`（zh-CN/zh-TW/en）。
3. **合规话术内建**，这是最有价值的设计：
   - 每页写明「资料可以说明什么 / 不能说明什么」
   - `披露存在时间差，不代表当前持仓或实时交易`
   - AI 产出标注为**引擎整理的研究观点**，从不写成事实
   - 首页直接写「不提供盘口数据与仓位建议」
4. **多语言**：zh-CN / zh-TW / en（A 股版可先只做 zh-CN，保留 i18n 结构）

---

## 3. 模块取舍与 A 股映射

| openbit 模块 | A 股方案 | 数据可得性 | 本期 |
|---|---|---|---|
| 首页 | 挑 5 只看研判 | ✅ | P1 |
| 开问 ASK | LLM 问答（复用你已有 LLM 链路） | ✅ | P3 |
| **板块图谱** | 东财行业（496）+ 概念板块（504） | ✅ **已实测** | **P1** |
| **板块详情** | 成分股 + 涨停梯队 + 龙虎榜 | ✅ | **P1** |
| 股票研究 | 个股页：行情 + 财务 + 估值 + 异动 | ✅ | P2 |
| 档案 DOSSIER | 判断历史 + 待验证事件 | ⚠️ 需自建 | P3 |
| **聪明钱 FILINGS** | **游资 / 基金经理 / 机构**（见 §3.1） | ⚠️ 需映射 | **P2** |
| 追踪 MONITOR | 自选板块/标的追踪 | ✅ | P3 |
| 市场雷达 | 涨跌分布 + 涨停池 + 板块动量 | ✅ | P2 |
| 主力资金雷达 | 涨停/炸板/连板/异动/热榜（**非传统资金流**，见 §3.2） | ⚠️ 部分 | P2 |
| 高管异动 | 董监高增减持（**数据源未确认，见 §13**） | ❓ | P4 |
| 持仓体检 | 上传截图 → 共同暴露 | ⚠️ 需自建 | P4 |
| 社区 / 实验室 / 洞察 | 静态占位 + 方法论文 | ✅ | P4 |
| ~~期权雷达~~ | — | — | 砍 |
| ~~Polymarket~~ | — | — | 砍 |

### 3.1 「人物持仓」→ 游资 / 基金经理 / 机构

openbit 的 `/people` 本质是**公开披露记录整理**，不是实时持仓。它混合了 4 种口径：`13F`（机构季报）、`13D`（举牌）、`PTR`（国会申报）、`日度`（ARK ETF）。

A 股替换方案：

| openbit 口径 | A 股替换 | 主键 | 数据来源 | 可得性 |
|---|---|---|---|---|
| 国会 PTR（最有"人味"的） | **游资**（龙虎榜营业部席位） | 席位 → 游资别名 | `special_data_dragon_tiger_list` | ✅ |
| 13F 机构持仓 | **基金经理**（比机构更像"人"） | 基金经理 | `fund_managers_*` + `fund_portfolio_stock_history` | ✅ |
| 13F / 13D | **机构**（基金公司 / 社保 / 险资 / QFII） | 机构 | `fund_portfolio_*` + 十大流通股东 | ⚠️ 部分 |
| ARKK 日度 | 场内 ETF 持仓 | ETF | `fund_portfolio_stock_history` | ⚠️ 滞后 |
| Form 4 内部人 | 董监高增减持 | 个人 | **源未确认** | ❓ |

**三类页面的落地形态：**

#### (1) 游资页 —— 最接近 openbit 的"人物"

核心是**一张人工维护的席位映射表** `mapping/seats.yaml`（**v0.2 已实现证据分层**）：

```yaml
# 已实现：字段结构（v0.2）
- operatedept_code: null          # ★ P0 必补，名称会因合并/更名变化，不能做主键
  name: "国泰海通证券股份有限公司武汉紫阳东路证券营业部"
  alias: "紫阳东路"
  classification: hot_money       # 行为特征分类（≠ 身份认定）
  classification_method: heuristic # heuristic | community | measured_stats
  confidence: medium
  activity_evidence: measured     # 只证明“出现过 + 金额”
  identity_evidence: unknown      # 未证实一律 unknown
  stats: {buy_yi: 115.52, sell_yi: 28.89, window: "2026-06..09"}
  source_query: "RPT_OPERATEDEPT_ACTIVE?filter=ONLIST_DATE>=2026-06-01"
```

**当前状态（已验证 YAML）**：33 条，无重名/重别名

| 维度 | 分布 |
|---|---|
| 分类 | hot_money 24 / quant_like 4 / foreign 3 / northbound 2 |
| activity_evidence | measured 22 / none 11 |
| identity_evidence | unknown 28 / claimed 3 / verified 2 |
| operatedept_code | **27/33（已由实测数据回填）** |

> **为什么要分层**：`activity_evidence: measured` 只能证明「这个席位在区间内出现且测得买卖金额」，
> 它**不能**证明这是某个自然人、是游资、或属于量化机构。
> 把两者合并会造成“用数据包装主观结论”，这是本项目要避免的。

每个游资一页展示：上榜次数、买入额、偏好标的、次日溢价（T+1 平均收益）、最近上榜记录。

> ⚠️ **合规红线**：席位 ≠ 具体自然人，映射是社区主观归纳。页面必须标注
> 「本页为公开龙虎榜席位的社区归纳口径，不代表特定自然人，不构成投资建议」。

#### (2) 基金经理页 —— 数据最扎实

以基金经理为主键：任职基金、季报十大重仓、行业配置、季度变动、任职回报。

这是三类里**唯一口径干净、来源权威**的（基金定期报告强制披露）。

#### (3) 机构页 —— 降级处理

公募 / 社保 / 险资 / QFII 的持仓只能从季报十大重仓 + 十大流通股东聚合，覆盖率低、滞后一个季度。**建议合并进「基金经理」页做附属视图，不单独做一级入口。**

#### (4) 量化机构 —— ❗ 明确不做

**私募量化持仓（幻方、九坤、明汯等）完全不公开，任何声称能拿到"量化机构持仓"的产品都是编的。**

可做的降级方案（本期不做，P4 再议）：

- 「公募量化基金」十大重仓 —— 如实展示，命名为**量化基金（公募）**
- 龙虎榜量化特征席位 —— 只能标为**疑似**，不能当事实
- 成交特征反推（换手率、日内反转）—— 只能做**标签**

> 如果一定要有这一栏，命名必须是「量化基金（公募）」+「量化特征席位（推断）」，
> **不能叫「量化机构持仓」**，否则是虚假陈述。

### 3.2 主力资金雷达：一个必须说明的落差

openbit 的 `flow-radar` 用的是美股四层资金流（tick 级买卖盘推断 + 筹码分布），四张榜：吸筹 / 出货 / 背离 / 筹码异动。

**东财 / 同花顺 / 腾讯都不提供标准资金流。** QMT 也没有标准资金流字段。

A 股可行替代（口径不同，页面必须说明）：

| openbit 榜 | A 股替代 | 数据 |
|---|---|---|
| 吸筹 | 涨停池 + 连板梯队 | `special_data_limit_up_pool`, `limit_up_ladder` |
| 出货 | 炸板池 + 跌停池 | `special_data_limit_break_pool`, `limit_down_pool` |
| 背离 | 异动分析 + 热榜趋势 | `special_data_anomaly_analysis_list`, `hot_stock_rank_trend` |
| 筹码异动 | 换手率/量比异常 | `prices_snapshot` 派生 |

> 若要真·资金流（主力净流入），需补 **Tushare Pro（约 ¥200–500/年）** 或东财接口。
> **本期不做，P4 再评估。**

---

## 4. 数据源方案（2026-10-05 已在 NAS 逐接口实测）

### 4.0 结论先行：改为免费直连，不用 fuyao

初版方案以 `hithink-finance`（同花顺 fuyao HTTP API）为主数据源。**该前提已不成立**——`HITHINK_FINANCE_API_KEY` 目前没有。

改为 **东财 + 同花顺 + 腾讯 直连**，全部免费、无需 key，已在 NAS 上逐接口跑通（见 §4.2）。

fuyao 保留为**可选升级路径**：日后若申请到 key，其接口语义与 `fuyao_client.py` 一致，可平滑替换，但**不构成任何前置依赖**。

### 4.1 NAS 实测环境

| 项 | 值 |
|---|---|
| 主机 | `DX4600PRO-5192`（绿联 DX4600 Pro / UGOS Pro） |
| 内核 | Linux 6.18.15 |
| CPU / 内存 | 4 核 / **7.6 GiB（可用 3.4 GiB）** |
| 磁盘 | `/volume1` 3.6T，已用 787G（22%） |
| Python | 3.11.2 + pip 26.2（`--user`） |
| 已装 | `requests 2.32.3` `pandas 3.0.5` `numpy 2.4.6` `pyyaml 6.0.2` |
| 待装 | `jinja2`（**唯一新增依赖**，约 200KB） |
| 网络 | 东财 / 腾讯 / 同花顺 / PyPI **全部可达** ✅ |
| 同步 | `/volume1/docker/Python_Proj/` = 本机 `nas_codes/` 的 Syncthing 镜像（`.stfolder-kasq7wEHii` 对应） |

> **7.6G 内存是本方案坚持静态生成、不用 Next.js 常驻构建的硬理由**（见 §7.2）。

### 4.2 实测通过的接口清单

均为 `2026-10-05` 在 NAS 实跑，最近交易日 `2026-09-30`。

| # | 用途 | 接口 | 实测结果 |
|---|---|---|---|
| 1 | 行业板块列表 | `push2delay.eastmoney.com/api/qt/clist/get` `fs=m:90+t:2` | ✅ `total=496` |
| 2 | 概念板块列表 | 同上 `fs=m:90+t:3` | ✅ `total=504` |
| 3 | 板块 K 线（算 1/5/20 日） | `push2his.eastmoney.com/api/qt/stock/kline/get?secid=90.BK0475` | ✅ 返回 `klines[]` |
| 4 | **板块成分股** | `push2.eastmoney.com/api/qt/clist/get` `fs=b:BK0475` | ✅ 银行板块 42 只 |
| 5 | **涨停池** | `push2ex.eastmoney.com/getTopicZTPool` | ✅ 52 只（含连板/封单） |
| 6 | **龙虎榜明细** | `datacenter-web.eastmoney.com/api/data/v1/get` `reportName=RPT_DAILYBILLBOARD_DETAILSNEW` | ✅ 含 `EXPLAIN`、`D1_CLOSE_ADJCHRATE`（次日涨幅） |
| 7 | **买入席位** | 同上 `reportName=RPT_BILLBOARD_DAILYDETAILSBUY` | ✅ 含 `OPERATEDEPT_NAME` |
| 8 | **卖出席位** | 同上 `reportName=RPT_BILLBOARD_DAILYDETAILSSELL` | ✅ 如「国盛证券…宁波桑田路」 |
| 9 | 指数行情 | `qt.gtimg.cn/q=sh000001,sz399001` | ✅ |
| 10 | 板块指数历史（补充） | `d.10jqka.com.cn/v6/line/bk_881101/01/last.js` | ✅ 含全历史年份 |

### 4.3 ⚠️ 域名 fallback 策略（实测踩坑，必须实现）

东财**同一接口在不同域名下可用性不一致**：

| 接口 | `push2` | `push2delay` |
|---|---|---|
| 板块列表 | — | ✅ |
| 板块成分股 | ✅ | ❌ `RemoteDisconnected` |

**结论：数据层必须实现「双域名轮询 fallback」（`push2` ↔ `push2delay`），并在 `fetch_log` 记录实际命中域名。**

> 你 `daily-review` 的历史经验是「push2 被拦，用 push2delay」——本次实测**恰好相反**。
> 说明东财限流策略会变，**不能硬编码单一域名**。

### 4.4 接口 → openbit 模块映射

| openbit 模块 | 数据来源 |
|---|---|
| 板块图谱列表 | 接口 1 / 2 |
| 板块 1/5/20 日 + 强弱四段 | 接口 3（计算派生，口径见 §5） |
| 板块详情 · 成分股 | 接口 4 |
| 板块详情 · 谁在买 | 接口 6 / 7 / 8 |
| **游资（聪明钱）** | 接口 7 / 8 + 自建席位映射 `mapping/seats.yaml` |
| 资金雷达 | 接口 5（涨停池）+ 炸板 / 连板 / 异动接口 |
| 市场雷达 | 接口 9 + 接口 5 |
| 个股研究 | 接口 9 + 东财个股接口 |
| 基金经理 / 机构持仓 | ⚠️ **东财基金接口，P3 开工前需先实测**（见 §4.5） |

### 4.5 已知缺口

| 缺口 | 影响模块 | 处置 |
|---|---|---|
| 基金/基金经理接口未实测 | 聪明钱（机构侧） | P3 前先实测；**若不可用，本模块降级为「仅游资」** |
| 主力资金净流入（四层） | 资金雷达 | 用涨停 / 炸板替代；P4 评估 Tushare Pro |
| 筹码分布 / 成本分布 | 资金雷达 | 不做，页面说明 |
| 董监高增减持 | 高管异动 | 东财数据中心有接口，P4 实测 |
| 新闻 / 公告原文 / 研报 | 逻辑链 | 需另配源（东财公告接口 + LLM） |
| 北向资金 | 聪明钱 | 已停止实时披露，放弃 |

### 4.6 为什么不用 QMT

| 维度 | QMT / xtdata | 东财直连 |
|---|---|---|
| 运行环境 | **必须 Windows + 客户端常驻** | 任意 Linux / NAS |
| NAS 可用 | ❌ | ✅（已实测） |
| 龙虎榜 / 游资 / 涨停池 | ❌ | ✅ |
| 成本 | 券商授权 | 免费 |

**在「NAS 部署 + Windows 不常开」的约束下，QMT 直接出局。**
保留 `quant-lab/backend/data/qmt_cn.py` 作为「本机可选补充源」（K 线历史校验用），**不作为任何模块的前置依赖**。

> 保留 `DataSource` 抽象层（借鉴 `quant-lab/backend/core/datasource.py`），
> 使 `eastmoney` / `qmt` / `fuyao` / `mock` 可互换；本期默认实现为 `eastmoney`。

### 4.7 ⚠️ 限流与访问纪律（实测教训）

实测中因短时间连续请求东财，**IP 被临时封禁**（`RemoteDisconnected`）并持续数十分钟。
这是 P0 就必须实现的纪律，不是后期优化：

| 措施 | 要求 |
|---|---|
| 请求间隔 | 同域名 ≥ 1.0s，随机抖动 ±0.3s |
| 并发 | 单域名**串行**，不并发 |
| 退避 | 失败按 1s→2s→4s→8s 指数退避，最多 4 次 |
| 双域名 | `push2` ↔ `push2delay` 轮换（§4.3） |
| UA 池 | 轮换 User-Agent（复用 `daily-review/fetchers/http.py`） |
| 原始留存 | 每个响应写 `data/raw/{run_id}.json`，开发期优先读缓存 |
| 每日配额 | 记录当日请求数，超阈值告警 |

> **开发期铁律：先抓一次存到 `tests/fixtures/`，之后离线开发，不要反复打东财。**
> 这直接对应 §10.1 验收项 #8（离线可测）。

#### 被封不是常态，是探索导致的

被封的根因是**探索期连续几十次请求**，不是每日运行。每日正常出数只需很少请求：

| 数据 | 请求数（估） | 备注 |
|---|---|---|
| 行业+概念板块列表 | 2–6 | `clist` 分页，一次拿全量 |
| 板块多周期涨跌幅 | 0（合并） | 优先用 `clist` 的多周期字段，避免逐个拿 K 线 |
| Top 100 概念板块 K 线 | 100 | 仅当上面拿不到 5/20 日时才需要 |
| 龙虎榜明细 | 5–20 | 分页 |
| 涨停/炸板/连板池 | 3 | |
| **合计** | **~150–300** | 按 1s 间隔 = **3–5 分钟**，安全 |

> 所以 P0 的关键动作是：**合并请求 + 缓存 + 只拿变化的部分**，而不是想着换源。

#### 备用源（东财被封时的 fallback，已实测）

| 备用源 | 能提供 | 实测 |
|---|---|---|
| **新浪** `vip.stock.finance.sina.com.cn/q/view/newSinaHy.php` | 行业板块列表 | ✅ `S_Finance_bankuai_sinaindustry` |
| **同花顺** `d.10jqka.com.cn/v6/line/bk_XXXXXX/01/last.js` | 板块指数历史 | ✅ 含全历史 |
| **同花顺** `data.10jqka.com.cn/market/longhu/` | 龙虎榜 | ✅ HTML，需解析 |
| 腾讯 `qt.gtimg.cn` | 指数/个股行情 | ✅ |

**多源优先级：**

```text
板块行情：东财 → 同花顺 → 新浪
龙虎榜：  东财 → 同花顺
指数：    东财 → 腾讯
```

> 多源差异必须记入 `source_provider`（§6.2），**不同源不得拼成同一条序列**（§6.4）。

#### 如果 IP 仍被封：可选手段

| 手段 | 成本 | 评价 |
|---|---|---|
| 等恢复（几十分钟–几小时） | 0 | ✅ 首选 |
| 切备用源 | 0 | ✅ 已就绪 |
| 家庭宽带重拨换 IP | 0 | ⚠️ NAS 在机房/固定 IP 时不可行 |
| 代理池 | ¥/月，不稳定 | ⚠️ 仅在长期受限时考虑 |
| 换 Windows 出数 | 0 | ⚠️ 违背“Windows 不常开”约束 |
| 付费源（Tushare Pro） | ¥200–500/年 | ✅ 若长期受限，比代理池值 |

> **QMT 不是这个问题的解药**：QMT 没有龙虎榜、席位、涨停池、概念板块——
> 而这些正是本项目最核心的数据。QMT 只能做 K 线补充源（§4.6）。

### 4.8 同花顺接口细节（P0 主力源，已实测）

| 用途 | 接口 | 实测 |
|---|---|---|
| 行业板块列表 | `http://q.10jqka.com.cn/thshy/` | HTML，140 链接去重后 **90** 个，代码 **881xxx** |
| 概念板块列表 | `http://q.10jqka.com.cn/gn/` | HTML，**361** 个，代码 **30xxxx** |
| 板块 K 线 | `https://d.10jqka.com.cn/v6/line/bk_{code}/01/last.js` | JSONP，含 OHLC+成交额 |

**last.js 结构：**

```json
quotebridge_v6_line_bk_881101_01_last({
  "name": "种植业与林业", "total": 4628, "num": 140, "today": 20261005,
  "data": "20260311,开,高,低,收,量,额,,,,0;20260312,..."
})
```
每段字段：`date, open, high, low, close, volume, amount, ...(空), 0`

**⚠️ 代码体系不一致（P1 待解决）：**

| 类型 | 列表页代码 | K 线代码 | 状态 |
|---|---|---|---|
| 行业 | `881xxx` | `881xxx` | ✅ 直接可用 |
| 概念 | `30xxxx` | **`885xxx`** | ❌ 映射未知 |

实测：`bk_308614` → **404**，`bk_885800` → **200**。
所以概念板块（Top 100 需要）在 P1 必须先解决 `30xxxx ↔ 885xxx` 映射，或换数据源。

---

## 5. 核心指标口径

指标必须**自研并写清定义**，不能照抄 openbit（口径不同，抄了是错的）。

### 5.1 板块多窗口表现

```
ret_1d  = 板块指数(今收) / 板块指数(昨收) - 1
ret_5d  = 板块指数(今收) / 板块指数(T-5收) - 1
ret_20d = 板块指数(今收) / 板块指数(T-20收) - 1
```

- 板块指数优先用**东财板块指数**（接口 3，`secid=90.{板块代码}`）
- 若无指数点位，用成分股**等权收益均值**合成，并在页面标注「等权合成口径」
- 备用口径：同花顺板块指数（接口 10，`d.10jqka.com.cn`）

### 5.2 「强弱四段」定义（自研，需在页面公开）

按 20 日动量 × 当日动量 的正负四象限：

| 20日 | 当日 | 标签 | 语义 |
|---|---|---|---|
| + | + | **持续领涨** | 中期强、短期继续强 |
| + | − | **高位回落** | 中期强、短期转弱 |
| − | + | **超跌反弹** | 中期弱、短期转强 |
| − | − | **持续走弱** | 中期弱、短期继续弱 |

> openbit 的四段是它自己的口径，**不要试图对齐**。我们在页面写清定义即可。

### 5.3 游资指标

- 上榜次数 / 区间买入额（来自龙虎榜）
- 偏好标的（近 N 次上榜的行业分布）
- 次日溢价：该席位买入标的的 **T+1 平均收益**（用于衡量"跟风价值"，标注为统计值）
- 最近上榜记录明细

### 5.4 板块覆盖策略（已定）

| 类型 | 数量 | 策略 |
|---|---|---|
| 行业板块 | 496 | **全量**渲染 |
| 概念板块 | 504 | **Top 100**（按当日成交额降序） |

**Top 100 选择规则（必须固定且可复现）：**

- 排序键：板块当日**成交额**（稳定、可解释、代表资金关注度）
- 每日收盘后重算，当日 Top 100 上列表页
- **URL 稳定性**：曾入选过的板块详情页**永久保留**，不因掉出 Top 100 而删 URL，
  页面标注「近期未进入活跃 Top 100」

> 兼顾 SEO（链接不失效）与热点反映（列表每天更新）。
>
> 备选排序键：涨幅（波动大、每天换一批，不稳定）、综合热度（需自造指标）。
> 本期用**成交额**，后续可评估。

> ⚠️ **开放问题**：概念板块的成交额是东财直接给，还是用成分股加总？
> `clist/get` 对板块返回的 `f6`（成交额）需实测确认；若无则由成分股 `f6` 汇总。

---

## 6. 数据模型

### 6.1 存储选型

- **SQLite**（NAS 已有 `sqlite3`）：存历史、支持增量、便于口径追溯
- **JSON**：作为渲染中间产物（`data/snapshot/`）
- **静态 HTML**：最终产物（`dist/`）

之所以不只存 JSON：板块成分股和龙虎榜明细每天全量重取太贵，需要**增量 + 快照**两层。

### 6.2 核心表（草案）

> **设计原则（评审点 2/3）：每一个数字都必须能回答「从哪来、怎么算、什么时候可得」。**

```sql
-- ==================== 维度表 ====================
CREATE TABLE sector (
  sector_code TEXT PRIMARY KEY,      -- 东财板块代码 BKxxxx（稳定主键）
  name        TEXT NOT NULL,
  name_en     TEXT,                  -- 英文译名（§7.4）
  category    TEXT NOT NULL,         -- industry | concept
  updated_at  TEXT NOT NULL
);

-- ==================== 事实表：全部带溯源 ====================
CREATE TABLE sector_daily (
  sector_code        TEXT NOT NULL,
  trade_date         TEXT NOT NULL,
  close              REAL,
  ret_1d             REAL,
  ret_5d             REAL,
  ret_20d            REAL,
  stage              TEXT,           -- 强弱四段
  amount             REAL,           -- 成交额（Top 100 排序键，§5.4）
  -- 溯源字段（评审点 3：口径不可悄悄切换）
  source_provider    TEXT NOT NULL,  -- eastmoney | ths | synthetic
  source_symbol      TEXT,           -- 90.BK0475 / bk_881101 / NULL
  calculation_method TEXT NOT NULL,  -- index_direct | member_equal_weight | member_cap_weight
  member_snapshot_id INTEGER,        -- 指向成分快照
  available_at       TEXT NOT NULL,  -- 数据可得时间（PIT，不是抓取时间）
  input_hash         TEXT NOT NULL,  -- 输入指纹
  algorithm_version  TEXT NOT NULL,
  PRIMARY KEY (sector_code, trade_date)
);

-- 成分快照（成分会变，必须按快照分步）
CREATE TABLE sector_member_snapshot (
  snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  sector_code     TEXT NOT NULL,
  trade_date      TEXT NOT NULL,
  source_provider TEXT NOT NULL,
  input_hash      TEXT NOT NULL,
  UNIQUE (sector_code, trade_date, source_provider)
);

CREATE TABLE sector_member (
  snapshot_id INTEGER NOT NULL,
  stock_code  TEXT NOT NULL,
  PRIMARY KEY (snapshot_id, stock_code),
  FOREIGN KEY (snapshot_id) REFERENCES sector_member_snapshot(snapshot_id)
);

CREATE TABLE stock_daily (
  stock_code         TEXT NOT NULL,
  trade_date         TEXT NOT NULL,
  close              REAL, pct_chg REAL, turnover REAL, amount REAL,
  source_provider    TEXT NOT NULL,
  available_at       TEXT NOT NULL,
  input_hash         TEXT NOT NULL,
  algorithm_version  TEXT NOT NULL,
  PRIMARY KEY (stock_code, trade_date)
);

-- ==================== 龙虎榜 / 席位（评审点 4） ====================
CREATE TABLE lhb_record (
  trade_date      TEXT NOT NULL,
  stock_code      TEXT NOT NULL,
  operatedept_code TEXT NOT NULL,    -- 用代码而非名称做主键
  side            TEXT NOT NULL,     -- buy | sell
  amount          REAL, reason TEXT,
  source_provider TEXT NOT NULL,
  input_hash      TEXT NOT NULL,
  PRIMARY KEY (trade_date, stock_code, operatedept_code, side)
);

-- 席位表：把「出现证据」与「身份推断」分开（评审点 4）
CREATE TABLE seat (
  operatedept_code      TEXT PRIMARY KEY,  -- 东财席位代码（P0 就补，不是 P2）
  seat_name             TEXT NOT NULL,     -- 名称会因合并/更名变化，仅作展示
  last_seen_name        TEXT,
  -- 证据分层
  activity_evidence     TEXT,   -- measured | none（只证明“出现过+金额”）
  identity_evidence     TEXT,   -- unknown | claimed | verified（未证实一律 unknown）
  classification        TEXT,   -- hot_money | quant_like | foreign | northbound
  classification_method TEXT,   -- heuristic | community | manual
  classifier_version    TEXT,
  confidence            TEXT,   -- low | medium | high
  source_query          TEXT,   -- 证据来源（接口/页面）
  raw_hash              TEXT,
  updated_at            TEXT NOT NULL
);

-- ==================== 基金（P3） ====================
CREATE TABLE fund_manager (
  manager_id TEXT PRIMARY KEY, name TEXT, company TEXT, updated_at TEXT
);
CREATE TABLE fund_holding (
  report_date TEXT NOT NULL, fund_code TEXT NOT NULL,
  stock_code  TEXT NOT NULL, weight REAL, shares REAL,
  source_provider TEXT NOT NULL, input_hash TEXT NOT NULL,
  PRIMARY KEY (report_date, fund_code, stock_code)
);

-- ==================== 涨停/连板/异动 ====================
CREATE TABLE limit_up (
  trade_date TEXT NOT NULL, stock_code TEXT NOT NULL,
  pool_type  TEXT NOT NULL,          -- up | down | break
  ladder INTEGER, amount REAL,
  source_provider TEXT NOT NULL, input_hash TEXT NOT NULL,
  PRIMARY KEY (trade_date, stock_code, pool_type)
);
```

### 6.3 运行账本与写入原子性（评审点 2）

**`fetch_log` 升级为 `run_ledger`。** 原来的 `trade_date + task + status`
只能回答「跑过没」，回答不了「跑得对不对、用的是谁、结构变没变」。

```sql
CREATE TABLE run_ledger (
  run_id            TEXT PRIMARY KEY,     -- uuid，一次运行一个
  task              TEXT NOT NULL,        -- sectors / lhb / limit_up ...
  trade_date        TEXT,
  provider          TEXT,                 -- eastmoney | ths | tencent
  domain            TEXT,                 -- ★ 实际命中的域名（评审点 2）
  endpoint          TEXT,                 -- 实际接口路径
  started_at        TEXT NOT NULL,
  finished_at       TEXT,
  status            TEXT NOT NULL,        -- success | failed | partial
  row_count         INTEGER,
  raw_hash          TEXT,                 -- 原始响应指纹（可复核）
  schema_version    TEXT,                 -- 接口结构版本
  algorithm_version TEXT,                 -- 算法版本
  error_class       TEXT,                 -- network | schema | rate_limit | empty
  error_message     TEXT
);

-- 发布记录（每次 publish 一行，支撑守门与回滚追溯）
CREATE TABLE publish (
  publish_id        TEXT PRIMARY KEY,
  trade_date        TEXT NOT NULL,
  built_at          TEXT NOT NULL,
  page_count        INTEGER,
  data_hash         TEXT,
  algorithm_version TEXT,
  status            TEXT,                 -- published | rejected
  reason            TEXT
);
```

**强制流程（不可跳步，评审点 2）：**

```text
1. fetch      → 原始响应写 data/raw/{run_id}.json（保留证据）
2. validate   → 校验：条数区间 / 字段完整 / 日期==目标交易日
                任一不过 → status=rejected，停止，不写正式表
3. stage      → 写入 staging 表
4. commit     → 事务内原子写入正式表
5. compute    → 计算指标，写 algorithm_version
6. hash       → 计算数据快照哈希
7. render     → 渲染 dist.new/
8. verify     → 页面数 / 板块数 / 样例页面断言
9. publish    → 原子替换 dist/（dist.new → dist），写 publish 表
```

> **幂等判据不是「跑过没」，而是「当日 success 的 run_ledger 存在 +
> schema_version 一致 + algorithm_version 一致 + data_hash 可复现」**。
> 任一不一致 → 视为需重跑。

### 6.4 数据降级必须显式（评审点 3）

三种板块指数口径**不是同一种序列**，绝不能拼成同一条历史曲线：

| 口径 | source_provider | calculation_method | 使用条件 |
|---|---|---|---|
| 东财板块指数 | `eastmoney` | `index_direct` | 首选 |
| 成分股等权合成 | `synthetic` | `member_equal_weight` | 板块无指数时 |
| 同花顺板块指数 | `ths` | `index_direct` | 备用 |

**规则：**

1. 同一 `(sector_code, trade_date)` 只允许一种口径；
2. 口径变化必须在页面**显式标注**（如「等权合成口径」）；
3. 图表遇到口径切换时**断线**，不得平滑连接；
4. 换口径必须 bump `algorithm_version`，使旧快照可区分。

> 原则：**允许显式降级，但绝不允许静默换口径。**

---

## 7. 系统架构（NAS 优先）

### 7.1 数据流

```text
        ┌──────────────────────────────────────────┐
        │ NAS (绿联 DX4600 Pro / UGOS Pro)         │
        │                                          │
  ┌─────▼──────┐   ┌──────────┐   ┌────────────┐  │
  │ cron 15:40 │──▶│ pipeline │──▶│  SQLite    │  │
  │  (交易日)  │   │  fetch + │   │ data/*.db  │  │
  └────────────┘   │  归一化  │   └─────┬──────┘  │
                   └──────────┘         │         │
                                        ▼         │
                                 ┌────────────┐   │
                                 │  compute   │   │
                                 │ 动量/四段/ │   │
                                 │ 游资聚合   │   │
                                 └─────┬──────┘   │
                                       ▼          │
                                 ┌────────────┐   │
                                 │  render    │   │
                                 │ Jinja2 →   │   │
                                 │ 静态 HTML  │   │
                                 └─────┬──────┘   │
                                       ▼          │
                                 ┌────────────┐   │
                                 │  Caddy     │   │
                                 │ dist/ :8080│   │
                                 └─────┬──────┘   │
        └─────────────────────────────┼──────────┘
                                      │
                    Tailscale (内网)  │  Cloudflare Tunnel (日后外网)
                                      ▼
                                   浏览器
```

**关键点：整条链路没有 Windows，没有 QMT，没有常驻 GPU/大内存服务。**

### 7.2 为什么不用 Next.js / SvelteKit 常驻

| 方案 | NAS 成本 | 评价 |
|---|---|---|
| **Pelican/Jinja2 静态生成 + Caddy** | 极低（构建几分钟，托管几乎零开销） | ✅ **推荐** |
| Astro / 11ty 静态生成 | 低 | ✅ 可选，需 Node 构建 |
| Next.js `output: export` | 中（构建吃内存） | ⚠️ 备选，若复用 quant-lab 前端 |
| Next.js SSR 常驻 | 高（常驻 Node 进程） | ❌ 不做 |

openbit 本身就是**静态生成**（我抓到的 HTML 里直接内嵌了全部数据）。**照抄这个形态是对的**，既省钱又符合"收盘后更新"的产品语义。

前端交互用原生 JS + **ECharts**（本地打包，不引 CDN，NAS 内网无外网也能看）。

### 7.2.1 ASK 是独立动态服务（评审点 5）

**“纯静态架构”与 ASK 存在根本矛盾，必须显式拆分：**

| 层 | 内容 | 部署 |
|---|---|---|
| **静态核心** | 板块 / 个股 / 人物 / 雷达 | NAS 生成 → CDN，**无服务器** |
| **动态扩展** | ASK（问答） | **独立服务**，可关闭，不影响静态站 |

ASK 必须独立承担：

- 在线 API 或 Serverless Function（**不是静态**）
- LLM 密钥（`opencode go` / DeepSeek）
- **限流与成本控制**（每 IP 配额 + 每日预算上限）
- **Prompt injection 防护**（用户输入不可直通 LLM 检索层）
- 用户输入日志与隐私政策（若留存）
- 超时与失败降级（LLM 挂了 → 降级为“检索结果直出”）

> **架构声明修正**：不再说“完全静态、无任何常驻服务”，而是
> **“静态核心 + 可选的独立 ASK 服务”**。ASK 未上线时，静态站完全不受影响。
>
> **ASK 放哪**：NAS 仅 3.4 GiB 可用内存，**不建议在 NAS 常驻 LLM 服务**；
> 建议放 Cloudflare Workers / 独立轻量服务器，**只读** NAS 产出的 JSON。

### 7.3 发布方式（内网 → 公网，分三阶段）

#### 阶段一：内网验证（P0–P1）

| 项 | 方案 |
|---|---|
| 入口 | Tailscale 直连 `http://100.70.84.18:8080` |
| 托管 | NAS 上 Caddy 托管 `dist/` |
| 面向 | 只有你 |

#### 阶段二：灰度（P2，拿到域名后）

| 项 | 方案 |
|---|---|
| 入口 | Cloudflare Pages **预览链接**（不公开索引） |
| 托管 | NAS 每天 push `dist/` 到 Pages |
| 面向 | 小范围邀请，验证观感与数据质量 |

#### 阶段三：公开（P3+）

| 方案 | 成本 | 备案 | 国内速度 | 推荐度 |
|---|---|---|---|---|
| **A. Cloudflare Pages + 自定义域名** | ¥0 + 域名 | **不需要** | 一般 | ⭐⭐⭐ **推荐起步** |
| B. 国内 OSS/COS + CDN | ¥10–50/月 | **需要（1–3 周）** | 快 | 若主打国内则选它 |
| C. Cloudflare Tunnel 直连 NAS | ¥0 | 不需要 | 一般，受 NAS 上行带宽限制 | 不推荐（NAS 挂则站挂） |

**关键架构原则（不变）：**

```text
NAS 出数（内网，永不暴露公网端口）
   └─ dist/ 静态产物（中英双语）
         ↓ 单向推送（rclone / wrangler / ossutil）
      公网 CDN（Cloudflare Pages 或 国内 OSS+CDN）
         ↓
      访客
```

> **NAS 只做数据生产，不做公网服务。** NAS 完全不需要暴露端口，也不受上行带宽限制；
> CDN 承担全部流量。数据生产失败最多导致站点停更一天，不会宕机。

**已定（2026-10-05）：海外 + 国内都要 → A 先上，B 后补。**

| 阶段 | 入口 | 说明 |
|---|---|---|
| 先 | Cloudflare Pages | 免备案，当天可上线，覆盖海外 |
| 后 | 国内 OSS/COS + CDN | 走 ICP 备案（1–3 周），覆盖国内 |

同一份 `dist/` 推两边，内容一致。

### 7.4 国际化：中英双语

openbit 是三语（zh-CN / zh-TW / en）。本项目做 **zh-CN + en** 双语，暂不做繁中。

**URL 结构（照抄 openbit 约定）：**

```text
/            → 中文（默认，x-default）
/en/         → 英文
```

**实现方式：**

| 层 | 做法 |
|---|---|
| 模板 | Jinja2 + `locales/{zh-CN,en}.yaml` 文案字典 |
| 页面文案 | 全部走字典，模板里**不出现硬编码中文** |
| 板块名 | 需自有译名表 `mapping/sector_names_en.yaml`（东财只给中文） |
| 公司名 | A 股英文名不统一，策略见下 |
| SEO | 双向 `hreflang` + 各自 `sitemap` |

**⚠️ 最大难点：A 股专有名词英译。** 分三层处理：

| 类型 | 数据量 | 策略 |
|---|---|---|
| 板块名（496 行业 + 504 概念） | ~1000 | 建译名表，LLM 批量 + **人工复核** |
| 股票代码 | — | 直接可用（如 `600519`） |
| 公司名 | ~5000 | **不做全量翻译**：英文页用「代码 + 可选英文名」 |

> **建议：英文页不承诺公司名全量英译。** 以 `600519 / Kweichow Moutai`
> 形式呈现，英文名只在少量权重股上人工维护。
> 否则 5000 个名字翻错带来的信誉风险远大于收益。

**译名表（关键资产）：**

```yaml
# mapping/sector_names_en.yaml
"BK0475": {zh: "银行Ⅱ", en: "Banks II"}
"BK1296": {zh: "视频媒体", en: "Video Media"}
```

> ~1000 条。P1 先覆盖行业板块（496 全量），概念板块按 **Top 100** 再补（§5.4）。

**已定：英文页公司名策略** = 「代码 + 可选英文名」。

```text
中文页：贵州茅台（600519）
英文页：600519 · Kweichow Moutai     ← 英文名仅权重股人工维护，其余只显代码
```

> 不做 5000 个公司名的全量英译——翻错比不翻风险更大。

---

### 7.5 域名规划（待购）

**目前没有域名。** 已用 RDAP/whois 实测查询（2026-10-05）：

| 域名 | 状态 | 备注 |
|---|---|---|
| `tidewatch` 全系列（.com/.io/.net/.org/.cn） | ❌ 全占用 | **项目名 ≠ 域名**，很正常 |
| `stockatlas.com` | ❌ 占用 | |
| **`stockatlas.cn`** | ✅ **可用** | **推荐**：简短、可备案、国内便宜 |
| `astockatlas.com` | ✅ 可用 | .com 通用，可备案 |
| `astockatlas.cn` / `cnstockatlas.com` | ✅ 可用 | |
| `longhu.io` / `stockatlas.io` / `guanchao.io` / `stocktide.io` | ✅ 可用 | 仅海外（**.io 不能国内备案**） |

**建议方案（国内 + 海外都要）：**

```text
主域名：stockatlas.cn        ← 国内备案 + 海外也走它（Cloudflare 支持 .cn）
   ├─ 国内：阿里云/腾讯云 OSS + CDN（已备案）
   └─ 海外：Cloudflare Pages（同一域名，DNS 分流或双 CNAME）
备选：astockatlas.com        ← 更通用，但略长
```

> ⚠️ **关键约束：`.io` 不能在国内 ICP 备案。** 既然国内也要，主域名必须是
> `.cn` / `.com` / `.net` 这类可备案后缀。`longhu.io` 只能做海外备用，**不能做国内入口**。
>
> 预算：`.cn` 约 ¥30/年，`.com` 约 ¥70/年，`.io` 约 ¥200–400/年。
>
> 备案需：国内主体（个人可）+ 国内服务器/主机 + 域名实名。ICP 备案期间（1–3 周）
> 网站可先用 Cloudflare 上线，不阻塞。

## 8. 项目结构

```text
tidewatch/
├── DESIGN.md                  # 本文档
├── README.md                  # 运行说明
├── pyproject.toml             # 依赖：requests / jinja2 / pyyaml（刻意不用 pandas）
├── config/
│   ├── config.yaml            # 板块清单、路径、域名 fallback 开关
│   └── .env.example           # 占位（当前无需任何 key）
├── src/tidewatch/
│   ├── datasource/
│   │   ├── eastmoney.py       # ★ 核心：东财直连 + 双域名 fallback
│   │   ├── http.py            # ← 复制自 daily-review/fetchers/http.py
│   │   ├── fuyao_client.py    # 可选：拿到 key 后接入（P4）
│   │   └── base.py            # DataSource 抽象（借 quant-lab）
│   ├── pipeline/              # 每模块一个抓取器
│   │   ├── calendar.py        # ← 复制自 daily-review/market_calendar.py
│   │   ├── sectors.py
│   │   ├── dragon_tiger.py    # 游资
│   │   ├── funds.py           # 基金经理/机构
│   │   ├── stocks.py
│   │   └── radar.py           # 涨停/炸板/连板/异动
│   ├── compute/
│   │   ├── momentum.py        # 1/5/20 日 + 强弱四段
│   │   └── seats.py           # 席位 → 游资聚合
│   ├── store/
│   │   └── db.py              # SQLite schema + 幂等写入
│   ├── render/
│   │   ├── builder.py         # 快照 JSON → 静态 HTML（双语）
│   │   ├── i18n.py            # 语言路由 / hreflang / sitemap
│   │   ├── locales/           # zh-CN.yaml / en.yaml（页面文案）
│   │   ├── templates/         # Jinja2
│   │   └── assets/            # CSS / ECharts（本地）
│   └── cli.py                 # tidewatch run --date --stage
├── mapping/
│   ├── seats.yaml             # 游资席位映射（核心资产）
│   └── sector_names_en.yaml   # 板块中英译名表（核心资产）
├── data/                      # SQLite + 快照（git 忽略，且 .stignore 排除）
├── dist/                      # 静态产物（git 忽略，且 .stignore 排除）
├── scripts/
│   ├── run_daily.sh           # NAS cron 入口（含发布守门）
│   └── deploy_nas.sh          # rsync 到 NAS + 装依赖
└── tests/
```

---

## 9. 可复用资产清单（复制而非重写）

| 来源 | 复用内容 | 方式 |
|---|---|---|
| **新写** `src/tidewatch/datasource/eastmoney.py` | 东财直连客户端（§4.2 十接口 + 双域名 fallback） | **本项目核心工作量** |
| `daily-review/fetchers/http.py` | 重试 / 退避 / UA 池 / 限速 / 线程安全 | **必需**，直接复制 |
| `daily-review/utils.py` | logger / dotenv / `Asia/Shanghai` 时区 | 复制 |
| `daily-review/market_calendar.py` | A 股交易日历（周末 + 节假日表） | 复制 |
| `daily-review/main.py` | 分阶段幂等编排模式（stage 分发 + 幂等检查） | 借鉴结构 |
| `daily-review/pusher.py` | 飞书推送（出数完成通知） | 可选复制 |
| `quant-lab/backend/core/datasource.py` | DataSource 抽象接口 | 借鉴 |
| `quant-lab/backend/data/qmt_cn.py` | QMT 可选补充源 | 可选复制 |
| ~~`hithink-finance/toolkit/scripts/fuyao_client.py`~~ | 同花顺 API（当前无 key） | **降级：P4 若拿到 key 再接入** |
| `Stock Intelligence Platform/frontend` | 前端组件/图表参考（SvelteKit/stocknear） | 仅参考视觉 |
| `quant-lab/frontend` | Next.js 页面结构参考 | 仅参考视觉 |

> 原则：**数据与编排层复制，前端视觉参考。** 不引入 SvelteKit/Next.js 作为运行依赖。

---

## 10. 实施路线图

### P0 · 地基（先跑通一条线）✅ **已完成（2026-10-05）**

- [x] **命名冻结**：仓库/包/CLI 统一 `tidewatch`（§0.1）
- [x] `.stignore` 排除运行产物
- [x] 项目骨架 `src/tidewatch/{datasource,store,compute,pipeline}`
- [x] `http.py`：按域名限速 + 抖动 + 指数退避 + 多域名 fallback + 原始留档 + 请求计数
- [x] `datasource/ths.py`：同花顺行业列表 + 板块 K 线（**东财因限流暂缓**，见 §10.2）
- [x] `store/db.py`：全表溯源 schema + `run_ledger` + 事务原子写入 + 幂等判据
- [x] `compute/momentum.py`：1/5/20 日收益 + 强弱四段
- [x] `calendar.py`：交易日历（含节假日表）
- [x] `pipeline/sectors.py`：抓取 → 日期校验 → 计算 → 原子落库
- [x] `tests/fixtures/` 离线样本 + **13 个单测**
- **交付**：✅ 小样本（3 行业板块）跑通，通过 6/12 验收项（见 §10.2）

### 10.2 P0 交付实绩

**代码产出：**

```text
src/tidewatch/
├── http.py              # 限速器 + 多域名 fallback + 原始留档
├── utils.py             # 日志 / 时区 / 配置
├── calendar.py          # 交易日历
├── datasource/ths.py    # 同花顺数据源
├── datasource/base.py   # 抽象接口
├── compute/momentum.py  # 指标 + 强弱四段
├── store/db.py          # schema + 运行账本
├── pipeline/sectors.py  # 板块管道
└── cli.py               # tidewatch run / show
tests/  test_momentum.py · test_ths_parse.py · test_pipeline_offline.py · 13 PASS
```

**NAS 实跑结果（目标 2026-09-30）：**

```
代码      名称          收盘       1日      5日     20日   四段       额(亿)
881121  半导体     16092.61  -2.92%  -7.84%  -3.13%  持续走弱  1782.90
881273  白酒        1958.00   2.82%  -1.02%  -4.67%  超跌反弹   107.46
881101  种植业与林业   4674.82   2.43%  -4.55%  -7.56%  超跌反弹    93.72
```

**验收项完成情况（§10.1）：**

| # | 验收项 | 状态 |
|---|---|---|
| 1 | 幂等（重复运行一致） | ✅ 单测 `test_force_rerun_stable` |
| 2 | 字段缺失必须失败 | ⚠️ 部分（空数据已处理，字段级待补） |
| 3 | 域名 fallback 可追溯 | ✅ `run_ledger.domain` 已记录 |
| 4 | 非交易日拒绝 | ✅ `test_non_trading_day_raises` |
| 5 | 数据日期校验 | ✅ `test_date_mismatch_rejected` |
| 6 | 页面数守门 | ⏳ P1（尚无渲染） |
| 7 | 席位主键稳定 | ⏳ P2（归 `operatedept_code`） |
| 8 | 离线可测 | ✅ 13 个单测全离线 |
| 9 | 指标手算校验 | ✅ `test_momentum` |
| 10 | 双语链接自洽 | ⏳ P1 |
| 11 | 降级显式 | ✅ `calculation_method` 字段已落库 |
| 12 | 限速生效 | ✅ `RateLimiter` 按 host 串行限速 |

**P0 未完成 / 待办：**

- 东财数据源（`eastmoney.py`）——因 IP 限流暂缓，P1 实现（同花顺已足够跑通）
- 概念板块 `885xxx` 代码映射（§4.8）
- 字段级校验（验收项 #2 完整化）
- 落库 `member_snapshot`（成分股，P1）

### 10.1 验收合同（PASS/FAIL，评审点 8）

> 每条可执行、可自动断言。**未通过不算完成。**

| # | 验收项 | 判据 |
|---|---|---|
| 1 | 幂等 | 同日重复运行两次，`data_hash` 完全一致 |
| 2 | 字段缺失必须失败 | HTTP 200 但关键字段缺失 → `status=failed`，不写正式表 |
| 3 | 域名 fallback 可追溯 | 主域名失败、备用成功 → `run_ledger.domain` 记录实际命中 |
| 4 | 非交易日拒绝 | 目标日非交易日 → 拒绝出数 |
| 5 | 数据日期校验 | 返回日期 ≠ 目标交易日 → 拒绝发布 |
| 6 | 页面数守门 | 页面数 < 阈值 → 拒绝替换旧站 |
| 7 | 席位主键稳定 | 同一席位更名后仍归入同一 `operatedept_code` |
| 8 | 离线可测 | 用 `tests/fixtures/` 跑完单测，不联网 |
| 9 | 指标手算校验 | 1/5/20 日收益与手工样例一致（容差 1e-6） |
| 10 | 双语链接自洽 | `/` 与 `/en/` 的 `hreflang`、canonical、互链一致 |
| 11 | 降级显式 | 换口径时页面标注 + `calculation_method` 变化 |
| 12 | 限速生效 | 连续请求间隔 ≥ 配置值，被限流后按退避重试 |

### P1 · 板块图谱（第一个可用页面）✅ **已完成（2026-10-05）**

- [x] 板块目录 + 指数行情落库（**同花顺 90 个行业板块**）
- [x] 计算 1/5/20 日 + 强弱四段
- [x] Jinja2 渲染 `sectors/index.html` + `sectors/{code}/index.html`
- [x] **i18n**：`/` 与 `/en/` 双份产物 + **`sector_names_en.yaml`（90 条）**
- [x] **发布守门**：页面数校验 + 原子替换（§11.5）
- [x] **nginx 容器托管**（`tidewatch-web`, 端口 8080, restart unless-stopped）
- **交付**：✅ 内网可看的**中英双语**板块图谱

**访问地址（Tailscale 内网）：`http://100.70.84.18:8080/`**

```text
/                      首页（中文）          /en/                   首页（英文）
/sectors/              板块图谱              /en/sectors/
/sectors/{code}/       板块详情              /en/sectors/{code}/
/assets/style.css                            （共 10 页 HTML）
```

**P1 实绩：**

| 项 | 值 |
|---|---|
| 页面数 | 10（2 语言 × 5） |
| 单测 | **20 PASS**（新增 7 个渲染/发布测试） |
| 译名表 | 90/90 行业板块，无缺失 |
| 托管 | nginx:latest 容器，端口 8080，自动重启 |
| 验证 | Windows 与 NAS 双端 HTTP 200 |

**P1 新增代码：**

```text
src/tidewatch/render/
├── i18n.py            # 文案字典 + 板块译名 + 展平
├── builder.py         # SQLite → dist/（双语）
├── publish.py         # 发布守门（页面数 + 原子替换）
├── locales/{zh-CN,en}.yaml
├── templates/{base,index,sectors,sector}.html
└── assets/style.css
mapping/sector_names_en.yaml   # 90 条行业译名
```

### P2 · 游资 + 雷达 ✅ **已完成（2026-10-05）**

- [x] `lhb_record` + `seat` 落库（**东财龙虎榜：838 记录 / 240 席位**）
- [x] 游资列表页 / 游资详情页（240 × 2 语言）
- [x] 席位主键用 `operatedept_code`（评审点 4，更名后仍归同一键）
- [x] 证据分层落库（`activity_evidence=measured` / `identity_evidence=unknown`）
- [x] **`seats.yaml` 回填 `operatedept_code`：27/33**（游资页显示社区别名）
- [x] **资金雷达**：涨停 52 / 炸板 12 / 跌停 9 / 强势股 199（共 272 条）+ 连板梯队
- [ ] 个股页（行情 + 财务 + 估值）→ 归 P3
- [ ] **灰度发布**：Cloudflare Pages 预览链接（`noindex`）
- **交付**：✅ 游资 + 资金雷达均已上线

**P2 实绩：**

| 项 | 值 |
|---|---|
| 龙虎榜 | 838 记录 / 240 席位 |
| 资金雷达 | 272 条（up 52 / break 12 / down 9 / strong 199） |
| 连板梯队 | 7 板 1 · 4 板 1 · 3 板 4 · 2 板 6 · 1 板 40 |
| 站点总页数 | **864** |
| 单测 | **31 PASS** |
| 代码量 | 2499 行（src + tests） |

**P2 新增代码：**

```text
src/tidewatch/
├── datasource/eastmoney.py   # 龙虎榜席位 + 涨跌停池（push2ex）
├── pipeline/lhb.py           # → lhb_record + seat
└── pipeline/radar.py         # → limit_up（4 个池）
render/templates/{people,person,radar}.html
```

**实测踩坑（已写入测试）：**

> 四个池需要**不同的 sort 字段**：`up`/`break` 用 `fbt:asc`，`down`/`strong` 用 `zdp:asc`。
> **用错会返回空数据但不报错**——这是隐蔽陷阱，已加测试 `test_pool_sort_keys` 锁定。

### P3 · 基金经理 + AI 逻辑链

- [ ] `fund_portfolio_*` + `fund_managers_*` 落库
- [ ] 基金经理页
- [ ] 板块「引擎逻辑」：LLM 生成结构化 JSON（观点/驱动/来源/时间/状态）
- [ ] 开问 ASK 雏形（检索 + LLM）
- **交付**：具备 AI 叙事层，这是 openbit 的护城河

### P4 · 公网发布与合规

- [ ] 市场雷达（涨跌分布 / 新高新低）
- [ ] 追踪 MONITOR
- [ ] 董监高增减持（若数据源确认）
- [ ] 概念板块英文译名补齐（按实际渲染 Top N）
- [ ] **公网正式发布**：域名 + CDN + 解除 `noindex`
- [ ] **逐项完成 §12.1 对外发布准入清单**
- [ ] 评估 Tushare Pro 补资金流
- **交付**：功能对齐 openbit（除已砍项），公开发布合规就绪

---

## 11. 部署与定时

### 11.1 代码位置与同步策略（重要）

**代码自动同步，运行产物绝不同步。**

你本机 `C:/A_trade/QuantCodes/nas_codes/` 与 NAS 的 `/volume1/docker/Python_Proj/` 是 Syncthing 双向同步关系（`.stfolder-kasq7wEHii` 已确认）：

```text
Windows  C:/A_trade/QuantCodes/nas_codes/tidewatch/    ← 开发
              ↕  Syncthing 自动同步（无需 rsync/scp）
NAS      /volume1/docker/Python_Proj/tidewatch/        ← 运行
              ├── data/   (SQLite + 快照)  ⚠️ 必须排除同步
              ├── dist/   (静态产物)       ⚠️ 必须排除同步
              └── logs/                    ⚠️ 必须排除同步
```

**P0 第一件事：在 `C:/A_trade/QuantCodes/nas_codes/.stignore` 末尾追加：**

```gitignore
# tidewatch 运行产物禁止同步
tidewatch/data
tidewatch/dist
tidewatch/logs
tidewatch/__pycache__
```

> ⚠️ **若 `data/` 参与同步，SQLite 会在两端反复覆盖，必然损坏数据库。**
>
> 备选（不推荐）：把 data/dist 放到同步区外（如 `/volume1/docker/tidewatch-data/`），由 `config.yaml` 指向。推荐用 `.stignore`，更简单。

### 11.2 依赖

NAS 已有 `python3 3.11` / `pip 26.2` / `requests` / `pandas` / `numpy` / `pyyaml`。
**唯一需新增：`jinja2`**（模板渲染，约 200KB）。

```bash
python3 -m pip install --user jinja2
```

> 刻意**不用 pandas 做核心计算**（NAS 仅 3.4 GiB 可用内存），标准库 + numpy 足够。

### 11.3 定时任务（分时段，评审点 6）

15:40 只够行情快照；**龙虎榜/公告等盘后数据更晚才齐**，因此拆成多段：

| 时间 | 任务 | 说明 |
|---|---|---|
| 15:35 | 行情快照 | 板块/个股收盘价、涨跌停初判 |
| 16:00 | 板块指标计算 | 1/5/20 日 + 强弱四段 |
| 18:30 | 龙虎榜 / 席位 | 东财盘后数据通常此时齐 |
| 19:30 | 计算 + 渲染 + 发布 | **数据完整性校验通过后才发布** |
| 21:00 | 补跑 | 只补当日失败任务（据 `run_ledger` 判断） |

```cron
35 15 * * 1-5   cd .../tidewatch && ./scripts/run_daily.sh fetch   >> logs/cron.log 2>&1
00 16 * * 1-5   cd .../tidewatch && ./scripts/run_daily.sh compute >> logs/cron.log 2>&1
30 18 * * 1-5   cd .../tidewatch && ./scripts/run_daily.sh lhb     >> logs/cron.log 2>&1
30 19 * * 1-5   cd .../tidewatch && ./scripts/run_daily.sh publish >> logs/cron.log 2>&1
00 21 * * 1-5   cd .../tidewatch && ./scripts/run_daily.sh retry   >> logs/cron.log 2>&1
```

> **发布条件：当日全部必需任务 `status=success` 才发布；否则保留前一日站点。**
> 节假日由交易日历判定后自动跳过。基金季报等低频数据单独按周跑。
>
> NAS 宿主机 cron 需 sudo；也可用容器内 cron 或 openclaw cron（`NAS_INFO.md` 有先例）。

### 11.4 前置条件

**私有内网开发：无阻塞 ✅**

| 项 | 状态 |
|---|---|
| NAS 可达 | ✅ `100.70.84.18`（Tailscale），SSH 免密可用 |
| 数据源 | ✅ 东财直连，无需 key；⚠️ 但**限流敏感**（§4.7） |
| NAS 规格 | ✅ 4 核 / 7.6 GiB（可用 3.4 GiB）/ 磁盘 2.8T 空闲 |
| Python 依赖 | ✅ 仅需补装 `jinja2` |
| 代码同步 | ✅ Syncthing 自动同步 |

**公网正式发布：仍有阻塞 ⛔（评审点 7）**

| 阻塞项 | 状态 |
|---|---|
| 数据公开再分发授权 | ⛔ 未确认（**必须在 P0 就启动评估，不能拖到 P4**） |
| 概念板块成交额口径 | ⚠️ 部分确认（单板块 `f48` 可用；批量接口限流中） |
| 基金 / 基金经理接口 | ⛔ 未实测（P3 开工前必测） |
| 域名 + ICP 备案 | ⛔ 未办（1–3 周） |
| §12.1 准入清单 | ⛔ 未逐项完成 |

> **准确表述：私有内网 P0 开发无阻塞；公网发布被「数据授权 + 备案」两道 gate 阻塞。**
> 数据授权需在 P0 并行启动，否则可能全部做好才发现核心数据不能公开。

### 11.5 公网部署（P2 之后启用）

**⚠️ 本工程默认不做公网。** 以下步骤在灰度前才执行。

**步骤（以 Cloudflare Pages 为例）：**

```bash
# 1. 生成中英双语产物
python3 -m tidewatch render --lang all --out dist/

# 2. 单向推送（凭据放 config，不入 git）
wrangler pages deploy dist --project-name=tidewatch   # 或 rclone sync dist/ r2:tidewatch-site/
```

**必须写进 `scripts/run_daily.sh` 的守门逻辑：**

```bash
# 数据为空 / 页面数异常 / 渲染失败 → 拒绝发布，保留上一版
python3 -m tidewatch render --lang all --out dist.new || { echo "渲染失败，不发布"; exit 1; }
PAGES=$(find dist.new -name '*.html' | wc -l)
[ "$PAGES" -lt 50 ] && { echo "页面数异常($PAGES)，不发布"; exit 1; }
rsync -a --delete dist.new/ dist/ && wrangler pages deploy dist --project-name=tidewatch
```

> **公网发布必须有守门：宁可停更，不可发布半成品或空数据。**

**域名与 DNS：**

| 项 | 值 |
|---|---|
| 域名 | 待购（约 ¥30–80/年） |
| DNS | Cloudflare 免费套餐足够 |
| 证书 | Cloudflare 自动签发 |
| 备案 | 方案 A 不需要；方案 B 需要 |

> 注意：`.stignore` 已排除 `dist/`，因此**产物不会同步回 Windows**，只在 NAS 上推送。
> 推送凭据（`~/.wrangler` 或 `~/.config/rclone/`）也必须写在同步区**之外**。

---

## 12. 风险与合规

| 风险 | 等级 | 处置 |
|---|---|---|
| **东财/同花顺数据公开分发授权** | 高 | 内网自用 OK；公开上线前必须核实授权（免费接口 ≠ 可商用分发），否则只做私有 |
| **证券投资咨询资质** | 高 | 只展示数据 + 免责声明；**不出现买卖建议/目标价/荐股** |
| **AI 生成内容的虚假陈述** | 高 | 全部标注为"引擎整理的推断"，挂来源与时间；游资席位映射标注为社区口径 |
| **量化机构持仓不可得却硬做** | 中 | 明确不做；只做"公募量化基金"并如实命名 |
| **个人隐私（游资映射指向自然人）** | 中 | 只写席位与公开别名，**不指向具体自然人身份**；保留删除通道 |
| 数据滞后被误读为实时 | 中 | 每页显示"快照日期"；照抄 openbit 的"不能说明什么"话术 |
| 备案 | 低（本期） | 内网 Tailscale 不需要；外网发布前再处理 |
| 单点：NAS 挂了 | 低 | SQLite + dist 目录做 Syncthing/快照备份 |

### 12.1 对外发布准入清单（公开前逐项打勾）

> **「自用」和「对外展示」是两回事。** 自用一切好说；一旦对公众开放，
> 数据授权、投顾资质、免责披露三项都可能变成实际风险。

**数据与授权**

- [ ] 确认东财数据条款允许公开再分发（**免费接口 ≠ 可商用分发**）
- [ ] 若不允许：改为只展示**自有计算结论**（涨跌幅、分类），不展示原始接口字段
- [ ] 页面标注数据来源与快照时间

**资质与话术**

- [ ] 全文不出现：买卖建议、目标价、荐股、收益率承诺、「必涨」类表述
- [ ] AI 产出统一标注为「引擎整理的推断」，挂来源与时间
- [ ] 游资席位页标注「社区归纳口径，不代表特定自然人」
- [ ] 每页保留「资料能说明什么 / 不能说明什么」
- [ ] 底部固定免责声明 + 非投资建议
- [ ] 英文页同样有免责声明（不能只写中文）

**合规与法务**

- [ ] 域名实名认证
- [ ] **ICP 备案（已确定要走，1–3 周）+ 页脚备案号**
- [ ] 海外（Cloudflare）与国内（OSS+CDN）两份部署内容一致
- [ ] 涉及个人信息处理的（如持仓体检）需隐私政策
- [ ] 评估是否触及《证券投资咨询业务》——**存疑则先咨询专业人士**

**技术**

- [ ] 发布守门逻辑已实现（§11.5）
- [ ] 灰度期用 `noindex`，确认后才放开索引
- [ ] robots.txt / sitemap.xml 齐备（中英各一份）

---

## 13. 待确认问题（请评审时回复）

**已定（2026-10-05）：**

| 问题 | 决定 |
|---|---|
| 项目名 | **tidewatch（观潮）**（域名另选，见 §7.5） |
| 板块口径 | **东财**：行业 496 全量 + 概念 **Top 100**（按成交额，§5.4） |
| 语言 | **中英双语**（zh-CN + en） |
| 英文公司名 | **接受「代码 + 可选英文名」** |
| 数据源 | **东财直连**（免 key，已实测） |
| 部署 | **海外 Cloudflare + 国内 OSS/CDN，两者都要** |
| 域名 | **无，待购**；推荐 `stockatlas.cn`（§7.5） |
| LLM | opencode go / DeepSeek 等国内可用模型 |
| 游资映射 | 从零整理，首批 24 个已出草案 |

**仍需你确认：**

1. **域名**：从 §7.5 候选里选一个（推荐 `stockatlas.cn`），还是想要别的名字？
2. **是否走 ICP 备案**？（国内要上的话是必须的，1–3 周，可先用 Cloudflare 上线不阻塞）
3. **概念板块成交额**：需实测东财是否直接给板块成交额（§5.4 开放问题）
4. **董监高增减持**：P4 是否需要？

**已无阻塞项，可开工 P0。**

---

## 附：本方案的三个关键判断

1. **数据源必须从 QMT 换成 HTTP 直连（东财 / 同花顺 / 腾讯）** —— 这是「部署在 NAS 且 Windows 不常开」能成立的唯一前提。
2. **形态照抄 openbit 的静态生成，不引入常驻前端服务** —— NAS 资源有限，且产品语义本来就是"收盘后更新"。
3. **砍掉量化机构持仓** —— 数据不存在，硬做就是造假；游资与基金经理才是 A 股真正可得且有"人物感"的两类。
