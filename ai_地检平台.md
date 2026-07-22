# 地检上位机（卫星激光终端地面检测系统）

本系统实在RuoYi-Vue3-FastAPI项目上进行的二次开发，原项目地址：https://github.com/insistence/RuoYi-Vue3-FastAPI。
当前已经进行了一定修改，数据库新增了sqlite，当前配置使用了sqlite，项目能正常运行。
这些修改不涉及具体项目内容，只是修改了框架。


目录说明：
ruoyi-fastapi-frontend：前端项目，vue3
ruoyi-fastapi-frontend：后端项目，python + FastAPI实现
ruoyi-fastapi-app：手机前端
test：参考资料，不要对这个目录进行修改。
whl：项目的py依赖库，can通信库，遥测解析库
ruoyi-fastapi-backend\assets\config：遥控、遥测配置文件，这个是需要后端读取的，现在是放在了这里，文件位置可以移动。
TeleControlCfg.json：遥控配置，发送can指令需要
TeleMetryCfg.json：遥测表配置，解析遥测数据需要， can遥测类型："FF"，'FD"，"FB"，"F9"，'F7"，'FE"，工程遥测："7E9B"，"7E9D"，"7E9F"

ruoyi-fastapi-backend/venv：后端环境虚拟目录，激活后 python app.py --env=dev  启动后端服务

# 二次开发项目说明

二次开发项目说明是一套**浏览器 / 服务器（BS）架构的实时数据采集、监控、控制与可视化系统**，核心目标是：通过前端可视化界面实现对串口设备、多类型 CAN 总线设备、网络设备的实时数据监控、图表分析、图片状态展示及指令下发，后端采用多进程架构保证数据采集稳定性与 http API 服务响应速度。

数据采集进程和主进程的通信，使用redis。
二次开发的功能是从c++ 移植过来的，c++项目目录：test\GeniusProsSoftPlatform

# 数据采集层

独立于 API 服务，专门负责对应类型设备的数据采集与指令执行，避免采集异常影响整体系统，支持多类型设备灵活扩展

## 进程 1：CAN 采集进程

调用can通信库进行数据采集和发送。
can库使用参考test/pygpcan目录，这是库源码。
whl/gpcan-1.0.0-py3-none-any.whl是源码打包的扩展库。

## 进程 2：串口采集进程

初始化串口（配置波特率、端口号等所有串口相关的参数）、实时读取串口二进制数据、接收并执行后端下发的串口指令。
参考test\GeniusProsSoftPlatform下 rs422，serial相关文件，如GpPayloadMsgRs422TimeAck.h


## 进程 3：网络采集进程


  * 功能：配置网络连接参数（IP 地址、端口号、通信协议 TCP/UDP）、建立网络连接、实时接收网络数据包、接收并执行后端下发的网络指令（如 TCP/UDP 发送指令）

  * 特性：独立进程运行，支持网络断开自动重连，兼容自定义网络数据协议，支持多网络设备并行采集（通过多连接实例实现）


## 进程管理
做好进程管理

can卡（--vendor、--dev-index相同，--can-index不同，因为1张cna卡有多个通道，通道就是--can-index）同一张can卡，使用同一个进程，需要等所有can通道关闭才能关闭。
get_opened_channel_list：获取当前厂家驱动下已打开的设备通道列表（n_dev_index）。
udp，串口，打开开启进程，关闭则关闭进程。
从redis中获取数据，需要唯一标识。


# 数据解析
不同方式获取的数据，内容的解析，放在子进程。


## （1）数据采集→前端展示流程


1. 采集进程（CAN / 串口 / 网络）启动时，获取对应设备配置参数（CAN 卡类型 / 串口参数 / 网络连接参数），完成初始化，

2. 采集进程实时读取对应设备原始数据（CAN 二进制 / 串口二进制 / 网络数据包）

3. 采集进程将原始数据解析后传递给redis

6. 前端通过调用 HTTP API 接口，从主进程获取redis的结构化数据，支持按数据来源筛选

7. 前端将数据渲染为列表、图表、图片状态展示

## （2）前端指令→硬件 / 网络设备执行流程


1. 前端通过指令面板选择目标设备类型（CAN / 串口 / 网络）、目标设备标识，输入指令内容（十六进制字符串 / 网络指令字符串）

2. 前端调用后端指令下发 API，将指令数据传递给主进程

3. 主进程将指令写入redis，对应设备类型的指令字段

4. 对应采集进程（CAN / 串口 / 网络）实时监听reids的指令字段，发现新指令后读取

5. 采集进程将指令转换为对应设备可识别的格式（CAN 指令 / 串口指令 / TCP/UDP 数据包），下发给目标设备

6. 设备执行指令后，采集进程将执行结果（成功 / 失败 / 响应数据）反馈至redis，主进程向前端返回执行状态与反馈信息



# 界面菜单

1.  遥控：有二级菜单，

控制开关页：
页面控件功能参考 `test/GeniusProsSoftPlatform` 下的PayloadControlWidget的代码（ui+cpp）。
效果图参考 `test/控制开关.jpg`，效果图中的ui排版是label和输入框放在两行，我需要放在同一行。
详细控件功能需要看代码。

遥控页面：
界面参考`test/遥控.jpg`、`test/遥控2.jpg`。
代码参考在 `test\GeniusProsSoftPlatform\Src\SoftPlatform\Ui\SatellitePayload\TeleControl`，参考功能实现，但界面方案按照效果图来，使用树形结构，点击具体项目，在输入参数发送。
遥控的配置读取TeleControlCfg.json


指令序列页面：
把遥控命令+参数，做成指令，排除广播帧。指令保存在数据库。需要新建数据库表。
序列的增删改查，
序列复制功能：在序列列表，修改后面增加复制，复制后，直接跳到新增，但数据已填充。
内容包括指令序列id，name，
指令内容：json字段，对象数组，指令数组：指令hex文本（AA BB CC），发送后下一帧发送间隔（默认2000 毫秒），


3. 遥测：有二次菜单，二级菜单通项在TeleMetryCfg.json配置文件的"page"字段。需要根据配置创建遥测菜单，写入到数据库。
菜单如下：
0xFF:B-1主要包
0xFD:B-2捕跟同轴标校包
0xFB:B-3算轨包
0xF9:B-4-1指向标校包
0xF7:B-4-2星敏遥测包
0xFE:算轨异步包1
0xFC:算轨异步包2

所有二级菜单的都是遥测相关的表单显示。
表单功能参考：SatellitePayload/TeleMetry/TeleMetryTable/TeleMetryTableHelper

3. 遥测曲线页面：
这个功能c++中没有的。
进入方式：点击菜单栏进入，页面包括遥测表下拉菜单，遥测量下拉菜单（根据不同的遥测表切换），确认按钮，点击确认后，间隔获取这个遥测量的数据并显示成图表曲线（echarts），显示对应遥测量曲线。可以选中曲线一段区间，进行放大缩小；
也可以在遥测页面，点击遥测量数值进入（这时候下拉菜单需要选中对应项目），默认已点击确认按钮，


4. 单板：有二次菜单，当前只有1项，相机测试。
相机测试页：
参考test\showimg\serial_image_viewer.py
通过串口获取图像数据。

6. 重构：点击直接显示页面，没有二级菜单。当前点击显示空白页

5. LVDS：有二次菜单，当前只有1项，工程遥测，效果图参考 `test/工程遥测.jpg`。


页面添加需要在sql语句中插入对应的页面配置，现在有三种sql需要更新。
同时sqlite数据库文件是：ruoyi-fastapi-backend/ruoyi-fastapi.db，需要同步更新。sqlite3命令存在。



# 输出
这是一个完整的工程项目，可以分步骤输出，先输出文档(放doc目录)，在修改代码。



修改1：
首页/遥控/控制开关，http://localhost/telecontrol/control ,前后端都需要修改。


把设备连接区域拆分成 CAN连接 和 串口连接 两块。

CAN连接区域：
把can设备的所有输入参数补全，尽量使用下拉菜单，按下面顺序制作控件ui。
vendor: int = Field(default=0, description='CAN厂家 0=DEMO')
can_index: int = Field(default=0)  0 1两个通道
baud_rate: int = Field(default=500) 波特率
cable_flag: int = Field(default=0)， 线A，线B
node_addr_to: int = Field(default=0x0D) 激光终端A，B
dev_index: int = Field(default=0) // 下拉菜单只有0，不需要其他数据

波特率默认选中500
1000kbps
800kbps
500kbps
250kbps
125kbps
100kbps
50kbps
20kbps
10kbps
5kbps

打开后这些选项都不能选了，关闭后才能再次选择。
具体选项参考 can_def.py，在test/pygpcan中


增加 帧ID(HEX)输入框+数据(HEX)输入框+发送按钮
帧ID(HEX):00000000 （默认值）
数据(HEX):00 01 02 03 04 05 06 07 （默认值）



串口连接区域：
下面的参数都需要，都是下拉菜单
串口号
波特率， 下拉菜单最后一项时自定义输入，选中后变成输入框
数据位
停止位
校验位
流控制


增加 数据输入框+HEX复选框+发送按钮


修改2：
can的标题，
vendor 厂商
can_index 通道号
baud_rate 波特率
dev_index 设备索引号
cable_flag 线缆
node_addr_to 目标地址
都写成中文


串口：
波特率：
110
300
600
1200
2400
4800
9600
14400
19200
38400
56000
57600
115200
128000
230400
256000
460800
921600
1000000
2000000
Customize


流控制：
NONE
XON/XOFF
RTS/CTS
DTR/DSR
RTS/CTS/XON/XOFF
DTR/DSR/XON/XOFF


CAN发送 和 串口发送 label放在分割线下。
串口的发送按钮和输入框直接需要间隔
can连接区域和 串口连接区域，高度设置成一样，现在大小不一致。
具体查看：test/界面问题1.jpg




修改3：
can的波特率下拉菜单按照下面的顺序，然后默认选中500kbps。
1000kbps
800kbps
500kbps
250kbps
125kbps
100kbps
50kbps
20kbps
10kbps
5kbps


串口的刷新按钮 效果优化。
波特率默认选中9600，
校验位去掉前缀：
N=
E=
O=
M=
S=


修改4：

can：
厂商：
    CAN_VENDOR_DEMO = 0           # 演示/虚拟设备
    CAN_VENDOR_USB_V502 = 1       # USB-CAN V502
    CAN_VENDOR_USB_ALYST_PRO = 2  # USB-CAN Alyst Pro
    CAN_VENDOR_ZLG = 3            # PCIE ZLG CANFD


串口
校验位是去掉前缀，保留后面部分。
HONE
EVEN
ODD
MARK
SPACE



修改4
串口和can的数据输入框，做成和帧id的输入框一样长。
串口的复选框、发送按钮放入新的一行
串口，默认不勾选hex复选框。
选中hex复选框后，如果文本框有内容，需要把内容都转换成hex文本，如果本身就是hex文本，就不需要转换了。
取消选中后，需要把hex文本转换成普通文本，如果转换结果包含非打印字符，提示“包含非打印字符，无法转换!”，然后文本不变，依旧保留hex文本。
hex文本举例：00 dd   00   aa    bb， 不管中间都多少空格，都是。


修改5
提示“包含非打印字符，无法转换!”  没有。
选中hex复选框后，如果文本框有内容，需要把内容都转换成hex文本，如果本身就是hex文本，就不需要转换了。
取消选中后，需要把hex文本转换成普通文本，如果转换结果包含非打印字符，提示“包含非打印字符，无法转换!”，然后文本不变，依旧保留hex文本，但复选框需要去掉。
我把复选框的文本移动到了<el-form-item label="HEX">，el-checkbox内没有hex，复选框自身点击有时候会无效。
hex文本举例：00 dd00   aa    bb， 不管中间都多少空格，或者没有空格。


修改6
串口和can点击连接，显示已连接，但网页刷新后，变成未连接。

修改7：
can支持的设备列表通过api获取，pygpcan的get_vendor_info_list获取。默认值是3，没有3就是0.


can增加刷新按钮，类似串口。
can列表没获取前，下拉菜单是空的，不要出现一个数字3.
如果获取了列表，存在pcie类型，就是默认值。如果不存在，就选下拉菜单索引0的。

payload_device_service.py 的 list_can_vendors 中不要传输label属性，这个在前端拼接。
当前刷新按钮点击，调用了后端数据，但前端没有刷新。


加载页面的时候，can设备厂商能显示列表，但点击刷新后就没有数据了
async function refreshCanVendors(showMsg = false)
这个函数的ElMessage.success(`已刷新，发现 ${nextVendors.length} 个厂商`)触发异常，
异常中：ElMessage.error('刷新厂商列表失败')也出错。
Uncaught (in promise) ReferenceError: ElMessage is not defined


串口：
复选框选中HEX，输入的时候，需要判断 isHexText ，不是的话，需要提示“当前在十六进制输入模式下，只能输入十六进制形式的字符。”
且输入框内容不变。HEX模式的输入框不能出现非isHexText的字符。

新增 解析转义符 的复选框，当hex复选框为选中时启用，选中后禁用。
在非hex文本时，输入了文本"\r\n\t"等，需要转换成对应的转移字符.


解析转义符 和 HEX 放在同一行。
选hex复选框的时候，禁用解析转义符，但复选框是否选中的状态不要修改。
数据提交的时候，需要做好hex是否选中，解析转义符只在hex未选中有效的处理


解析转义符复选框和hex复选框放在同一行。


isHexText的判断优化
当前是
hex文本举例：00 dd   00   aa    bb， 不管中间都多少空格，0个也可以都是。
00 11    2233 44 这些都可以。
这个正则是对的：/^([0-9a-fA-F]{2})(\s*[0-9a-fA-F]{2})*$/

现在修改下，如果最后一个字符只有1个，自动扩展成两个。
如：00 11 2  就扩展成 00 11 02
如：AABBC 就是AABB0C


还未完全修改正确，在HEX模式下，当输入框已有AA情况下，在输入字符B就不能输入

规则修改：空白字符 是 16进制字符的分割
具体示例如下：
a b c -> 0A 0B 0C
ab c -> AB 0C
ab c de f -> AB 0C DE 0F
ab c d -> AB 0C 0D
aabbc  -> AA BB 0C
aabbc d -> AA BB 0C 0D
aabb c d  -> AA BB 0C 0D
aab ccd d eef 445 -> AA 0B CC 0D 0D EE 0F 44 05

所有进行isHexText判断相关的都需要修改


刚才修改的代码被我还原了。
can：
帧ID(HEX) 输入的时候需要校验 ，帧ID(HEX)  32位，4字节 无符号整型，  hex的写法， 需要连续的8个hex字符，不能有空格，有空格，输入的时候直接去掉，非hex字符不让输入。

数据(HEX)输入框，  最多8个字节的数据，这8个字节是转换后的，不足8个字节，前面补0，HEX格式参考串口的格式。
HEX格式字符串，发送前需要转换， 输入的时候需要校验，校验参考串口的数据hex的时候的输入框。
这里发送是发送原始的数据，不需要走can的业务通道，直接通过send或sendObj接口发送。

新建一个api接口 不要走/payload/telecontrol/sendraw

当前有报错：
    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^
PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问。: 'E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\logs\\2026\\06\\25\\info.log' -> 'E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\logs\\2026\\06\\25\\info.2026-06-25_10-13-01_784465.log'
--- End of logging error ---
--- Logging error in Loguru Handler #2 ---
Record was: {'elapsed': datetime.timedelta(seconds=821, microseconds=632737), 'exception': None, 'extra': {'startup_phase': True, 'startup_log_enabled': True, 'trace_id': '', 'request_id': '', 'span_id': '', 'path': '', 'method': '', 'worker_id': '25208-7c0d81', 'instance_id': 'dev', 'service': 'ruoyi-fastapi-backend', 'sanitized_exception': ''}, 'file':(name='__init__.py', path='D:\\tools\\Python\\Lib\\logging\\__init__.py'), 'function': 'callHandlers', 'level': (name='INFO', no=20, icon='ℹ️'), 'line': 1737, 'message': 'Scheduler has been shut down', 'module': '__init__', 'name': 'loggiing', 'process': (id=25208, name='SpawnProcess-7'), 'thread': (id=29048, name='MainThread'), 'time': datetime(2026, 6, 25, 16, 57, 23, 659875, tzinfo=datetime.timezone(datetime.timedelta(seconds=28800), '中国标准时间'))}
Traceback (most recent call last):
  File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\loguru\_handler.py", line 315, in _queued_writer
    self._sink.write(message)
    ~~~~~~~~~~~~~~~~^^^^^^^^^
  File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\loguru\_file_sink.py", line 204, in write
    self._terminate_file(is_rotating=True)
    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
  File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\loguru\_file_sink.py", line 276, in _terminate_file
    os.rename(old_path, renamed_path)
    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^
PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问。: 'E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\logs\\2026\\06\\25\\info.log' -> 'E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\logs\\2026\\06\\25\\info.2026-06-25_10-13-01_784465.log'
--- End of logging error ---
2026-06-25 16:57:23.666 |  |  |  | 25208-7c0d81 | INFO     | config.get_scheduler:close_system_scheduler:774 - 🔓 Worker 25208-7c0d81 释放 Application 锁
--- Logging error in Loguru Handler #2 ---
Record was: {'elapsed': datetime.timedelta(seconds=821, microseconds=639785), 'exception': None, 'extra': {'startup_phase': True, 'startup_log_enabled': True, 'trace_id': '', 'request_id': '', 'span_id': '', 'path': '', 'method': '', 'worker_id': '25208-7c0d81', 'instance_id': 'dev', 'service': 'ruoyi-fastapi-backend', 'sanitized_exception': ''}, 'file':(name='get_scheduler.py', path='E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\config\\get_scheduler.py'), 'function': 'close_system_scheduler', 'level': (name='INFO', no=20, icon='ℹ️'), 'line': 774, 'message': '🔓 Worker 25208-7c0d881 释放 Application 锁', 'module': 'get_scheduler', 'name': 'config.get_scheduler', 'process': (id=25208, name='SpawnProcess-7'), 'thread': (id=29048, name='MainThread'), 'time': datetime(2026, 6, 25, 16, 57, 23, 666923, tzinfo=datetime.timezone(datetime.timedelta(seconds=28800), '中国标准时间'))}
Traceback (most recent call last):
  File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\loguru\_handler.py", line 315, in _queued_writer
    self._sink.write(message)
    ~~~~~~~~~~~~~~~~^^^^^^^^^
  File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\loguru\_file_sink.py", line 204, in write
    self._terminate_file(is_rotating=True)
    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
  File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\loguru\_file_sink.py", line 276, in _terminate_file
    os.rename(old_path, renamed_path)
    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^
PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问。: 'E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\logs\\2026\\06\\25\\info.log' -> 'E:\\plat\\PayloadGroundTest\\ruoyi-fastapi-backend\\logs\\2026\\06\\25\\info.2026-06-25_10-13-01_784465.log'


前端发送的数据是
{"deviceId":"can:2:0:0","frameIdHex":"AABBCCDD","dataHex":"00 01 02 03 04 05 06 07"}

后端处理的时候把frameIdHex  和 dataHex  合并了,
在send_can_raw函数中，是不对的。
raw = bytes.fromhex(fid) + bytes(data_bytes)
给redis的命令，不要使用can业务的，这个是独立的，can的发送包括raw发送和遥控发送，在所有地方都需要分开。



can的发送，把帧ID和帧数据合并在一起时不对的。 raw = bytes.fromhex(fid) + bytes(data_bytes)


测试：
发送id：AABBCCDD
发送数据：aa 01 02 03 04 05 06 07

接收id： 000004dd
接收数据：aa 01 02 03 04 05 06 07



前端加入帧ID的判断，加入提示
“帧ID溢出。标准帧有效范围0-0x7FF，扩展帧有效范围0-0x1FFFFFF“
帧id输入框 如果输入 7FF，在发送按钮点击后，需要补全0，输入框显示 000007FF

数据(HEX)输入框，输入超过8个字节进行提示，并且不让输入。
数据有效性和格式化、解析等，使用串口的相关函数

帧ID输入框 和 数据(HEX)输入框，失去焦点前 和 点击发送后，
把  帧ID输入框 和 数据(HEX)输入框 的数据显示成 转换好的数据
例如：
数据(HEX)输入框： 11 23 4  44 ff dd ee d -> 11 23 04 44 FF DD EE 0D
帧ID输入框： 105 显示成 00000105

数据(HEX)输入框
发送小于8个字节的数据，不要补0， 按照实际大小发送。


can_collector.py 中 execute_command， # 兼容旧格式：hex 前4字节为帧ID，其余为数据
代码不需要兼容旧格式。其他地方如果有这种兼容，都去掉。


串口的 数据输入框，失去焦点后，在hex模式下，
把数据显示成 转换好的数据
例如：11 23 4  44 ff dd ee d -> 11 23 04 44 FF DD EE 0D

串口没有8个字节的限制。
不需要修改ishextext函数



遥控帧发送的c++ 函数，spData 是发送数据。这个函数在SoftPlatform\Ui\SatellitePayload\TeleControl\TeleControlTable\TeleControlTableOrderWidget.cpp文件

    std::shared_ptr<TeleControlOrderData> CTeleControlTableOrderWidget::getOrderData()
    {
        auto spData = std::make_shared<TeleControlOrderData>();
        auto &buf = spData->buffer;

        //取值
        int nSize = static_cast<int>(m_cfg.component.size());
        for (int i = 0; i < nSize; i++)
        {
            auto p = m_vecItem[i];
            if (p)
            {
                auto bufSub = p->value();
                buf << bufSub;
            }
            else
            {
                //固定值
                auto &cfg = m_cfg.component[i];
                auto fixedBuf = ByteBuffer::from_hex(cfg.defaultVal);
                buf << fixedBuf;

            }
        }

        //长度校验
        if (buf.size() < 8)
        {
            CTipDialog::showCentral(tr("can frame length < 8"), CTipDialog::TipLevel_Error, CTipDialog::ButtonType_OK);
            return nullptr;
        }

        //CanFrameType的索引位置，单帧索引0，复合帧索引2
        int ucCanFrameType = buf.size() == 8 ? buf[0] : buf[2];
        spData->frameType = ucCanFrameType;

        //遥控单帧 || 遥测请求帧 || 时间广播
        if (ucCanFrameType == PAYLOAD_CAN_FRAME_TYPE_YK_SIGNLE ||
            ucCanFrameType == PAYLOAD_CAN_FRAME_TYPE_YC_SINGLE ||
            ucCanFrameType == PAYLOAD_CAN_FRAME_TYPE_BROADCAST_DATA_ONBOARD_TIME)
        {
            return spData;
        }

        //遥控复合帧 || 姿轨广播
        if (ucCanFrameType == PAYLOAD_CAN_FRAME_TYPE_YK_COMPLEX ||
            ucCanFrameType == PAYLOAD_CAN_FRAME_TYPE_BROADCAST_ATTITUDE_ORBIT)
        {
            auto unDateLen = buf.peek<uint16_t>(0);

            //没有校验和，添加校验和
            if (unDateLen + 2 == buf.size())
            {
                auto verify = utils::CalcCheckSum_Byte((uint8_t *)buf.data(), buf.size());
                buf << verify;
                return spData;
            }

            //有校验和，进行校验和验证
            if (unDateLen + 3 == buf.size())
            {
                //进行校验和验证
                auto verify = utils::CalcCheckSum_Byte((uint8_t *)buf.data(), buf.size() - 1);
                if (verify != buf.at(buf.size() - 1))
                {
                    //校验和不一致
                    CTipDialog::showCentral(tr("can verify sum error!"), CTipDialog::TipLevel_Error, CTipDialog::ButtonType_OK);
                    return nullptr;
                }
                return spData;
            }

            //长度不对
            CTipDialog::showCentral(tr("can frame length error!"), CTipDialog::TipLevel_Error, CTipDialog::ButtonType_OK);
            return nullptr;
        }

        CTipDialog::showCentral(tr("can frame type error!"), CTipDialog::TipLevel_Error, CTipDialog::ButtonType_OK);
        return nullptr;
    }


遥控指令有问题，测试发现，
比如
D1601 计算时间补偿设置 ：  00 0A 91 11 01 00 00 00 00 00
正确的是：0A 91 11 01 00 00 00 00

D1516 捕跟控制参数设置：00 00 14 0F 92 88 21 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
正确：00 14 0F 92 88 21 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E
其中5E是校验位


界面：首页/遥控/遥控，http://localhost/telecontrol/command
搜索指令代码，过滤的时候，
不考虑大小写，
a b → 文件名同时有 a 和 b，顺序不限，不管中间多少空格，正则的\s
匹配后直接展开所有树枝

界面：首页/遥控/遥控，http://localhost/telecontrol/command
选择姿轨广播，界面异常，指令参数内容多高度变大合理，但指令代码这一行高度变大不合理。
test/姿轨广播界面异常.jpg
正常界面看：test/遥控指令正常界面.jpg


标题：
指令代号，参数长度，指令参数 固定宽度，并且保持一样，当前宽度不一致难看

首页/遥控/遥控
B001 姿轨广播 界面，指令多，出现了垂直滚动条，但其他指令短，没有滚动条，切换的时候界面出现了抖动，


现在改动的方向是对的，三块区域需要三个不同的滚动条。
但滚动条的样式需要和搜索指令区域的样式一样，现在不统一。
整体界面没有占到内容区域的满屏。
历史区域也是需要滚动条的，现在不知道有没有，样式对不对，数据补全没测试到。
参考test/遥控界面异常.jpg


现在点击指令，中间区域不显示了。
[Vue warn]: Invalid prop: type check failed for prop "modelValue". Expected Number | Null, got String with value "".
  at <ElInputNumber key=0 modelValue="" onUpdate:modelValue=fn<onUpdate:modelValue>  ... >
  at <ElFormItem key=2 label="APD温度修正参数3" >
  at <ElForm label-width="120px" >
  at <ElScrollbar class="panel-scroll" >
  at <ElCard key=0 shadow="never" class="detail-card" >
  at <ElCol span=12 class="panel panel-detail" >
  at <ElRow gutter=12 class="command-row" >
  at <PayloadCommand onVnodeUnmounted=fn<onVnodeUnmounted> ref=Ref< Proxy(Object) {__v_skip: true} > key="/telecontrol/command" >
  at <KeepAlive include= ['Command'] >
  at <BaseTransition mode="out-in" appear=false persisted=false  ... >
  at <Transition name="fade-transform" mode="out-in" >
  at <RouterView >
  at <AppMain >
  at <Index onVnodeUnmounted=fn<onVnodeUnmounted> ref=Ref< Proxy(Object) {__v_skip: true} > >
  at <RouterView >
  at <App>


首页/遥控/遥控，这个页面，http://localhost/telecontrol/command
现在点击指令，中间区域不显示了。

  ARIA roles used must conform to valid values: Role must be one of the valid ARIA roles: bar
  受影响的资源
  <div class="bar" role="bar" style="transform: translate3d(0%, 0px, 0px); transition: 200ms;">


  中间区域滚动条位置不对。
  参考test/滚动条位置不对.jpg

还是不对，滚动条需要贴着区域边沿。是不是嵌套太多了。
<el-col :span="12" class="panel panel-detail">
        <el-card shadow="never" v-if="currentOrder" class="detail-card">
          <template #header>{{ currentOrder.id }} {{ currentOrder.name }}</template>
          <el-scrollbar class="panel-scroll">



当前系统，界面，界面切换后，数据都没有了。需要缓存页面。

module_payload\cfg\telecontrol_assembler.py
def assemble_order(components: list[dict[str, Any]], values: list[Any] | None = None) -> dict[str, Any]
如果value的数据是空的，组帧的时候数据就没有了，造成实际帧长度不对。 空情况下根据components的item类型，填充数据0，长度需要根据实际类型来。



这个界面的缓存不对。切换页面会丢失
http://localhost/telecontrol/command



遥控界面，选中一个指令，输入参数，在点击其他指令，在切换回来，输入的参数都会丢失，需要缓存。


遥控界面，指令，生成的控件，输入框需要有默认值。下拉菜单也需要默认选中第一项，

遥控界面，指令，生成的控件，输入框，下拉菜单，数字输入框等，需要宽度保持一致。
整数数字输入框，需要限制输入浮点


发送历史，清理按钮无效。
OK按钮，2026-06-26 10:08:39.134， title  这三个换在一行
00 01 02 03 04 05 06 07


指令列表，页面切换，列表的展开状态也需要保留，当前值保留了点击的那个指令所在列表打开

点击树节点，事件执行不会切换中间指令窗口。
切换页面没有保存树节点状态。
<div class="app-container command-page">  这个没有占满全屏，底部还留有空白区域。

现在只能点击树的三角符号能展开收缩，箭头所在的文字也要能点击展开收缩


遥控界面页面还是没有铺满全屏。
参考这个界面，它是铺满的：ruoyi-fastapi-frontend\src\views\tool\build\index.vue


遥控界面嵌套还是多了，下面两层嵌套多了1层。,参考界面只有1层div，。
<div data-v-d3a07bc2="" data-v-e7e0a46a="" class="command-page">
<div data-v-d3a07bc2="" class="el-row command-row" style="margin-left: -6px; margin-right: -6px;">
...
</div>
</div>


遥控界面的 command-page 对应的margin border padding 都是0， 最终内容尺寸是1392*778


遥控界面
中间的指令输入区域，如果没有输入框之类的，只有固定数据的时候预览组帧的按钮不需要




http://localhost/telecontrol/control
的串口连接区域，新增下拉菜单，在复选框hex的同一行。
下拉菜单宽度设置40.
下拉菜单选项： 无追加，\n, \r, \r\n 。
就是在发送内容后面增加换行符，这个需要在解析转义符后面处理。
这个在非hex模式和hex都支持。


无追加，value是空，显示的时候会变成请选择，这个问题修复下。请显示无追加。


getSerialLineEndingSuffix 的判断不对。判断非none吧。
然后，获取的字符，有转移。比如\n 获取到的是 \\n



# 修改1：
AI相关的模块需要删除。 我试了直接git还原，冲突很多。
这两个个是git相关的，可以能还有其他的，帮我还原下。
76943141f7f8c6f192dc80ebc2d233f5e08e3957  这个是最早的ai相关提交

SHA-1: 56036d6c00f70d3532efe360a80f1272c216bf50
* perf: 优化AI管理模块


SHA-1: 76943141f7f8c6f192dc80ebc2d233f5e08e3957
* feat: 新增AI管理模块 (#69)


我没有接入usb can 设备，点击打开can，会出现异常
发生异常: RuntimeError
CAN0 init_can 失败
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\can_collector.py", line 72, in _open_channel_client
    raise RuntimeError(f'CAN{can_index} init_can 失败')
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\can_collector.py", line 43, in setup
    self._open_channel_client(int(ch['can_index']), ch)
    ~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\base_collector.py", line 51, in run
    if not self.setup():
           ~~~~~~~~~~^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\runner.py", line 26, in run_collector
    CanCollector(device_id, config).run()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\runner.py", line 46, in main
    run_collector(args.collector_type, args.device_id, config)
    ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\runner.py", line 50, in <module>
    main()
    ~~~~^^
RuntimeError: CAN0 init_can 失败



# 20260710
# 修改1：
下面进行can消息回复后的功能测试。

现在没有can设备给平台发消息。现在只能模拟。
平台接收can消息，需要经过can库的消息组合后，得到完整消息，放入redis。
模拟的过程是前端页面发送完整消息（can消息内容）给后台，后台存入redis
后面的流程后台从redis读取，处理流程都一样了。


新增：平台在遥控菜单的指令序列后，添加新菜单“开发测试”，先添加第一个区域，CAN遥测数据，输入框（提示输入CAN遥测数据）+ 发送按钮。然后测试平台从redis获取消息内容，在遥测界面显示的完整流程。



can回复的消息，复合帧，经过多帧组合，合成的测试数据，如下：
00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C


C++解析can消息相关参考代码，这个是qt界面版本的，ui的输入框内容，调用setPayloadCommandCanYcDataTest，最后通过调用 canYcAck（内部调用了ui监听的回调函数）：

INT32 CGpPayloadDevice::setPayloadCommandCanYcDataTest(const std::string &strCanIndex, const char *pBuffer, UINT32 unSize)
{
    auto sp = proto::createCanYcAck(pBuffer, unSize);
    if (sp)
    {
		// 这里是返回到前端
        return canYcAck(strCanIndex, sp.get(), false);
    }
    return SDK_RET_CODE_FAIL;
}


std::shared_ptr<GpPayloadCanYcRspFrame> proto::createCanYcAck(const char *pBuffer, UINT32 unSize)
{
    if (!pBuffer)
    {
        return nullptr;
    }

    //这里 sizeof(GpPayloadCanYcRspFrame) > m_byteBuffer.size(), 不能直接指针指向。
    if (unSize > CAN_PACKET_RSP_YC_FULL_SIZE)
    {
        LOGERROR("%s: package size error, max size:%d, cur size:%u", __FUNCTION__, CAN_PACKET_RSP_YC_FULL_SIZE, unSize);
    }
    auto unRealSize = unSize;
    bool bVerify = NetSwitchAndVerify(pBuffer, unRealSize);
    if (!bVerify)
    {
        auto msg = utils::toHex(pBuffer, unSize >= 4 ? 4 : unSize);
        LOGERROR("%s: can msg verify is error. [%s]", __FUNCTION__, msg.c_str());
        return nullptr;
    }

    auto msg = std::make_shared<GpPayloadCanYcRspFrame>();
    safeMemCopy(msg.get(), sizeof(GpPayloadCanYcRspFrame), pBuffer, unRealSize);
    msg->dataLen = msg->dataLen - 2;

    auto ackId = msg->frameType;
    LOGMSG("%s: can recv cmd=[%X], dataCode=[%X], msgSize=[%u], recvSize=[%u]", __FUNCTION__, ackId, msg->dataType, unRealSize, unSize);
    if (ackId == PAYLOAD_CAN_FRAME_TYPE_YC_COMPLEX)
    {
    }
    else
    {
        LOGERROR("%s: ackId is error. cmd=[%X]", __FUNCTION__, ackId);
        return nullptr;
    }
    return msg;
}

/*
1)	数据长度（D1）：为复合帧中数据字节长度（包含D2~D4的数据总字节数）；
2)	数据类型（D2）：按照约定的数据的类型定义，见5.3.1.3节；
3)	数据编号（D3）：某一数据类型下的数据子类型/编号，见5.3.1.3节；
4)	数据/指令参数（D4）：传输的具体数据；
5)	校验和（D5）：采用无符号和校验的方式，校验仅包括D1（含）~D4（含）数据的字节累加和。

域名  数据长度（D1）    数据类型（D2）    数据编号（D3）    数据/指令参数（D4）     校验和（D5）
长度  2B              1B              1B              有效数据               1B

*/

static bool NetSwitchAndVerify(const char *data, size_t &size)
{
    //Buffer长度会变，不能直接转换成结构体

    auto pDataLen = (UINT16 *)data;
    auto dataLen = TO_NET_UINT16(*pDataLen);

    size_t realSize = dataLen + 3;
    if (realSize > size)
    {
        auto strMsg = utils::toHex(data, size >= 4 ? 4 : size);
        LOGERROR("%s: package size error, dataLen:%hu + 3 > recvSize:%u, [%s]", __FUNCTION__, dataLen, size, strMsg.c_str());
        return false;
    }

    //计算校验和
    auto pDataStart = reinterpret_cast<const BYTE *>(data);
    auto pDataEnd = reinterpret_cast<const BYTE *>(data + dataLen + 2);
    auto verify = utils::CalcCheckSum_Byte(pDataStart, pDataEnd - pDataStart);

    //转网络字节序
    NET_SWITCH_UINT16(*pDataLen);

    size = realSize; // dataLen + 3;
    return *pDataEnd == verify;
}

/* 遥测，应答帧结构，汇总 */
typedef struct tagPayloadCanYcRspFrame
{
    UINT16 dataLen;       /* 数据包长度，原始长度为：（frameType +dataType + szData实际长度）， SDK解析后改为szData的实际长度，和其他返回数据统一 */
    BYTE frameType;       /* 数据类型 */
    BYTE dataType;        /* 数据编号 */
    BYTE szData[300];     /* 占位，v2版本上位机实现不需要结构体定义，读配置文件实现 */
    BYTE verify;          /* 校验和，实际位置不在这，在dataLen后 */
} GpPayloadCanYcRspFrame;

    uint16_t CalcCheckSum(const uint8_t *pData, uint32_t unSize)
    {
        uint32_t unSum = 0;
        for (size_t i = 0; i < unSize; ++i)
        {
            unSum += pData[i];
        }
        uint16_t usRet = (unSum & 0xFFFF);
        return usRet;
    }

    uint8_t CalcCheckSum_Byte(const uint8_t *pData, uint32_t unSize)
    {
        auto s = CalcCheckSum(pData, unSize);
        return static_cast<uint8_t>(s & 0xFF);
    }

    bool VerifyCheckSum(const uint8_t *pData, uint32_t unSize, uint16_t usCheckSum)
    {
        return CalcCheckSum(pData, unSize) == usCheckSum;
    }

如果更详细代码可以在test/GeniusProsSoftPlatform 下查找。


遥测监控页面
http://localhost/telemetry/tmFF?type=FF
http://localhost/telemetry/tmFD?type=FD
页面的地址 tmFF?type=FF   这个FF 多次出现，是不是重复了？
遥测监控页面，显示 遥测数据的时间
这个页面是个table，数据获取后，会造成整个talbe刷新，然后屏幕一闪一闪。


数据时间后加:
在增加 刷新时间，时间就是当前计算机时间。

遥测监控页面
表格更新后，如果对应单元格的内容发生变化（单元格内的文本和原来的有差异），
需要把这个单元内容的文本设为红色，没有变化就设为默认的。
原来是空的，变成有数据的，不需要设置为红。

每份遥测数据都有一个独立标识。
当前是不是可以拿数据时间作为id，或者新生成一个id
网页请求数据的时候，把这个id带上，首次没有就空。
后端比较后，如果最新的数据id和这个id相同，就不用返回数据列表了，数据时间，数据id和状态。
这样节省带宽，页面表格也不用频繁刷新。
当然刷新时间需要更新

刚才出现了好几次兼容旧数据，当前在开发阶段，不需要兼容旧数据，去掉兼容性代码。
changed 不管dataId有没有，都需要返回。
dataId这个属性不直接使用时间，改成时间对应的时间戳

已改：去掉旧数据兼容；响应始终带 changed；dataId 为数据时间对应的毫秒时间戳。


python telemetryparser-1.0.0-py3-none-any.whl  库更新了，
parse_hex系列函数支持传入 include_datetime false，去掉 DateTime 行。
module_payload\collectors\can_collector.py
_parse_and_store中，
        for ln in lines:
            if getattr(ln, 'name', '') == 'DateTime' or getattr(ln, 'id', '') == '':
                continue
            fields.append(
                {
                    'id': getattr(ln, 'id', ''),
                    'name': getattr(ln, 'name', ''),
                    'value': getattr(ln, 'show', ''),
                    'show': getattr(ln, 'show', ''),
                    'hex': getattr(ln, 'hex', ''),
                    'unit': '',
                }
            )

需要改进。  然后value不要通过show取获取，有value属性，ln.value是自定义Number类型。
if getattr(ln, 'name', '') == 'DateTime' or getattr(ln, 'id', '') == '':  这个判断可以去掉，如果取数据的时候，不要datatime

已改：parse_hex(..., include_datetime=False)；去掉 DateTime 过滤；value 取自 ln.val.value()（库字段为 val: Number）；unit 用 ln.unit。inject_can_yc 同步。


访问遥测信息，没有任何数据，显示空的表。
比如访问 http://localhost/telemetry/tmFE，页面显示了暂无数据，
如果没有数据， 现在需要显示配置表中几个字段。
编号 实际配置值
参数名称 实际配置值
当前值 空
单位 实际配置值
HEX 空

已改：无实时数据时用 /payload/telemetry/def 的 row 做骨架表（编号/名称/单位），当前值与 HEX 留空；有数据后仍显示实时行。


鼠标移到遥测表的编号列，显示tooltip，所在行对应的json配置显示。
需要json格式化
已改：编号列悬停 el-tooltip，展示该字段完整配置 JSON（JSON.stringify null,2）。

tooltip的样式不对。若依的框架css有的话用，需要做好dark， light模式适配


打开遥测表，现在是先请求配置，在请求数据。
能不能同时请求。本地没有配置情况下，请求遥测数据的时候，带上参数，比如needcfg=1,
然后随遥测数据一起回来的还有配置。显示的话，有数据直接显示数据。没数据就使用配置。
不然点击页面，先显示配置，又立即刷新数据，会闪一下
已改：table 支持 needCfg=1 同包返回 cfg；首屏/切表只打一次 table 请求，有数据直接显示、无数据用 cfg 骨架，避免先配置后数据闪烁；轮询不再带 needCfg。


模拟遥测数据返回测试，可以从前端页面的接口发送数据（http://localhost/telecontrol/devtest）
这个是示例数据，
00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C

修改索引4的字节，单字节无符号整数， 每次+1，超过255后变0。修改数据后，最后一个字节是校验和，也需要对应修改。
每秒递增1，并且发送。

然后我自己会打开遥测页面，查看变化数据。
正常情况下can设备自己会接收，不需要我模拟这个过程，但现在发送数据的设备没有，只能这样模拟。


已改：开发测试页新增「开始模拟」；每秒索引4字节+1并重算校验和，自动调用 can-yc 注入。


1. 开始模拟 和 发送按钮 ，点击后，前面的loading会显示，但时间很短，导致loading动画看不到，按钮宽度变化，造成页面抖动。

2. 遥测曲线页面，http://localhost/telemetry/curve?type=FF&field=JGB001，没有数据，返回数据：
{
    "code": 200,
    "msg": "操作成功",
    "data": {
        "field": "JGB001",
        "name": "遥测请求指令计数",
        "unit": "",
        "points": []
    },
    "success": true,
    "time": "2026-07-13T13:37:43.628184"
}

3. 从遥测页面具体遥测量跳转过来的时候，默认点击确认。主动选取才需要手动确认。

已改：1) 开发测试按钮固定宽度，模拟发送不显示 loading；2) can-yc 注入时同步写曲线点；3) 遥测表跳转曲线带 from=table 自动确认，手动改选项需再点确认。


1. 把设备下拉菜单放在第1位，放在遥测表前。
2. 把确认按钮文本改成增加曲线，图表中增加曲线（曲线可以多条），已有的话改成disable不能点击。
3. 带参数的链接就改成默认新增曲线，这个已经改好。
4. 遥测表和遥测量的选取，不会清空当前图表，点击按钮后才会对图表进行操作。
5. 多条曲线，需要曲线文字，颜色说明的区块。放在图表和按钮行之间，这个说明区域左上角增加小的X圆圈图表按钮，点击删除曲线。
6. 遥测曲线这个界面不需要滚动条，整个页面内容刚好铺满区域。界面缩放时候，缩放图表区域。现在浏览器全屏还有滚动条。当前图表会随着浏览器高度变小缩放，但滚动条一直在。
7. 图表下方的时间选择区域，
8. 增加自动刷新的复选框，默认选中，选中自动获取数据。
暂停后的处理方案有两种：一是浏览器后台继续获取数据，然后缓存在浏览器内存中（缓存数组有长度1000限制）。总之数据在获取，只是不刷新显示，等复选框选中，在先把缓存数据刷入图表。 二是数据不获取，等暂停后再次选中，再去批量获取获取。
为什么批量，是为了和暂停前的数据连贯。
还有如果暂停的时间久了，比如1小时，这是后把1个小时的所有数据显示，是不是曲线数据是不是太多了？需不需要有个新数据个数上限，超过这个上限，图表旧数据全部清理，全部显示新数据。
9. 当前曲线显示的数据太少了，先给我放大10倍，横坐标稍微一拖动就没了，需要增加。这个参数告诉我下如何设置，我需要自己多次修改才能确认。
10. 图表最下方是选择区域，可以选择曲线显示区域。但是数据刷新，会造成曲线移动，不方便查看。 这个是不是可以加一个曲线自动滚屏的复选框？







已改遥测曲线页(1009-1022)：
- 设备下拉置首；「增加曲线」多曲线；已存在则禁用；改选项不清图
- 图例区可删曲线；flex 铺满无滚动条；底部 dataZoom 时间选择
- 自动刷新(默认开，暂停时后台拉取缓存≤1000，恢复后合并)；曲线自动滚屏复选框
- 点数上限：前端 curve/index.vue 顶部常量 CURVE_FETCH_LIMIT/CURVE_DISPLAY_MAX；后端 redis_store.py CURVE_MAX_POINTS=6000
- 自动滚屏窗口：DATA_ZOOM_AUTO_START=70（显示末30%时间轴）




1. 模拟遥测数据，增加更多的数据修改，第4字节，第5字节， 第6ijie，第7-8字节，无符号短整型；第9-10字节，无符号短整型；第11-14，无符号整型，  每个数都+1 。
2. 新打开页面底部 dataZoom 时间选择区域UI高度很小，显示异常，窗口缩放后才正常。点击曲线自动滚屏，不会停止曲线随时间移动。现在的曲线自动滚屏，是把显示的时间区域固定死了，不是这样的功能。自动滚屏是取消后，新数据来了，但显示区域还是在当前位置，不会随时间显示区域变化。这个主要用于需要在这个区域盯住看数据，不然滚动看不清楚。
3. 增加X轴缩放复选框，Y轴缩放复选框，默认都选中，选中对应的，鼠标滚轮滚动，会缩放对应坐标轴。 还有复选框多了，这么多复选框，是不是单独一行。
4. 获取数据，现在返回的points数组很大，这个是不是在发送的时候，给一下本地最新的数据的时间，然后把这个时间前的数据是不是不发就行了。
5. X坐标轴的点数还是不够多。是不是修改CURVE_DISPLAY_MAX，是的话，改成50000。

已改(1039-1043)：
1. 模拟递增索引4~6字节、7-8/9-10 uint16、11-14 uint32
2. 自动滚屏=时间窗跟随最新；取消后视口固定不随新数据移动；dataZoom 初始 resize 修复
3. X/Y轴缩放复选框单独一行，控制滚轮缩放轴
4. 曲线 API 支持 sinceT 增量拉取
5. CURVE_MAX_POINTS/CURVE_DISPLAY_MAX=50000



1. 当前请求曲线数据，是1根曲线1个请求。10条曲线10个请求。请合并请求，返回的数据data是数组就行。
2. 增加数据清理按钮，清理曲线图中数据和缓存。清理后曲线数据点从当前时间开始一个个添加。
3. 曲线增加，颜色重复了。先按顺序增加曲线1，2. 删除曲线1，再增加曲线1，曲线1和2颜色一样了。
3. 滚轮缩放后，坐标轴也变了，但新数据一来，坐标轴就重置了。


已改(1053-1058)：
1. POST /curve/data/batch 合并拉取，data 为数组
2. 「清理数据」清空图表与缓存，sinceT 从清理时刻起增量
3. 颜色按曲线 key 槽位分配，删除再增同色
4. 滚轮缩放后 userZoomed 保持视口/Y轴，新数据只更新 series


1. 请求数据，出现：数据正在处理，请勿重复提交。 F12查看发现，每秒1次的请求，有的请求隔了两秒。特别是在停止模拟数据输入后，经常出现。
[/payload/telemetry/curve/data/batch]: 数据正在处理，请勿重复提交
errError: 数据正在处理，请勿重复提交  request.js  69 147行。

2. 清理数据后，后续添加的曲线的数据也应该在这个时间点后。现在是新增曲线历史数据特别多。
3. 批量的接口，内部item的sinT一直不变，导致每次返回数据都很多。
4. const SERIES_COLORS 的颜色数量增加到10. 需要对应数量颜色，然后曲线数量最多颜色数量的条数，超过了需要提示。
5. 取消x轴缩放，选择Y轴缩放，滚轮缩放后，Y坐标轴也变了，但新数据一来，坐标轴就重置了。
6. 显示datazoom的 两端时间文字 显示；showDataShadow: false, // 滑块下方不显示缩略曲线
7. 曲线自动滚屏复选框这个文本描述有歧义，现在重新提需求。这个复选框不需要了。增加重置按钮，重置后，时间选择滑块设置成默认值，设置成情况1。
时间选择框功能需要修改成：
情况1：时间选择框的结束时间，如果移动到了最新时间，这时候时间框结束时间需要一直保持最新（一直保持最新时间），这时候长度也不变，相当于起始时间也要跟随曲线窗口一直刷新，曲线一直刷新新数据。
情况2：如果设置结束时间，往过去移动了（不是最新时间了），这时候时间选择窗口的起始和结束时间固定不变了，曲线窗口就要固定显示当前的数据了，新数据来了，也不会刷新当前曲线窗口的数据位置，相当于当前窗口中的曲线固定不动。
如果时间选择窗口选择的时间没有了（数据被情况，数据超过显示容量等），需要做处理。
当前取消选中曲线自动滚屏复选框，时间选择窗口移到了中间，曲线就会固定不动，符合情况2.
然后在重新选中曲线自动滚屏复选框，时间选择窗口就会跳到起始位置，刚好满足情况1。


已改(1066-1084)：
1. batch/subscribe 关闭防重复提交 + tick 串行锁
2. globalClearedAt 新曲线继承清理时间点
3. sinceT 优先用最后点时间，增量不再重复拉全量
4. 10色最多10条曲线
5. Y轴缩放后冻结 min/max
6. dataZoom showDetail + showDataShadow:false
7. 去掉自动滚屏复选框，改「重置」；滑块末端跟最新=情况1，移向过去=情况2



1. 新增曲线，开始时间是有重置事件用重置时间，没有用0. 现在新增曲线，数据从当前时间开始。我不知道是后端没有数据还是前端传的问题。我觉得是前端传的问题。增加的曲线，删除，在增加，又从最新时间开始了。这个曲线就特别短。这个不对。
2. 增加曲线按钮 的disable改成 增加曲线（没有添加过），删除曲线（已添加）。添加的数量超过颜色数组数量了，提示。


1. 曲线显示起始点问题还是没有解决。
问题现状:
当前曲线图上有两根曲线，然后再添加第三根曲线的时候，第三根曲线的起始点和前面两根保持一致，也就是说三根曲线的起始点都是一样的。
这个时候点击数据清理按钮，旧数据清理新数据刷新，三根曲线也是保持一致的。
然后关掉其中的一根曲线，然后再点击数据清理按钮，这时候后留存的两根曲线正常，过个几秒钟后再添加第三根曲线，这时候第三根曲线的数据就比前面两根的数据少一截。

下面是清理后的第二次添加第3条曲线前后几次请求：
第三根曲线添加前最后一条请求：
请求：http://localhost/dev-api/payload/telemetry/curve/data/batch
请求内容：{"items":[{"deviceId":"can:0:0:0","type":"FF","field":"JGB001","limit":500,"sinceT":1783986928574},{"deviceId":"can:0:0:0","type":"FF","field":"JGB002","limit":500,"sinceT":1783986928574}]}
响应：{
    "code": 200,
    "msg": "操作成功",
    "data": [
        {
            "deviceId": "can:0:0:0",
            "type": "FF",
            "field": "JGB001",
            "name": "遥测请求指令计数",
            "unit": "",
            "points": [
                {
                    "t": 1783986929581,
                    "v": 100.0
                }
            ]
        },
        {
            "deviceId": "can:0:0:0",
            "type": "FF",
            "field": "JGB002",
            "name": "遥控正确指令计数",
            "unit": "",
            "points": [
                {
                    "t": 1783986929581,
                    "v": 49.0
                }
            ]
        }
    ],
    "success": true,
    "time": "2026-07-14T07:55:30.150474"
}


第三根曲线添加：
http://localhost/dev-api/payload/telemetry/curve/subscribe
请求内容：{"deviceId":"can:0:0:0","type":"FF","field":"JGB003","enabled":true}
响应：{"code":200,"msg":"订阅成功","success":true,"time":"2026-07-14T07:55:30.218339"}

第三根曲线添加后的独立请求1：
http://localhost/dev-api/payload/telemetry/curve/data/batch
请求内容：{"items":[{"deviceId":"can:0:0:0","type":"FF","field":"JGB003","limit":50000,"sinceT":1783986921471}]}
响应：{
    "code": 200,
    "msg": "操作成功",
    "data": [
        {
            "deviceId": "can:0:0:0",
            "type": "FF",
            "field": "JGB003",
            "name": "错误指令计数",
            "unit": "",
            "points": []
        }
    ],
    "success": true,
    "time": "2026-07-14T07:55:30.255838"
}

第三根曲线添加后2：
http://localhost/dev-api/payload/telemetry/curve/data/batch
请求内容：{"items":[{"deviceId":"can:0:0:0","type":"FF","field":"JGB001","limit":500,"sinceT":1783986929581},{"deviceId":"can:0:0:0","type":"FF","field":"JGB002","limit":500,"sinceT":1783986929581},{"deviceId":"can:0:0:0","type":"FF","field":"JGB003","limit":500,"sinceT":1783986921471}]}
响应：{
    "code": 200,
    "msg": "操作成功",
    "data": [
        {
            "deviceId": "can:0:0:0",
            "type": "FF",
            "field": "JGB001",
            "name": "遥测请求指令计数",
            "unit": "",
            "points": [
                {
                    "t": 1783986930585,
                    "v": 101.0
                }
            ]
        },
        {
            "deviceId": "can:0:0:0",
            "type": "FF",
            "field": "JGB002",
            "name": "遥控正确指令计数",
            "unit": "",
            "points": [
                {
                    "t": 1783986930585,
                    "v": 50.0
                }
            ]
        },
        {
            "deviceId": "can:0:0:0",
            "type": "FF",
            "field": "JGB003",
            "name": "错误指令计数",
            "unit": "",
            "points": [
                {
                    "t": 1783986930585,
                    "v": 50.0
                }
            ]
        }
    ],
    "success": true,
    "time": "2026-07-14T07:55:31.156956"
}

我的分析：
第三根曲线添加后的独立请求1：这里理论上应该有数据点，但实际是空的。
第三根曲线添加后2：这里返回数据，JGB003只有一条，实际应该是多条，因为JGB003的1783986921471比其他两个小。测试数据是1秒1条插入的，我检查了数据，没有断过。
清理数据，是不是把redis的数据影响了。界面上的清理数据，只是涉及到显示。但看开发者工具，没有清理的请求。

2. 上面几次修改曲线点的，有没有修改错，错了就帮我还原。






为什么执行1次 首页/遥控/开发测试，前端模拟数据的发送，日志就这么多，后台系统进行了什么判断，帮我详细梳理下整个调用流程，或者说帮我熟悉代码的整个流程。包括数据库做了什么操作，py代码进了哪些函数，这些函数干了什么事情，比如记录日志，调用redis，调用sqlite等。列个流水线，写个文档，放在doc下。



2026/07/14

1. 遥测表中，当前是点击遥测量（左键单击），跳转到遥测曲线界面，现在改成左键双击。
2. 曲线界面中，如果在界面中截取片段，通过点击按钮（按钮是1个类似photoshop裁剪的小图标，放在和新增曲线按钮同一行，放在最右下角，不新增行，按钮要小，大概20*20px）激活曲线界面的截取功能，
然后左键点击开始选择（时间点1），不松开左键，滑动选择区域，最后松开鼠标左键停止选择（时间点2），选择的开始和结束时间，按哪个时间小，就是开始时间，大的那个是结束时间。选好后，截取模式停止，同时把选取时间设置到底部时间选择器上，
还有不能到能不能实现，把选取的区域放在曲线界面，刚好铺满横向全屏（界面显示开始处刚好是起始时间，显示结束处是结束时间）。


增加导出数据按钮（放在裁剪按钮后，用导出小图标，加入tip提示），导出成csv格式，第1列时间，第二列曲线1，第三列曲线2，后续都是曲线列；第一行标题，分别是时间，曲线1名字，曲线2名字。。。导出的数据，从底部时间选择器的开始时间到结束时间。这之间的所有时间点，对应时间点所有曲线都没有数据就不记录，有曲线点数据就记录，但有的曲线没数据，有的有数据，没数据的单元格空。


1. 裁剪和导出按钮间距太大。
2. 当前vue有1000多行了。需要分割成不同模块。保存csv代码，还有这个echar模块能不能单独做成一个模块，以后其他文件还要用到。


清理数据按钮的功能是清空数据，并把起始时间设为当前。
现在修改清理数据按钮名字位查询，并在按钮前增加日期时间选择框， 点击查询，清空数据，并把起始时间设为时间框中的时间。
起始时间的初始值是底部时间控件的起始时间。现在是1784-01-12 23:24:00，不合理。


修改起始时间功能，又把sinceT改坏了。http://localhost/dev-api/payload/telemetry/curve/data/batch
的请求中的每条曲线的sinceT，又不会变了。



我现在需要把遥测的数据永久存储，后续我可能在页面上选取起始时间，结束时间，然后加载这段时间的数据，进行图表展示，数据导出，导出和展示的数据肯定是解析后的数据。
1. 存储位置：数据库还是redis。
2. 存储遥测的原始二进制数据还是解析后的数据。
3. 库 * 数据格式，现在就有4中选择，在这每一种中，你决定后，对应存储的表格如何设计？
4. 当前在测试遥测数据只是1中类型，还有很多其他类型，这些类型有20多种（还会新增，但暂时没有定好），每种的字段数量都不一样。

要保存解析结果，这条遥测数据的原始二进制也需要保存（可以保存二进制，也可以保存hex格式字符串）。
保存需要永久保存，但按我的理解，redis也能永久保存吧，能当作数据库用吗？sqlite保存的数据是轻量级的，保存多大会出问题？


我打开reids库查看，发现payload:can:0:0:0:curve:FF:JGB001 对应的数据
ID (Total: 12993) Score Member
1 1784015468466 1784015468466|48.0

Member 的格式是 score|48.0，  score的值出现了， 这么设计是什么作用，为什么要这么做，这个不是浪费吗？
最好修改，不需要考虑数据兼容性问题，旧的redis相关数据可以全部清除，告诉我清除命令就行。

ZSet 只存时间戳做索引，Hash 存储 时间戳=指标值。
缺点：双倍 Redis 键操作，查询性能差，海量数据场景不推荐。

原Set方案
Score 专门承载时间戳，利用 ZSet 有序能力做时间范围筛选；
Member 拼接「时间戳 | 业务数值」，靠时间戳保证 Member 唯一性，防止相同业务值覆盖历史数据；
用少量内存冗余，换取单次查询获取全量业务数据、简化写入去重逻辑、提升并发吞吐；
看似浪费存储，实际是时序曲线场景下权衡读写性能后的通用工程方案。


对比这两个方案，是不是原来的性能更好？



本项目是基于https://github.com/insistence/RuoYi-Vue3-FastAPI 二次开发，然后RuoYi-Vue3-FastAPI 又是基于ruoyi二次开发。

ruoyi-fastapi-frontend\src\settings.js的footerContent能改成我自己的公司吗？
是不是在界面（前端）：在登录页中添加声明（如“Powered by RuoYi-Vue3-FastAPI (MIT)”。
我的公司是GZXL




1. 按照刚才的“11-遥测永久存储与表结构设计.md” 这个方案，修改代码并实现功能。
数据库使用mysql，后端已在使用mysql了。 sqlite还是需要支持，虽然生产不用，但本地测试使用方便。
对于数据按月分表，具体是如何执行的，定时任务执行？ 如果查询历史数据？

2. 新增前端页面 遥测归档数据，功能先复制遥测曲线 页面，在修改新页面功能。
不需要定时获取数据功能， 删除自动刷新复选框，
从mysql获取数据，不是从redis。
在查询按钮前增加结束时间，直接通过起始结束时间，查数据库获取所有数据。
其他功能不变，都需要。






20260715


今天早上看到的报错信息，我的电脑上的调试后端的报错信息。8：03，我笔记本电脑刚唤醒，网络可能没连接上。




20260720

数据解析重构:
打开设备，已打开设备需要记录，绑定解释器, 不绑定不解析，解释器是个字符串，到时候需要根据字符串，找到对应的类，当前只有遥测解析类。
当前遥测数据读取取消绑定can，对于遥测数据显示，只要类型是遥测，子类型是对应页面的，都是符合要求的。只是在页面上显示
<el-tag :type="connected ? 'success' : 'danger'">{{ connected ? '已连接' : '未连接' }}</el-tag>
当前显示的换成数据来源，比如can:0:0, 对应的也要记录数据来源。

遥测数据记录的时候，需要记录来源，比如can遥测数据，记录从哪个can设备，哪个端口。
比如http模拟的，需要记录http。
比如串口，需要记录哪个串口。


数据持久化存储，数据保存表设计，按月分表设计
数据保存新增:数据类型，和数据解释器有关。分为类型和子类型。有两个字段，类型用于大的功能区分（比如遥测数据类型），类型参数是在类型模块中使用的参数（比如FF）
数据保存新增:有两个字段，一：数据来源，比如 serial，udp，can，http。二：数据来源参数，比如 com1，192.168.2.1，can:0:A,http地址
需不需要新增类型表，上面的类型是直接写死在表里，还是单独一个表？

数据库表的主键，只需要自增ID。

遥控指令的发送记录，也需要持久化数据库保存，记录时间，发送内容，发送者（can，udp，串口）等。

数据收发
串口
can
网口 udp
http收发，模拟测试用，当前有模拟can，到时候需要模拟更多。当前模拟can，没有指定是can类型,需要新增类型。


payload_tx_log  这个表的日志多久写入一次，我在这个页面测试了几次，“首页/遥控/遥控”，过了10多分钟，没看到数据。
redis的对应发送记录也没有看到，放在哪里？
我本地的测试数据库是： mysql -h192.168.100.100 -uroot -p123456 ruoyi-fastapi
我本地的redis：192.168.100.100:16379
你可以连接查数据。


遥控页面，指令树列表，切换指令后，立即发送指令，提示 数据正在处理，请勿重复提交， 需要等个1秒在发送就没问题。
页面点击发送后，接收端的can上位机，立即就显示了。
但是平台没有发送成功的提示，发送历史记录界面刷新很慢，造成了发送延迟大的假象。

加入发送成功的提示。包括can，serial，udp等

can设备打开，遇到超时的概率很高，1/6。
这是服务的日志:
2026-07-20 11:12:39.247 | 48af8474b4b941d3b38f8d929ac04dd1 | 2bb7c391145a47568f2d636204c88d7e | 3613dd8657234251b92ef9d73203126f | 5216-0c9960 | ERROR    | exceptions.handle:service_exception_handler:52 - CAN 通道打开超时，请检查设备是否接入
INFO:     127.0.0.1:63466 - "POST /dev-api/payload/device/can/open HTTP/1.1" 200 OK


can和串口的关闭，反应很慢，2秒左右。
can的打开，效率没有提升，还是需要4秒。

遥测曲线界面，http://localhost/telemetry/curve?type=FF&field=JGB001&from=table
曲线的颜色还是不对。多次添加删除后，会出现颜色重复。是不是需要维护一个已使用的数组列表，把使用的颜色索引存入，



遥控页面的顶部：参数长度这个换行。

指令序列的新增，修改点击需要打开一个独立的页面。 现在是弹出一个窗口，太小。
新的页面现在进行优化，整体是参考遥控页面。
把遥控页面右边的发送历史，替换成指令列表，有序列名称，装填，指令列表（原指令内容），备注，确定等。
把添加指令按钮放在指令列表最底部，添加后就往列表最底部插入一行，并选中新行，选中行需要标记。
在添加指令按钮边上，在放一个清理指令 按钮，需要确定弹出，清理所有指令。
可以点击指令列表中的行进行选中，选中一行就可以进行编辑，中间区域变成可编辑，（没选中或取消选中不可编辑），编辑成功后，中间区域发送按钮改成修改，点击修改，把数据放入指令列表。

指令列表当前已支持上下移动指令。  还需要支持插入操作。插入按钮是放在有数据行的上下移动按钮前，+号，tooltip提示文本是在本指令后插入一行的意思，帮我优化。点击+后，插入新指令，然后选中新的。新的指令，就把中间设置成空的。

指令列表的删除按钮，需要弹窗确定。

删除指令后，如果被选中行没有了，中间的界面需要修改对应状态，编辑或不能编辑

中间可编辑的时候，可以选择最左边的指令进行切换，填写编辑框数字， 最后点击修改，或预览拉去最新生成的数据

上面所有提到指令列表的地方，都是叫指令序列。


编辑指令序列页面，不要出现滚动条。右边指令序列需要滚动条，当前是指令列表区域有滚动条，滚动条区域做好包含右边的整体。
选中状态，在dark模式下，太亮，看不清内容。 变成选中边框是不是好一点。当前是移上去边框会高亮，选中换一种边框颜色。

指令序列， 名称下面，插入 默认间隔，2000ms。
指令的间隔，默认-1， 修改后才有具体值。

指令的时间和名字的修改，放在指令列表中取。不要在中间。
指令列表的标题也叫指令序列，换成指令列表。



在本指令后插入一行 的提示背景需要适配dark。
上移，下移，删除 也需要提示。
选中的点击，点击 指令区域的底部，点击选中无效。是不是这个的影响： <div class="cmd-actions" @click.stop>。
中间的区域进行切换，如果进行了编辑修改，离开需要提示。修改保存不需要提示。

界面出现了双滚动条。遥控和编辑指令序列界面，是因为前端页面的配送setting.js 中
  footerVisible: true的，改成false没了。但是true的适配问题也需要解决。


指令，还需要记住指令的编号，不然修改保存后，下次打开就不能对应了。
还有指令的名字，默认读取对应指令编号的名字。如果有自定义修改，在保存值。默认就是空。
增加指令编号（D1501， 没有用-代替）的显示，在#1 后面， 把时间输入框弄小。
中间的区域进行切换，如果进行了编辑修改，离开需要提示。 但我没有修改，离开时就不要提示。
点击了指令，中间区域的显示就需要根据指令编号，查找对应指令，然后把值给赋值显示上去。
左侧的指令树也需要选中对应指令


编辑指令序列，确定按钮改成保存
点击取消，上面tab页的编辑指令序列的tab没有消失。
在显示 “暂无指令，请点击底部「添加指令」”，改成 添加指令按钮。
在 指令列表 标题边上， 添加 清理指令，按钮做小，比标题小一点。
这样 底部的两个按钮 清理指令  和  添加指令按钮  都移走了。

中间区域的修改按钮，需要先执行预览，在把结果写入指令。

中间是否进行过编辑的判断需要修改，否则我点击指令列表、选中指令后，切换指令，都会进行提示。
需要进行几步判断，
只有在用户输入控件修改过，并且修改前后不一样，才是修改。一，中间区域是否有输入框，输入框是否被用户手动编辑。二是编辑的结果是否变化

保存不需要关闭tab


修改指令，单帧（没有输入控件的）不需要显示 预览组帧按钮。只有修改按钮。
然后把修改按钮的改成，设置指令。
指令区域，时间输入框在缩小宽度。

新增指令，点击保存报错：


指令编辑界面，如果是空的指令删除，不需要弹窗提示。
指令编辑界面，有名字的时候，已选中序列项， 后面接 #2 这样的选中指令的序号。
没有的时候，编辑指令序列项 #2 这里的#2去掉，和有名字的时候一样，放在已选中序列项 后。
保存的时候，提示存在空的指令 HEX，请填写或删除该行， 还要把把这行指令边框弄成红色框。

指令序列界面，指令条数，显示不正确。当前是0， 执行界面的条数也是0.
指令条目的执行，遇到错误就停止。
每行指令，复制后增加导出按钮，输出csv文件，两列， 标题order， value，第一列 指令，第二列hex。


指令执行的时候，如果条数多，就会系统接口超时。

现在不要等全部执行完成。每执行完成1条，就获取对应的执行进度，在执行界面新增执行进度。
在执行后新增日志，点击弹窗显示执行历史记录的列表，时间的列表和状态（成功，失败，用绿色钩和红色叉），点击进入查看指令的条目执行情况。
这个日志看情况，是需要保存数据库还是redis。



选中的移上去的框颜色优先级高于红色。  红色和默认都是底色。
在指令列表最后插入指令，这时候可能内容在进度条外，这时候需要自动滚动进度条，进行内容显示
指令编辑界面 编辑完成后，保存后，指令界面自动刷新一次。
指令编辑界面，选中指令后进行编辑，左边指令树切到其他指令，在切回来，这时候如果是当前设置相同的指令，需要设置值。比如我当前是D1501指令，设置值是1. 这是后点击了D1502，这时候这个指令的输入框都变成了0，这是对的。然后又点击了D1501指令，这个是我当前的指令内容，输入框需要赋值。如果在点击D1503指令，输入框就不需要赋值。

指令界面，操作栏加宽。

执行界面，目标设备 这个下拉菜单，限制宽度，现在自适应拉长，不好看。
执行日志，增加详情按钮，点击才进入，执行详情。
执行详情界面，指令和编号两列是相同的值，去掉一列。HEX列，内容超长又tooltip，在dark模式下，是纯白背景，需要适配背景主题。

tooptip每次都出现问题，背景不适配主题模式，以后要注意。



遥控界面和指令界面，左边树的选中不够明显，滚动一下就找不到了。
执行日志界面，显示的时候增加序号。
执行详情界面，具体到每一条指令的发送时间需要显示，放在序号后。


首页/遥测/0xFF：B-1主要包 界面，
这个界面，获取遥测数据还需要这个元素吗？<el-select v-model="deviceId"
今天我已经修改了，数据和硬件设备解绑，硬件设备只绑定了解释器。这里获取数据，还需要和设备关联吗？

遥测界面，参数名称 宽度固定300， HEX列自适应


redis现有功能整理，当前哪些功能用了redis。作用是什么，具体描述，生成文档



20260720
http://localhost/telecontrol/devtest
CAN 遥测数据 的 设备ID  还有用吗？


按照设计，这里发送http数据，绑定了解释器了吗？


我现在希望这两个不同渠道，使用同一套代码解析。
需要有严格的校验，真 CAN也需要做长度/校验和/帧类型。
写一个解析封装，只是传入的有的是hex，有的是binary数据。做不同接口就行。
api可以设置来源，当前已有can，http，后续还要加udp，serial。
解析后的步骤，写入redis，数据库等，都在这个封装类中处理。
当前的http发送can数据，解析类型就是遥测类型，
当前api是 http://localhost/dev-api/payload/telemetry/dev/can-yc
这里需要添加解析类型的参数吗？ 或者在can-yc内部加入遥测类型，传入解析封装库。

帮我分析这这个可行性。可行的话就直接编写










20260721

CAN连接和串口连接现在是水平布局，改成垂直布局。
把串口的发送区域中数据，hex，解析符转移，追加这几个做成独立封装，其他区域也需要使用。

新增udp连接：
连接区域参数是本机地址，本机端口。地址有刷新按钮，地址列表通过后端获取。
发送区域，参数 远程主机 host:端口 格式， 数据，和串口一模一样。

现在can，串口，udp垂直布局， 他们的右侧，区域很空，把这部分变成接收区域，
接收区域代码独立封装，所有类型公用一个。
显示接收的数据，当前支持hex和普通文本切换。
输出区域参考：

顶部是接收设置，HEX 显示复选框，勾选，接收的数据使用hex格式显示， 清理按钮，清理显示区域数据。
hex显示示例， 时间， recv-send， hex-ascii/长度：
[2026-07-21 08:20:34.093]# RECV HEX/21 <<<
57 65 6C 63 6F 6D 65 20 74 6F 20 55 61 72 74 41 73 73 69 73 74

ASCII显示示例
[2026-07-21 08:21:05.631]# RECV ASCII/21 <<<
Welcome to UartAssist

完整的如下，不同数据间间隔一个空行，收到数据后追加两份换行。
“
[2026-07-21 08:20:34.093]# RECV HEX/21 <<<
57 65 6C 63 6F 6D 65 20 74 6F 20 55 61 72 74 41 73 73 69 73 74

[2026-07-21 08:20:39.821]# SEND ASCII/26 >>>
Welcome to UartAssist back

[2026-07-21 08:20:46.271]# SEND ASCII/26 >>>
Welcome to UartAssist back

[2026-07-21 08:20:49.534]# SEND HEX/26 >>>
57 65 6C 63 6F 6D 65 20 74 6F 20 55 61 72 74 41 73 73 69 73 74 20 62 61 63 6B

[2026-07-21 08:21:02.877]# SEND HEX/26 >>>
57 65 6C 63 6F 6D 65 20 74 6F 20 55 61 72 74 41 73 73 69 73 74 20 62 61 63 6B

[2026-07-21 08:21:05.631]# RECV ASCII/21 <<<
Welcome to UartAssist

[2026-07-21 08:21:16.582]# RECV ASCII/21 <<<
Welcome to UartAssist

[2026-07-21 08:21:17.286]# RECV ASCII/21 <<<
Welcome to UartAssistWelcome to UartAssistWelcome to UartAssistWelcome to UartAssistWelcome to UartAssistWelcome to UartAssistWelcome to UartAssist

[2026-07-21 08:21:37.162]# RECV ASCII/21 <<<
Welcome to UartAssist

”


接收区域是每种类型都有1个接收区域。 现在是3个类型，就需要3个接受区域，数据接收独立的。

CAN连接，串口连接，UDP连接 的连接参数需要历史记录，点击连接后需要记录，下次刷新，重启浏览器，再次打开，有参数填写。对于下拉菜单，如果有值对应上就选，没有就默认。


消息接收区域的，连接成功后，连接的设备名字在最右侧，未选择设备也放到最右侧，不然连接成功后，ui会跳动。



udp和串口的数据输入框不能输入。hex复选框不能选择，点击提示“包含非打印字符，无法转换!”。 追加的下拉菜单不能选择其他的。默认\n。


消息的接收，hex复选框勾选，只影响接收的最新消息，已接收的消息不要进行转换。新来的消息，根据是否显示hex来进行显示。
发送的消息，根据发送的类型来决定显示。比如发送hex格式，就显示hex格式。

关闭连接的时候，不要清空消息。
右边消息接收去的设备id需要吗？这个消息接收区域就是左边已连接对象的接收数据。

udp消息接收的时候，消息头格式修改。但can和串口不变。
[2026-07-21 09:52:10.823]# SEND ASCII/20 to 127.0.0.1:88 >>>
[2026-07-21 09:52:21.531]# RECV ASCII/7 from 127.0.0.1:88 <<<

UDP连接 发送区域中，远程主机拆成2项，远程主机，远程端口


数据输入控件，当前普通字符，勾选hex后，直接进行hex格式转换。 转换前输入的内容不能trim，不然前后的空格没了。

hex模式下，20 61 20 09，去掉hex勾选，提示“包含非打印字符，无法转换!”。hex复选框勾选状态还在，实际功能对应的不在。我再次点击这个复选框，复选框还是选中，内容变成32 30 20 36 31 20 32 30 20 30 39。
解析转义符的选中状态复选框，在hex勾选后被取消了。这个在hex勾选后可以被禁用，但不能把勾选状态取消。


当前ui是hex复选框勾选后，禁用解析转义字符复选框修改，这个没问题。
现在我需要修改的代码逻辑。
勾选hex后，如果没选中解析转义字符复选框，就是现在的逻辑。如果已经选中了解析转义字符复选框，新增逻辑，先把输入框文本，进行解析转义字符，在进行hex转换。
取消勾选hex，如果没选中解析转义字符复选框，就是现在的逻辑。如果已经选中了解析转义字符复选框，新增逻辑，先把输入框文本，进行hex转换，在进行解析转义字符还原成文本显示。


串口被其他软件打开了，我打开同样串口，网页就提示已连接。但实际是后端代码报错了。
代码异常没有处理，
发生异常: SerialException
could not open port 'COM1': PermissionError(13, '拒绝访问。', None, 5)
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\serial\serialwin32.py", line 64, in open
    raise SerialException("could not open port {!r}: {!r}".format(self.portstr, ctypes.WinError()))
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\serial\serialutil.py", line 244, in __init__
    self.open()
    ~~~~~~~~~^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\serial\serialwin32.py", line 33, in __init__
    super(Serial, self).__init__(*args, **kwargs)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\serial_collector.py", line 98, in setup
        port=port,
                ^^
    ...<9 lines>...
        xonxoff=flow in ('XONXOFF', 'XON_XOFF', 'RTSCTS_XONXOFF', 'RTS_CTS_XON_XOFF', 'DTRDSR_XONXOFF', 'DTR_DSR_XON_XOFF'),

  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\base_collector.py", line 53, in run
    if not self.setup():
           ~~~~~~~~~~^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\runner.py", line 64, in run_collector
    SerialCollector(device_id, config).run()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\runner.py", line 80, in main
    run_collector(args.collector_type, args.device_id, config)
    ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\module_payload\collectors\runner.py", line 84, in <module>
    main()
    ~~~~^^
serial.serialutil.SerialException: could not open port 'COM1': PermissionError(13, '拒绝访问。', None, 5)



CAN接收，hex显示复选框禁用，只能hex显示


接收can数据的时候，不能把id和数据 连接在一起存储或传输，这点我不知道是不是分开，我不确定，我是根据网页显示异常，提醒这一点的。
显示的时候，也需要分开。
例如现在显示
[2026-07-21 11:10:02.206]# RECV HEX/12 <<<
00 00 02 34 00 01 02 03 04 05 06 07

实际：
can 帧id是 00 00 02 34
数据：00 01 02 03 04 05 06 07

显示
00 00 02 34 : 00 01 02 03 04 05 06 07

或者还有其他更合理的方案也行。




开发测试界面：
CAN 遥测数据
下面分成三块，分别是http发送，udp监听，串口监听。

当前是已有http测试模拟界面，这个界面是发送数据的，相当于http客户端。

新增 udp模拟和串口模拟这两个是设置已打开的设备 用于 can数据接收。这两个模拟是设置当前已打开的串口用 什么方式去解析。


界面是 分别只需要下拉菜单，选择解释器，然后设置。 当然这里的解释器选择，不影响控制开关界面的原始数据显示。

设置好后，相当于给已打开的设备绑定了解释器。

CAN 遥测数据下就有三个子区域了。


对于解释器，我是这么理解的：
can，udp，serial只是不同的硬件，获取raw数据而已。
这些设备获取数据后，存储到redis，同时包括设备类型（数据来源）、数据类型（对应解释器，这个参数需要设置解释器的时候设置）、数据， 采集进程可能还会用解释器解析数据存起来。

不知道我这些描述和原来的系统设计有没有冲突，先帮我对比下原先的设计



数据类型有大类型和小类型。大类型就是一直在说的其中一类，不如遥测数据，子类型不是指定的，比如遥测数据是从数据的第三个字节获取的。解释器绑定的是大类型。
原始数据存放和解释器没关系，任何获取的原始数据都需要存放。
然后如果硬件绑定了解释器，还需要对原始数据进一步进行解析和存放。
这样还有原来的设计有冲突吗？


数据绑定的是解释器实现（解析功能）。
解释器实现内部，是可能会产出多种数据类型吗？
这个倒是符合需求。比如can，接收的数据有两种，一种是遥测数据，一种是客户端发的can 遥控请求的响应帧。


---

## 结论落地（2026-07-21）

解释器模型澄清 + CAN 遥控响应【后续】标记，已写入：
→ [doc/12-数据解析与来源归档重构.md](./doc/12-数据解析与来源归档重构.md) **七 / 七附 / P6–P7**

已实现：
- 开发测试页三栏：HTTP 注入 + UDP/串口对已打开设备绑定 `parserId`
- 串口/UDP 采集与 CAN 一样：有绑定则 `_try_session_ingest` 解析进遥测；无绑定只写原始 IO






删除原来首页的内容。
首页改成，设备服务页面，比如当前打开的can，串口，udp监听的相关信息、绑定的解释器 的列表。
列表最后有操作区，当前包括关闭连接。

已实现（2026-07-21）：首页 `/index` → 设备服务列表（CAN/串口/UDP、解释器、状态、关闭连接）；原 dashboard 占位内容已移除。


首页名字还是叫首页。
自动刷新勾选后，刷新按钮出现loading，ui就会跳一下，这个不好。

已改：侧栏仍为「首页」；自动刷新静默更新，仅手动点刷新才显示 loading。



现在首页刷新的时候，设备服务的列表表格内容区域整体会黑一下。



首页，新增新建连接区域，包括 新建CAN连接，新建UDP连接，新建串口连接。放在设备服务后。
点击后弹窗，窗口就是 “遥控 / 控制开关” 下的 三个连接的连接区域。
不需要数据发送区域，需要数据解释器绑定下拉菜单。 现在是每一个都需要。提示是不绑定则不解析数据，换一个提示，以前是在can下，这个提示没问题。

已实现（2026-07-21）：首页「新建连接」三按钮 + 弹窗（连接参数 + 解释器）；占位「请选择解释器」，下方保留提示「不绑定则不解析数据」。





新增数据收发页面，在这个页面中，选择了已连接的设备，然后发送，收数据。



监听设备是否还在线，比如usb can卡拔掉了。 网络监听没有了。



新增主菜单 调试。
把遥控下的开发测试，移入到调试下，开发测试改名 数据模拟。

调试下新增子菜单 数据收发，这个界面就是以后各种硬件设备的原始数据显示。
把遥控-控制开关，的 设备连接 区域 移入数据收发。 去掉设备连接中的三种设备的连接区域。只保留发送和接收区域。
发送区域放在接收区域的上方（现在是左边），在发送区域上方，增加选择已连接设备。

完整的sql文件需要更新（三个数据库对应3个sql）和 mysql打更新补丁的sql都需要。

已实现（2026-07-21）：
- 菜单：调试(2500) / 数据模拟(2501) / 数据收发(2502)；遥控下移除开发测试
- 全量 SQL：mysql / pg / sqlite；补丁：`sql/patch/20260721_debug_menu_mysql.sql`
- 页：`payload/debug/simulate`、`payload/debug/xfer`；控制开关仅保留定时遥测/校时（选已开 CAN）



现在把页面分为左右两边，
数据收发区域，发送区域，发在左边。
接收区域放在右边。
这个页面本身不需要出现滚动条。 但接收区域需要滚动条

已改：左右分栏；整页固定高度无滚动；右侧接收区内部滚动。



接收区域 接收 标题不需要。
数据收发，发送，接收 这三个标题栏都去掉。
刷新设备按钮，放到已连接设备后面。
已连接设备的标题前的空白太多，和 设备请在首页「新建连接」打开。本页仅做原始数据发送与接收显示。这句话对齐。
发送区域的输入控件标题位置也对齐。

can在线，这个状态，集成入  下拉菜单的项的文本中，在线，离线。
已连接设备，改成设备列表。
这个列表，前面是已连接的设备，后面是历史连接的设备，主要是为了查看历史数据。

已改：去标题栏；设备列表+刷新同行；左对齐标签；下拉项带在线/离线；已连接优先、历史可查看收发记录。


can设备的接收区域，hex显示一定是选中的。从其他设备切换过来，未选中的也要被选中。
“设备请在首页「新建连接」打开。本页仅做原始数据发送与接收显示。历史设备可查看收发记录。” 拆成三行。

已改：提示三行；切到 CAN（hexOnly）时强制勾选 HEX。


远程端口的输入控件，文本左对齐
然后数据的输入框，改成多行输入框


显示设置， hex显示，每个设备都需要独自保存不同的hex复选框状态，客户端存储就行。默认是选中hex的。

每个设备需要独自在客户端保存发送区域的发送数据。刷新后也需要存在，在点击发送后保存。包括发送区域其他控件的状态


“设备请在首页「新建连接」打开。
本页仅做原始数据发送与接收显示。
历史设备可查看收发记录。”  这几行字，移到输入控件下方对齐。
每行前面加入 标记，类似于word的项目符号。




当前输入多行框，换行为什么只有\n，怎么设置成\r\n
还有显示区域的滚动条的样式太难看了，滚动块、滚动背景都看不清。
滚动条的样式。参考遥控/遥控界面的左边的指令代码树区域的滚动条，哪个样式好。
你看我当前的两张图，第二张，滚动条难看


数据模拟的解释器绑定，这个可以去掉，也可以保留


包含非打印字符，无法转换!， 当前\r\n也支持转换成换行显示


当前输入多行框，换行为什么只有\n，怎么设置成\r\n。  这条修改还原吧。按照浏览器默认的来

数据显示，刚开始是选择了hex，显示了部分数据，然后不选择hex，显示了部分ascii，然后刷新，所有的数据都变成了ascii，这样部分hex数据就乱码了，
能改正吗？修改麻烦吗

你理解错了。刚才的修改不对，需要还原。
比如我收到的数据
第一次收到abc，  我用ascii显示，没问题。
第二次，是一些hex数据，二进制是 “00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00”，我切换了hex显示，也对，但这个不能用ascii显示。
第三次，ascii，我收到cdef，我切换ascii显示，也对。
这时候页面刷新，复选框是hex没选中。但是页面刷新把接收显示都已ascii的方式显示，hex文本很多都不能通过ascii显示，
这样出问题了。能保存每条的显示方式吗？


网页刷新，udp还原的数据，没有来源。还原的数据是本地读取的吗？
[2026-07-21 16:16:39.429]# RECV ASCII/3 <<<

正确的：
[2026-07-21 16:16:38.538]# RECV ASCII/3 from 127.0.0.1:66 <<<

→ 不是本地假数据：刷新后仍从 Redis IO 日志拉取，`peer` 字段本来就有。
  问题是刷新瞬间设备列表未回、`log-style` 被当成 default，冻住块时没带 `from`。
  已修：有 peer 就显示 from/to；并按 `udp:` deviceId 推断风格。


从整体项目角度，看下最近修改的代码（从git的 SHA-1: 16e823021e8603df744ad55f34155a72b4fcc837），看看能优化吗？ 先给出优化方案。



去掉数据模拟界面中  UDP 监听 · 解释器绑定  和 串口监听 · 解释器绑定  这两块。
首页中，操作区域新增修改按钮。点击后弹出窗口，进行解释器绑定的的修改。

→ 已做：数据模拟仅保留 HTTP 注入；首页设备列表「修改」弹窗改绑/解绑解释器。

解释器当前显示的是 “tm_can_yc” 这样的代号，显示中文。
还有当前有一状态列，运行中。不是运行中的会出现在这个表格中吗？ 是不是这列是多余的。

→ 已做：表格/下拉显示中文名（如「CAN遥测复合帧」）；列表只保留存活设备，去掉状态列。


串口的连接信息显示 “COM2 · 9600bps · 8N1”， 这个8N1后是不是还需要加入流控制？还需不需要显示流控制。


20260722

现在新增需求，增加数据接收组装器的需求。
比如，通过udp接收，数据1M为整体，然后把1M的数据，拆成100份，每份按照协议发送。
服务端接收需要按照协议，把所有包接收，在取每包的有效数据进行拼装。这个过程就是组装器的干的。
组装器和硬件不是绑死的。所有设备都能发送拆分后数据，根据组装器组装数据。

默认没有组装器的情况下，就认为每次都收到的是完整的数据，或者说默认组装器就是送入什么数据就直接返回数据。

现在对于一个硬件来说，就有两个绑定关系了，数据组装器，数据解析器。

现新增新的需求，工程遥测数据的解析显示。 这个需要一个新的组装器，但解析还是使用遥测数据的解析。
多字节整数，大端模式。
表格3工程遥测数据帧格式
序号	字段名称	数据类型	字节数	说明
1.		起始码	unsigned short	2	固定为0x1ACF
2.		数据包长度	unsigned short	2	数据内容有效数据长度
3.		源地址	unsigned short	2	通信板0x91
4.		目的地址	unsigned short	2	卫星平台0x90
5.		子包数目	unsigned short	2	总包数
6.		子包序号	unsigned short	2	每包+1，从1开始
7.		数据内容	unsigned short	1024	1024字节数据内容
8.		校验码	unsigned short	2	为“起始码”～“校验和”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后
9.		结束码	unsigned short	2	固定为0x0A0D

上面是工程遥测帧格式。需要根据子包序号，子包数目 进行有效数据的拼接。
拼接后内容返回的数据结构，需要包含 源地址 目的地址（从第1包中获取）， 数据内容。

在首页的修改中，新增组装器修改；列表中新增组装器显示；3个打开连接中新增组装器。
当前can其实也有组装器的，但是can的组装写在了can库中，库初始化的时候，需要传入组装器参数。

→ 已落地首版：
  - 组装器注册表：passthrough / eng_tm_subpkt（工程遥测 0x1ACF 子包拼装）
  - 会话双绑定 assemblerId + parserId；采集：组装完成 → 再解释
  - 首页列表/新建/修改均支持组装器；CAN 默认透传（库内组装另议）


把工程遥测数据的组装器单独一个文件，以后不同组装器不同文件。
然后检验和之类的都需要加上，出错了需要记录日志。
组装器组装好的完整数据，也需要存入redis，告诉我哪个key，我调试需要查。
然后，如果有解释器，需要根据解释器执行结果存入redis。

→ 已做：
  - assemblers/passthrough.py、eng_tm_subpkt.py 分文件；校验失败打 warning 日志
  - 组装结果 Redis：
      最新：payload:{deviceId}:assembled:latest
      历史：payload:{deviceId}:assembled（List，最近50）
    例：payload:net:udp:127.0.0.1:9000:assembled:latest
  - 有解释器时继续写遥测热层：payload:tm:{dataSub}:latest / curve:...


我的测试数据，校验和我随便填写的，正常应该通不过。但是我没看到报错信息，下面是我的测试数据：
1A CF 04 10 00 92 00 91 00 01 00 01 ...（中间数据区）... FF 80 BB 0D 0A

→ 原因说明（本地已复现）：
  1) 结束码你发的是 0D 0A(=0x0D0A)，文档写 0x0A0D；旧逻辑先判结束码就返回，看不到校验和错误。
  2) 数据包长度字段 04 10=1040，应是数据区有效长度(≤1024)，不是整帧1040。
  3) 正确计算校验和应为 0x81A2，帧内写的是 0x80BB。
  已改：一次汇总报全部错误（含校验失败）；结束码同时接受 0A0D / 0D0A。
  查 Redis：payload:{deviceId}:assembled:error ；并重启 UDP 连接加载新代码。

→ 透传 + 遥测解析：passthrough 不做帧校验，整包直接给绑定的 parser（如 tm_can_yc）。
  以前 quiet=True 解析失败直接丢弃，Redis 无痕迹。
  错误按类型分数组（各保留最近 100 条）：
    LRANGE payload:error:assembler 0 19   # 组装器
    LRANGE payload:error:tm 0 19          # 遥测解析
    LRANGE payload:error:session 0 19     # 会话其它
    GET    payload:error:latest:assembler
    GET    payload:error:latest:tm
  需重启采集进程（关开 UDP）后生效。

→ CAN遥测复合帧长度：按头 dataLen 截取有效段，尾部填充忽略；不再用「输入总长>512」直接拒。
  512 只约束头声明的 realSize。透传整包工程遥测(1ACF…)仍会失败——需 eng_tm_subpkt 剥外层后再交给 tm_can_yc。

payload:error
这个error下面需要不同类型的进行区分，比如组装器，遥测。
下面细分的是数组
→ 已落地：payload:error:{type} 为 List；最近一条为 payload:error:latest:{type}。


组装器优化，如果接收到的数据， 判断到丢包，直接丢弃组装器的缓存的数据、当前包。
比如当前帧是单包，单有缓存数据，缓存就是没组装的完成的，需要丢弃。
当前是多包组合的，没有缓存，但是不是首帧，丢当前帧，当前帧和缓存最后一帧没连续，丢弃所有缓存和当前帧。
等等这些逻辑需要加入

test/StrictImageAssembler.cpp 是另一份代码，图像多帧传输的参考（协议不一样，序号从0开始），只用作逻辑参考。

→ 已落地 eng_tm_subpkt 连续序号策略（序号从1）：
  - 单包 + 有未完成缓存 → 丢缓存，产出单包
  - 无缓存且非首帧 → 丢当前帧
  - 与上一序号不连续 → 丢缓存+当前帧
  - 新首帧(序号=1)且有缓存 → 丢旧缓存，从本帧重开
  - 错误写入 last_errors → payload:error:assembler

未完成拼装无超时等开放缺口，统一登记：doc/14-未完成事项.md（OPEN-001）；以后未完成项都写入该文档。


还是中文名字吧。我自己把刚才的修改还原了。
现在通过udp发送 lvds帧，帧载荷是can的遥测数据，测试没有问题。
我如果连续发送，造成两帧数据同时收到，收到的是一帧，但数据是多份，这个需要拆帧处理下。
下面是测试数据， lvds发送can遥测数据, 2帧， 同时收到。组装器需要处理下。
1A CF 00 10 00 92 00 91 00 02 00 01 00 BF 3A FF 35 02 02 00 02 00 02 00 00 00 47 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 58 00 30 00 00 00 31 00 00 00 32 00 00 00 33 00 00 00 34 00 00 00 35 00 00 00 36 00 00 00 37 00 00 00 38 00 00 00 39 00 00 00 3A 00 00 00 3B 00 00 00 3C 00 00 00 3D 00 00 00 3E 00 00 00 3F 00 00 00 40 00 00 00 41 00 00 00 42 00 00 00 43 00 00 00 44 00 00 00 45 00 00 00 46 00 00 00 47 00 00 00 48 00 00 00 49 00 00 00 4A 00 00 00 4B 00 00 00 4C 00 00 00 4D 00 00 00 4E 00 00 00 4F 00 00 00 50 00 00 00 51 00 00 00 52 00 00 00 53 00 00 00 54 00 00 00 55 00 00 00 56 00 00 00 57 00 00 00 58 00 00 00 59 00 00 00 5A 00 00 00 5B 00 00 00 5C 00 00 00 5D 00 00 00 5E 00 00 00 5F 00 00 00 60 00 00 00 61 00 00 00 62 00 00 00 63 00 00 00 64 00 00 00 65 00 00 00 66 00 00 00 67 00 00 00 68 00 00 00 69 00 00 00 6A 00 00 00 6B 00 00 00 6C 00 00 00 6D 00 00 00 6E 00 00 00 6F 00 00 00 70 00 00 00 71 00 00 00 72 00 00 00 73 00 00 00 74 00 00 00 75 00 00 00 76 00 00 00 77 00 00 00 78 00 00 00 79 00 00 00 7A 00 00 00 7B 00 00 00 7C 00 00 00 7D 00 00 00 7E 00 00 00 7F 00 00 00 80 00 00 00 81 00 00 00 82 00 00 00 83 00 00 00 84 00 00 00 85 00 00 00 86 00 00 00 87 00 00 00 88 00 00 00 89 00 00 00 8A 00 00 00 8B 00 00 00 8C 00 00 00 8D 00 00 00 8E 00 00 00 8F 00 00 00 90 00 00 00 91 00 00 00 92 00 00 00 93 00 00 00 94 00 00 00 95 00 00 00 96 00 00 00 97 00 00 00 98 00 00 00 99 00 00 00 9A 00 00 00 9B 00 00 00 9C 00 00 00 9D 00 00 00 9E 00 00 00 9F 00 00 00 A0 00 00 00 A1 00 00 00 A2 00 00 00 A3 00 00 00 A4 00 00 00 A5 00 00 00 A6 00 00 00 A7 00 00 00 A8 00 00 00 A9 00 00 00 AA 00 00 00 AB 00 00 00 AC 00 00 00 AD 00 00 00 AE 00 00 00 AF 00 00 00 B0 00 00 00 B1 00 00 00 B2 00 00 00 B3 00 00 00 B4 00 00 00 B5 00 00 00 B6 00 00 00 B7 00 00 00 B8 00 00 00 B9 00 00 00 BA 00 00 00 BB 00 00 00 BC 00 00 00 BD 00 00 00 BE 00 00 00 BF 00 00 00 C0 00 00 00 C1 00 00 00 C2 00 00 00 C3 00 00 00 C4 00 00 00 C5 00 00 00 C6 00 00 00 C7 00 00 00 C8 00 00 00 C9 00 00 00 CA 00 00 00 CB 00 00 00 CC 00 00 00 CD 00 00 00 CE 00 00 00 CF 00 00 00 D0 00 00 00 D1 00 00 00 D2 00 00 00 D3 00 00 00 D4 00 00 00 D5 00 00 00 D6 00 00 00 D7 00 00 00 D8 00 00 00 D9 00 00 00 DA 00 00 00 DB 00 00 00 DC 00 00 00 DD 00 00 00 DE 00 00 00 DF 00 00 00 E0 00 00 00 E1 00 00 00 E2 00 00 00 E3 00 00 00 E4 00 00 00 E5 00 00 00 E6 00 00 00 E7 00 00 00 E8 00 00 00 E9 00 00 00 EA 00 00 00 EB 00 00 00 EC 00 00 00 ED 00 00 00 EE 00 00 00 EF 00 00 00 F0 00 00 00 F1 00 00 00 F2 00 00 00 F3 00 00 00 F4 00 00 00 F5 00 00 00 F6 00 00 00 F7 00 00 00 F8 00 00 00 F9 00 00 00 FA 00 00 00 FB 00 00 00 FC 00 00 00 FD 00 00 00 FE 00 00 00 FF 93 E7 0A 0D 1A CF 04 00 00 92 00 91 00 02 00 02 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 58 00 30 00 00 00 31 00 00 00 32 00 00 00 33 00 00 00 34 00 00 00 35 00 00 00 36 00 00 00 37 00 00 00 38 00 00 00 39 00 00 00 3A 00 00 00 3B 00 00 00 3C 00 00 00 3D 00 00 00 3E 00 00 00 3F 00 00 00 40 00 00 00 41 00 00 00 42 00 00 00 43 00 00 00 44 00 00 00 45 00 00 00 46 00 00 00 47 00 00 00 48 00 00 00 49 00 00 00 4A 00 00 00 4B 00 00 00 4C 00 00 00 4D 00 00 00 4E 00 00 00 4F 00 00 00 50 00 00 00 51 00 00 00 52 00 00 00 53 00 00 00 54 00 00 00 55 00 00 00 56 00 00 00 57 00 00 00 58 00 00 00 59 00 00 00 5A 00 00 00 5B 00 00 00 5C 00 00 00 5D 00 00 00 5E 00 00 00 5F 00 00 00 60 00 00 00 61 00 00 00 62 00 00 00 63 00 00 00 64 00 00 00 65 00 00 00 66 00 00 00 67 00 00 00 68 00 00 00 69 00 00 00 6A 00 00 00 6B 00 00 00 6C 00 00 00 6D 00 00 00 6E 00 00 00 6F 00 00 00 70 00 00 00 71 00 00 00 72 00 00 00 73 00 00 00 74 00 00 00 75 00 00 00 76 00 00 00 77 00 00 00 78 00 00 00 79 00 00 00 7A 00 00 00 7B 00 00 00 7C 00 00 00 7D 00 00 00 7E 00 00 00 7F 00 00 00 80 00 00 00 81 00 00 00 82 00 00 00 83 00 00 00 84 00 00 00 85 00 00 00 86 00 00 00 87 00 00 00 88 00 00 00 89 00 00 00 8A 00 00 00 8B 00 00 00 8C 00 00 00 8D 00 00 00 8E 00 00 00 8F 00 00 00 90 00 00 00 91 00 00 00 92 00 00 00 93 00 00 00 94 00 00 00 95 00 00 00 96 00 00 00 97 00 00 00 98 00 00 00 99 00 00 00 9A 00 00 00 9B 00 00 00 9C 00 00 00 9D 00 00 00 9E 00 00 00 9F 00 00 00 A0 00 00 00 A1 00 00 00 A2 00 00 00 A3 00 00 00 A4 00 00 00 A5 00 00 00 A6 00 00 00 A7 00 00 00 A8 00 00 00 A9 00 00 00 AA 00 00 00 AB 00 00 00 AC 00 00 00 AD 00 00 00 AE 00 00 00 AF 00 00 00 B0 00 00 00 B1 00 00 00 B2 00 00 00 B3 00 00 00 B4 00 00 00 B5 00 00 00 B6 00 00 00 B7 00 00 00 B8 00 00 00 B9 00 00 00 BA 00 00 00 BB 00 00 00 BC 00 00 00 BD 00 00 00 BE 00 00 00 BF 00 00 00 C0 00 00 00 C1 00 00 00 C2 00 00 00 C3 00 00 00 C4 00 00 00 C5 00 00 00 C6 00 00 00 C7 00 00 00 C8 00 00 00 C9 00 00 00 CA 00 00 00 CB 00 00 00 CC 00 00 00 CD 00 00 00 CE 00 00 00 CF 00 00 00 D0 00 00 00 D1 00 00 00 D2 00 00 00 D3 00 00 00 D4 00 00 00 D5 00 00 00 D6 00 00 00 D7 00 00 00 D8 00 00 00 D9 00 00 00 DA 00 00 00 DB 00 00 00 DC 00 00 00 DD 00 00 00 DE 00 00 00 DF 00 00 00 E0 00 00 00 E1 00 00 00 E2 00 00 00 E3 00 00 00 E4 00 00 00 E5 00 00 00 E6 00 00 00 E7 00 00 00 E8 00 00 00 E9 00 00 00 EA 00 00 00 EB 00 00 00 EC 00 00 00 ED 00 00 00 EE 00 00 00 EF 00 00 00 F0 00 00 00 F1 00 00 00 F2 00 00 00 F3 00 00 00 F4 00 00 00 F5 00 00 00 F6 00 00 00 F7 00 00 00 F8 00 00 00 F9 00 00 00 FA 00 00 00 FB 00 00 00 FC 00 00 00 FD 00 00 00 FE 00 00 00 FF 00 BF 3A FF 35 02 02 00 02 00 02 00 00 00 47 00 93 DC 0A 0D

→ 粘包拆帧流程（已按此落地）：
  1) 找固定起始头 1ACF
  2) 取固定长度 1040
  3) 判固定结尾（兼容 0A0D / 0D0A）；不对则滑过伪起始再搜
  4) 校验和/长度/子包序号
  5) 按 dataLen 提有效数据，再按序号拼装
  6) 本帧处理完后循环处理缓冲剩余数据
  关开 UDP 后生效。



逻辑还需要补充，需要先找固定起始头，找到后，再通过固定长度1040，判断固定结尾（代码中兼容，有两个结尾），校验等，后续按照你的逻辑提取有效数据。这次处理后，循环处理后续还有的数据。



现在调试/数据模拟 页面修改。
当前我自己也改动了页面，显示方面的，功能方面没有修改。

现在需要修改功能， 新增区域，通用数据发送模拟。
有控件，两个下拉菜单，一个是帧组装类型（组装器），一个是帧解析类型（解析器）。
一个输入框（提示Hex 文本），发送按钮，清空按钮。
然后标题对应添加。

当前的can发送不要修改。
具体举例：
比如发送can遥测数据，下拉菜单选择透传+can遥测数据解析
比如lvds发送的can遥测数据，下拉菜单选择 lvds帧 + can遥测数据解析

→ 已做：通用数据发送模拟（调试/数据模拟）
  - 组装器+解析器下拉、Hex、发送/清空；CAN 原区域不动
  - API POST /payload/telemetry/dev/pipeline
  - 例：透传+tm_can_yc；eng_tm_subpkt(LVDS)+tm_can_yc


Hex 文本 框，高度缩小一半，宽度变宽，宽度适配全屏

can的输入框也这么修改。
还有两个输入框的文字，和上下边框碰到一起了。

然后发送后的提示“已写入 Redis · 组装 1 · 解析 1 · 类型 0xFF · B-1主要包 · 字段 135 · 2026-07-22 14:26:48.644”  这句话显示，会造成这块区域的界面抖动。 突然出现也会导致下面的界面移动。

当前输入框如果出现滚动条，滚动条就要适配dark模式。请参考 数据收发页面的接收设置的滚动条。

这个页面的输入框数据，控件，都需要浏览器缓存，刷新后还原
