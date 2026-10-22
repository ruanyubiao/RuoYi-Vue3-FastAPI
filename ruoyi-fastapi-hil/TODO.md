# ruoyi-fastapi-hil 待办 / 待确认

角色：**工控机（被测）** = 192.168.100.52，部署发布版本（PCIe ZLG CANFD vendor 3 dev0 ch0/ch1、Exar PCIe 串口卡 COM8，RS422/485；后端采集机 gk3）；
**测试机（本机）** = RYB-L16，运行本目录（USB-CAN Alyst Pro vendor 2 ch0/ch1、FTDI USB 转 RS422/485 COM9）。

每项写明：影响的用例、需要用户提供/确认什么。

## 1. 暂不测的三种应答（已 skip，原因写在用例里）
| # | 内容 | 影响用例 | 需要用户提供 |
|---|---|---|---|
| 1.1 | XL 实时遥控包的下位机应答（gpcan XlPacketApidTid 注释要求「按规定格式应答」，代码未定义） | `test_hil_can.py::test_xl_realtime_tc_reply` | 应答帧格式（CAN ID、包类型、APID/TID、数据内容、何时发） |
| 1.2 | 热控电机 / CPA-ZK D15xx 复合帧指令的应答帧 | `test_hil_serial.py::test_serial_tc_reply_pending[xl-rkdj]`、`[xl-zk]` | 是否有独立应答帧；有则给格式（或一段实测 hex） |
| 1.3 | CPA 指向 12B 遥控的应答 | `test_hil_serial.py::test_serial_tc_reply_pending[xl-cpazx]` | 同上 |

确认后：在 `scenarios/reply_map.json` → `custom_rules` 填 `reply_hex` 并设 `enabled: true`，再把上述用例改成断言。

## 2. 推断项（按代码/样本推断实现，需用户确认是否符合真实设备）
| # | 推断 | 影响用例 | 需要确认 |
|---|---|---|---|
| 2.1 | 相机收到 D0 控制帧后立即回一帧 D8，CAM001=指令码、CAM002=AA(正确)，seq+1 | `test_serial_loop[xl-camera]`、`[xl-camera-v17]`（遥测断言排除 CAM001/CAM002） | 真实相机是否立即回 D8、CAM002 的取值 |
| 2.2 | XL CAN 缓变请求（副导头 02）也回 FF 主表样本（仓库只有 passthrough_xlcan_ff 一份） | `test_can_loop[xl]` 定时遥测 | 缓变遥测的真实数据/表号；最好给一份缓变样本 |
| 2.3 | YJ216 RS422 应答数据区全 0（长度按 YJ216-RS422-TeleMetryCfg） | `test_serial_loop[yj216-rs422]`（只断言表格刷新，不比字段值） | 一份真实 RS422 遥测样本，才能比字段 |
| 2.4 | UDP 地检板只验证表格刷新，不比字段值 | `test_hil_udp.py::test_udp_dj_loop` | 是否需要比字段；需要则给期望字段值 |
| 2.5 | CPA-ZK 的 D1503 期望线上帧按热控电机（RKDJ）黄金帧处理 | `test_serial_loop[xl-zk]` | ZK 的 D15xx 组帧是否与 RKDJ 完全一致（首字节/地址） |

## 3. 覆盖缺口
| # | 内容 | 影响 | 需要用户提供 |
|---|---|---|---|
| 3.1 | LVDS 页面没有菜单（sys_menu 中无路由），未覆盖 | `test_ui_pages.py` 不含 LVDS | 是否有入口/路由；LVDS 硬件如何接 |
| 3.2 | 串口在工控机端经接口 `/payload/device/serial/open` 打开，没有走页面「新建串口连接」对话框 | `test_serial_loop[*]` | 是否要求必须走 UI；如要求则补对话框自动化 |
| 3.3 | UDP 页面「新建UDP连接」按 cfg_device_connect.json（xl_udp_dj localHost/remoteHost=127.0.0.1）锁定本机/远程地址，UI 上填不了测试机 IP，测试改走接口（localHost=0.0.0.0、remoteHost=测试机 IP） | `test_udp_dj_loop` | 正式部署时 xl_udp_dj 的地址应改成什么（这是业务配置，本目录不改） |
| 3.4 | 相机图像串口（xl-camera-image / v17-image，D6 图像）未覆盖 | 无用例 | 是否需要测；需要则给图像样本 |
| 3.5 | 指令序列页（BIU/XL/YJ216 sequence）只做了打开冒烟，未执行序列 | `test_ui_pages.py` | 是否需要；给一个可执行的序列定义 |

## 4. 环境 / 硬件待确认
| # | 内容 | 影响 | 需要用户做/确认 |
|---|---|---|---|
| 4.1 | 多采集机：后端按请求头 X-Collector-Host 区分采集机；不带头时默认 local（100.52 上 local 离线，所以裸调 `/can/vendors` 为空——早先「CAN 厂商为空」是误判）。实际采集机为 gk3。snapshot 需 `data.devices[]`（commit `2f13aeb`，parts 已忽略）；HIL 只认 devices，旧包 collectors 会明确失败。测试所有请求带该头、从 snapshot 读当前机 | 全部硬件用例、`test_can_dialog_readonly` | **必须先部署含 2f13aeb 的包**；采集机有变化时设 HIL_IPC_HOST 或 hil.local.json ipc.collector_host |
| 4.2 | 测试机两个通道各用一个 `CanSdkClient` 同时打开（Alyst Pro ch0、ch1）。gpcan 的 CanUsbAlystPro 对同一设备有引用计数（VCI_OpenDevice 共享），按代码应可并发，但尚未在真卡上验证 | 全部 `test_can_loop` | 首次接卡后跑一次确认 |
| 4.3 | 相机串口 2000000 8O1：COM9 为 FTDI FT232R USB 转 RS422/485（芯片上限 3 Mbaud），工控机 COM8 为 Exar PCIe 串口卡；两端 2 Mbaud + 奇校验需实测 | `test_serial_loop[xl-camera*]` | 实测一次；不行就只能降速或换卡 |
| 4.4 | gk3 的 registry 显示 `can:3:0` channels [0,1] alive（assembler can_biu，cable_flag 0/1），但 /sessions 为空。用户说已关，可能快照未刷新。按占用预检，CAN 用例此时会直接失败并列出占用 | 全部 `test_can_loop` | 开跑前在页面确认 CAN-A/B 已关闭、registry 已刷新；或设 HIL_ALLOW_BUSY=1 复用 |
| 4.5 | UDP：测试机 IP 自动探测，本机当前探测到 192.168.100.20（WLAN，/22；有线「以太网」为 169.254 未联网）。端口 99 需放行入站，命令见 README（New-NetFirewallRule … -LocalPort 99） | `test_udp_dj_loop` | 执行防火墙命令；多网卡时确认探测结果或设 HIL_TEST_PC_IP |
| 4.6 | 尚未在真硬件上跑过任何 hil_can / hil_serial / hil_udp 用例（目前只跑了 unit + ui + 收集计划） | 全部硬件用例 | 接线后按 README「运行」逐个跑，结果反馈 |
| 4.7 | 100.52 正式包必须含 `2f13aeb`（`data.devices[]`）；旧包 snapshot 只有 collectors 时 HIL login/选采集机会失败（属预期） | 全部 | 部署含 2f13aeb 的包后再跑 ui / 硬件用例 |
| 4.8 | 本机另有 ELTIMA 虚拟串口 COM1↔COM2（与本测试无关，测试只用实体 COM9）| 无 | 无需处理，勿误选 |
| 4.9 | 本机已安装的 gpcan 在 D:\tools\Python\Lib\site-packages\gpcan（非 E:\plat\pygpcan 可编辑安装） | CAN 用例 | 确认与工控机 gpcan 版本一致 |

## 5. 工具链
| # | 内容 | 影响 | 处理 |
|---|---|---|---|
| 5.1 | `pytest_*.log` 为空：用例/模拟器用 print 输出，没走 logging；收发记录在 `sim_io.log` | 运行目录日志 | 如需要可把 print 改为 logging |
| 5.2 | BIU 目标地址（0x0D/0x0C）用页面默认值，未分别测试 | `test_can_loop[biu]` | 是否需要两个地址都测 |
| 5.3 | gpcan 不在 PyPI，需 `pip install -e E:\plat\pygpcan`；Alyst Pro / ZLG 的 DLL 由 gpcan 提供 | CAN 用例与 CAN 自测 | 保持本机 gpcan 与工控机版本一致 |
