# 09 · 遥测 Redis 存储与前后端显示流程

> 目标：让接手的人 **立刻理解**：一帧遥测到了 Redis 存什么、为什么这样存；前端遥测表/曲线怎么读。
>
> 相关代码：
> - 采集写入：`module_payload/collectors/base_collector.py`
> - 主进程 Redis：`module_payload/redis_store.py` / `redis_keys.py`
> - 服务：`module_payload/service/payload_telemetry_service.py`
> - 接口：`module_payload/controller/payload_telemetry_controller.py`
> - 前端表：`ruoyi-fastapi-frontend/src/views/payload/telemetry/table/index.vue`
> - 前端曲线：`ruoyi-fastapi-frontend/src/views/payload/telemetry/curve/index.vue`

---

## 一、先直接回答关键问题

### 1. 一条遥测到了，会给每个字段都「订阅」吗？会缓存 6000 条吗？

**没有订阅机制。** 帧到达后直接落库。

| 项目 | 现状 |
| ---- | ---- |
| 最新一帧 | **覆盖写**一条 JSON：`payload:{deviceId}:tm:{表类型}` |
| 曲线时间序列 | **本帧里每个可数值化字段**各写 1 个点到各自的 ZSet |
| 是否依赖前端 | **不依赖**。前端加不加曲线都不影响落库 |
| 每字段缓存上限 | **`CURVE_MAX_POINTS = 50000`**（不是 6000） |
| 超限策略 | `ZREMRANGEBYRANK` 丢掉最旧的点，保留最近 5 万点 |

所以若某表有约 135 个可数值字段、持续按 1Hz 注入：

- Redis 上大约会有 **135 个** `payload:{deviceId}:curve:{表}:{字段}` ZSet
- 每个 ZSet 最多约 **5 万** 点（约 13.9 小时 @1Hz）
- **不是**每字段 6000 点

### 2. 曲线显示和 Redis 落库有关系吗？

- 曲线页只要知道 `(deviceId, type, field)`，调 `POST /payload/telemetry/curve/data/batch` 拉 ZSet 点即可
- 「增加/删除曲线」只动 **前端图表列表**，**不删 Redis**
- 「清理数据」只清 **前端本地点数 + `globalClearedAt`**，**不删 Redis**

### 3. 产品原则

> **Redis 要把能落库的遥测量时间序列都存上，与前端用不用无关。**  
> 前端只决定「看哪些、从哪个时间轴窗口看」，不决定「后端记不记」。

---

## 二、总体数据流（一张图看懂）

```text
设备 / 开发注入
      │
      ▼
采集进程 parse  /  主进程 inject_can_yc
      │
      ├─► SET  payload:{device}:tm:{TYPE}          【最新一帧快照】表页用
      ├─► SET  payload:{device}:tm:{TYPE}:ts       【最近时间戳字符串】
      └─► ZADD payload:{device}:curve:{TYPE}:{字段} 【每字段时间序列】曲线用
                member = "{tsMs}|{val}"   score = tsMs
                超 50000 点裁掉最旧

前端遥测表 ──轮询──► GET  /payload/telemetry/table?deviceId&type&dataId&needCfg
前端遥测曲线 ─轮询─► POST /payload/telemetry/curve/data/batch  { items:[…] }
```

主进程与采集进程共享同一套 Redis；注入接口与采集写入路径对齐，保证开发测试页与真采一致。

---

## 三、后端：收到一帧遥测后的 Redis 存储

### 3.1 入口有两条，落库语义相同

| 入口 | 场景 | 关键步骤 |
| ---- | ---- | -------- |
| 采集进程 `BaseCollector._write_telemetry` | 真设备 CAN/等 | 解析 → `SET` 最新帧 → `_append_curve` 全字段 |
| 主进程 `PayloadTelemetryService.inject_can_yc` | 开发测试 HEX 注入 | 校验组帧 → 解析 → `set_telemetry` → `append_curve_points` |

### 3.2 Key 一览

定义见 `module_payload/redis_keys.py`。

| Key | 类型 | 含义 |
| --- | ---- | ---- |
| `payload:{deviceId}:tm:{TYPE}` | String(JSON) | 该表**最新一帧**全字段 |
| `payload:{deviceId}:tm:{TYPE}:ts` | String | 可读时间，如 `2026-07-14 08:00:00.123` |
| `payload:{deviceId}:curve:{TYPE}:{fieldId}` | ZSet | 该字段时间序列 |

`TYPE` 为表类型，如 `FF`、`FC`（配置里 page.key）。

### 3.3 最新一帧 JSON 结构（表页数据源）

```json
{
  "type": "FF",
  "name": "某某包",
  "ts": "2026-07-14 08:00:00.123",
  "dataId": 1783986930585,
  "fields": [
    { "id": "JGB001", "name": "…", "value": 100.0, "show": "100", "hex": "…", "unit": "" }
  ]
}
```

要点：

- **整键覆盖**：新帧到了就覆盖旧帧，表页永远只看到「当前最新」
- `dataId`：毫秒时间戳，前端用它做「未变化则不下发行」优化

### 3.4 曲线 ZSet 结构（曲线页数据源）

对每个可 `float(...)` 的字段：

```text
ZADD payload:{device}:curve:FF:JGB001
  score  = tsMs
  member = "{tsMs}|{val}"     # 例: "1783986930585|100.0"
```

为什么 `member` 要用 `ts|val`：

- Redis ZSet **member 必须唯一**
- 若把 `member` 直接做成数值，数值一重复就把旧点盖掉
- score 仍是时间，读取按 score 排序/按 `sinceT` 截取；一次查询即可拿到 `{t,v}`

裁剪：

```text
ZREMRANGEBYRANK key 0 -(CURVE_MAX_POINTS+1)   # 保留最新 50000
```

不可数值化的字段（转不成 float）会跳过，不进曲线。

### 3.5 容量粗算（方便评估 Redis 内存）

假设单设备单表约 **135** 字段、每字段 **50000** 点、1Hz：

| 量 | 估算 |
| -- | ---- |
| ZSet 个数 | ≈ 135 / 表 / 设备（有数据的表） |
| 每字段时长 | ≈ 50000 秒 ≈ **13.9 小时** |
| 写入成本 | 每帧一次 pipeline：N 次 `ZADD` + N 次 `ZREMRANGEBYRANK` |

「所有数据都保存」在工程上 = **环形缓冲最近 N 点**，不是无限磁盘归档。若要更长历史，需要另做落盘/冷存。

### 3.6 读曲线 API（服务如何取点）

`get_curve_points(redis, device, type, field, limit, since_t)`：

- `since_t` 为空：`ZRANGE` 取最近 `limit` 个
- `since_t` 有值：`ZRANGEBYSCORE (since_t +inf`（**开区间**，不含 since_t 本身）取增量

批量接口把多项串起来返回，减少前端 N 次 HTTP。

---

## 四、前端：遥测表显示流程

页面：`views/payload/telemetry/table/index.vue`

### 4.1 启动

1. 解析表类型：路由 `tmFF` / query `type` → 如 `FF`
2. 选 `deviceId`（localStorage `payload:activeDeviceId`）
3. 首次 `GET /payload/telemetry/table?needCfg=1`：一次拿 **配置 + 当前值**，避免骨架闪屏
4. 之后约每秒轮询：带上上次的 `dataId`

### 4.2 轮询契约

请求：

```http
GET /payload/telemetry/table?deviceId=can:0:0:0&type=FF&dataId=1783986930585
```

后端：

- `dataId` 与 Redis 最新相同 → `{ changed: false }`，**不带 rows**（前端保持旧表）
- 不同 → `{ changed: true, rows, ts, dataId, connected, … }`

前端：

- `changed=false`：只刷本地「刷新时间」
- `changed=true`：更新表格；值变化的格子短暂高亮
- 无数据时仍可用 `cfg` 画出编号/名称/单位空值行

### 4.3 点数值跳曲线

点击当前值 → `router.push({ path: '/telemetry/curve', query: { type, field, from: 'table' } })`  
曲线页检测到 `from=table` 会自动「增加」对应曲线。

遥测表 **自己不读曲线 ZSet**，只读最新帧 JSON。

---

## 五、前端：曲线显示流程

页面：`views/payload/telemetry/curve/index.vue`

### 5.1 和 Redis 的分工

| 层次 | 职责 |
| ---- | ---- |
| Redis | 全字段历史点（上限 5 万/字段） |
| 前端 curves[] | 用户当前要画的 ≤10 条 |
| `globalClearedAt` | 「清理数据」后的显示基准时间；**不改 Redis** |
| 轮询 | 仅当前曲线页激活时跑；切到其他 Tab `onDeactivated` 停轮询 |

### 5.2 增加 / 删除曲线

- **增加**：组 stub → `batch` 拉点（`initial: true`）→ 推进图例与 ECharts
  - 有过「清理」：`sinceT = globalClearedAt`，limit 可用到 50000
  - 没清理：不传 `sinceT`，取 Redis 最近全量（上限 limit）
- **删除**：只从 `curves` 移除；**不删 Redis**

颜色槽：最多 10 色；超限提示。

### 5.3 增量轮询

每秒对图上曲线 `batch`：

- 已有末点：`sinceT = 末点时间`（开区间，只要更新点）
- 无点但清过数据：`sinceT = globalClearedAt`
- limit 增量一般 500

### 5.4 「清理数据」vs「重置」

| 按钮 | 作用 |
| ---- | ---- |
| 清理数据 | 清空本地 points；记下 `globalClearedAt=now`；之后拉数只取清理时刻之后；**Redis 不动** |
| 重置 | 时间轴回到「跟最新」的视窗策略（situation 1），不清点 |

这就是为什么开发者工具里清理没有「清 Redis」的请求——**故意如此**。

### 5.5 keep-alive 行为

若依多标签会缓存页面：

- 切走曲线页：停 `setInterval`，避免在遥测表 Tab 仍打 `curve/data/batch`
- 切回：按末点时间补一批再开轮询

---

## 六、接口速查（遥测相关）

| 方法 | 路径 | 用途 |
| ---- | ---- | ---- |
| GET | `/payload/telemetry/table` | 最新表数据；`dataId` 增量；`needCfg` 带配置 |
| GET | `/payload/telemetry/fields` | 曲线页遥测量下拉 |
| POST | `/payload/telemetry/curve/data/batch` | 批量曲线点 |
| GET | `/payload/telemetry/curve/data` | 单字段曲线点 |
| POST | `/payload/telemetry/dev/can-yc` | 开发注入整帧 |

权限：`payload:telemetry:view` / `payload:telemetry:curve` / `payload:devtest:view`。

---

## 七、设计取舍（给后来者）

| 决策 | 原因 |
| ---- | ---- |
| 最新帧与曲线分离 | 表要「一眼当前」；曲线要「一段时间趋势」 |
| 全字段落曲线 | 存库与前端使用解耦；随时加曲线都能看到历史 |
| ZSet + score=时间 | 按时间范围增量拉取简单 |
| member=`ts\|val` | 避免同值覆盖；单次 ZRANGE 即得全量点 |
| 环形 5 万点 | 内存可控；不是无限归档 |
| 清理只清前端 | 联调可随时「从现在重新看」，不破坏底库 |
| 无订阅接口 | 开发阶段不需要按需订阅；减少前后端耦合 |

若后续内存压力大，可考虑：按表/字段白名单落库、降低 `CURVE_MAX_POINTS`、或冷热分离——那是下一阶段，不改变「与前端解耦」原则。

---

## 八、相关文件索引

```text
ruoyi-fastapi-backend/module_payload/
  collectors/base_collector.py     # _write_telemetry / _append_curve
  redis_store.py                   # set_telemetry / append_curve_points / get_curve_points
  redis_keys.py                    # Key 命名
  service/payload_telemetry_service.py
  controller/payload_telemetry_controller.py

ruoyi-fastapi-frontend/src/
  api/payload/telemetry.js
  views/payload/telemetry/table/index.vue
  views/payload/telemetry/curve/index.vue
```
