# AGX Racing Agent

用于 AGX 多人赛车的 Python 车手、车辆设计与实验。合同 `rsi-racing-4.4`，核查日期 2026-11-15。

**v8（8 kg）已通过 AGX 准入，“我的比赛”显示赛车已发布代码 v8；包指纹 `f9da6220f841`，上传时间 2026-11-16 12:42 北京时间。** 修复 v7 将低速急弯的正常车身侧向运动误判成甩尾的问题，允许道路和交通余量足够时低速绕过弯中的停驶车辆。保留真实失稳保护、抓地余量、无固定直道限速、车辆配置和 ERS 策略。详见[第三名复盘与 v8](docs/podium-v8-2026-11-16.md)和[平台回执](experiments/submission-v8.json)。新正式比赛表现尚待验证。

v7 首场 Highland 正式比赛完成四圈、第三名，落后冠军 29.008 s，8 kg 起步、终点剩 2.5133 kg。最后约 700 m 累计落后冠军约 20.93 s，是本次修正重点。此前 v7 的稳定性修复记录见[v7 文档](docs/v7-stability-2026-11-16.md)。

触发修复的 Crossover 比赛使用旧的 15 kg 配置，第 4 圈甩尾后损坏退赛，见[事故复盘](docs/damage-race-2026-11-16.md)。此前四场为 2、1、1、2 名，历史 ERS 与燃油改动见[四场复盘](docs/recent-races-2026-11-16.md)和[九场燃油统计](docs/fuel-audit-2026-11-16.md)。

此前 v4 的三圈被套圈、固定限速及 v5 修复记录见[历史分析](docs/parkland-2026-11-15.md)，平台版本和包指纹见[实验日志](experiments/iteration-log.md)。

## 开发与提交

只需 Python 3.10+ 标准库，无第三方运行依赖。

```bash
python3 -B -m unittest discover -s tests -v
python3 -B scripts/validate_design.py
python3 -B scripts/benchmark.py --calls 30000
python3 -B scripts/kinematic_check.py
python3 -B scripts/pack.py
```

`dist/agx-racing-agent.zip` 仅包含 `agent.py`、`design.json`、`track_data.py` 和三个 `track_*.py`。打包器校验语法、设计和大小，固定 ZIP 元数据；日志、凭据、测试和文档不进入参赛包。

在[报名页](https://agx.cool/#/competitions/1eb91364-950b-5725-aa4b-3501b16860ec/enter)上传后，核对校验结果、当前代码版本及指纹。新版本影响随后新分配的比赛。

## 驾驶策略

| 模块 | v8 行为 |
| --- | --- |
| 直道 | 无固定 km/h 上限，由引擎、阻力和前方制动需求决定 |
| 道路 | 检查完整约 2 米地图原始节点及全部合法前视，范围至少覆盖估计停车距离；处理圈长舍入和接缝 |
| 弯道 | 按本站 C1–C5 胎方、最低单轮胎温、磨损和湿度估计抓地；横向规划留余量，联合纵横向需求反推制动点并考虑下坡 |
| 动力 | 取消滑移标志驱动的持续降速、0.28/0.65 固定油门上限、温度固定限速及目标恢复斜坡 |
| 制动 | 油门与刹车受当前横向负荷后的可用轮胎力限制；未来弯道不冒充当前受力；碰撞紧急制动优先 |
| ERS | 按需求力、横向负荷和减速计划选择 neutral / balanced / attack；出弯立即释放，无固定电量储备与恢复等待，制动时回收 |
| 燃油 | 初始 8 kg；仅在实测单位距离耗油推算不足以到终点时按缺口比例调整油门 |
| 转向和交通 | 以运动方向偏差和真正过度旋转识别失稳；正常急弯中车头偏角与侧向速度可以互相抵消；保留转向限制、碰撞优先及有安全空间的低速弯道绕车 |
| 进站 | 保留干地双胎种、实际湿地豁免与进出站确认；按平台资格请求超越及 X 气动 |

抓地系数及下压力平方外推是待验证的控制近似，不能替代完整轮胎与气动模型。没有使用未来天气、隐藏对手状态或种子预测。严重侧滑、偏航、道路边界和临近碰撞仍会触发响应。

车辆配重 20 kg，前轴 45%；除燃油外其余设计沿用本人 v4。范围与约束见[规则说明](docs/rules.md)。

## 验证与复现

- 106 项测试通过；新增正常急弯不误刹、真正甩尾仍停动力、窄弯/占用车道不强行超车、高速弯不启用慢车绕行等回归。
- [30,000 次合成调用](experiments/benchmark-v8.json)零异常/非法动作；[加入正常几何侧向运动的三赛道简化模型](experiments/kinematic-v8-body-slip.json)均完成一圈且未跨路缘。两者均不等于正式比赛成绩。
- [Highland 25145 次合法观察](experiments/replay-v8-highland.json)与[Crossover 17724 次合法观察](experiments/replay-v8-crossover.json)均零异常/非法动作；Highland v7 基线与记录动作完全一致。[保护触发对照](experiments/stability-detector-v8.json)中，Highland 触发 1133→55 次，旧事故保护开始时刻保留，不推进物理状态、不证明新的圈速。
- [近期复盘](docs/recent-races-2026-11-16.md)核验四场完整事件与场景、两场亚军完整连续正赛采样；`scripts/analyze_race_comparison.py` 可复现对比。
- [公开回放审计](experiments/parkland-2026-11-15-audit.json)核对完整事件、静态元数据和所用帧分块 SHA256；仅取部分帧窗口，其油门均值和速度上限不能当作整场统计。
- `scripts/analyze_public_replay.py --help` 可复现公开回放审计；回放不会作为实时策略输入。
- `scripts/replay_check.py` 只接收完整本人席位训练导出，验证原始行数、字节数、SHA256 和结束标记。可选基线必须使用相同几何模块，旧 v1/v2 的约 6 米地图需在匹配的独立检出中复现。

## 公开几何与来源

`track_data.py` / `track_*.py` 派生于[官方工具包](https://agx.cool/docs/schema/kits/agx-racing-kit.zip)地图及官方 `/assets/formula-circuits/{parkland,highland,crossover}.json`，保留源文件 SHA256 与 ODbL 归属，见 [NOTICE.md](NOTICE.md)。

重新生成时，将工具包放在 `<reference>/kit/`，三个原始赛道 JSON 放在 `<reference>/assets/`：

```bash
python3 scripts/build_track_data.py /path/to/reference
python3 -B -m unittest discover -s tests -v
python3 scripts/pack.py
```

协议 fixture 来自官方公开文档。本人原始日志和下载包保存在 Git 忽略的 `data/private/`，不收录浏览器或账号资料。
