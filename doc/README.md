# 地检上位机（卫星激光终端地面检测系统）设计文档

> 本目录为项目的设计文档集。按照「先文档、后编码」的原则，先在此沉淀总体方案、
> 数据库设计、前后端接口与页面设计，再进入代码实现阶段。
>
> 本系统基于 [RuoYi-Vue3-FastAPI](https://github.com/insistence/RuoYi-Vue3-FastAPI) 二次开发，
> 是一套 **B/S 架构的实时数据采集、监控、控制与可视化系统**，用于卫星激光通信终端的地面检测。

---

## 一、项目概览

| 项目          | 说明                                                                 |
| ------------- | -------------------------------------------------------------------- |
| 系统定位      | 卫星激光终端地面检测上位机（地检平台）                                |
| 架构          | 浏览器 / 服务器（B/S），多进程数据采集 + FastAPI 服务 + Vue3 前端     |
| 进程间通信    | Redis（采集进程 ⇄ 主进程）                                            |
| 设备接入      | CAN 总线、串口（RS422）、网络（TCP/UDP）                              |
| 业务来源      | 由 C++ 桌面端 `GeniusProsSoftPlatform` 移植（参考源码在开发机本地 `test/` 目录，未入库） |
| 数据库        | MySQL（`--env=dev`，`.env.dev` 中 `DB_TYPE='mysql'`）；可切 SQLite（`--env=sqlite`）或 PostgreSQL（`.env.dockerpg`） |

### 目录结构（仓库根）

| 目录                       | 说明                                                |
| -------------------------- | --------------------------------------------------- |
| `ruoyi-fastapi-backend`    | 后端项目（Python + FastAPI）                         |
| `ruoyi-fastapi-frontend`   | 前端项目（Vue3 + Element Plus）                      |
| `ruoyi-fastapi-app`        | 手机前端                                             |
| `dist`                     | 离线安装包与脚本；`dist/pkg/` 下为扩展 wheel（gpcan、telemetryparser） |
| `ruoyi-fastapi-test`       | Playwright E2E 测试（见其 README）                  |
| `.github/workflows`        | CI：`unit-tests.yml`（pytest + vitest）、`playwright.yml`（E2E）、`ruff.yml` |
| `doc`                      | 设计文档（本目录）                                   |

### 关键依赖库（位于 `dist/pkg/`）

| 库                                       | 用途                       | 源码参考                |
| ---------------------------------------- | -------------------------- | ----------------------- |
| `gpcan-1.0.5-py3-none-any.whl`（`dist/pkg/`，另存旧版 1.0.4） | CAN 通信（收发、组帧，适配 gpcan 3.x API） | 本地 `test/pygpcan`（未入库） |
| `telemetryparser-1.0.1-py3-none-any.whl`（`dist/pkg/`） | 遥测帧解析 | 本地 `test/TeleMetry`（未入库） |

> 这两个 wheel 不在 PyPI，`requirements.txt` 中仅以注释记录，需单独安装：
> `pip install dist/pkg/telemetryparser-1.0.1-py3-none-any.whl dist/pkg/gpcan-1.0.5-py3-none-any.whl`（Windows 用 `dist\pkg\...`），详见根目录 `README.md`。

> 文档中出现的 `test/...` 路径（如 `test/pygpcan`、`test/TeleMetry`、`test/GeniusProsSoftPlatform`）均为开发机本地参考资料，**不在本仓库中**。

---

## 二、文档索引

| 文档                                                                 | 内容                                                              |
| -------------------------------------------------------------------- | ---------------------------------------------------------------- |
| [01-系统总体设计](./01-系统总体设计.md)                              | 总体架构、进程模型、数据流、技术选型、新增目录规划                |
| [02-数据采集层设计](./02-数据采集层设计.md)                          | CAN/串口/网络采集进程、进程管理、Redis IPC 协议、数据解析         |
| [03-数据库设计](./03-数据库设计.md)                                  | 新增数据表（指令序列、菜单）、三套 SQL 与 SQLite 同步方案         |
| [04-后端接口设计](./04-后端接口设计.md)                              | `module_payload` 模块划分、REST API 清单与出入参                  |
| [05-前端页面设计](./05-前端页面设计.md)                              | 首页设备服务、遥控/遥测/单板/调试页面、共用连接弹窗与 tooltip/缓存约定 |
| [06-配置文件说明](./06-配置文件说明.md)                              | `TeleControlCfg.json` / `TeleMetryCfg.json` 字段与组件类型说明    |
| [07-遥控帧组装与遥测解析规则](./07-遥控帧组装与遥测解析规则.md)      | 遥控组件编码、校验和、广播帧、遥测解析公式与格式化               |
| [08-开发计划与里程碑](./08-开发计划与里程碑.md)                      | 分阶段实施计划、任务拆解、验收要点                                |
| [09-遥测Redis存储与前后端显示流程](./09-遥测Redis存储与前后端显示流程.md) | 遥测落 Redis、曲线全字段存储、表/曲线前端轮询与设计取舍         |
| [10-开发测试注入请求完整调用流水线](./10-开发测试注入请求完整调用流水线.md) | 一次「开发测试发送」：鉴权 SQL、Redis、业务函数逐步流水线     |
| [11-遥测永久存储与表结构设计](./11-遥测永久存储与表结构设计.md) | 永久归档：MySQL 表设计、Redis 热层、原始+解析、分区与实施阶段   |
| [12-数据解析与来源归档重构](./12-数据解析与来源归档重构.md) | dataSub/srcParam、解释器绑定、热键按子类型共享；**含解释器模型澄清与 CAN 遥控响应【后续】标记** |
| [13-Redis功能与键一览](./13-Redis功能与键一览.md) | **现有 Redis 能力全清单**：业务/平台 Key、IO 双写、会话组装器、TTL、对照表 |
| [14-未完成事项](./14-未完成事项.md) | **开放缺口登记**：已知延后/待做项；后续未完成一律写入此文 |
| [15-新增总线协议接入清单](./15-新增总线协议接入清单.md) | **加一套 CAN 总线族要改的文件**。以 YJ216 为样例，下次按清单校对 |
| [平台人工功能测试清单.xlsx](./平台人工功能测试清单.xlsx) | **人工功能测试勾选表**：按页面覆盖登录壳层、设备服务、遥控/遥测/单板/LVDS/调试及系统管理监控 |

---

## 三、阅读建议

1. 先读 [01-系统总体设计](./01-系统总体设计.md) 建立整体认知；
2. 关注数据如何在「设备 → 采集进程 → Redis → 主进程 → 前端」之间流转，见 [02](./02-数据采集层设计.md)；
3. 实施前对照 [03 数据库设计](./03-数据库设计.md) 完成菜单与表结构落库；
4. 前后端联调对照 [04 接口设计](./04-后端接口设计.md) 与 [05 页面设计](./05-前端页面设计.md)；
5. 涉及具体协议字节的实现细节，查阅 [06 配置说明](./06-配置文件说明.md) 与 [07 组帧/解析规则](./07-遥控帧组装与遥测解析规则.md)。

> 文档中标注 **【待确认】** 的条目，为实现前需与硬件 / 协议方确认的设计点。

---

## 四、文档维护

| 日期 | 说明 |
| ---- | ---- |
| 2026-10-15 | 文档与代码对齐：04 接口表按 `module_payload/controller` 逐条核对（补 24 个接口、新增 7.1 单板 / 7.2 LVDS，`/payload/telemetry/pages` 更正为 `/config` + `/def`，权限列按代码更正，设备接口标注“仅登录”）；数据库默认值统一为 MySQL（`.env.dev`）；`whl/` → `dist/pkg/`、gpcan 1.0.5；03 ORM 路径更正为 `payload_sequence_do.py`（见 01/02/03/04/05/06/08）。 |
| 2026-10-14 | 协议文件名与入口对齐：三条总线都在 `protocol/<族>/can/`，文件为 `tc.py` / `tm.py` / `tm_timed.py`，入口为 `assemble` / `verify_tm` / `timed_tm`，不带族名；YJ216 回放扫描并入 `can/tm.py`。04/09/11 的旧解释器 id `tm_can_yc` 改为 `tm_can_biu`（见 01/04/07/09/10/11/12/15）。 |
| 2026-10-14 | 帧协议目录重构：`assemblers/`、`parsers/`、`cfg/*_telecontrol_assembler.py` 收进 `module_payload/protocol/{biu,xl,yj216}`，三家互不 import；落库零件进 `module_payload/tm/`。框架经 `protocol/registry.py` 按协议清单的 `module` 查 `BINDINGS`，不再按族名分支（见 01/02/07/10/12/15）。 |
| 2026-10-14 | 协议清单归位：`protocol_catalog.py` 移到 `module_payload/protocol/`；`BusFamily` / `BUS_FAMILIES` 改名 `CanBusFamily` / `CAN_BUS_FAMILIES`，一行只写族名（YJ216 另给解释器显示名），id、JSON 名、gpcan 名、模块路径由族名推出；删去 `ASSEMBLER_CAN_*` / `PARSER_TM_CAN_*` 常量（改用 `bus_assembler_id` / `bus_parser_id`）和遥控旧缓存键别名（见 01/02/04/06/12/15）。 |
| 2026-10-14 | 九月以来实现同步：YJ216 菜单 2600–2608、`family=yj216` 与 `YJ216-*` 配置、调试页「校验计算」2505；CAN `.txt` 与串口/网卡 `.bin` 落盘及 fileplay 拆帧约定（见 02/03/04/05/06/11）。 |
| 2026-09-03 | 自 `16e8230` 起全量对齐：遥控 BIU/XL 分族、遥测六页（实时/曲线/历史 CAN/历史文件）、调试菜单、单板地检板、fileplay/canplay 回放 API、HEX 统一规则、全双工与 IO 内存环缓、配置文件在线编辑等（见 02/03/04/05/06/07/11）。 |
| 2026-09-03 | 同步相机 V1.7 全链路：菜单 2205、D8V17/D9V17 遥测表、`tm_xl_camera_v17` / `camera_image_d6_v17`、共用 `camera/index.vue`、D6 帧标识按位规则、`cfg_device_connect.json`、模拟页 v17 黄金样本等（见 03/04/05/06/07/12/14）。 |
| 2026-07-30 | 同步近期实现：首页设备服务 UI、CAN/UDP/串口独立连接弹窗、组装器/解释器统一 tooltip、遥控页树交互与过滤、IO 双写与会话 `assemblerId`/`source`、设备 snapshot/bind-parser 等（见 01/04/05/13）。 |
