# 13 · Redis 现有功能整理

> 目标：一次性说清 **当前系统哪些能力用了 Redis、各自干什么、Key 长什么样**。  
> 键定义代码：`ruoyi-fastapi-backend/module_payload/redis_keys.py`、`common/enums.py`（`RedisInitKeyConfig`）。  
> 读写封装：`module_payload/redis_store.py`；采集侧同步客户端：`module_payload/collectors/redis_sync.py`。
>
> 遥测热数据细节另见 [09-遥测Redis存储与前后端显示流程](./09-遥测Redis存储与前后端显示流程.md)；采集 IPC 另见 [02-数据采集层设计](./02-数据采集层设计.md)。

---

## 一、总览：Redis 在系统里扮演什么角色

| 角色 | 说明 |
| ---- | ---- |
| **进程间通信（IPC）** | 主进程（FastAPI）与采集子进程通过 List / String 交换指令、控制、心跳、状态 |
| **实时热数据** | 遥测最新帧、曲线点、遥控发送历史、相机图、LVDS 点等，供前端轮询 |
| **异步落库队列** | 归档 / 遥控发送记录先入 Redis List，后台 worker 再写 MySQL |
| **会话与执行态** | 设备打开会话（含解释器绑定）、指令序列异步执行进度 |
| **平台基础能力** | 登录令牌、验证码、字典/参数缓存、接口缓存与限流、传输层防重放与监控统计 |

```text
设备 ──► 采集进程 ──► Redis(热数据/队列/IPC) ◄──► FastAPI 主进程 ──► 前端轮询
                              │
                              ▼
                     归档 Worker ──► MySQL（永久）
```

业务 Key 统一前缀 **`payload:`**；若依平台 Key 见下文「平台基础能力」一节（无统一 `payload:` 前缀）。

---

## 二、地检业务（`payload:`）功能清单

### 2.1 采集进程 IPC（开设备 / 发令 / 保活）

主进程与采集进程共享同一 Redis。主进程 **LPUSH** 指令/控制；采集进程循环 **LPOP** 消费并写回结果。

| 功能 | Key | 类型 | TTL / 容量 | 作用（具体） |
| ---- | --- | ---- | ---------- | ------------ |
| 设备状态 | `payload:{deviceId}:status` | String(JSON) | 无（关通道时 delete） | 连接态、`rx/tx` 计数、错误信息；设备页 / 打开会话查询 |
| 进程心跳 | `payload:{deviceId}:heartbeat` | String | **15s** | 采集进程周期性刷新；主进程据此判断进程是否存活 |
| 指令队列 | `payload:{deviceId}:cmd` | List | — | 主进程下发遥控帧（含 `cmd_id`、HEX）；采集 **LPOP** 后硬件发送 |
| 控制队列 | `payload:{deviceId}:ctrl` | List | — | 开/关通道、停进程、相机启停等控制消息 |
| 指令结果 | `payload:{deviceId}:cmd:result:{cmdId}` | String(JSON) | **120s** | 采集写回成功/失败；主进程短轮询 `GET` 等待返回 |
| 发送历史（热） | `payload:{srcParam}:history` | List | 保留最近 **100** 条 | 遥控页「发送历史」即时展示；成功发送后 LPUSH + LTRIM |

`deviceId` / `srcParam` 形态示例：

| 类型 | 标识示例 |
| ---- | -------- |
| CAN 卡（进程粒度） | `can:{vendor}:{devIndex}` |
| CAN 通道 | `can:{vendor}:{devIndex}:{canIndex}` |
| 串口 | `serial:{port}` |
| 网络 | `net:{proto}:{ip}:{port}` |

**读写方**：采集 `base_collector` / `can_collector` / `process_manager`；主进程 `redis_store.push_command` / `wait_command_result`、`payload_device_service`、`payload_telecontrol_service`。

---

### 2.2 设备会话与解释器绑定

| 功能 | Key | 类型 | 作用（具体） |
| ---- | --- | ---- | ------------ |
| 会话 | `payload:session:{srcKind}:{srcParam}` | String(JSON) | 记录设备已打开、绑定的 `parserId`、打开时间、状态；打开/关闭设备时 set/delete；采集解析前按 `srcParam` 取解释器 |

字段大致含：`srcKind`、`srcParam`、`parserId`、`openedAt`、`status`。  
**服务**：`payload_session_service.py`；列表接口扫描 `payload:session:*`。

---

### 2.3 遥测热数据（表页 + 实时曲线）

按 **数据子类型 `dataSub`（如 FF）** 共享，**不再按设备分键**；帧 JSON 内带 `srcParam` / `srcKind` / `parserId` 标明来源。

| 功能 | Key | 类型 | 容量 / 策略 | 作用（具体） |
| ---- | --- | ---- | ----------- | ------------ |
| 最新一帧 | `payload:tm:{TYPE}:latest` | String(JSON) | 覆盖写 | 遥测表页当前值；含全部字段、时间、`dataId`、来源元数据 |
| 最新时间戳 | `payload:tm:{TYPE}:latest:ts` | String | 覆盖写 | 可读时间字符串，辅助展示/调试 |
| 字段曲线 | `payload:tm:{TYPE}:curve:{fieldId}` | ZSet | 每字段最多 **50000** 点；超限删最旧 | score=`tsMs`，member=`{tsMs}\|{val}`；曲线页增量/全量拉取 |

**写入**：采集 `_write_telemetry`；开发注入 `inject_can_yc` → `set_telemetry` + `append_curve_points`。  
**读取**：`GET /payload/telemetry/table`、`POST /payload/telemetry/curve/data/batch`。  
**原则**：落库与前端是否加曲线无关——能数值化的字段都会进 ZSet。

---

### 2.4 归档与遥控落库异步队列

热数据进 Redis 后，额外投递队列，由归档 Worker 批量写入 MySQL（永久层）。

| 功能 | Key | 类型 | 作用（具体） |
| ---- | --- | ---- | ------------ |
| 遥测归档队列 | `payload:archive:queue` | List | 采集/注入后 LPUSH 帧事件；Worker **BRPOP** 消费 → 写帧表 + 数值点表 |
| 遥控发送归档队列 | `payload:tx:queue` | List | 指令发送成功后 LPUSH；Worker **LPOP** 消费 → 写遥控发送记录表 |

失败重试等逻辑在 `payload_telemetry_archive_service.py`。归档曲线查询走 **MySQL**，不读上述热 ZSet。

---

### 2.5 指令序列异步执行

序列定义在 MySQL；**单次运行态**放 Redis，供前端轮询进度与历史。

| 功能 | Key | 类型 | TTL / 容量 | 作用（具体） |
| ---- | --- | ---- | ---------- | ------------ |
| 单次运行详情 | `payload:seq:run:{runId}` | String(JSON) | **7 天** | 当前步、每条指令状态/结果、整体 running/done/error |
| 序列运行历史 | `payload:seq:{seqId}:runs` | List | 最近 **50** 条 runId，同 7 天过期 | 序列页「执行历史」；元素为 runId，详情再读 `seq:run:*` |

**服务**：`payload_sequence_service` + `redis_store.save_seq_run` / `get_seq_run` / `list_seq_run_history`。  
接口：`POST .../run`、`GET .../run/{runId}`、`GET .../{seqId}/runs`。

---

### 2.6 相机图像（串口）

| 功能 | Key | 类型 | 作用（具体） |
| ---- | --- | ---- | ------------ |
| 图像元数据 | `payload:{deviceId}:image:meta` | String(JSON) | 宽高、时间等；串口采集写 |
| 图像数据 | `payload:{deviceId}:image:data` | String(Base64) | 最新一帧图；相机页拉取 |

`deviceId` 一般为 `serial:{port}`。控制启停仍走 `ctrl` 队列。

---

### 2.7 工程遥测（LVDS）

| 功能 | Key | 类型 | 作用（具体） |
| ---- | --- | ---- | ------------ |
| 信号点序列 | `payload:{deviceId}:lvds:{signal}` | List(JSON 点) | 高速工程量短时缓存；接口按 signal 拉取最近 N 点 |

当前读路径：`payload_lvds_service` / `get_lvds_points`（默认 demo 设备 `lvds:demo`）。写入侧随采集/演示注入扩展。

---

## 三、平台基础能力（若依 `RedisInitKeyConfig` 等）

与地检 `payload:` 并存于同一 Redis 实例（配置见 `config/get_redis.py` / 环境变量）。

| 功能 | Key 模式 | 作用（具体） |
| ---- | -------- | ------------ |
| 登录令牌 | `access_token:{sessionId}` 或 `access_token:{userId}` | JWT 会话存放与续期；在线用户列表、强退、登出删键 |
| 数据字典 | `sys_dict:{dictType}` | 字典项 JSON 缓存，减少 DB 读 |
| 系统参数 | `sys_config:{configKey}` | 如验证码开关、注册开关、黑名单 IP、初始密码策略等 |
| 接口响应缓存 | `api_cache:{namespace}:{digest}` | `@Cache` 注解结果缓存 |
| 接口限流 | `api_rate_limit:{namespace}:{algo}:{digest}[:bucket]` | `@RateLimit` 计数窗口 |
| 图片验证码 | `captcha_codes:{uuid}` | 登录/注册校验，短 TTL（约 2 分钟） |
| 账号锁定 | `account_lock:{userName}` | 密码错误过多后临时锁定 |
| 密码错误计数 | `password_error_count:{userName}` | 累计错误次数（约 10 分钟窗口） |
| 短信验证码 | `sms_code:{sessionId}` | 忘记密码等流程（约 2 分钟） |
| 缓存监控 | 运维页读 `INFO` / `KEYS` / 按前缀清理 | `CacheService`；可按名称清缓存 |

### 传输层加解密（独立前缀）

| 功能 | Key 模式 | 作用（具体） |
| ---- | -------- | ------------ |
| 防重放 | `transport:replay:{kid}:{nonce}` | `SET NX` + TTL，拒绝重复 nonce |
| 监控聚合 | `transport:monitor:*`（`counters` / `kids` / `recent_failures` / 按 kid 计数等） | 多 worker 聚合加解密成功/失败统计；监控页展示 |

---

## 四、按「用户能感知的功能」对照

| 用户侧功能 | Redis 用途摘要 |
| ---------- | -------------- |
| 打开/关闭 CAN、串口 | `session` + `status` + `heartbeat` + `ctrl` |
| 单条遥控发送 | `cmd` → `cmd:result` → `history` + `tx:queue` |
| 指令序列运行 / 进度 / 历史 | `seq:run:*` + `seq:{id}:runs` |
| 遥测表实时值 | `tm:{TYPE}:latest` |
| 实时曲线 | `tm:{TYPE}:curve:{field}` |
| 归档曲线 | **不读 Redis 热曲线**；读 MySQL（由 `archive:queue` 异步写入） |
| 相机预览 | `image:meta` / `image:data` |
| LVDS 工程量 | `lvds:{signal}` |
| 登录 / 在线用户 / 验证码 | `access_token` / `captcha_codes` 等 |
| 系统字典与参数 | `sys_dict` / `sys_config` |
| 传输加密监控 / 防重放 | `transport:*` |

---

## 五、容量与 TTL 速查

| 项 | 值 | 出处 |
| -- | -- | ---- |
| 心跳 TTL | 15 s | `HEARTBEAT_TTL` |
| 指令结果 TTL | 120 s | `CMD_RESULT_TTL` |
| 发送历史条数 | 100 | `HISTORY_MAX` |
| 曲线每字段点数 | 50000 | `CURVE_MAX_POINTS` |
| 序列运行态 TTL | 7 天 | `SEQ_RUN_TTL` |
| 序列历史 run 数 | 50 | `SEQ_RUN_HISTORY_MAX` |

---

## 六、相关代码索引

| 模块 | 路径 |
| ---- | ---- |
| Key 命名 | `module_payload/redis_keys.py` |
| 主进程异步读写 | `module_payload/redis_store.py` |
| 采集同步 Redis | `module_payload/collectors/redis_sync.py`、`base_collector.py` |
| 会话 | `module_payload/service/payload_session_service.py` |
| 遥测读写 | `module_payload/service/payload_telemetry_service.py` |
| 归档队列消费 | `module_payload/service/payload_telemetry_archive_service.py` |
| 序列运行态 | `module_payload/service/payload_sequence_service.py` |
| 平台 Key 枚举 | `common/enums.py` → `RedisInitKeyConfig` |
| 传输层 Redis | `utils/transport_crypto_util.py` |

---

## 七、与专题文档的关系

| 文档 | 侧重 |
| ---- | ---- |
| 本文 **13** | **全量功能清单**：谁用 Redis、干什么、Key 一览 |
| [02](./02-数据采集层设计.md) | 采集进程模型与 IPC 协议细节 |
| [09](./09-遥测Redis存储与前后端显示流程.md) | 遥测 latest/curve 结构与前后端轮询 |
| [11](./11-遥测永久存储与表结构设计.md) | Redis 热层 ↔ MySQL 冷层分工 |
| [12](./12-数据解析与来源归档重构.md) | `dataSub` / `srcParam` 与键演进 |
