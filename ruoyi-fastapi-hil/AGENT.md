# AGENT.md — ruoyi-fastapi-hil 编写与运行指南



> 面向后续 agent / 开发者。以**当前仓库真实代码**为准（闭环黄金改造后）。  

> 改规则、补用例、跑 plan/unit/真机前先读本文，再读 `README.md` / `TODO.md`。



---



## 1. 项目定位与目录



**定位**：正式环境**硬件在环（HIL）**。测试机（本机，如 RYB-L16）跑本目录脚本；工控机（被测）默认 `http://192.168.100.52:12580`（`/prod-api`），采集机常为 `gk3`。



| 角色 | 机器 | 硬件 |

|------|------|------|

| 工控机（被测） | 192.168.100.52 | PCIe ZLG CANFD vendor **3** ch0/ch1；Exar 串口 **COM8**；UDP `:66` |

| 测试机（模拟器） | 跑 `run_hil.bat` 的 PC | USB Alyst Pro vendor **2** ch0/ch1；FTDI **COM9**；UDP `:99` |



**本仓库只改 `ruoyi-fastapi-hil`（简称 hil）**。不改业务前后端；不在此目录 `git commit`（除非用户明确要求）。



```

ruoyi-fastapi-hil/

  AGENT.md                 ← 本文

  README.md / TODO.md

  run_hil.bat              ← 入口（GBK 编码，勿改成 UTF-8 乱码）

  conftest.py              ← fixture、版本核对、硬件 skip、--hil-plan、close-all

  hil.local.json           ← 本机硬件默认（可被 HIL_* 覆盖）

  hil/

    config.py              ← HILConfig + artifacts 目录

    goldens.py             ← 闭环黄金加载/生成（python -m hil.goldens）

    round.py               ← 多协议串行轮测 + 靶间 ensure_hardware_idle

    ipc_api.py             ← 登录 / snapshot / open|close / close-all / ensure_hardware_idle

    samples.py             ← tc/tm golden 读取

    browser/pages.py       ← Playwright：send_order / send_command_order / can_ui_*（发遥控只点 UI）

    hw/                    ← CanSim / SerialSim / UdpSim

    protocol/              ← 本机模拟器协议模型

    repro_scripts/         ← 专项复现/诊断（非正式 pytest；见该目录 README）

  scenarios/

    goldens/*.json         ← 逐条用例清单（生成物，可再生成）

    reply_map.json         ← 应答规则说明；custom_rules 未确认勿瞎编

    hil_steps.py           ← 线帧/字段断言

    test_hil_can.py        ← marker hil_can，按 GoldenCase 逐条

    test_hil_serial.py     ← marker hil_serial

    test_hil_udp.py        ← marker hil_udp

    test_ui_pages.py / test_unit_selfcheck.py

  artifacts/<时间戳>/      ← junit、截图、summary.txt、sim_io.log、plan.txt

```



业务侧只读依赖（**不要在 hil 任务里改**）：

- `../ruoyi-fastapi-backend/assets/config/*-TeleControlCfg.json`

- `../ruoyi-fastapi-backend/tests/data/telecontrol_wire_goldens.json`

- `../ruoyi-fastapi-backend/assets/data/tm_golden_cases.json`

- `../ruoyi-fastapi-backend/assets/config/cfg_device_connect.json`



---





### 1.1 专项复现脚本（`hil/repro_scripts/`）



非正式回归入口。同类一次性/排查脚本放此目录（约定见 `hil/repro_scripts/README.md`）。



当前：`ghost_busy_repro.py` — 量化 XL CAN **网页关后** `busy_can` 仍短暂 `assembler=can_xl` 的幽灵窗口（长指令 + UI 关 CAN + `ensure_hardware_idle` 兜底）。



```bat

set PYTHONPATH=%CD%

python -m hil.repro_scripts.ghost_busy_repro --rounds 40 --order D1651

```



产物：`artifacts/can_xl_ghost_busy_<时间戳>/`。不纳入 `run_hil.bat all`。



---

## 2. 硬性规则（必须遵守）



1. **只改 hil**  

   不改 `ruoyi-fastapi-backend` / `ruoyi-fastapi-frontend`；不擅自 git 提交。



2. **发遥控 = 界面点击**  

   - CAN：`send_command_order(page, order_id)` → `/＜fam＞/telecontrol/command` 点「发送指令」。  

   - 串口 / UDP 单板：`send_order(page, order_id)` → 板页指令卡点「发送指令」。  

   - **禁止**在测试里调用发送遥控 HTTP API（如 `sendTelecontrol` / `sendBoardTelecontrol`）。  

   - 控制页 Hex 透传（`control_send_hex`）**不是**闭环路径，仅调试。  

   - **关硬件优先网页**：CAN `can_ui_close`；串口 `serial_ui_close`（关闭串口/关闭控制·图像串口）；UDP `udp_ui_close`（关闭 UDP）。开串口/UDP 仍可用 `IpcApi.open_*`（打开对话框未一律封装）。API `close_*` / `close_all` **仅**作 `ensure_hardware_idle` 清场兜底。



3. **公用线，不是换设备换线**  

   - CAN：BIU / XL / YJ216 **共用一根线，仅 A/B 两通道**。  

   - 串口：一对 **COM9↔COM8** 公用。  

   - 顺序：测完一个协议 → **全关硬件** → 再测下一个。



4. **每协议测完必须清场**  

   - `hil.round --auto` / `all`：靶间调用 `IpcApi.ensure_hardware_idle`（close-all + 确认 `sessions=[]` 且 registry 无 alive）。  

   - 用例 finally：先网页关设备，再 `ensure_hardware_idle`（内含 close-all）兜底。失败若因占用，先清场再归因协议。



5. **版本三边核对**  

   - 本地 backend `version.py` + 前端 `version.js` + 工控机 `GET /payload/device/version` 须一致（`appVersion`）。不一致属**环境级失败**，应停，不要硬跑硬件。



6. **缺黄金 → skip；不瞎编应答**  

   - `scenarios/goldens/*.json` 里 `status=missing_tx_golden` 收集期 skip。  

   - `reply_map.json` 的 `custom_rules` 未确认协议前保持 `enabled: false`，用例 skip + TODO，**不要编 reply_hex**。



7. **真机须用户明确批准**  

   - 未批准：只跑 `unit` / `--hil-plan` / 文档与代码修改。  

   - 批准范围写清：机器、DUT、是否 `all` / 单靶。



---



## 3. 如何编写规则 / 用例



### 3.1 闭环数据流（现状）



```

TeleControlCfg（指令列表）

        + telecontrol_wire_goldens（线帧）

        + tm_golden_cases（遥测字段）

        ↓  python -m hil.goldens

scenarios/goldens/<protocol>.json

        ↓  pytest 收集

test_hil_*::test_*_golden_case[case_id]

        ↓  ready → Playwright 点 UI → 模拟器收 → 对比 expect/actual

           missing_* → SKIP「缺黄金：…」

```



### 3.2 `scenarios/goldens/*.json` 字段



| 字段 | 含义 |

|------|------|

| `protocol` | 如 `can_biu` / `serial_xl-camera` / `udp_xl_udp_dj` |

| `case_id` | 用例 id（pytest ids） |

| `order_id` | 界面指令卡 id（如 `K1501`、`CAM_A0`） |

| `page` | 前端路由 |

| `ui_action` | `send_order` \| `tm_request` \| `tm_observe` |

| `tx_expect_hex` | 本机模拟器应收到的遥控线帧（空格分隔 hex） |

| `reply_expect_hex` | 设备应答线帧；未知则 `null`，勿编造 |

| `tm_golden_key` / `tm_table_key` / `tm_exclude` | 遥测字段黄金（`tm_golden_cases`） |

| `status` | `ready` \| `missing_tx_golden` \| … |

| `skip_reason` | skip 时展示的原因 |

| `cable` | CAN 时 `a`/`b` |

| `source` | 溯源（cfg 名、wire_key、computed 等） |



生成入口（不碰硬件）：



```bat

cd /d E:\plat\PayloadGroundTest\ruoyi-fastapi-hil

python -m hil.goldens

```



实现：`hil/goldens.py` 的 `build_and_write_goldens()`。有线帧 → `ready`；TeleControlCfg 有指令但无 wire golden → `missing_tx_golden`。



### 3.3 补一条可跑遥控黄金



1. 在业务侧对默认参数组帧，得到线帧 hex。  

2. 写入 `ruoyi-fastapi-backend/tests/data/telecontrol_wire_goldens.json`（或 hil 内可复用的映射；**若用户禁止改 backend，则只在 hil 的 goldens JSON 手写 `tx_expect_hex` 并 `status: ready`**，并在 `source` 注明）。  

3. 若走生成器：在 `hil/goldens.py` 的 `_ORDER_WIRE` 增加 `(protocol, order_id) → wire_key`。  

4. `python -m hil.goldens`  

5. `python -m pytest -m hil_can --hil-plan -q` 确认该 `case_id` 为 **RUN**。  

6. 真机需用户批准后再 `run_hil.bat can <fam>` 等。



### 3.4 `reply_map.json`



- `builtin_responders`：说明本机模拟器已有协议回包（代码在 `hil/protocol/*`），不是让你填 hex。  

- `custom_rules`：缺协议应答时 `enabled: false` + `note`；确认后填 `reply_hex` 再 `enabled: true`，并去掉对应 pending skip。



### 3.5 新增一个协议 / 板的清单



1. 确认 `cfg_device_connect.json` 有设备键；`hil/config.py` 的 `SERIAL_KEYS` / `CAN_FAMILIES` / UDP 键是否需扩。  

2. 有 TeleControlCfg → 加入 `hil/goldens.py` 的 `_CFG_MAP`。  

3. 补至少一条 `tx_expect_hex` 或 wire golden。  

4. 模拟器模型：`hil/protocol/*` + `CanSim`/`SerialSim`/`UdpSim`。  

5. 页面路由与 `send_order` / `send_command_order` 选择器是否适用。  

6. 生成 goldens → unit → plan →（批准后）真机。  

7. 更新 `TODO.md` 缺黄金 / 待确认项。



### 3.6 断言辅助



- 线帧：`hil.goldens.assert_tx_bytes` / `hex_diff`（失败带 expect/actual hex）。  

- 遥测字段：`scenarios.hil_steps.assert_tm_live` / `assert_fields_on_page`（失败带字段 diff）。  

- 刷新：`assert_refreshing` 仅作**附加**，不能作为 UDP/RS422 唯一断言（UDP ready 用例已比 `passthrough_board_dj` 字段）。



---



## 4. 如何运行



工作目录：



```bat

cd /d E:\plat\PayloadGroundTest\ruoyi-fastapi-hil

```



### 4.1 `run_hil.bat`（推荐）



| 命令 | 作用 |

|------|------|

| `run_hil.bat unit` | 纯自测，不连工控机、不开硬件 |

| `run_hil.bat ui` | 有头浏览器冒烟（只读页面） |

| `run_hil.bat can` | CAN 全协议 `--auto`（biu→xl→yj216，靶间清场） |

| `run_hil.bat can biu` | 只跑 CAN 目标 biu |

| `run_hil.bat serial` | 串口全协议 `--auto` |

| `run_hil.bat serial xl-camera` | 只跑一个串口键 |

| `run_hil.bat udp` | 单板 UDP（会设 `HIL_UDP_ENABLE=1`） |

| `run_hil.bat round can` | 交互轮测（提示后回车） |

| `run_hil.bat plan` | 只列 CAN/串口/UDP 的 RUN/SKIP，**不碰硬件** |

| `run_hil.bat all` | unit + ui + can --auto + serial --auto + udp |

| `run_hil.bat ui -k index` | 额外参数透传 pytest |



默认 `run_hil.bat`（无参数）= `all`。



### 4.2 等价 pytest / 模块



```bat

python -m hil.goldens

python -m pytest -m unit -q

python -m pytest -m "hil_can or hil_serial or hil_udp" --hil-plan -q

python -m hil.round can --auto

python -m hil.round serial --plan

set HIL_CAN_TARGET=biu

python -m pytest -m hil_can -v -s

```



### 4.3 常用环境变量



| 变量 | 含义 | 默认/来源 |

|------|------|-----------|

| `HIL_FRONTEND_URL` | 工控机前端 | `http://192.168.100.52:12580` |

| `HIL_USERNAME` / `HIL_PASSWORD` | 登录 | admin / admin123 |

| `HIL_IPC_HOST` | 采集机 | 空=第一个 online（如 gk3） |

| `HIL_CAN_TARGET` | 本进程只测该 CAN 族 | 空=按 default_targets |

| `HIL_SERIAL_TARGET` | 本进程只测该串口键 | 空=按 default_targets |

| `HIL_SERIAL_PORT` / `HIL_IPC_SERIAL_PORT` | COM9 / COM8 | `hil.local.json` |

| `HIL_CAN_VENDOR` / `HIL_IPC_CAN_VENDOR` | 2 / 3 | 同上 |

| `HIL_UDP_ENABLE` | 是否启用 UDP 用例 | bat udp/all 会置 1 |

| `HIL_TEST_PC_IP` | 测试机 IP（UDP 对端） | 自动同网段探测 |

| `HIL_RUN_DIR` | 本次产物目录 | bat 生成 `artifacts\yyyyMMdd_HHmmss` |

| `HIL_ALLOW_BUSY` | 允许复用已占用 CAN | 默认 0（占用则 fail） |

| `HIL_HEADED` / `HIL_SLOW_MO_MS` | 有头浏览器 / 减速 | 1 / 200 |



硬件默认探测：本机有 CAN/COM/UDP 绑定能力才默认打开对应协议；探测不到则 skip（原因写「本机未检测到…」）。



### 4.4 产物 `artifacts/<时间戳>/`



- `summary.txt` — 各分组通过/失败  

- `junit_*.xml` / `pytest_*.log`  

- `*_FAIL_*.png` — 失败截图  

- `sim_io.log` — 模拟器收发  

- `plan.txt` — `--hil-plan` 输出  



整次 `all` / `round --auto` **共用同一个** `HIL_RUN_DIR`。



---



## 5. 真机前检查清单与禁止事项



### 检查清单



- [ ] 用户已**书面批准**真机范围（机器、DUT、`all` 或单靶）。  

- [ ] 测试机 = 批准的 machine；工控机 100.52 可达；采集机 online（如 gk3）。  

- [ ] 版本三边一致。  

- [ ] CAN 线已接 A/B；串口 COM9↔COM8；UDP 防火墙放行本机 **UDP 99**（如需要）。  

- [ ] 工控机页面无残留连接；或依赖 HIL close-all / `ensure_hardware_idle`。  

- [ ] 先 `run_hil.bat plan` 或 `unit`，确认 ready 用例符合预期。  

- [ ] 测完确认 `sessions=[]`（可手动 `IpcApi.close_all` + `sessions()`）。



### 禁止



- 未批准就 `all` / 开 CAN/串口/UDP / 发遥控。  

- 用 API 发遥控冒充闭环。  

- 为通过测试编造 `reply_hex` / 假黄金。  

- 改业务前后端「顺便修」。  

- 擅自 `git commit` / `git push`。  

- 把「未换线」当失败原因（线是公用的；应报协议收发/黄金对比或清场失败）。



---



## 6. 常见失败归因



| 现象 | 可能原因 | 处理 |

|------|----------|------|

| 登录 `HTTP 429` | `--auto` 多进程登录过频 | `ipc_api.login` 已退避；靶间 sleep；稍后再跑 |

| CAN busy / assembler 仍为上一族 | close-all 报空但 registry 仍 alive（幽灵占用） | `ensure_hardware_idle` / `_force_close_registry_leftovers`；确认 sessions 空 |

| `缺黄金：…无对应线帧` | TeleControlCfg 有指令，wire golden 未补 | skip 预期；补 golden 后重新 `python -m hil.goldens` |

| 模拟器 10s 未收到遥控 | UI 未真正发出 / 通道或波特错 / 会话未开 | 看截图与 `sim_io.log`；确认点的是指令卡；expect/actual hex |

| 遥测字段不匹配 | 模拟器回包与 `tm_golden` 不一致 | 字段 diff；核对 exclude（如 CAM001/002、YJ001/002） |

| `本机未检测到 CAN/串口` | 测试机无硬件或端口号不对 | 查 `hil.local.json` / `HIL_SERIAL_PORT`；属环境 skip |

| 版本不一致 | 工控机包与本地 version 文件不同 | **环境级**，停硬件，先对齐版本 |

| UDP 无刷新 / tx=0 | 防火墙、IP 探测错、未 open | `HIL_TEST_PC_IP`；放行 UDP 99；看 summary 里的探测 IP |



---



## 7. Agent 建议工作流（摘要）



1. 读 `AGENT.md` → `TODO.md`（缺黄金 / 待确认）→ 相关 `scenarios/goldens/*.json`。  

2. 只改 hil；补规则用 `goldens` + UI 点击路径。  

3. `python -m hil.goldens` → `pytest -m unit` → `pytest -m "hil_can or hil_serial or hil_udp" --hil-plan`。  

4. 真机：**等用户批准** → 单靶优于 `all` → 结束后 close-all 并汇报 artifacts 路径与 pass/fail/skip。



---



## 8. 快速命令抄送



```bat

cd /d E:\plat\PayloadGroundTest\ruoyi-fastapi-hil

python -m hil.goldens

python -m pytest -m unit -q

python -m pytest -m "hil_can or hil_serial or hil_udp" --hil-plan -q

REM 以下需用户批准真机后：

REM run_hil.bat can biu

REM run_hil.bat serial xl-camera

REM run_hil.bat udp

REM run_hil.bat all

```


## 测试清单模板与填写报告

- **调试·数据模拟**：测 `/debug/simulate` 及其 `/payload/telemetry/dev/*`（can-yc/sample/samples/pipeline）。


硬规则：自动化（pytest nodeid）每一项必须在 ../doc/PGT测试清单模板.xlsx 有「自动化ID」行；跑完必须出填写版报告。

- 重建：python -m hil.report sync（**不生成 bak**；按实采自动化 + 业务页重建）
- 填报：python -m hil.report fill %HIL_RUN_DIR%（
un_hil.bat 结束也会调）
- 产出：rtifacts/<时间戳>/PGT测试清单_填写.xlsx
- **手自动共用一张表**：已有自动化的行填「通过/失败/跳过」；suite=manual_page 或自动化ID 为空的行可手填，也可后续补脚本再 sync 挂上自动化ID。
- **57 条（及后续）手工深测项可以自动化**，当前未脚本化的是「待深自动化」（真发/真收/图像等），不是不能做。
- 范围：业务全量（首页=dashboard 设备服务、载荷、调试等）；不含若依 system/monitor/tool；transportCrypto 保持不测。
- 数据库：pytest -m db_schema 对照本地 SQL **全部表/字段** vs DUT（含 sys_*）；另保留 payload_* 点名。

## 深自动化 TODO（原 manual_page）

浅层「页面打开 + 关键控件可见 / 开连接按钮」已由 ui_only 的 PAYLOAD_PAGES + KEY_ELEMENTS 覆盖。
更深的发送/接收/回放/出图闭环见模板中 [待深自动化] 行，以及 TODO.md 本节对应列表；每补一条脚本必须带自动化ID 并 python -m hil.report sync。

## 调试菜单深测

- 专项：scenarios/test_debug_{simulate,xfer,config,tmcalc,checksum,numconv}.py
- 预存期望：hil/testdata/debug/*.json（checksum/numconv 由 hil/debug_algo.py 对齐前端算法生成；tmcalc 由 DUT /payload/telemetry/calc 校准写入）
- 排除旧壳 	elecontrol/devtest；数据模拟测 /debug/simulate + /payload/telemetry/dev/*
- xfer：ensure_hardware_idle → 接口开设备 → 网页收发 → idle
