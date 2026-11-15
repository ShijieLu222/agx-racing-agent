# AGX Racing Agent

用于 AGX「多人赛车 / Formula Racing」的 Python 车手、车辆设计及实验记录。当前合同 `rsi-racing-4.4`，核查日期 2026-11-15。

**当前状态：v1 于 2026-11-15 通过 AGX 校验并已自动启用参赛，包指纹 `65251f60a801`；尚无正式对局或排名证据。** 36 项测试通过，代码以可解释、可测试和稳定完赛为目标，不将合成运行当作圈速或胜率证明。

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

车辆设计保持官方基线的主要参数，将配重从 40 kg 降至合法最低 20 kg；不凭猜测减少燃油。详细取舍与单位见[规则说明](docs/rules.md)，公开研究依据见[策略参考](docs/strategy-references.md)。

这些控制增益和抓地余量是待验证的工程假设。公开几何不是完整动力学；力遥测也不能替代轮胎联合滑移模型。没有隐藏对手状态或未来天气输入，`init()` 不使用种子猜测天气。

## 验证与下一轮

- 36 项单元测试通过，覆盖列重排、窄峰制动、转向方向与速率、天气与打滑、交通、持续进站、阶段重置、实际双胎种、设计约束、环绕几何和可复现打包。
- `benchmark.py` 在三赛道、多天气、交通和进站状态中检查接口与 CPU；它是脚本化观测，不推进正式物理、不判断比赛胜负。详见[实验日志](experiments/iteration-log.md)。
- `kinematic_check.py` 使用明确假定的力和无轮胎滑移限制的单轨模型，检查反馈方向及振荡；它帮助定位了高速偏航微振。合成圈时不作为正式成绩，Highland 实际时间余量仍需首场日志验证。
- 第一场完成后下载本人完整 `training.jsonl`，保存在已忽略的 `data/private/`，确认末尾 `export_complete`。先分析是否完赛、faults、停滞、越界、胎账、最低油量，再决定下一项修改。
- 每次记录源码 commit、参赛包 SHA256、AGX 版本、赛道/天气和对局 ID；用不同对局做调参与验证。

## 公开数据与复现

`track_data.py` 是从[官方赛车工具包](https://agx.cool/docs/schema/kits/agx-racing-kit.zip)的 `data/*.mapdata.json` 及官方 `/assets/formula-circuits/{parkland,highland,crossover}.json` 提取的数据，内含源文件 SHA256。公开几何的来源和 ODbL 归属保留在 [NOTICE.md](NOTICE.md)。

重新生成时，把工具包内容放在 `<reference>/kit/`，三个原始赛道 JSON 放在 `<reference>/assets/`：

```bash
python3 scripts/build_track_data.py /path/to/reference
python3 -m unittest discover -s tests -v
python3 scripts/pack.py
```

仓库中的观察 fixture 来自官方公开文档，不是个人比赛日志。个人日志、课程材料、账号资料及浏览器文件不放入公开仓库。
