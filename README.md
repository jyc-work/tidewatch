# tidewatch（观潮）

A 股市场图谱：**板块 / 游资 / 资金雷达**。
每个交易日收盘后离线出数，生成静态页面发布到 CDN。

> 设计文档：[DESIGN.md](DESIGN.md)（v0.6，含全部决策与验收合同）

## 快速开始

```bash
# 依赖（NAS 已有 requests / pyyaml；jinja2 供 P1 渲染用）
python3 -m pip install --user -e .

# 跑板块管道（默认「最近一个已收盘的交易日」）
PYTHONPATH=src python3 -m tidewatch.cli run --stage sectors --date 2026-09-30

# 查看结果
PYTHONPATH=src python3 -m tidewatch.cli show --date 2026-09-30

# 离线模式（读 data/raw 缓存，不打网络）
PYTHONPATH=src python3 -m tidewatch.cli run --stage sectors --use-cache

# 指定板块 / 强制重跑
PYTHONPATH=src python3 -m tidewatch.cli run --stage sectors \
    --codes 881101,881121,881273 --force
```

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
```

13 个单测，**全部离线**（基于 `tests/fixtures/`），不需要网络。

## 目录

```text
src/tidewatch/
├── http.py              # 限速器（按域名串行 + 抖动 + 退避）+ 多域名 fallback + 原始留档
├── utils.py             # 日志 / 时区 / 配置
├── calendar.py          # A 股交易日历（含节假日表）
├── datasource/
│   ├── base.py          # 数据源抽象
│   └── ths.py           # 同花顺（P0 主力源）
├── compute/momentum.py  # 1/5/20 日收益 + 强弱四段
├── store/db.py          # SQLite：全表溯源 + 运行账本 + 原子写入
├── pipeline/sectors.py  # 板块管道：抓取 → 校验 → 计算 → 落库
└── cli.py               # tidewatch run / show
config/config.yaml       # 配置（路径 / 限速 / 域名 / 样本）
mapping/seats.yaml       # 游资席位映射（证据分层）
tests/fixtures/          # 离线样本
```

## 关键纪律

**限速是硬要求，不是优化**（DESIGN §4.7）：东财对高频请求会临时封 IP。
`http.py` 已实现按域名串行限速（默认 1s + 抖动）、指数退避、多域名轮换。
开发期请优先用 `--use-cache`，不要反复打数据源。

**所有数据带溯源**：`sector_daily` 落 `source_provider` / `calculation_method` /
`input_hash` / `algorithm_version`；每次运行写 `run_ledger`（含实际命中域名）。
不同口径不会拼成同一条曲线（DESIGN §6.4）。

## 当前状态

- ✅ P0 完成：板块管道跑通（Windows + NAS 双端验证）
- ⏳ P1：东财数据源 · 概念板块映射 · Jinja2 渲染 · 中英双语 · 发布守门
- ⛔ 公网发布：待数据授权确认 + ICP 备案（DESIGN §11.4 / §12.1）
