# AGX Racing Agent

用于 AGX「多人赛车 / Formula Racing」的 Python 车手、车辆设计及实验记录。当前合同 `rsi-racing-4.4`，核查日期 2026-11-15。

**当前版本：v2，于 2026-11-15 13:03:53 上传并随后通过 AGX 校验，已自动启用参赛，包指纹 `8f54f7eff581`。** 60 项测试通过；完整本人历史观察检查与三赛道合成压力检查均无异常/非法动作。v1 首场第 3 名，v2 尚无正式对局成绩；不将历史观察或合成运行当作新圈速/胜率。

## 开发与提交

只需 Python 3.10+ 标准库，没有 API key、付费模型或第三方运行依赖。

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_design.py
python3 scripts/benchmark.py --calls 30000
python3 scripts/kinematic_check.py
python3 scripts/pack.py
```

打包输出 `dist/agx-racing-agent.zip`，仅包含 `agent.py`、`track_data.py`、`design.json`。打包器校验语法、设计、大小，并固定 ZIP 元数据，重复构建应得到相同 SHA256。`tests/`、脚本、日志、凭据和文档不会进入参赛包。

在[赛车比赛报名页](https://agx.cool/#/competitions/1eb91364-950b-5725-aa4b-3501b16860ec/enter)上传 ZIP。网页当前会自动采用最新通过的版本，但仍须检查「当前代码版本」及指纹。每场结算后从「我的对局」查看结果；新版本只影响之后新分配的比赛。

## 驾驶策略

| 模块 | 处理方式 |
| --- | --- |
| 当前道路 | 三赛道公开几何压缩为约 6 米间隔表，按实际圈长和 `s` 插值；处理起终点接缝，未知赛道退回合法前视 |
| 速度规划 | 使用全部 24 行、360 米前视，按列名读取；曲率限速与后向制动约束，考虑坡度、湿度、磨耗和打滑 |
| 转向 | 当前曲率前馈，加横向偏移、航向、侧滑和偏航反馈；遵守实际轮角与 1.6 rad/s 变化率 |
| 纵向控制 | 使用自身当前等效质量、阻力、驱动力和制动力遥测计算请求；保留功率过热和燃油余量控制 |
| 交通 | 保持超车目标与横向偏移；先检查当前车距，再平滑换道；没有安全空间时跟车 |
| 进站 | 持续请求直到入口；正赛实际向前行驶才记胎种；出站后确认停站完成；湿地豁免只由正赛实际湿度触发 |
| 能量与气动 | 直道分配 ERS 储备；只请求已获资格的电能超越；依据公开区域余量启用 X 模式，制动与恢复优先 |

v2 针对首场雨地日志修复了速度目标反复下调的问题：持久保存的几何/天气速度计划与临时滑移保护分开；短暂滑移保留即时油门限制，持续或高占空比滑移才进一步降速，严重侧滑、航向误差、边界及避碰仍立即保护。刹车与 ERS 使用不同进入/退出阈值；助推在失稳时立即关闭，连续安全 0.20 秒后才重新开放。设计与原速度/横向预算保持不变，收益需由新对局验证。

车辆设计保持官方基线的主要参数，将配重从 40 kg 降至合法最低 20 kg；不凭猜测减少燃油。详细取舍与单位见[规则说明](docs/rules.md)，公开研究依据见[策略参考](docs/strategy-references.md)。

这些控制增益和抓地余量是待验证的工程假设。公开几何不是完整动力学；力遥测也不能替代轮胎联合滑移模型。没有隐藏对手状态或未来天气输入，`init()` 不使用种子猜测天气。

## 验证与下一轮

- 60 项单元测试通过，覆盖 v1 的接口/设计/导航/进站约束，以及孤立与持续滑移、速度目标恢复、紧急保护、ERS 恢复等待、阶段重置、完整日志校验和聚合报告隐私。
- `benchmark.py` 在三赛道、多天气、交通和进站状态中检查接口与 CPU；它是脚本化观测，不推进正式物理、不判断比赛胜负。详见[实验日志](experiments/iteration-log.md)。
- `kinematic_check.py` 使用明确假定的力和无轮胎滑移限制的单轨模型，检查反馈方向及振荡；它帮助定位了高速偏航微振。合成圈时不作为正式成绩，Highland 实际时间余量仍需首场日志验证。
- 已取得首场正式结果：Crossover 雨地第 3 名，比赛在 663.4 秒时限结束，本车仍在跑、完成 2 圈，日志 faults 为 0。完整性及动作复现说明见[实验日志](experiments/iteration-log.md)。
- `replay_check.py` 严格核对本人导出的原始决策行数、字节数、SHA256 和结束标记；可对比固定基线与当前版本的合法动作、CPU、控制切换次数及目标速度。它不推进游戏物理，无法得出新版本圈速或胜率。聚合输出不含账号、比赛种子或原始观察。
- 每次记录源码 commit、参赛包 SHA256、AGX 版本、赛道/天气和对局 ID；用不同对局做调参与验证。

下载本人完整日志到 `data/private/` 后可复现 v1/v2 决策对照；`--seat` 必须改为该日志中的本人席位（从 0 开始）：

```bash
python3 scripts/replay_check.py data/private/training.jsonl --seat 4 \
  --baseline-ref f9ba63540f21d39c1634fe7beb53a77948c3fd30 \
  --output experiments/replay-v2.json
```

## 公开数据与复现

`track_data.py` 是从[官方赛车工具包](https://agx.cool/docs/schema/kits/agx-racing-kit.zip)的 `data/*.mapdata.json` 及官方 `/assets/formula-circuits/{parkland,highland,crossover}.json` 提取的数据，内含源文件 SHA256。公开几何的来源和 ODbL 归属保留在 [NOTICE.md](NOTICE.md)。

重新生成时，把工具包内容放在 `<reference>/kit/`，三个原始赛道 JSON 放在 `<reference>/assets/`：

```bash
python3 scripts/build_track_data.py /path/to/reference
python3 -m unittest discover -s tests -v
python3 scripts/pack.py
```

仓库中的观察 fixture 来自官方公开文档，不是个人比赛日志。个人日志、课程材料、账号资料及浏览器文件不放入公开仓库。
