# AGX Racing Agent

用于 AGX 多人赛车的 Python 车手、车辆设计与实验。合同 `rsi-racing-4.4`，核查日期 2026-11-15。

**v5：取消固定最高时速与功率压制，燃油 15 kg。** 保留实际上传 v4 的三赛道完整约 2 米几何，结合当前下压力、质量、制动力和道路曲率规划过弯与刹车。正式圈速需下一场对局验证。

本场本人完成 3 圈、状态 `finished`，被套圈后收车；正赛实际耗油 1.5966 kg。实际上传 v4 的干地上限为 300 km/h，满湿地降至 278.4 km/h。完整证据、其他选手公开操作及修改说明见[本场分析](docs/parkland-2026-11-15.md)，平台版本和包指纹见[实验日志](experiments/iteration-log.md)。

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

| 模块 | v5 行为 |
| --- | --- |
| 直道 | 无固定 km/h 上限，由引擎、阻力和前方制动需求决定 |
| 道路 | 检查完整约 2 米地图原始节点及全部合法前视，范围至少覆盖估计停车距离；处理圈长舍入和接缝 |
| 弯道 | 根据轮胎系数假设、下压力和有效质量估计过弯能力，逐区间反向传播制动约束并考虑下坡 |
| 动力 | 取消滑移标志驱动的持续降速、0.28/0.65 固定油门上限、温度固定限速及目标恢复斜坡 |
| 制动 | 跟随下降的制动计划，避免只看即时速度误差而刹晚；发动机力估计变化不触发直道误刹 |
| ERS | 加速和出弯可请求 attack，取消固定电量储备和恢复等待，制动时回收 |
| 燃油 | 初始 15 kg；仅在实测单位距离耗油推算不足以到终点时按缺口比例调整油门 |
| 转向和交通 | 当前曲率前馈及航向、横向、侧滑和偏航反馈；保持机械转向约束、避碰与超车车道选择 |
| 进站 | 保留干地双胎种、实际湿地豁免与进出站确认；按平台资格请求超越及 X 气动 |

抓地系数及下压力平方外推是待验证的控制近似，不能替代完整轮胎与气动模型。没有使用未来天气、隐藏对手状态或种子预测。严重侧滑、偏航、道路边界和临近碰撞仍会触发响应。

车辆配重 20 kg，前轴 45%；除燃油外其余设计沿用本人 v4。范围与约束见[规则说明](docs/rules.md)。

## 验证与复现

- 71 项测试覆盖接口、设计、地图窄峰和接缝、进站、紧急制动、无固定限速、attack 和阶段重置。
- [30,000 次合成调用](experiments/benchmark-v5.json)检查接口与 CPU；[三赛道简化模型](experiments/kinematic-v5.json)检查转向和制动反馈。两者均不等于正式比赛成绩。
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
