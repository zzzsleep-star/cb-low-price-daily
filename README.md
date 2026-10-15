# cb-low-price-daily

一个可独立运行的 Codex Skill。首次运行时自动通过 AKShare 建立当前沪深可转债数据库，以后每天增量更新上一交易日数据并输出低价策略前 10 名。

## 特点

- 不需要预先准备转债主表、历史行情、事件表或回测框架；
- 自动发现当前沪深可转债；
- 自动取得评级、到期日、正股代码和最后交易日；
- 自动下载最近 5 个交易日行情并建立本地缓存；
- 自动检查强赎状态和正股名称风险标记；
- 所有结果、失败记录和数据来源均保存在本地。

## 策略规则

转债必须同时满足：正股无已知 ST、*ST 或退市风险；发行债项评级不低于 A+；剩余期限不少于 90 个自然日；最近 5 个交易日估算成交额合计不少于 5,000 万元；收盘价不低于 90 元；正常交易；没有已公告实施强赎；尚未到达最后交易日。合格券按收盘价、转债代码升序取前 10 名。

详细定义见 [`references/strategy_rules.md`](references/strategy_rules.md)。

## 安装

要求 Python 3.10 或更高版本。

```bash
git clone https://github.com/YOUR_NAME/cb-low-price-daily.git
cd cb-low-price-daily
python -m pip install -r requirements.txt
```

安装为 Codex Skill：

```powershell
Copy-Item -Recurse -Force . "$env:USERPROFILE\.codex\skills\cb-low-price-daily"
```

## 第一次运行

```bash
python scripts/run_morning.py
```

首次运行会自动建立 `~/.cb-low-price-daily`，并下载当前约 300 只沪深转债的基础信息和最近 5 个交易日行情。由于需要调用较多接口，首次运行通常明显慢于后续运行。

如需指定缓存目录：

```bash
python scripts/run_morning.py --data-dir "D:/cb-low-price-data"
```

之后每天重复相同命令即可。程序会更新缓存并在以下目录生成结果：

```text
<data-dir>/runs/YYYY-MM-DD/
├─ low_price_top10.csv
├─ screening_detail.csv
├─ screening_summary.csv
├─ failures.csv
└─ run_metadata.json
```

本地缓存结构：

```text
<data-dir>/state/
├─ master.parquet
├─ daily_history.parquet
└─ trade_calendar.parquet
```

这些文件由Skill自动创建，不需要用户手工准备。

## 常用参数

```text
--data-dir PATH       设置缓存和结果目录
--run-date YYYY-MM-DD 指定运行日期，默认使用当天
--workers 4           设置并发请求数量
--refresh-master      重新下载全部基础信息
--max-bonds N         仅用于程序冒烟测试，不得作为正式名单
```

## Codex中使用

```text
请使用 $cb-low-price-daily，自动建库或更新上一交易日数据，输出低价策略前十名，并报告接口失败和数据覆盖情况。
```

## 每日自动执行

推荐在北京时间每天 08:00 执行：

```text
每天早上使用 $cb-low-price-daily 运行 scripts/run_morning.py。输出上一交易日低价策略前十、候选池数量、各项剔除数量和 failures.csv。只有 official_full_universe_run=true 且目标交易日数据有效时，才能称为正式名单。
```

## 数据口径与限制

- 日线行情主要来自 `AKShare.bond_zh_hs_cov_daily`；
- 评级、期限等基础信息主要来自 `AKShare.bond_zh_cov` 和 `AKShare.bond_zh_cov_info`；
- 强赎状态来自 `AKShare.bond_cb_redeem_jsl`；
- AKShare日线缺少真实成交额时，使用“收盘价×成交量”估算，并明确标记来源；
- 正股风险根据当前正股简称中的 ST、*ST 和退市标记判断，不能替代完整的历史风险数据库；
- 发行评级不能替代完整的历史动态评级；
- 接口失败的证券记录在 `failures.csv`，不得静默忽略；
- 输出属于规则筛选结果，不构成投资建议。

## GitHub上传

在仓库目录执行：

```bash
git init
git add .
git commit -m "Add standalone cb-low-price-daily skill"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/cb-low-price-daily.git
git push -u origin main
```

建议不要把自动生成的缓存、CSV、Parquet和运行结果上传GitHub；`.gitignore` 已默认排除这些文件。
