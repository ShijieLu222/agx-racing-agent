# 来源与许可说明

本项目核对 AGX 官方赛车示例、车辆设计、体育/技术规则及公开工具包。初始控制问题和设计参数参考官方 starter；策略实现、测试与工程工具在本项目中编写。官方示例未附明确开源许可，本仓库不替其声明 MIT 或其他再许可权。

- [官方 Python 示例](https://agx.cool/docs/schema/racing.example.agent.py)
- [官方车辆设计](https://agx.cool/docs/schema/racing.example.design.json)
- [官方赛车工具包](https://agx.cool/docs/schema/kits/agx-racing-kit.zip)
- [公开赛道数据](https://agx.cool/docs/schema/maps/racing.html)

`track_data.py` / `track_*.py` 中的赛道几何数据库派生于官方公开地图，原始数据标注：**© OpenStreetMap contributors · ODbL 1.0; Copernicus DEM / SRTM**。派生几何数据库按 [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/) 提供；[OpenStreetMap 版权说明](https://www.openstreetmap.org/copyright)。本仓库保留这些归属，生成脚本和源数据 SHA256 用于追溯。该数据许可不代表 AGX 引擎或其他官方代码的许可。

控制器研究还参考 CMU、F1TENTH 和 TUM 的公开工作；未复制其源码或引入相关运行库，具体链接与许可证见[策略参考](docs/strategy-references.md)。

官方公开观察样例只用于协议测试。没有收录用户私有日志、凭据、课程 PDF 或其他参赛者的隐藏观察。
