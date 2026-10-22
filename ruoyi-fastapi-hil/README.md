# ruoyi-fastapi-hil —— 正式包硬件在环（HIL）验收

**后续 agent / 编写与运行**：见同目录 [AGENT.md](./AGENT.md)（闭环规则、goldens、run_hil、真机清单）。


## 与 ruoyi-fastapi-test 的区别
| | ruoyi-fastapi-test | ruoyi-fastapi-hil |
|---|---|---|
| 目的 | 开发自测冒烟 | 正式发布包部署到工控机后的验收 |
| 目标环境 | 本机 localhost:18080 测试栈 | 工控机 http://192.168.100.52:12580（`/prod-api`） |
| 浏览器 | 无头 | **有头**（slow_mo，可观看） |
| 硬件 | 不打开串口/CAN | 测试机扮演载荷/单板：USB CAN、USB 串口/RS422、UDP；收到指令按协议回包，周期推遥测 |

以仓库源码为准：页面路由取自 `ruoyi-fastapi-backend/sql`（sys_menu）+ 前端 `src/views`，
设备参数取自 `assets/config/cfg_device_connect.json`，遥测/遥控期望值取自 `assets/data/tm_golden_cases.json`、
`tests/data/telecontrol_wire_goldens.json`，CAN 拼帧/组帧直接用 gpcan 的 `ProtocolParser` / `ProtocolBuilder`。

## 目录
```
conftest.py                 fixture：有头浏览器(会话级登录一次)、工控机接口、失败截图、按被测目标自动 skip、--hil-plan
hil.local.json              硬件接线默认值（CAN vendor/通道、COM9/COM8、UDP 端口），环境变量优先
hil/config.py               HILConfig（hil.local.json + HIL_* 环境变量）、运行目录、测试机 IP 探测
hil/round.py                交互轮测（run_hil.bat round can|serial）
hil/samples.py              样本加载 get_hex / tm_fields / iter_can_frames
hil/ipc_api.py              工控机后端接口：登录、getRouters、/payload/device/{can,serial,net}/open|close、遥测表
hil/protocol/can_device.py  BIU / XL / YJ216 载荷模型（gpcan）：遥测请求→黄金遥测，遥控只记录/计数
hil/protocol/serial_device.py 相机 v1.6/v1.7、热控电机、CPA-ZK、CPA指向、YJ216 RS422 模型
hil/protocol/frames.py      EB90 / 55AA / RS422 / 工程遥测帧的校验与拆帧
hil/hw/                     CanSim / SerialSim / UdpSim（真实 IO 或 dry-run）+ SimManager
hil/browser/session.py      有头 Playwright 会话、JS 异常收集、截图
hil/browser/pages.py        全部业务页清单(31) + 页面动作（控制页发 Hex、发遥测请求、单板发指令、读遥测表）
hil/repro_scripts/           专项复现/诊断脚本（非正式 pytest；见该目录 README；例：python -m hil.repro_scripts.ghost_busy_repro）
scenarios/test_unit_selfcheck.py  unit：样本/配置/菜单覆盖/协议应答自测（本机即可跑）
scenarios/test_ui_pages.py  ui_only：逐页有头冒烟 + 关键按钮
scenarios/test_hil_can.py   hil_can：BIU / XL / YJ216
scenarios/test_hil_serial.py hil_serial：相机 v1.6/v1.7、RKDJ、ZK、CPAZX、YJ216 RS422
scenarios/test_hil_udp.py   hil_udp：地检板 UDP 工程遥测
scenarios/reply_map.json    应答说明（内置）+ 待用户补充的自定义应答
TODO.md                     未做 / 待确认项
artifacts/<YYYYMMDD_HHMMSS>/  每次任务一个目录：junit、截图、日志、summary（artifacts/legacy_20261016 为旧截图）
```

## 角色与接线
- **工控机（被测）**：部署发布版本的机器 192.168.100.52，PCIe ZLG CANFD 2 通道 CAN 卡（gpcan vendor 3）+ Exar PCIe 串口卡（COM8，RS422/485）。后端挂多台采集机时，本测试用的采集机为 gk3（见下「多采集机」）。
- **测试机（本机）**：运行本目录脚本的电脑（RYB-L16），USB-CAN Alyst Pro 2 通道（gpcan vendor 2）+ FTDI USB 转 RS422/485 线（COM9），扮演载荷/单板设备。

全部是**实体硬件直连**，不使用虚拟串口/虚拟 CAN（不需要 com0com 之类）。默认值写在 `hil.local.json`，可被环境变量覆盖。

| 链路 | 测试机（本机） | 工控机（被测） | 说明 |
|---|---|---|---|
| CAN-A | Alyst Pro vendor 2 / dev 0 / **ch0** | ZLG vendor 3 / dev 0 / **ch0** | 各设备 `<fam>_can_a`，500 kbps |
| CAN-B | Alyst Pro vendor 2 / dev 0 / **ch1** | ZLG vendor 3 / dev 0 / **ch1** | 各设备 `<fam>_can_b`，500 kbps |
| 串口 | **COM9**（FTDI USB 转 RS422/485） | **COM8**（Exar PCIe 串口卡） | RS422/485，**一对 COM 公用**；6 协议共用，测完全关再测下一个｜
| UDP | 网口，自动探测与 192.168.100.52 同网段的 IP，端口 **99** | 网口，绑 0.0.0.0:**66** | 地检板 xl_udp_dj |

- **CAN**：BIU / XL / YJ216 **公用同一根 CAN 线、仅 A/B 两通道**（不是换设备换线；协议软件切换）。CAN_H/CAN_L/GND 对接，总线两端各 120Ω。
  测完一个协议族须 **全关硬件** 再测下一个（`round --auto` / `all` 靶间 `ensure_hardware_idle`）。
  A、B 两路都收发：测试时分别在「当前发送」选 CAN-A、CAN-B 发遥控/遥测请求，断言只在对应通道的模拟器收到并由它回遥测。
- **串口**：**一对 COM9↔COM8 公用**（不是换设备换线）；6 个协议键共用此线，测完一个须全关再测下一个。每端波特等参数取 `cfg_device_connect.json` 该设备键：

  | 设备键 | 页面 | 参数 |
  |---|---|---|
  | xl-camera / xl-camera-v17 | 相机控制 v1.6 / v1.7 | 2000000 8O1（FT232R 上限 3 Mbaud；两端 2 Mbaud 待实测） |
  | xl-rkdj / xl-zk | 热控电机板 / CPA-ZK 板 | 115200 8N1 |
  | xl-cpazx | CPA 指向 | 921600 8N1 |
  | yj216-rs422 | YJ216 RS422 | 115200 8E1 |

  RS422 接法：TX+/TX- 接对端 RX+/RX-，RX 同理，GND 共地。
- **UDP**：工控机（被测）绑 66 收地检板遥测，对端 = 测试机 IP:99。测试机 IP 自动探测（`HIL_TEST_PC_IP` 覆盖），写进 summary.txt。
  测试机需放行入站 UDP 99（管理员 PowerShell 执行一次）：
  ```powershell
  New-NetFirewallRule -DisplayName "HIL UDP 99 In" -Direction Inbound -Protocol UDP -LocalPort 99 -Action Allow -Profile Any
  ```


## 闭环对比（黄金收发）
对齐「预先准备发送/期望接收 → **界面逐条点指令** → 本机模拟器实时收 → 与预存期望对比」。

| 规则 | 说明 |
|---|---|
| **发遥控必须 UI** | Playwright 点击指令卡「发送指令」（CAN 走 `/＜fam＞/telecontrol/command` 的 `send_command_order`；串口/UDP 单板页 `send_order`）。**禁止**测试代码调用发送遥控 API；Hex 透传框仅调试，不作为闭环路径。 |
| 开/关设备 | CAN 工具栏 UI 开闭；串口/UDP 可暂用 `/payload/device/*/open|close`（非发指令）。 |
| 数据 | `scenarios/goldens/<protocol>.json`（由 `python -m hil.goldens` 从 TeleControlCfg + `telecontrol_wire_goldens` 生成）。每条含 `order_id` / `tx_expect_hex` / 可选 `tm_*` / `status`。 |
| 缺黄金 | `status=missing_tx_golden` → 收集期 skip，原因写「缺黄金：…」；`reply_map.custom_rules` 未确认的应答不瞎编，继续 pending skip。 |
| 失败信息 | 线帧用 expect/actual hex；遥测用字段 id→(期望,实际)。 |
| 公用线 | CAN A/B、串口 COM 公用；`round --auto` 靶间 `ensure_hardware_idle`。 |

重新生成黄金清单（不碰硬件）：
```bat
python -m hil.goldens
python -m pytest -m "hil_can or hil_serial or hil_udp" --hil-plan -q
```

## 多采集机（host）
工控机后端可以挂多台采集机，每台有自己的 CAN 卡/串口/网口。机制（以源码为准）：
- 后端 `middlewares/context_middleware.py` 按请求头 **`X-Collector-Host`** 绑定当前采集机（`module_payload/collector_host.py`）；
  open/close/sessions/can/vendors/serial 等接口都只作用于这台。不带头时用后端配置的默认值（100.52 上是 `local`，且 local 离线，
  所以裸调 `/payload/device/can/vendors` 会得到空列表——不是没有厂商）。
- `GET /payload/device/snapshot?hosts=...`（需含 commit `2f13aeb`）：`data.devices[]` 列出每台采集机：`host`、`online`、
  `canVendors`、`defaultCanVendor`、`serialPorts`、`localAddrs`、`registry`（已打开进程表），以及内嵌的 `can` /
  `serialOpened` / `netOpened` / `sessions`。`parts` 参数已忽略。HIL **只认** `devices[]`（不再读旧包 `collectors[]`）。
  `hosts` 参数不看请求头；点名时可含离线机。
- 前端：`utils/collectorHost.js` 把选中的采集机存 localStorage `payload:collectorHost`（首页「选择采集设备」可改），
  `utils/request.js` 给所有请求加 `X-Collector-Host`；未选或选的不在列表时 `pickCollectorHost` 取 `devices[0]`。
- 本测试：登录后按 `HIL_IPC_HOST` → `hil.local.json` 的 `ipc.collector_host` → 自动（第一个 online，当前为 **gk3**）选定采集机，
  接口请求都带 `X-Collector-Host`，浏览器写同一个 localStorage；厂商/串口/地址/已开设备都从 snapshot 里这台采集机读；summary 记录选中的采集机。
- **占用预检**：硬件场景开跑前读 registry，目标 CAN 通道 / 串口 / UDP 端口已被打开（非本次测试打开）时直接失败并列出占用项，
  不会替你关闭；`HIL_ALLOW_BUSY=1` 时 CAN 复用已开通道，结束时也不关闭它们。测试只关闭本次自己打开的设备。

## 运行
```bat
pip install -r requirements.txt
pip install -e E:\plat\pygpcan
python -m playwright install chromium

run_hil.bat unit                 :: 本机自测，不连工控机、不开硬件
run_hil.bat ui                   :: 有头逐页冒烟（只读）

:: CAN：接好哪个设备就跑哪个（A/B 两路一起测）
run_hil.bat can biu
run_hil.bat can xl
run_hil.bat can yj216

:: 串口：COM9-COM8 接好哪个设备就跑哪个
run_hil.bat serial xl-camera
run_hil.bat serial xl-camera-v17
run_hil.bat serial xl-rkdj
run_hil.bat serial xl-zk
run_hil.bat serial xl-cpazx
run_hil.bat serial yj216-rs422

run_hil.bat udp                  :: 地检板 UDP（自动设置 HIL_UDP_ENABLE=1）

:: 交互轮测：逐个提示「请接入 XXX 后按回车」（s=跳过该设备，q=结束），全部结果进同一个时间戳目录
run_hil.bat round can                    :: biu → xl → yj216
run_hil.bat round serial                 :: 6 个串口设备依次
run_hil.bat round serial xl-rkdj xl-zk   :: 只轮指定设备

run_hil.bat plan                 :: 只打印 CAN/串口/UDP 每个目标下会 RUN/SKIP 的用例（写入 plan.txt），不碰硬件
run_hil.bat                      :: = all：unit+ui+CAN×3+串口×6+UDP（探测到硬件才跑；同时间戳目录）
run_hil.bat ui -k index          :: 其余参数透传给 pytest
```
- **硬件默认要测且测全协议**：`all` / `can` / `serial`（无参）/ `udp` 先**探测本机**（CAN：PnP VID_04D8 / 安全 open；串口：COM9；UDP：绑 99）。探测到则启用全量；探测不到 skip「本机未检测到 …」。
- **全量覆盖（非交互）**：`run_hil.bat all` = unit → ui → `hil.round can --auto`（biu→xl→yj216）→ `hil.round serial --auto`（6 个串口键）→ udp。每个目标单独分组、共用同一 `HIL_RUN_DIR`；summary 写明「请接入 xxx」（未换线失败属预期）。交互换线仍用 `run_hil.bat round can|serial`。
- **单目标**：`run_hil.bat can biu` / `serial xl-rkdj` / `HIL_CAN_TARGET` / `HIL_SERIAL_TARGET`。`hil.local.json` 的 `can.default_targets` / `serial.default_targets` 为空列表 = 全部；可收窄。UDP 仅 `xl_udp_dj`（其他 net 协议见 TODO）。
- **版本核对**：连工控机的分组登录后比对本地 **backend** `ruoyi-fastapi-backend/version.py`、**frontend** `ruoyi-fastapi-frontend/version.js`（均按文本解析 `appVersion`，不 import/exec）与被测 `GET /payload/device/version`；三者不一致则失败，summary 写明三边版本。
- **共用线 + 靶间清场**：CAN A/B 公用一根；串口 COM9↔COM8 公用一对。`--auto` / `all` 串行每个 target **之间**强制 `close-all`，并确认 `sessions` 与 registry alive 为空后再开下一个（`hil.round._ensure_idle_between` / `IpcApi.ensure_hardware_idle`）。失败应报协议收发/黄金样例对比，不报「未换线」。
- **close-all**：硬件用例（can/serial/udp）在 session 开始与每个用例开始前调用 `POST /payload/device/close-all`（带 `X-Collector-Host`），会清掉该采集机上已有连接（含用户手动打开的）；测完仍关闭本次打开的连接。
- 选了 `can biu` 时 XL、YJ216 的用例 skip，原因「本次被测 CAN 设备为 biu」；串口同理。
- 分组名带目标：`junit_can_biu.xml`、`junit_serial_xl-camera.xml`，summary.txt 每段末尾记录硬件配置和测试机 IP。
- 直接 pytest：`set HIL_CAN_TARGET=biu` 后 `python -m pytest -m hil_can`；`--hil-plan` 只看计划不执行。
工控机不可达时 ui/hil 用例 skip 并写明原因。

## 输出目录（每次任务一个）
一次 `run_hil.bat` 调用 = 一次任务，时间戳在任务开始时生成一次，所有输出都进 `artifacts\<YYYYMMDD_HHMMSS>\`，
`run_hil.bat all` 依次跑 unit / ui / can / serial / udp 五个分组，也都进同一个目录；结束时打印目录路径和 summary。
```
artifacts\20261022_080552\
  summary.txt          每个分组一段：开始/结束时间、通过/失败/错误/跳过数、退出码
  junit_unit.xml       每个分组一个 junit
  junit_ui.xml
  pytest_unit.log      pytest 日志（INFO）
  pytest_ui.log
  sim_io.log           模拟器收发日志（CAN/串口/UDP 的 RX/TX）
  report_ui.html       装了 pytest-html 时才有
  080610_FAIL_test_page_opens__index_.png   失败截图（HHMMSS_用例名）
```
- 直接 `python -m pytest ...`（不经 bat）也会自动新建 `artifacts\<时间戳>\`，并自动补 `--junitxml` / `--log-file`（文件名按 `-m` 分组：unit/ui/can/serial/udp，否则 pytest）。
- 设置 `HIL_RUN_DIR` 可指定输出目录（相对路径按本目录解析），bat 和直接 pytest 都会沿用；想把几次调用并到一个目录时用它。
- 代码里统一用 `hil.config.run_dir()`（`CONFIG.artifacts_dir` 等价）取目录，不要再写死 `artifacts\`。

## 环境变量
硬件默认值在 `hil.local.json`；下表变量优先于它（`HIL_LOCAL_CFG` 可指向另一份 json）。

| 变量 | 默认 | 说明 |
|---|---|---|
| HIL_FRONTEND_URL | http://192.168.100.52:12580 | 正式 UI |
| HIL_API_PREFIX | /prod-api | 后端前缀（.env.production） |
| HIL_USERNAME / HIL_PASSWORD | admin / admin123 | 登录 |
| HIL_HEADED / HIL_SLOW_MO_MS | 1 / 200 | 有头 / 操作放慢 |
| HIL_TM_WAIT_S | 15 | 遥测字段等待秒数 |
| HIL_TM_PERIOD | 1.0 | 串口/UDP 主动遥测周期 |
| HIL_RUN_DIR | 自动 artifacts\<时间戳> | 本次任务输出目录 |
| HIL_CAN_TARGET | 空=全量（all/can 无参 --auto） | 单目标 biu/xl/yj216；空且无卡 → skip |
| HIL_CAN_VENDOR / HIL_CAN_DEV_INDEX | 2 / 0 | 测试机（本机）CAN 卡 |
| HIL_CAN_A_INDEX / HIL_CAN_B_INDEX | 0 / 1 | 测试机 CAN-A / CAN-B 通道 |
| HIL_IPC_CAN_VENDOR / HIL_IPC_CAN_DEV_INDEX | 3 / 0 | 工控机（被测）CAN 卡（页面对话框里选） |
| HIL_IPC_CAN_A_INDEX / HIL_IPC_CAN_B_INDEX | 0 / 1 | 工控机 CAN-A / CAN-B 通道 |
| HIL_SERIAL_TARGET | 空=全量（all/serial 无参 --auto） | 单目标设备键；空且无 COM → skip |
| HIL_SERIAL_PORT / HIL_IPC_SERIAL_PORT | COM9 / COM8 | 测试机 / 工控机串口（所有串口设备共用） |
| HIL_SERIAL_<KEY> / HIL_IPC_SERIAL_<KEY> | - | 个别设备换口时用，KEY=XL_CAMERA 等 |
| HIL_UDP_ENABLE | 空=能绑端口则开 | 1=强制开；0=强制关；空=本机探测 |
| HIL_TEST_PC_IP | 自动探测 | 测试机 IP（工控机 UDP 发往此地址） |
| HIL_IPC_HOST | 自动（第一个 online，当前 gk3） | 采集机标识（X-Collector-Host） |
| HIL_IPC_IP | HIL_FRONTEND_URL 的主机名 | 工控机 IP（UDP 对端、IP 探测） |
| HIL_ALLOW_BUSY | 0 | 1=目标 CAN 通道已被占用时复用（结束不关闭） |
| HIL_UDP_IPC_PORT / HIL_UDP_TEST_PC_PORT | 66 / 99 | UDP 端口 |
| HIL_UDP_BIND / HIL_UDP_PEER | 0.0.0.0:99 / 192.168.100.52:66 | 整体覆盖测试机绑定 / 工控机地址 |

## 每个硬件场景做什么
- **CAN（BIU/XL/YJ216，一次一个）**：测试机启动 A(ch0)/B(ch1) 两路模拟器 → 遥控页**通过 UI** 点「新建CAN连接-A/B」，
  选厂商 3、设备 0、通道 0/1 打开（source=`<fam>_can_a/_b`），并经 /sessions 核对 deviceId = `can:3:0:0` / `can:3:0:1` →
  对 A、B 各做一遍：「当前发送」选该路 → 填 `0A 91 00 01 00 01 55 55` 点「发送遥控指令」，断言只有该路模拟器收到 →
  「发送遥测请求」→ 该路模拟器按协议回黄金遥测 → 实时数据页字段 = tm_golden_cases → 「定时遥测」开 3 秒再关，请求数 ≥2 →
  UI 关闭 CAN-A/B（失败时经接口兜底关闭）。
- **串口（一次一个设备）**：模拟器在 COM9 启动并周期推遥测 → 接口在工控机打开 COM8（参数同 cfg）→ 单板页过滤指令点「发送指令」→
  断言模拟器收到期望帧（相机 CAM_A0 / RKDJ D1503 对黄金样例，CPAZX/RS422 按协议现算；相机忽略帧序号）→ 遥测字段 = 黄金样本
  （RS422 为一问一答，数据区全 0，只断言表格在刷新）。
- **UDP**：模拟器绑 0.0.0.0:99 推 844B 工程遥测到工控机:66 → 接口打开工控机 UDP（remoteHost=测试机 IP）→ 地检板页表格刷新。
  页面「新建UDP连接」按 cfg 锁定 127.0.0.1，无法填测试机 IP，所以这里走接口（见 TODO.md）。
- **暂不测（skip 并写明原因）**：XL 实时遥控应答、热控/ZK D15xx 指令应答、CPA 指向遥控应答，见 TODO.md。

## 自定义应答
协议代码能确定的应答已内置（见 `scenarios/reply_map.json` → builtin_responders）。
协议代码没有定义的（XL 实时遥控应答、单板/CPA 指令应答）在 `custom_rules` 中列为待确认：补 `reply_hex` 并把 `enabled` 改为 true 即生效。
