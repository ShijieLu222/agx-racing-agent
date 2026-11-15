# 策略参考与实现边界

核查日期：2026-11-15。赛车合同为 `rsi-racing-4.4`；赛事冻结版本与本人合法观察是最终依据。

本项目查阅以下一手资料，独立实现轻量 Python 控制，不复制 F1TENTH / TUM 源码，也不引入 ROS 或优化器依赖。

| 来源 | 实际查阅内容 | 本项目采用的原则 |
| --- | --- | --- |
| [AGX 体育规则](https://agx.cool/docs/racing-sporting.zh.md)、[官方 starter](https://agx.cool/docs/schema/racing.example.agent.py)、[官方赛车工具包](https://agx.cool/docs/schema/kits/agx-racing-kit.zip) | 合法输入输出、30 Hz 回调、车辆设计、前视、进站与轮胎规则；公开赛道与近似模型 | 参数、单位和参赛状态以 AGX 为准；完整几何是合法公开数据，未来天气与比赛引擎内部状态不是策略输入。 |
| [Coulter：Implementation of the Pure Pursuit Path Tracking Algorithm](https://www.ri.cmu.edu/pub_files/pub3/coulter_r_craig_1992_1/coulter_r_craig_1992_1.pdf) | 几何路径跟踪与前视距离的影响 | 前方曲率提供转向前馈，横向误差和航向误差需要闭环修正；前视过长可能切弯，不能只追远处一点。 |
| [F1TENTH Pure Pursuit](https://github.com/f1tenth-dev/pure_pursuit)、[adaptive_lookahead.py](https://github.com/f1tenth-dev/pure_pursuit/blob/master/scripts/adaptive_lookahead.py) | 随赛道区域调整前视与速度的监督控制 | 弯道和直道使用不同控制余量；借鉴架构，不移植缩比车的速度、轴距、单位或增益。该仓库为 [Apache-2.0](https://github.com/f1tenth-dev/pure_pursuit/blob/master/LICENSE)。 |
| [TUM trajectory_planning_helpers：calc_vel_profile.py](https://github.com/TUMFTM/trajectory_planning_helpers/blob/master/trajectory_planning_helpers/calc_vel_profile.py) | 横向加速度限速、前向加速与后向制动传播；闭合赛道跨起终点处理 | 速度规划必须预留前方制动距离，并正确处理闭环接缝。此库为 [LGPL-3.0](https://github.com/TUMFTM/trajectory_planning_helpers/blob/master/LICENSE)，本项目没有复制或链接它。 |

## 设计选择

- **速度规划：** 根据前方曲率限制目标速度，并用制动距离提前降低速度；湿度、磨耗、打滑及偏离赛道时保留更大余量。`v²κ` 和 `v² <= u² + 2ad` 是近似关系，不能把自选加速度当成平台的完整轮胎极限。
- **路径跟踪：** AGX 的曲率、横向偏移、航向误差和转向均以向左为正。`self.steer` 是实际轮角（rad），动作 `steer` 才是归一化值。制动和转向需要结合车况，不能仅提高直道限速。
- **交通：** 只使用合法可见对手的相对距离、横向位置与速度。换道保留目标和安全间隔，避免每拍左右切换；空间不足时跟车。
- **轮胎：** 干地正赛需要实际使用两种不同干胎键；请求换胎或排位用过的胎都不够。进站请求在入口前需持续，完整驶出后才增加停站数。湿地豁免只在正赛路面湿度达到 0.5 后锁存。
- **能量与气动：** 读取本人 SOC、热状态和超车资格；主动气动与电能超车是不同门。刹车、进站、低抓地和恢复控制优先于加速。

公开工具包没有完整比赛引擎。合成测试验证协议和行为分支；近似模型验证规划一致性与耗时，不证明正式完赛、排名或胜率。拿到本人训练日志后应按赛道、天气和轮胎条件校准，并保留未用于调参的完整对局做验证。
