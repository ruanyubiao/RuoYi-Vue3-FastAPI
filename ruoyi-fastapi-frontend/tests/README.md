# 前端单元测试（Vitest）

地检平台前端 `ruoyi-fastapi-frontend` 的纯 JavaScript 单元测试目录。  
目标：后续约 **80% 业务逻辑** 写成不依赖 Vue 组件/DOM 的纯函数，在此用 Vitest 覆盖。

## 工具链

| 工具 | 用途 |
|------|------|
| [Vitest](https://vitest.dev/) | 测试运行器（与 Vite 同生态，ESM 友好） |
| [happy-dom](https://github.com/capricorn86/happy-dom) | 轻量 DOM / `localStorage` / `sessionStorage` 环境 |
| Node.js | 建议 **18+**（与 Vite 6 一致） |

**不引入** Vue Test Utils / Playwright：组件 E2E 仍由 `ruoyi-fastapi-test`（Playwright）负责。

## 目录约定

```
tests/
├── setup.js              # 全局：每个用例前清空 Storage
├── plugins/              # 对 src/plugins 的测试
│   ├── cache.test.js
│   ├── cache.expire.test.js
│   ├── cache.normalize.test.js
│   └── cache.session.request.test.js
└── utils/                # 对 src/utils 的测试（与源码路径对应）
    ├── localPrefs.test.js   # 已改为 cache.local 行为对照（原 localPrefs 已删除）
    └── ...
```

- 测试文件命名：`*.test.js`
- 被测代码通过别名 `@/` 引用，与业务代码一致（见 `vitest.config.js`）
- **优先测**：纯函数、数据转换、缓存读写、校验逻辑
- **暂不测**：`.vue` 组件、`ElMessage` 等 UI 副作用（可只测抽出的纯函数部分）

## 存储规范（业务代码必须遵守）

统一入口：`import cache from '@/plugins/cache'`（Options API 可用 `this.$cache`）。

| 层级 | 用途 | TTL |
|------|------|-----|
| Pinia | 运行时状态（刷新丢失） | 否 |
| `cache.session` | 防重复提交、传输加密、会话信号 | 否 |
| `cache.local` | 页面偏好、连接参数、布局设置 | 否 |
| `cache.expire` | 需自动过期的本地数据，`set(key, val, expSeconds)` | **秒** |

- **禁止**业务代码直写 `localStorage` / `sessionStorage`（仅 `plugins/cache.js` 内部可直写）。
- **禁止**再引入 `localPrefs.js` 或 npm `web-storage-cache`。
- **禁止**为纯 TTL KV 再建 `*Cache.js`。领域薄层（遥测 cfg、相机图、设备快照）只保留业务语义，TTL 交给 `cache.expire`。
- 键名：`payload:<域>:<用途>:v1`。
- JSON 默认值：整对象用 `getJSON(key, defaultValue)`；字段级用 `fillDefaults` / `normalizeRecord`。

改存储实现前先补/跑 `npm run test:run`。

## 安装依赖

在 `ruoyi-fastapi-frontend` 目录下：

```bash
npm install
```

开发依赖已包含 `vitest`、`happy-dom`（见 `package.json`）。

## 运行测试

```bash
# 监听模式（开发时）
npm test

# 单次运行（CI / 提交前）
npm run test:run

# 覆盖率（可选）
npm run test:coverage
```

## 编写新用例

1. 在 `tests/utils/`（或 `tests/plugins/`）新增 `xxx.test.js`
2. 从 `@/utils/xxx` 或 `@/plugins/xxx` 导入被测函数
3. 若模块依赖 API，在测试文件顶部 `vi.mock('@/api/...')`（参考 `deviceConnectDefaults.test.js`）
4. 涉及 `localStorage` / `sessionStorage` 时无需手动 mock，`setup.js` 会在每个用例前 `clear()`

示例：

```javascript
import { describe, expect, it } from 'vitest'
import { normalizeHexDisplay } from '@/utils/payloadRawData'

describe('normalizeHexDisplay', () => {
  it('奇数段补 0', () => {
    expect(normalizeHexDisplay('aab')).toBe('AA 0B')
  })
})
```

## 与 E2E 的关系

| 层级 | 目录 | 范围 |
|------|------|------|
| 单元测试 | `ruoyi-fastapi-frontend/tests` | 纯 JS、快、无真实后端 |
| E2E | `ruoyi-fastapi-test` | 登录、页面冒烟、接口联调 |

修改存储、HEX 解析、遥测缓存等逻辑时，**先跑** `npm run test:run`，再按需跑 E2E。

## 当前已覆盖模块

- `plugins/cache` — local / session / expire / fillDefaults / normalizeRecord
- `utils/localPrefs` 行为 — 已并入 `cache.local`（见 `localPrefs.test.js`）
- `utils/payloadRawData` — HEX / 转义 / IO 日志格式化
- `utils/telecontrolOrderMatch` — 指令搜索
- `utils/recvFileTime` — 回放文件时间戳
- `utils/deviceConnectDefaults` — 连接预设纯函数
- `utils/telemetryCfgCache` / `cameraDeviceImageCache` / `deviceSnapshotCache` / `telemetryPages`
- `utils/csvExport` / `telemetryOptionLabel` / `payloadSend` / `validate`

后续新增业务逻辑时，请同步在 `tests/` 下补充对应用例。
