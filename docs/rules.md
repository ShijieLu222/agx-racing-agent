# AGX Formula 规则与设计依据

核查日期：2026-11-15。当前合同 `rsi-racing-4.4`，内核 `rsi-formula-4.0`。正式赛事及对应冻结合同优先于本文；这是平台规则摘要，不是现实 F1 认证标准。

## 一手资料

- [当前赛车赛事](https://agx.cool/#/competitions/1eb91364-950b-5725-aa4b-3501b16860ec)
- [体育规则](https://agx.cool/docs/racing-sporting.zh.md)：观察、动作、计时、进站和分类。
- [技术规则](https://agx.cool/docs/racing-regs.zh.md)：车辆字段范围、步长与跨字段约束。
- [Python 入门](https://agx.cool/docs/racing-starter.zh.md)
- [官方 agent.py](https://agx.cool/docs/schema/racing.example.agent.py) 与 [design.json](https://agx.cool/docs/schema/racing.example.design.json)
- [公开赛道数据](https://agx.cool/docs/schema/maps/racing.html)、[本地工具包](https://agx.cool/docs/schema/kits/agx-racing-kit.zip)：数据与近似分析工具，平台没有提供完整模拟器。

## 赛制和时间预算

十辆赛车各跑一次单圈排位，再跑四圈正赛。排位滚动发车，正赛静止发车；正赛车辆的燃油、轮胎、车况和停站计数重新建立，Python 进程和周末时钟继续。因此策略需在 `phase` 变化时重置阶段状态。

物理 60 Hz，`act(observation)` 每两拍调用一次（30 Hz），期间保持上次动作。每席独立进程、初始化 2 秒、每次回调 0.2 秒、排位及正赛合计 55 CPU 秒，初始化也计入。比赛宿主 wall 上限 1140 秒与验证预算 120 秒不是单车可用 CPU 额度。请求/响应上限为 1 MiB/64 KiB。

计时触发值 `T = 7200 × 4 / (floor(305000 / track_length_m) + 1)` 秒，正赛绝对时限为 `T + 120` 秒；排位每席时限为 `track_length_m / 55 + 120` 秒，均在首个达到时限的物理 tick 结束。前 10 秒和维修区期间豁免停滞判断，其他连续 30 秒内净前进不足 10 米会退赛。

平台按分类使用 OpenSkill，展示积分不替代排名。一般先比较完成圈数，再比较合法冲线时间；取消成绩者排在最后。未到冠军圈数 90% 向下取整门槛者未分类。时限结束仍在跑的车记 `running`，不等于接口故障，也不能当作完赛。

## 关键观察与控制单位

| 字段 | 含义 |
| --- | --- |
| `self.s` / `self.distance` | 单圈位置 / 累计进度，米；单圈位置按当前 `track_length_m` 环绕 |
| `self.n` / `self.heading_error` | 相对中心线横向距离，米 / 朝向误差，弧度；左侧为正 |
| `self.vx` / `self.vy` / `self.yaw_rate` | 车身向前、向左速度 m/s / 向左偏航角速度 rad/s |
| `self.steer` | 实际前轮角，rad，不是归一化动作 |
| `self.lap` / `self.pit_stops` | 已完成圈数 / 已通过出口的完整停站数 |
| `self.pit_state` | 0 在赛道、1 进站通行、2 静止服务、3 出站通行 |
| `self.tyre_wear` / `self.tyre_temp_c` | 四轮已消耗比例 / 摄氏度；依次左前、右前、左后、右后 |
| `self.fuel_kg` / `self.ers_soc_mj` | 燃油 kg / 电池储能 MJ |
| `self.effective_mass_kg` | 含等效旋转质量的当前质量，不应以设计干重代替 |
| `self.drag_n` / `self.downforce_n` / `self.brake_force_max_n` | 当前阻力 / 下压力 / 标称制动容量，N |
| `self.drive_force_n` | 四个 ERS 模式的标称驱动力，N；不是完整抓地响应模型 |
| `preview.rows` | 24 行，15 m 间隔；第一行在前方 15 m，并非当前位置 |
| `rivals[].gap_m` / `dn` | 最近有符号纵向间距 / 对手 n 减自身 n，米；前方、左侧为正 |

按 `preview.columns` 查找列名：`distance_m`、`curvature_1pm`、`grade`、`half_width_left_m`、`half_width_right_m`、`aero_zone`。曲率向左为正，坡度为平滑后的坡角正弦，不完全等于地图几何纵坡。可见对手限沿赛道折返距离 400 米内，排位为空；未提供隐藏对手状态和未来天气。

控制必填 `throttle`、`brake`、`steer`，空对象非法。油门、刹车在 0..1，转向在 −1..1；数值必须有限且不能为 bool。轮距控制模型的轴距为 3.4 m，最大前轮角 0.3 rad，角速度上限 1.6 rad/s。低速 `atan(3.4 × 曲率)` 可做前馈，但不是高速轮胎极限。

可选动作：`ers_mode` 为整数 0..3（回收、neutral、balanced、attack），`aero_mode` 为 0/1（Z/X），`aid`、`override`、`pit_request` 为 bool，`pit_compound` 为 soft/medium/hard/null。不得返回其他字段或错误类型。

## 进站、轮胎与天气

- 没有加油和救援动作。进站请求必须保持 `true` 到入口；入口前返回 `false` 会取消。到入口时冻结此次胎种，不能通过后续动作改变已开始的服务。
- 平台自动管理限速通行、停车换胎 2.4 秒、出站。仍须返回合法动作，但正常油门/转向不控制维修区通行；在出口完成后才增加 `pit_stops`。
- 无湿地豁免时，正赛必须实际使用两种不同干胎键。换胎请求或完成服务本身不算，换胎后在赛道向前行驶才计入；排位使用胎种不计入正赛。
- 只有正赛的 `track_wetness >= 0.5` 锁存湿地豁免。damp、预报有雨、排位下雨都不够；轮胎动作仍只有 soft/medium/hard，无 `wet` 枚举。
- 当前天气每拍更新，预报在排位前冻结。可选完整 `rain_design` 仅在冻结雨险严格大于 40% 时可启用，不能在回调动态改车。
- 低抓地门槛湿度 0.5 会禁用电能超越。`aid` 和正赛 `override` 共用资格，不叠加；制动至少 0.05 时停用。当前合法资格直接读自身字段，不从未来录像重建。
- X 低阻气动另受区域剩余长度大于 45 m、制动小于 0.05、非维修区条件限制。前视采样标志不保证精确揭示当前位置的区域余量。

## 三赛道设计兼容

正式局在 Parkland、Highland、Crossover 轮换，排位与正赛共用选定赛道。设计书需同时满足通用范围、步长、跨字段条件和赛道/胎方约束。

| 赛道 | 前/后有效最低胎压 psi | 前/后外倾下限 ° | hard / medium / soft |
| --- | --- | --- | --- |
| Parkland | 26 / 26 | −3 / −2 | C3 / C4 / C5 |
| Highland | 28 / 28 | −2.75 / −1.5 | C2 / C3 / C4 |
| Crossover | 28 / 26 | −2.75 / −1.5 | C1 / C2 / C3 |

Crossover 赛道后胎底线为 25 psi，公开地图的 `effective_pressure_floor_psi` 考虑胎方后为 26 psi；不能仅校验赛道底线。每圈回收上限均为 8.5 MJ。参数数据来自上述官方地图工具包。

本项目 v5 保留官方示例的翼面、悬挂、传动、冷却及 29/28 psi 胎压；配重 **20 kg**，前轴 **45%**。按用户最终选择使用 **15 kg 燃油**。本场本人 22 kg 起步、三圈消耗 1.5966 kg，冠军四圈消耗 4.8512 kg；15 kg 对本场有明显余量，新动力策略仍需重新测量，见[本场分析](parkland-2026-11-15.md)。

- 干重 `748 + 20 = 768 kg`，满足最低 768 kg。
- 前轴 `768 × 45% = 345.6 kg >= 337.92 kg`；后轴 `422.4 kg >= 414.72 kg`。
- 配重下限 `20 + 8.2 × abs(45 − 45) = 20 kg`。
- 八档齿比逐档递减，相邻比值在 1.08..1.45；一档总传动比 `4.1 × 5.4 = 22.14 <= 25.1`。
- 前后离地高度差 `75 − 40 = 35 mm`，在 0..70 mm 内。
- 胎压 29/28 psi 与外倾 −2.5/−1.5° 满足三赛道约束；其余字段在官方范围和步长网格内。

未添加未经标定的雨天备用设计，车手按实际湿度调整驾驶。燃油和悬挂等性能权衡需以后用本人完整对局日志验证，再做独立实验；本地几何模拟和准入通过均不证明优秀圈速或胜率。

## 提交与日志

ZIP 根目录必须包含 `agent.py` 和 `design.json`。外层 JSON 只允许 `design` 和可选 `rain_design`，各自是完整设计，单份 4096 UTF-8 字节上限；禁止缺项、多项、重复键、NaN/Infinity、布尔数值及错误步长。

上传成功、准入通过、版本生效、正式排名结果分别核对。本人日志只从已授权席位导出并检查 `export_complete`，保存到被 Git 忽略的私有目录；公开回放不是当时合法观察，不能用于逆造隐藏输入。
