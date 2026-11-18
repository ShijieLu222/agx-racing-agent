# AGX Racing Agent

用于 AGX 多人赛车的 Python 车手、车辆设计与实验。合同 `rsi-racing-4.4`，核查日期 2026-11-15。

**2026-11-18 13:15（北京时间）**　AGX 已通过赛车 v12 准入。Parkland 两组连续弯使用由赛道宽度约束的走线，转向和制动规划共用其曲率。附近有车时采用交通策略。三场本人日志共 59,089 次决策重放、147 项测试通过。[平台回执](experiments/submission-v12.json) · [闭环模型与验证数据](experiments/v12-validation.json)

**2026-11-18**　最近八场均使用 v10，一冠一季。v11 已于北京时间 11:18 提交，11:19 确认通过 AGX 准入。[平台回执](experiments/submission-v11.json)。该版本针对 Crossover 跟随慢车期间的超车选边及 Parkland 湿地入弯制动进行了优化，已经过两场本人日志共 42,217 次决策重放。详见[最近八场、前两名对比与参赛包](docs/recent-races-2026-11-18.md)。

**2026-11-17 更新：赛车 v10 已上传并通过 AGX 准入。** 核查到 v9 在 08:34 Parkland 正赛第九，随后 10:35 湿地场第二。已完成两场与前三名对比；本地修正冷胎干地校准及下压力制动规划，125 项测试、60,130 次真实合法输入重放通过。发布包 `dist/agx-racing-v10-candidate.zip`，指纹 `4e36a195502d`；版本号 10，详见[平台回执](experiments/submission-v10.json)。详见[第九名原因、最新亚军及 v10 验证](docs/parkland-v10-review-2026-11-17.md)。

**历史 v9（8 kg）已通过 AGX 准入，赛车卡片显示“已发布代码 v9”；提交包指纹 `507756dfbe4b`，上传时间 2026-11-16 14:55 北京时间。** 修正起步油耗外推引发的误省油，在暖胎干地条件下适度提高抓地规划，允许满足速度、曲率和道路空间条件时绕过行驶中的慢车。保留冷胎/湿地基线、真正失稳保护及碰撞制动。详见[v9 改动与验证](docs/v9-pace-2026-11-16.md)及[发布回执](experiments/submission-v9.json)。下列策略与 118 项测试说明保留为 v9 历史基线；当前候选版见上方更新。

v8 首场 Crossover 第三，落后冠军 42.022 s，耗油 4.4986 kg、终点余油 3.5014 kg；主要正常弯速差距、起步误省油和末圈跟车证据见[正式比赛复盘](docs/crossover-v8-result-2026-11-16.md)。历史[平台回执](experiments/submission-v8.json)与[急弯修复](docs/podium-v8-2026-11-16.md)保留。

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

`dist/agx-racing-agent.zip` 包含 `agent.py`、`design.json`、`parkland_line.py`、`track_data.py` 和三个赛道几何模块。打包器校验语法、设计和大小，固定 ZIP 元数据；日志、凭据、测试和文档不进入参赛包。

在[报名页](https://agx.cool/#/competitions/1eb91364-950b-5725-aa4b-3501b16860ec/enter)上传后，核对校验结果、当前代码版本及指纹。新版本影响随后新分配的比赛。

## 驾驶策略

| 模块 | v9 行为 |
| --- | --- |
| 直道 | 无固定 km/h 上限，由引擎、阻力和前方制动需求决定 |
| 道路 | 检查完整约 2 米地图原始节点及全部合法前视，范围至少覆盖估计停车距离；处理圈长舍入和接缝 |
| 弯道 | 按本站 C1–C5 胎方、最低单轮胎温、磨损和湿度估计抓地；暖胎干地估计最多提高 28%，65°C 以下或湿度 0.30 以上回到 v8 估计；横向规划留余量，联合纵横向需求反推制动点并考虑下坡 |
| 动力 | 取消滑移标志驱动的持续降速、0.28/0.65 固定油门上限、温度固定限速及目标恢复斜坡 |
| 制动 | 油门与刹车受当前横向负荷后的可用轮胎力限制；未来弯道不冒充当前受力；碰撞紧急制动优先 |
| ERS | 按需求力、横向负荷和减速计划选择 neutral / balanced / attack；出弯立即释放，无固定电量储备与恢复等待，制动时回收 |
| 燃油 | 初始 8 kg；排除起步前 300 m 与跨进站采样，积累足够距离后按滚动耗油估计判断是否省油；极低余油保留提前保护 |
| 转向和交通 | 以运动方向偏差和真正过度旋转识别失稳；正常急弯中车头偏角与侧向速度可以互相抵消；保留转向限制、碰撞优先及有安全空间的低速停驶车辆绕行及中低速缓弯慢车通过，每次决策重查目标车道占用 |
| 进站 | 保留干地双胎种、实际湿地豁免与进出站确认；按平台资格请求超越及 X 气动 |

抓地系数及下压力平方外推是待验证的控制近似，不能替代完整轮胎与气动模型。没有使用未来天气、隐藏对手状态或种子预测。严重侧滑、偏航、道路边界和临近碰撞仍会触发响应。

车辆配重 20 kg，前轴 45%；除燃油外其余设计沿用本人 v4。范围与约束见[规则说明](docs/rules.md)。

## 验证与复现

- 118 项测试通过，覆盖燃油估计成熟度、真实不足保护、冷胎/湿地回退、慢车通过及新进入车辆占用目标车道等行为。
- [30,000 次合成调用](experiments/benchmark-v9.json)及三场共 63,862 次完整本人合法观察重放，零异常/非法动作。记录见 [Crossover 正式场](experiments/replay-v9-crossover.json)、[Highland](experiments/replay-v9-highland.json)、[旧事故场](experiments/replay-v9-damage.json)。
- [三赛道简化模型](experiments/kinematic-v9-body-slip.json)均完成一圈且未越路缘；不包含真实轮胎动力学，不将模型圈时作为比赛成绩。
- [针对最新场的固定输入诊断](experiments/v9-latest-diagnostics.json)确认误省油 258→0 次；[旧事故诊断](experiments/v9-damage-diagnostics.json)保持 465.333 s 首次失稳响应。改变动作不推进历史轨迹，不能宣称新的圈速、超车成功或救回事故。
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
