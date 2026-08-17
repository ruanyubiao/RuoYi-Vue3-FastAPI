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
7.		数据内容	BYTE	1024	1024字节数据内容
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





现在制作功能，单板测试/相机。
协议文档参考：test/SC-LINK41EP短波红外模组通信协议（V1.6）.pdf
所有控制的串口指令，生成json配置文件CameraTeleControlCfg.json，
格式参考：ruoyi-fastapi-backend\assets\config\TeleControlCfg.json。
所有遥测的配置，生成json配置文件，CameraTeleMetryCfg.json
格式参考：ruoyi-fastapi-backend\assets\config\TeleMetryCfg.json
新配置也放在目录ruoyi-fastapi-backend\assets\config 下。

先生成配置，再根据配置在单板测试/相机 页面上，显示遥控指令发送，遥测显示，图像显示，传输信息显示。
页面分为左右两部分，左边上部分显示遥控，下部分显示遥测（遥测数据不多，10多条），右边部分显示图像区域和传输信息。
传输信息界面需要做成通用界面，其他单板测试界面可能复用。

图像功能：
参考 test/MiliankeCamera/ui/right/ImageWidget.ui  这个页面，可以完全照抄。
ui相关代码也直接翻译过来就行，这里参考界面布局，鼠标双击，拖动，滚轮操作等。
然后，图像显示的数据组装逻辑，参考下面的代码，功能已经实现，test/serial_image_viewer.py，这个显示图像时正确的。

这里新增解析器 相机SC-LINK41EP的。 组装器是两个，这里有两个串口，1个是透传，1个是相机图像数据组装器，组装的结果是图像数据（宽高，数据结构体）。
遇到组装错误，向reids的错误key写入错误日志。error下id是camera。

这里的遥控指令，不需要遥控指令树。改成把每一条遥控指令区域（标题，控件）全部显示出来。占据左侧除了遥测外的所有区域。 最顶部的输入框，还是过滤器，过滤命令标题，规则和遥控页面的过滤器一样。




把子菜单相机改名还原，不需要改名。

当前页面404错误：
http://localhost/dev-api/payload/camera/telecontrol/config?reload=false

控制串口行去掉。改成 新建控制串口连接，新建图像串口连接，
连接成功后，改成关闭控制串口 · COM1 ，；连接成功，按钮背景改成。点击新建，弹窗串口创建连接界面。但已经指定的参数对应的输入框，下拉菜单需要disalbe，不让选，显示已指定的值。界面其他不需要改动。
删除刷新串口按钮。
遥控区域，控件没有创建，就是需要创建示例图像的控件列表。
遥测区域表格也没有显示，就算没有数据，也要显示遥测的空表格。当前遥测表配置的key是D8，这个D8是怎么来的？
遥测应该使用通用的遥测页面，包括 这几项。编号，参数名称，当前值，单位， HEX。

传输信息区域，显示的是日志信息，不需要使用数据接收这个控件，只需要一个文本信息展示框。
信息输出内容参考：
[2026-07-22 16:41:36.593]#Send EB 90 D1 00 00 02 00 00 00 55 28
[2026-07-22 16:41:38.731]#Send EB 90 D0 00 00 05 00 01 B3 00 00 00 23 AC
[2026-07-22 16:41:43.186]#Send EB 90 D0 00 00 05 00 02 B3 00 00 00 23 AD
[2026-07-22 16:41:43.839]#Send EB 90 D0 00 00 05 00 03 B3 00 00 00 23 AE
[2026-07-22 16:41:47.536]#Send EB 90 D0 00 00 05 00 04 B3 00 00 00 23 AF
[2026-07-22 16:41:47.957]#Send EB 90 D0 00 00 05 00 05 B3 00 00 00 23 B0
[2026-07-22 16:42:13.915]#Recv 遥测帧校验错误 EB 90 D8 00 00 2D 00 52 00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 01 10 11 12 13 14 15 16 17 18 19 1A 1B 1C 1D 1E 1F 20 21 22 23 24 25 26 27 28 29 2A 2B 2C 35




传输信息 边上的清理按钮， 直接放在最右边，和传输信息往下对齐。
发送/接收数据将显示在这里， 这个提示文本不对，直接不显示或改成更友好的。

去掉第一行 的 分辨率 及后面的控件。

遥控界面
中间区域的指令代号行删除，因为标题已经有了。
参数长度行， 把字节移入到标题，显示示例：K1504 - 工程遥测存储使能 - 8 字节

单板/相机测试界面，遥控区域，每一个指令，指令代号 行删除，因为标题上已经有了。
参数长度，我看到没有选择参数情况下，显示 - 字节，就算没有选择参数，但字节数其实是确定的，也要把这行的字节显示到标题上。


新建串口连接的窗口，串口列表的下拉菜单，对于已连接的串口，后面添加 - 已连接  。


新建连接，已有连接归属问题。
在单板相机页面建立的 新建控制串口连接，连接后，变成关闭，我再次刷新页面后，新建控制串口连接 这个按钮就找不回状态了。
是不是给建立的连接分配一个来源。这个来源和页面能关联。
首页的列表也给与一个来源列。



首页/调试/数据收发, 设备列表，当前后缀是在线，离线， 在添加后缀来源。

在浏览器窗口缩小的时候，首页表格的格子变小，文字显示补全，出现tooltip，
这个tooltip，背景是白色的，需要适配dark模式。
还有检查下其他页面，这个是不是也都是白色的背景。
能不能统一设置，我每次测试，凡是出现tooltip的背景没有一个是对的。

【已处理】Element Plus effect=dark 在 html.dark 下用 text-primary 当背景导致发白；已在 element-ui.scss 全局修正，并统一 theme-aware / tm-cfg tooltip 样式。


在单板相机页面，
新建串口连接，选择已经连接的设备，如果设备已连接使用的参数和当前串口需求的不一样，不能直接拿来用。  这一项应该改成不能选。
比如我在首页创建的串口连接，如果连接参数和当前页面需求一致，我能拿来使用，把来源绑定成本页。选择本项后，把连接按钮改成 使用。
这时候其实不用创建连接，只是把解释器，组装器重新绑定成本页面需要的。

【已处理】参数不符的已连接口禁用；参数一致显示「使用」，仅 bind parser/assembler/source，不重启进程。




如果前端传了错误的参数，比如已连接的参数不一致的，后端会正确处理吗？还是直接拿来绑定？


新建连接的参数解释下，除了串口的参数，其他参数解释下。
{"port":"COM3","baudrate":115200,"dataBits":8,"stopBits":1,"parity":"N","flowControl":"NONE","parserId":"camera_sc_link41ep","assemblerId":"passthrough","source":"camera_ctrl"}



这样设计不合理，不需要mode参数，然后使用souce就行。
然后不要再直接再代码中 serial_collector.py  中，
直接新建变量 self._camera_enabled = self.config.get('mode') == 'camera'
        self._camera_cfg = {
            'resolution': self.config.get('resolution', '256×256'),
            'image_no': int(self.config.get('image_no', 1)),
        }

如果以后串口功能多了，是不是这个类上会建立非常多的各种功能的变量。
需要把图像处理相关功能抽象成接口的形式，把图像采集功能做成插件形式。
如果是camera_image类型, 就去找对应的插件，
这个插件是再收到串口数据后，进行一层过滤处理，再本插件中，图像数据处理后，不需要再透传出来。
其他插件以后可能会透传出来。
关联的时候，挂在这个插件，取消关联或，关联改变，去掉这个插件。
功能需要尽可能解耦。

【已处理】SerialCollector 只负责串口；图像拉流迁至 collectors/plugins/camera_image；
按 session.source（camera_image）挂载/卸载；已去掉 mode；改绑会通知采集进程。


把mode参数相关的能去掉吗？开发阶段，不考虑兼容问题



单板相机测试，如果串口没有打开，对应的功能不要一直请求。
比如遥测，控制串口没有就不请求。
图像，图像串口不打开不请求

关闭串口连接的时候，需要确认弹窗。


这是打开传图串口后的请求，分别是什么作用？
status?port=COM4
io-log?deviceld=serial%3ACOM4&sinceSeq=77&limit=200
image?port=COM4
snapshot?parts=serialOpened



读采集进程状态文案（如「图像就绪 / 采集失败」），刷到页面状态栏   这个状态是redis读取还是其他方法？
status?port=COM4 和 image?port=COM4  这两个功能能合并吗？返回的数据对象合并

image数据单独一个对象区域，不要和status数据放在同一层。


io-log的请求频率特别高，而且会同时（间隔非常短），请求两次。
遥测信息改成1s请求1次。


~~信息输出区域，一次输出两条相同的信息，还有这个区域有行数上限吗？没有的话限制1000行。~~
[2026-07-23 14:15:11.097]#Send EB 90 D0 00 00 02 00 00 A1 01 74
[2026-07-23 14:15:11.107]#Send EB 90 D0 00 00 02 00 00 A1 01 74

~~配置文件中，ruoyi-fastapi-backend\assets\config\CameraTeleControlCfg.json，id和key类似 CAM_AA的， 这个改成CAM_A10，对应的都需要改。~~

~~CAM_AA（改名后CAM_A10）中，有component是BYTE类型，大小是0-255，但输入的提示 'b' format requires -128 <= number <= 127 。~~
{
    "title": "缓存间隔(帧)",
    "componentType": "number",
    "dataType": "BYTE",
    "unit": "",
    "minVal": "0",
    "maxVal": "255",
    "defaultVal": "0",
    "options": {}
}

~~~~配置文件中的这几个也要修改。~~
                "CAM_AB"→CAM_A11,
                "CAM_AC"→CAM_A12,
                "CAM_AD"→CAM_A13,
                "CAM_AE"→CAM_A14,
                "CAM_AF"→CAM_A15,

~~通信协议文档解析错误，
12）数据处理控制  中 表A.12数据处理控制指令

控制字节 这个字段，是 下拉菜单
0x00：非均匀性校正关闭，CameraLink关闭
0x02：非均匀性校正关闭，CameraLink开启
0x80：非均匀性校正开启，CameraLink关闭（默认）
0x82：非均匀性校正开启，CameraLink开启~~


配置文件中的这几个也要修改
                "CAM_B1",  A16
                "CAM_B2",  A17
                "CAM_B8",  A18


CAM_B1 - 串口2图传波特率切换 - 11 字节
16）串口2图传波特率切换指令
默认波特率的默认两个字需要加上


CAM_A14 - 曝光时间设置 - 14 字节
表A.14曝光时间设置指令
第10字节是保留字节
第11-14字节指令数据 4字节


CAM_A15 - 增益设置 - 11 字节
表A.15增益设置指令
第10字节是保留字节
第11字节是指令数据
低增益：0x00
高增益：0x01



test/SC-LINK41EP短波红外模组通信协议（V1.6）.pdf 文档中，重构部分指令没有。
A.2.2 重构/上注指令，是串口1的，但开头使用C，CAM_D1开始。

A.2.3 图像下传请求帧（串口2） 这个是串口2了，指令id从B开始

A.2.4 遥测开关 ，是串口1的，属于指令A
 "CAM_D7" 把它改成A0，特殊处理。~~


~~界面的遥控指令部分，修改数据，预览按钮会出现loading抖动一下。发送按钮又是也是。
这是整个工程的通病，每次遇到这样的按钮，1个出现没什么问题，但是和其他控件在一起，就会造成界面抖动。
这个是很不好的体验。
这个能改动按钮，使得loading出现，按钮空白区域也足够大，使得按钮大小不变，按钮文字位置不变，
这样就不会出现页面抖动。~~


~~ruoyi-fastapi-backend\assets\config\CameraTeleMetryCfg.json
相机遥测配置错误。

参考示例：
“
ruoyi-fastapi-backend\assets\config\TeleMetryCfg.json
这是1个字节被分成多个bit部分的写法，遥测库解析支持下面配置的写法。
               {
                    "no": 56,
                    "id": "JGB056",
                    "name": "未响应执行标志",
                    "bytepos": 109,
                    "bits": 2,
                    "bitpos": 0,
                    "showType": 0,
                    "formula": "",
                    "unit": "",
                    "fmt": "",
                    "value": {
                        "00b": "正常",
                        "11b": "未响应"
                    },
                    "dataType": "BYTE",
                    "variableName": "ucUnresponsiveExecutionFlag:"
                },
                {
                    "no": 57,
                    "id": "JGB057",
                    "name": "校验错误标志",
                    "bytepos": 109,
                    "bits": 2,
                    "bitpos": 2,
                    "showType": 0,
                    "formula": "",
                    "unit": "",
                    "fmt": "",
                    "value": {
                        "00b": "正常",
                        "11b": "校验错误"
                    },
                    "dataType": "BYTE",
                    "variableName": "ucCheckTheErrorFlag"
                },
                {
                    "no": 58,
                    "id": "JGB058",
                    "name": "重构数据发送完成",
                    "bytepos": 109,
                    "bits": 4,
                    "bitpos": 4,
                    "showType": 0,
                    "formula": "",
                    "unit": "",
                    "fmt": "",
                    "value": {
                        "0000b": "待机",
                        "0001b": "发送中",
                        "0011b": "发送完成"
                    },
                    "dataType": "BYTE",
                    "variableName": "ucRefactoringSending"
                },
”

A.3.1 全窗模式下慢遥应答帧 ，我检查配置，发现下面的问题，当然其他肯定还有。

文档中是：
当前加载分区号
[7:4]fpga分区：
0：1分区
1：2分区
F：加载失败

[3:0]app分区：
0：1分区
1：2分区
F：加载失败

CameraTeleMetryCfg.json配置是：
{
    "no": 12,
    "id": "CAM012",
    "name": "当前加载分区号",
    "bytepos": 16,
    "bits": 8,
    "bitpos": 0,
    "showType": 0,
    "formula": "",
    "unit": "",
    "fmt": "%02X",
    "value": {},
    "dataType": "BYTE",
    "variableName": "CAM012"
},

需要改成bit位的写法。


其他还有的是：
数据处理控制
bit7：非均匀性校正，1-开
启，0-关闭。
bit 6：自动阈值状态，
1-开启，0-关闭。
bit5：空间滤波状态，
1-开启，0-关闭。
bit4：滤波模式，
1-模式1，0-模式2。
bit3：保留。
bit 2：自动曝光状态，1-开
启，0-关闭。
bit 1：CameraLink图像传输
接口状态，
1-开启，0-关闭。
bit 0：非均匀性校正参数是
否加载完毕，
1-是，0-否。
*注：保留比特为0



还有 A.3.2 开窗模式下快遥应答帧
这个遥测表需要。

字节序号 名称 字节数 数据内容 说明
1 帧头 1 0xEB
2 帧类型 1 0xD9
3 帧序号 1 0x00-0xFF，帧序号从0开始累加

4-19 数据部分
                1 最后一条指令码
                1 指令执行情况
                1 形心/质心，0：形心坐标；1：质心坐标
                2 X坐标值 无符号数
                2 Y坐标值 无符号数
                1 过阈值像元数 无符号数
                1 饱和像元数 无符号数
                2 平均灰度值 无符号数
                1 光斑能量 有符号数
                4 模组工作状态反馈 内容由帧序号最低三位决定，见表A.28

20 校验和 1 3-19字节累加和低8位


*说明：
·数据部分-Y坐标值：该值采用2字节表示。高9bit为整数部分，低7bit为小数部分，
若图像中没有任何光斑，则坐标输出为0xffff。
·数据部分-X坐标值：该值采用2字节表示。高9bit为整数部分，低7bit为小数部分，
若图像中没有任何光斑，则坐标输出为0xffff。
·数据部分-过阈值像元数：光斑区域中灰度值超过分割阈值的像元个数，用于判断光斑
有无，该值大于3 时，判断为有光斑出现。
·数据部分-饱和像元数：光斑区域中灰度值大于饱和阈值的像元个数。
·数据部分-平均灰度值：质心：光斑区域所有像素点的灰度平均值。形心：扫描区域所
有像素点的灰度平均值
·数据部分-光斑能量：表示当前帧窗口内光斑的有无和能量的大小，单位为dBm。
光斑有无（bit7）：1-有光斑，0-无光斑
 光斑能量（bit0~bit6）：为无符号数 X，表示光斑能量为-X dBm


数据部分-Y坐标值：该值采用2字节表示。高9bit为整数部分，低7bit为小数部分，
这里显示公式使用：
"formula": "floor(D/128)+(D%128)/128",~~




~~上面的bit位的顺序反了。
比如 当前加载分区号
[7:4]fpga分区：
0：1分区
1：2分区
F：加载失败

[3:0]app分区：
0：1分区
1：2分区
F：加载失败

0-3bit是app分区，但配置中
 bitpos：4  表示从bit位索引4开始，
 "bits": 4, 表示占用4位。
                {
                    "no": 13,
                    "id": "CAM012A",
                    "name": "APP分区",
                    "bytepos": 16,
                    "bits": 4,
                    "bitpos": 4,
                    "showType": 0,
                    "formula": "",
                    "unit": "",
                    "fmt": "",
                    "value": {
                        "0000b": "1分区",
                        "0001b": "2分区",
                        "1111b": "加载失败"
                    },
                    "dataType": "BYTE",
                    "variableName": "CAM012A"
                },

还有 TeleMetryParser 库是用来解析这个配置文件的，不要自己写解析库，但需要传入数据部分。~~


新建图像串口连接，波特率二选一，当前是禁用的，
2000000(默认)
11000000
选择已打开的串口的时候，需要判断是否符合这两个


选择已连接，参数符合的串口的时候，选中了，下面的串口参数需要改成已连接串口的参数，并且需要disable不让修改。
切换成未连接的，需要可以选择波特率。


未连接的，波特率选择第二项不行，一直显示默认值




终端ctrl+c结束执行，后端，这时候有串口开着，报错了报错信息如下：

(venv) E:\plat\PayloadGroundTest\ruoyi-fastapi-backend>2026-07-23 13:07:27.153 | 4e220d96ef97426a86614d91f7079b5c | b25c9266a7aa4440b2f1254357d3703e | d30b6de88f9947d490093c409ae8807e | 7472-3deec2 |ERROR    | exceptions.handle:service_exception_handler:52 - 设备打开超时，请检查设备是否接入2026-07-23 13:07:27.153 | 4e220d96ef97426a86614d91f7079b5c | b25c9266a7aa4440b2f1254357d3703e | d30b6de88f9947d490093c409ae8807e | 7472-3deec2|ERROR    | exceptions.handle:service_exception_handler:52 - 设备打开超时，请检查设备是否接入2026-07-23 13:07:27.153 | 4e220d96ef97426a86614d91f7079b5c | b25c9266a7aa4440b2f1254357d3703e | d30b6de88f9947d490093c409ae8807e | 7472-3deec2 |ERROR    | exceptions.handle:service_exception_handler:52 - 设备打开超时，请检查设备是否接入

前端也有问题，后端关了后， 单板相机页面，串口显示连接着，这个没问题，网络断了。但是我点击关闭，直接状态变了。






单板/相机测试：

在新建串口连接按钮的同一区域， 图像区域上方，新增分辨率，图像序号下拉菜单，增加按钮图片刷新，参考test/serial_image_viewer.py,
这个按钮点击后变成停止刷新（红色背景），开始后需要把分辨率，图像序号传输给后端。
后端收到图片刷新指令后，同时后收到分辨率和图像序号，这时候 图像下传应答帧（串口2） 才知道总序号（根据分辨率），图像序号。当前的指令一直发图像序号0.
当前 打开图像串口的时候，一直会发送获取第一帧的指令，不合理。
造成这个日志一大堆： [2026-07-24 11:29:00.889]#Send EB 90 D6 04 00 01 00 00 01 DC


后端在收到打开图像串口指令的时候，不需要打开图像刷新，用户会手动操作。
后端在收到关闭图像串口后，也要关闭图像获取的串口传输指令，清空收到的数据缓存。

[已完成] 工具栏分辨率/序号+图片刷新切换；打开串口不自动拉图；camera_start 才按分辨率/序号发 D6；stop/关闭清缓存。




把分辨率移到 图像显示区域正上方，现在是跟在新建串口连接按钮后，
还有分辨率和图像序号的下拉菜单宽度只需要100和60px。

[已完成] 分辨率/序号/刷新移到图像区上方；下拉宽 100px / 60px。


把页面分成左右结构布局，把新建串口连接两个按钮的区域，昂儒左边布局。

分辨率/序号额下拉菜单的宽度改成 100px 、 60px。
图片刷新按钮 点击后，分辨率和图像序号不能点击了。

[已完成] 下拉宽强制 100/60；刷新中分辨率与序号可继续选择。

点击图片刷新后，分辨率和图像序号不能切换。 只有在串口打开，图片没刷新的时候能选分辨率和图像序号。
还有串口连接按钮区域和 图像刷新区域高度不一致。 我看着感觉是两个区域按钮不一样大。遥控区域和图像区域的顶部边框没在一条水平线上。

[已完成] 刷新中禁用分辨率/序号；左右顶栏同高 32px、按钮同尺寸；图像工具栏移出面板使遥控/图像顶边对齐。




图像显示区域：
灰色背景。
中间放置显示的图像，默认是黑色图像，正方形，高度和背景区域高度一样。
可以鼠标左键拖放图像控件，滚轮缩放图像，双击左键重置图像大小和位置。

图像上方的图像信息显示：
FPS: -
分辨率: 0×0
序号: -
坐标: 0, 0
灰阶: -

 坐标：x,y 和 灰度：0 的显示。
其中坐标x，y是鼠标移入图像后，鼠标指向图像坐标转换成原始数据图像的坐标系的坐标（不能受到缩放影响）。注意图像显示的时候是可能经过缩放的，需要坐标转换；灰度是从原始图像中获取对应坐标的值（值就是灰度）。没有图像，坐标就直接显示控件内的坐标，灰度0，界面初始化坐标0，0。坐标轴原点在左上角。
图像坐标显示，当鼠标移出了图像的时候需要显示为（nan,nan）。当移入图像则显示坐标。

没有图像数据的时候，图像就是默认图像，纯黑，初始化的时候。

[已完成] 灰底+居中等高黑方默认图；拖拽/滚轮/双击复位；坐标按原图像素换算，移出显示 nan,nan；无图灰度 0。

分辨率需要根据当前显示图片的分辨率填写。
当前默认图片情况下是 分辨率: 0×0。改成图片分辨率。
FPS 改名帧率。
然后  这篇区域，随着文字内容改变，它的ui会移动。能不能每个显示元素固定，
FPS: - 分辨率: 0×0 序号: - 坐标: nan, nan 灰阶: -
 当前测试情况是，我鼠标移动，坐标或变换，比如1，1 变到 220，200，后面的灰阶就会左右移来移去。

[已完成] 默认黑图显示实际正方形分辨率；FPS→帧率；信息栏各字段固定宽度防跳动。


遥测表格，编号列，移上去显示tooltip，参考遥测表页面的规则显示。

相机测试页面，
分辨率下拉菜单默认不选择，如果用户没有选择，点击图片刷新按钮时提示。

前端页面，获取到遥测表数据 CAM027 开窗模式 的值，然后匹配分辨率下拉菜单，需要设置下拉菜单。
规则如下：
不管下拉菜单是不是禁用状态，都需要修改。
如果获取了遥测数据，然后用户还没有选择，给设置分辨率。
如果遥测分辨率旧数据和新数据发现改变了，就需要给下拉菜单设置值，没改变不要设置，
可能用户自己选择了。

[已完成] 分辨率默认空+刷新校验；按 CAM027 同步（未选手动设/遥测变化才覆盖）。



增加图片保存按钮，在图片刷新这一行，但靠右。
点击保存，就保存当前页面显示的这张图片。

[已完成] 图像工具栏右侧「图片保存」；下载当前显示图为 PNG。


控制串口的连接参数，旧的错了：
2000000，8 位数据位，1位停止位，1位奇校验，

灰阶后面，增加刷新时间字段，显示图片获取的时间。
信息框，清理按钮左边，增加复制按钮。

[已完成] 控制串口默认 2M/8/1/奇校验；信息栏刷新时间；传输信息复制按钮。


后端串口收发数据的频率需要提升，现在图像传输，从发送，到收，在到发的间隔都太大。大大影响传输速率。

接收信息区域，一条消息长度超过100个字符，后面需要用...代替。


没有开启串口，串口还未连接，遥测表需要显示没有值和hex的空表




采集图片的串口。
完整一次采集过程的日志，Recv截取了部分，收发的时间间隔，还是有7-9毫秒。
有什么更好的办法降低收发延迟吗？

[已优化] 拉图热路径零 Redis：收发时刻本地记时，整图后再刷日志；帧间不再 reset RX；收包循环不轮询控制。日志里的 7~9ms 先前含 hex+Redis，现可更接近真实线延迟。
日志如下：
[2026-07-24 16:20:28.079]#Send EB 90 D6 04 00 01 00 00 01 DC
[2026-07-24 16:20:28.086]#Recv EB 90 D6 04 01 01 00 00 01 38 38 39 39 39 39 39 39 39
[2026-07-24 16:20:28.135]#Send EB 90 D6 02 00 01 00 0F 01 E9
[2026-07-24 16:20:28.140]#Recv EB 90 D6 02 01 01 00 0F 01 46 44 46 44 46 45 46 45 45
[2026-07-24 16:20:28.191]#Send EB 90 D6 02 00 01 00 1F 01 F9
[2026-07-24 16:20:28.198]#Recv EB 90 D6 02 01 01 00 1F 01 49 48 48 49 48 47 49 48 48
[2026-07-24 16:20:28.250]#Send EB 90 D6 02 00 01 00 2F 01 09
[2026-07-24 16:20:28.258]#Recv EB 90 D6 02 01 01 00 2F 01 3B 3A 3D 3B 3A 3B 3B 3A 3C
[2026-07-24 16:20:28.309]#Send EB 90 D6 02 00 01 00 3F 01 19
[2026-07-24 16:20:28.316]#Recv EB 90 D6 02 01 01 00 3F 01 42 40 41 42 42 41 41 42 41
[2026-07-24 16:20:28.368]#Send EB 90 D6 02 00 01 00 4F 01 29
[2026-07-24 16:20:28.376]#Recv EB 90 D6 02 01 01 00 4F 01 45 46 43 46 45 46 45 44 46
[2026-07-24 16:20:28.427]#Send EB 90 D6 02 00 01 00 5F 01 39
[2026-07-24 16:20:28.436]#Recv EB 90 D6 02 01 01 00 5F 01 49 4A 49 48 49 49 49 49 48
[2026-07-24 16:20:28.486]#Send EB 90 D6 02 00 01 00 6F 01 49
[2026-07-24 16:20:28.493]#Recv EB 90 D6 02 01 01 00 6F 01 39 3B 3B 3B 3A 3B 38 3A 39
[2026-07-24 16:20:28.543]#Send EB 90 D6 02 00 01 00 7F 01 59
[2026-07-24 16:20:28.550]#Recv EB 90 D6 02 01 01 00 7F 01 41 41 41 40 42 41 41 41 41
[2026-07-24 16:20:28.599]#Send EB 90 D6 02 00 01 00 8F 01 69
[2026-07-24 16:20:28.605]#Recv EB 90 D6 02 01 01 00 8F 01 46 45 44 46 45 46 46 45 45
[2026-07-24 16:20:28.657]#Send EB 90 D6 02 00 01 00 9F 01 79
[2026-07-24 16:20:28.663]#Recv EB 90 D6 02 01 01 00 9F 01 48 49 47 49 49 4A 49 48 49
[2026-07-24 16:20:28.713]#Send EB 90 D6 02 00 01 00 AF 01 89
[2026-07-24 16:20:28.719]#Recv EB 90 D6 02 01 01 00 AF 01 3A 3A 3B 37 3A 3A 3B 3B 3A
[2026-07-24 16:20:28.771]#Send EB 90 D6 02 00 01 00 BF 01 99
[2026-07-24 16:20:28.779]#Recv EB 90 D6 02 01 01 00 BF 01 40 40 40 41 41 41 3F 40 41
[2026-07-24 16:20:28.831]#Send EB 90 D6 02 00 01 00 CF 01 A9
[2026-07-24 16:20:28.839]#Recv EB 90 D6 02 01 01 00 CF 01 43 43 44 43 45 45 45 45 44
[2026-07-24 16:20:28.894]#Send EB 90 D6 02 00 01 00 DF 01 B9
[2026-07-24 16:20:28.901]#Recv EB 90 D6 02 01 01 00 DF 01 48 49 48 4A 47 49 49 48 47
[2026-07-24 16:20:28.955]#Send EB 90 D6 02 00 01 00 EF 01 C9
[2026-07-24 16:20:28.961]#Recv EB 90 D6 02 01 01 00 EF 01 49 4A 4C 49 4A 4A 4A 4B 4A
[2026-07-24 16:20:29.049]#Send EB 90 D6 02 00 01 00 FF 01 D9
[2026-07-24 16:20:29.059]#Recv EB 90 D6 02 01 01 00 FF 01 3F 3F 40 3F 3F 3E 41 3E 40
[2026-07-24 16:20:29.114]#Send EB 90 D6 02 00 01 01 0F 01 EA
[2026-07-24 16:20:29.124]#Recv EB 90 D6 02 01 01 01 0F 01 45 45 45 45 45 45 43 45 43
[2026-07-24 16:20:29.178]#Send EB 90 D6 02 00 01 01 1F 01 FA
[2026-07-24 16:20:29.184]#Recv EB 90 D6 02 01 01 01 1F 01 48 47 47 48 48 47 48 48 47
[2026-07-24 16:20:29.234]#Send EB 90 D6 02 00 01 01 2F 01 0A
[2026-07-24 16:20:29.243]#Recv EB 90 D6 02 01 01 01 2F 01 49 4A 4A 4A 4A 49 4A 48 4A
[2026-07-24 16:20:29.293]#Send EB 90 D6 02 00 01 01 3F 01 1A
[2026-07-24 16:20:29.304]#Recv EB 90 D6 02 01 01 01 3F 01 3D 3F 3D 3F 3D 3F 3E 3F 3D
[2026-07-24 16:20:29.355]#Send EB 90 D6 02 00 01 01 4F 01 2A
[2026-07-24 16:20:29.373]#Recv EB 90 D6 02 01 01 01 4F 01 46 43 43 42 44 43 45 45 44
[2026-07-24 16:20:29.425]#Send EB 90 D6 02 00 01 01 5F 01 3A
[2026-07-24 16:20:29.432]#Recv EB 90 D6 02 01 01 01 5F 01 47 47 46 47 48 47 47 48 47
[2026-07-24 16:20:29.489]#Send EB 90 D6 02 00 01 01 6F 01 4A
[2026-07-24 16:20:29.498]#Recv EB 90 D6 02 01 01 01 6F 01 4A 49 4B 48 4A 49 4B 4B 4A
[2026-07-24 16:20:29.549]#Send EB 90 D6 02 00 01 01 7F 01 5A
[2026-07-24 16:20:29.559]#Recv EB 90 D6 02 01 01 01 7F 01 3D 3D 3D 3D 3D 3C 3B 3D 3C
[2026-07-24 16:20:29.609]#Send EB 90 D6 02 00 01 01 8F 01 6A
[2026-07-24 16:20:29.615]#Recv EB 90 D6 02 01 01 01 8F 01 43 42 44 42 42 41 44 44 43
[2026-07-24 16:20:29.666]#Send EB 90 D6 02 00 01 01 9F 01 7A
[2026-07-24 16:20:29.673]#Recv EB 90 D6 02 01 01 01 9F 01 46 45 45 47 46 46 46 46 47
[2026-07-24 16:20:29.721]#Send EB 90 D6 02 00 01 01 AF 01 8A
[2026-07-24 16:20:29.727]#Recv EB 90 D6 02 01 01 01 AF 01 49 4A 4A 49 48 49 48 4A 49
[2026-07-24 16:20:29.773]#Send EB 90 D6 02 00 01 01 BF 01 9A
[2026-07-24 16:20:29.779]#Recv EB 90 D6 02 01 01 01 BF 01 3C 3C 3C 3C 3C 3A 3C 3C 3C
[2026-07-24 16:20:29.831]#Send EB 90 D6 02 00 01 01 CF 01 AA
[2026-07-24 16:20:29.844]#Recv EB 90 D6 02 01 01 01 CF 01 41 42 42 41 43 42 42 42 41
[2026-07-24 16:20:29.896]#Send EB 90 D6 02 00 01 01 DF 01 BA
[2026-07-24 16:20:29.903]#Recv EB 90 D6 02 01 01 01 DF 01 44 45 45 47 45 45 46 45 44
[2026-07-24 16:20:29.956]#Send EB 90 D6 02 00 01 01 EF 01 CA
[2026-07-24 16:20:29.967]#Recv EB 90 D6 02 01 01 01 EF 01 47 47 48 45 47 48 49 48 47
[2026-07-24 16:20:30.026]#Send EB 90 D6 02 00 01 01 FF 01 DA
[2026-07-24 16:20:30.034]#Recv EB 90 D6 02 01 01 01 FF 01 3B 3B 3B 3B 3B 3B 39 3B 3C
[2026-07-24 16:20:30.086]#Send EB 90 D6 02 00 01 02 0F 01 EB
[2026-07-24 16:20:30.093]#Recv EB 90 D6 02 01 01 02 0F 01 41 40 41 41 41 3F 42 42 41
[2026-07-24 16:20:30.144]#Send EB 90 D6 02 00 01 02 1F 01 FB
[2026-07-24 16:20:30.151]#Recv EB 90 D6 02 01 01 02 1F 01 44 44 45 44 45 44 44 44 43
[2026-07-24 16:20:30.201]#Send EB 90 D6 02 00 01 02 2F 01 0B
[2026-07-24 16:20:30.207]#Recv EB 90 D6 02 01 01 02 2F 01 45 46 47 47 47 47 46 48 47
[2026-07-24 16:20:30.258]#Send EB 90 D6 02 00 01 02 3F 01 1B
[2026-07-24 16:20:30.266]#Recv EB 90 D6 02 01 01 02 3F 01 3A 39 39 3A 39 3A 3A 3A 3A
[2026-07-24 16:20:30.317]#Send EB 90 D6 02 00 01 02 4F 01 2B
[2026-07-24 16:20:30.325]#Recv EB 90 D6 02 01 01 02 4F 01 3F 3F 3F 3F 3F 3F 40 3F 40
[2026-07-24 16:20:30.375]#Send EB 90 D6 02 00 01 02 5F 01 3B
[2026-07-24 16:20:30.381]#Recv EB 90 D6 02 01 01 02 5F 01 43 43 43 43 42 42 44 43 42
[2026-07-24 16:20:30.430]#Send EB 90 D6 02 00 01 02 6F 01 4B
[2026-07-24 16:20:30.437]#Recv EB 90 D6 02 01 01 02 6F 01 46 46 47 45 45 45 46 46 46
[2026-07-24 16:20:30.446]#Send EB 90 D6 01 00 01 02 70 01 4B
[2026-07-24 16:20:30.452]#Recv EB 90 D6 01 01 01 02 70 01 42 40 41 40 40 40 41 40 41


新的日志，现在时间消耗在Recv收到到发送，间隔非常大。给下为什么延迟大，是在做什么操作吗？

说明：日志每 16 帧抽样一次。例如 seq 0 的 Recv(13.308) → seq 0x0F 的 Send(13.348) 约 40ms，中间还有 15 帧未打印，折合约 2.5ms/帧；并不是 Recv 后空等 40ms。相邻帧真实操作仅：校验 → 拼图 → 组下一请求 → write。Send→Recv≈2~3ms 才是线往返。

[已改] 前 4 帧连续记日志便于看相邻间隔；整图结束追加 avg ms/frame 摘要行。
[2026-07-24 16:28:13.306]#Send EB 90 D6 04 00 01 00 00 01 DC
[2026-07-24 16:28:13.308]#Recv EB 90 D6 04 01 01 00 00 01 38 38 39 39 39 39 39
[2026-07-24 16:28:13.348]#Send EB 90 D6 02 00 01 00 0F 01 E9
[2026-07-24 16:28:13.351]#Recv EB 90 D6 02 01 01 00 0F 01 46 44 46 44 46 45 46
[2026-07-24 16:28:13.389]#Send EB 90 D6 02 00 01 00 1F 01 F9
[2026-07-24 16:28:13.391]#Recv EB 90 D6 02 01 01 00 1F 01 49 48 48 49 48 47 49
[2026-07-24 16:28:13.428]#Send EB 90 D6 02 00 01 00 2F 01 09
[2026-07-24 16:28:13.430]#Recv EB 90 D6 02 01 01 00 2F 01 3B 3A 3D 3B 3A 3B 3B
[2026-07-24 16:28:13.467]#Send EB 90 D6 02 00 01 00 3F 01 19
[2026-07-24 16:28:13.470]#Recv EB 90 D6 02 01 01 00 3F 01 42 40 41 42 42 41 41
[2026-07-24 16:28:13.510]#Send EB 90 D6 02 00 01 00 4F 01 29
[2026-07-24 16:28:13.513]#Recv EB 90 D6 02 01 01 00 4F 01 45 46 43 46 45 46 45


当前串口处理方式是，或者说所有拼接数据的处理方式是：
先会把读取到的数据放入缓存，
判断剩余数据是否有字节，
找eb 这个帧头，找不到，删除eb前数据，一直找一直删除，
直到找到eb后，在确定 是否是eb 90 d6（剩余字节足够），不是，重复上面的查找，直接没有缓存。
是这个帧头，看数据是否满足完整帧，不满足，等下一帧数据。

我的这个方法是通用的拼接帧处理方法吗？

通用的话，写一个通用的类：这个类就是用于固定帧头，固定长度的数据，组帧，返回完整帧。
这个类内有数据写入（类内部缓存），清理（或者重置，清空缓存，回到初始状态），读取帧（有返回，没有none），类内的缓存实现，要符号高速的需求，直接bytebuffer拼接是不是效率不高。
相当于插件使用这个类对象，只要初始化这个类（参数帧头，长度）。使用这个类就只要写数据，读帧。
这个类不涉及到帧的载荷具体解析，只是在传输层面进行简单的处理。
返回帧后，得到帧的程序，还需要进行进一步的帧协议处理，比如校验和。

[已完成] 是通用「定帧头+定长」流式组帧法。已实现 `module_payload.framing.FixedHeaderLenFrameBuffer`
（write / clear / read_frame；bytearray+读偏移，避免反复整段拷贝）。

我的理解是，
串口打开后，默认是没有插件的串口（或者说有个默认插件），就是普通的收发，实现最基础的。
打开camera取图类型的串口，给串口类设置了的相机取图插件，这个插件功能是，外部通过插件的通用指令函数，指令是启动传图，插件内部有个循环就开始了自动发串口消息，收消息，收到的消息给FixedHeaderLenFrameBuffer对象，然后获取帧，把帧传给组装器（assemblers/camera_image_d6），组装器陆陆续续获取帧，等到获取到足够多的帧，能够组装完整图像数据后, 在redis存完整的数据。需要把camera_image_d6从串口获取一帧改成插件给，camera_image_d6如果自己从串口取，就需要处理粘包，不合理。
这样修改后，串口数据只有插件在获取，只有插件有FixedHeaderLenFrameBuffer对象，camera_image_d6组装器只负责数据拼接。

[已完成] 分层已按上文调整：
- 插件 `camera_image`：串口收发 + 唯一 `FixedHeaderLenFrameBuffer` 拆完整帧 + 调组装器 + 写 Redis 图
- 组装器 `camera_image_d6`：只 `accept_frame`/`feed` 完整 266B 帧，校验与按序号拼像素，不碰串口/粘包




FixedHeaderLenFrameBuffer 是固定头和长度。
新增类型固定头和尾部。
新增类型固定头，尾，长度。
处理下新增的两种类型。


工程遥测子包（LVDS），需要用到固定头尾长度的流式FrameBuffer
收到的流数据，是不是先放到这个流式处理器， 在从中取出完整帧。
也就是把“粘包按 1040 拆帧”的功能 从 lvds的组装器中去除，这个功能和业务组装没关系，和网络处理关系更大，但eng_tm_subpkt的其他功能都要保留。
当前先把这个流处理对方放在eng_tm_subpkt 中。

[已完成] framing 三种流式缓冲：
- `FixedHeaderLenFrameBuffer`：定头 + 定长（相机 D6）
- `FixedHeaderTrailerFrameBuffer`：定头 + 定尾（变长正文）
- `FixedHeaderLenTrailerFrameBuffer`：定头 + 定长 + 定尾（可多尾）
`eng_tm_subpkt` 已用第三种拆 1040B（头 1ACF / 尾 0A0D|0D0A）；组装器只做校验与子包拼装。流缓冲暂仍挂在组装器内。




CameraTeleMetryCfg.json 改名 XL-Camera-TeleMetryCfg.json
CameraTeleControlCfg.json 改名 XL-Camera-TeleControlCfg.json

[已完成] 文件已改名；`payload_config_loader` / `gen_camera_cfg` / 解析器注释已同步。

根据 test/XL卫星地检遥测数据源包明细及处理方法_CPA地检ZK包_20260724.docx 的 章节 1.1.1	激光地检ZK包， 生成遥测配置文件，XL-ZK-TeleMetryCfg.json

[已完成] 已生成 `ruoyi-fastapi-backend/assets/config/XL-ZK-TeleMetryCfg.json`（表 ZK，65 项 JGB001–JGB065，含公式/枚举/位域）。





当前从硬件收到数据后，最终给了组装器，但组装器只处理一类数据，相当于这一个硬件绑定了1个组装器，但数据只能解析一类，如何处理多类数据，需要如何改？

[已完成] 会话可选 `routes` 混流分流：`StreamDemux` 拆完整帧 → 按 assemblerId 喂多组装器（优先 `accept_frame`）。
无 `routes` 时仍走单 `assemblerId`（兼容旧行为）。前端多路配置 UI 二期。


把单板相机的传输信息区域 和 遥测区域 交换位置
控制串口使用了com1，打开了， 传图串口这时候连接也选择com1（连接参数一样），可以选择，没问题。
但是传图的使用了com1后，控制按钮的状态没关掉。界面的两个按钮都和com1关联了。我强制F5刷新就没问题。切到首页去查看连接状态，也是正确的。


问题：
在遥测曲线界面，我选择起始时间： 2026-07-20 14:42:48，点击查询后变成 2026-07-27 14:42:48。
遥测归档数据页面的起始时间也是这个问题。


相机遥测d8 d9， 也需要数据持久化存储 和  曲线支持（redis缓存）。
当前只有在遥测菜单下有曲线，下拉菜单还是只有遥测表TeleMetryCfg.json 对应的几项，没有其他配置文件相关的。
如何把其他配置文件加进去？


遥测配置的page字段已经删除，代码中需要进行相应修改，page字段不要使用了。
下拉菜单项，由id + "：" + name 拼接显示
XL-RKDJ-TeleMetryCfg.json  这份配置没有



# 遥测 table 合并顺序：先 CAN 主表，再相机 / ZK / RKDJ（key 冲突时保留先出现的）
TELEMETRY_CFG_SOURCES = (
    ('telemetry', TELE_METRY_CFG_FILE),
    ('camera_telemetry', CAMERA_TELE_METRY_CFG_FILE),
    ('zk_telemetry', ZK_TELE_METRY_CFG_FILE),
    ('rkdj_telemetry', RKDJ_TELE_METRY_CFG_FILE),
)

TELEMETRY_CFG_SOURCES 改成遍历 config目录下的 *-TeleControlCfg.json 文件获取，不固定写死。


调试页面，增加 配置文件 子菜单。sql需要更新，数据库帮我更新。
页面显示遥控遥测配置的列表， 序号，文件名，修改时间（系统的修改时间），操作（预览，编辑，下载）
预览，按配置文件的内容原文显示。
修改，需要检查json格式是否正确。



TeleMetryCfg.json 改名 BIU-TeleMetryCfg.json
TeleControlCfg.json 改名 BIU-TeleControlCfg.json

表格样式参考：http://localhost/system/dict  首页 / 系统管理 / 字典管理。
刷新按钮也需要参考字典管理 页面的刷新图标按钮，放在最右边。

当前配置文件页面，表格有个外框，但又全屏，很怪。
增加生成时间列，在文件名列后，读取配置的“datetime”字段。
预览页面，关闭前加 下载按钮。

是否需要加入重新载入配置按钮，如果本地配置修改了，如果不想系统重启，是否需要重新加载配置。
如果要加入，这个按钮放在现在刷新的位置，左边。

src\views\payload\debug\config\index.vue  这个文件，我自己有修改页面效果，不要给我还原了。

预览和编辑弹窗的滚动条样式没有和dark匹配，是不是全局的样式就是不对的，没有做dark的样式？
在操作区域，添加重新加载按钮    下载，  预览， 编辑， 重载配置。


重新载入配置，加入tooltip， 更新系统的所有配置（ 这个意思，需要你润色），
每行的重载配置也需要tooltip
滚动条控件，不需要显示顶部和底部的箭头小方块，难看，只需要一根滚动条，最好全局修改。

每行的重载配置，只重载当前行的配置，tooltip文本也不合适。
重新载入配置的tooltip的放在最顶部，难看，能不能放右边。
预览 和 编辑 界面的滚动条，还是有上下的顶部滑块，不需要，是不是刚才修改的全局的不生效？


还是不对，预览 和 编辑 界面的滚动条区域，还是有上下的箭头按钮。
可以参考 首页/单板/相机测试 页面中 遥测表格的下拉菜单，就没有顶部底部的上下箭头按钮，而且滚动条样式适配dark的。



首页 /遥测/0xFF：B-1主要包， 改了全局滚动条样式后，现在出现了双重滚动条，最外层的页面滚动条不应该出现，而且是带箭头滚动条。页面内的表格自带滚动条。
指令序列的 编辑指令序列页面，的指令序列部分，滚动条带箭头。
调试 / 数据模拟  滚动条带箭头。


指令序列的 编辑指令序列页面，的指令序列部分，滚动条 覆盖到了 右边的UI。



# ruoyi系统自带功能修改

通知公告 删除旧的通知。
用户管理  niangao 改成 test  年糕改成 我叫测试

部门管理 删除 长沙分公司 改名 成都总公司，
修改 深圳分公司 为杭州分公司，
两个分公司都只需要 研发部门  和 测试部门。
去掉 系统监控/ 数据监控 页面
上面的需要 更新sql文件和 生成mysql数据库的补丁文件，不要直接执行，我自己去执行。

http://localhost/system/config  这个页面404， 什么时候删除了？ 原本的内容是什么？





20260729

新增单板 - “热控电机”，子菜单项
新增单板 - “CPA-ZK”，子菜单项
需要更新数据库，更新sql语句。

协议：

遥控遥测协议如下：
热控电机：
配置： XL-RKDJ-TeleMetryCfg.json  XL-RKDJ-TeleControlCfg.json
上位机<->CPA驱动板 RS422 DEBUG
主控板指令通过通信板透传到通信板遥控透传
表格9 遥控指令帧格式（≤8字节）
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据类型	BYTE	1	单帧0x0A
3		设备编号	BYTE	1	CPA驱动板0x93
4		指令码	unsigned short	2	具体内容见遥控配置表
5		校验码	BYTE	1	为“帧头”～“校验和”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后

表格10 遥控指令帧格式（>8字节）
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据长度	unsigned short	2	“数据长度”~“校验和”之间的数据长度
3		数据类型	BYTE	1	复合帧0x0F
4		设备编号	BYTE	1	CPA驱动板0x93
5		指令码	unsigned short	2	具体内容见遥控配置表
6		参数	BYTE	XX（>6）	具体内容见遥控参数表，内部多字节整数需要大端
7		校验码	BYTE	1	为“帧头”～“校验码”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后

表格11 遥测返回数据帧格式
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据长度	unsigned short	2	“数据长度”~“校验和”之间的数据长度
3		源地址	BYTE	1	CPA驱动板0x93
4		目的地址	BYTE	1	上位机星务0x90
5		数据内容	unsigned short	XXX	XXX字节数据内容
参考地检遥测表
6		校验码	BYTE	1	为“帧头”～“校验码”之间的数据按字节进行累计求和的结果



CPA-ZK：
配置： XL-ZK-TeleMetryCfg.json  XL-ZK-TeleControlCfg.json
上位机<->主控板 RS422 DEBUG
主控板指令通过通信板透传到通信板遥控透传
表格12 遥控指令帧格式（≤8字节）
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据类型	BYTE	1	单帧0x0A
3		设备编号	BYTE	1	主控板0x92
4		指令码	unsigned short	2	具体内容见遥控参数表AAXX
5		校验码	BYTE	1	为“帧头”～“校验和”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后

表格13 遥控指令帧格式（>8字节）
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据长度	unsigned short	2	“数据长度”~“校验和”之间的数据长度
3		数据类型	BYTE	1	复合帧0x0F
4		设备编号	BYTE	1	主控板0x92
5		指令码	unsigned short	2	具体内容见遥控参数表AAXX
6		参数	unsigned short	XX（>6）	参数内容
7		校验码	BYTE	1	为“帧头”～“校验码”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后

表格14 遥测返回数据帧格式
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据长度	unsigned short	2	“数据长度”~“校验和”之间的数据长度
3		源地址	BYTE	1	主控板0x92
4		目的地址	BYTE	1	上位机地检0x96
5		数据内容	unsigned short	XXX	XXX字节数据内容
参考地检遥测表
6		校验码	BYTE	1	为“帧头”～“校验码”之间的数据按字节进行累计求和的结果


协议中，单帧和复合帧的判断逻辑顺序是：
1. 先判断单帧，条件：长度<=8, 且 索引2字节是不是0x0a。
2. 不是单帧，在判断是否是复合帧，索引4是0x0f 且 数据长度符合帧长度（字节索引1和2，unsigned short， 大端）
以上都不是，错误中类型。

这里的遥测协议解析器，命名：XL单板遥测，遥测协议中的源地址是子类型。


界面：
新增的这两个界面，界面暂时是一模一样的。
url分别是 rkdj  和 zk

界面布局是左右水平布局，左边占1/3宽度，固定宽度。 右边占2/3宽度。
左边区域，垂直布局，参考单板相机（功能应该一样，只是遥控列表的配置一样），
新建串口连接按钮 区域，只有1个按钮，
遥控命令区域，
传输信息区域，

右边，当前只需要遥测表显示。


遥测内容按照协议提取到有效数据后，按照遥测配置解析， 使用遥测库解析有效数据。
需要数据持久化和曲线支持。


新建串口连接界面参考 相机测试， 现在界面ui没对齐，串口列表和相机测试界面差距很大，新建串口界面需要统一，比如串口列表下拉菜单内的item就和相机测试不一样。
页面刷新后，已经打开的串口，按钮失去了关联，新建串口窗口，com1（已代开）出现了2个。。
菜单，热控电机和cpa-zk 子菜单名字前，前面没有图标
遥控指令列表，指令参数 页面打开是-，需要默认的，参考相机测试

新建串口连接窗口， 现在有单板的相机测试，热控电机，CPA-ZK。
 这三个页面的新建串口界面，串口号的下拉菜单应该做成和下面输入框一样宽，刷新按钮在旁边。
还有这三个界面的新建串口窗口，独立出来，做成单独文件，方便后续调用。页面id绑定之类的参数，传入即可。这里打开串口有参数限制。

首页的 已打开的，ui上不能选择，新建串口这个页面，是不是也可以和上面的新建串口页面统一。只是这里不传入绑定的是首页。
首页的规则特殊，不能修改已代开的串口。这里打开串口没有参数限制。


相机测试页面，控制串口打开后，再次新建传图串口，新建窗口中com1状态没有更新。刷新页面解决。
新建串口连接页面，“新建图像串口连接” 这个标题和下面的控件标题对齐。 所有的控件长度，和串口号的下拉菜单长度对齐。 刷新按钮单独一列。

传输信息窗口，当前我这两个页面时新做的，但是已经有信息了。新加的页面，没有测试过，这个旧的发送信息，肯定是和串口绑定的。
修改reids信息缓存逻辑，
单板的信息展示，需要和页面关联，在一个页面上，我可以打开不能串口连接，可能这次测试使用了com3，但下次测试，这个串口被人用了，我就用com4了，这时候历史记录就需要和功能标识（串口打开时的来源）关联，而不是和串口号。这样对于相机测试页面，原来信息窗显示com3，现在改成显示来源的下拉菜单。
但是旧的和串口关联的也不能丢失，在调试，数据收发页面，还是需要通过串口号去查看串口收发历史。

修改后告诉我现在的redis相关的key


串口连接，串口号下拉菜单，默认选择没有连接的串口，如果没有没有连接的，才按照原来的规则走。

相机测试页面的传输信息区域的信息切换使用了下拉才改，改成横向排布的文字按钮点击，大小和只有1个页面的时候的文字一样大，和1个页面时候位置对齐。


相机测试页面  选中的是蓝色的，是不是把只有1个的时候，默认也改成蓝色，相机测试，热控电机，CPA-ZK 只有1个的时候都修改。

串口默认选择：
再按原逻辑（偏好口 / 首个可选），这个如果是已连接的，  并且还有 未连接的，就改成 选未连接口；否则按照原来的逻辑走。


传输信息， 第一个已打开，打开第二个的时候，信息框不要自动切换到新打开的，原来显示的是什么类型，切换成多个的时候也不切换显示类型。
进入页面后，串口的状态获取优先级高于遥测表。现在是我进入页面，马上新建串口，要等一会才有串口列表信息。

现在串口的连接状态浏览器保存了吗，切换页面也能用。
这样的话，把can，udp 也加入。
当然有有效期。


热控电机和ZK 页面，遥控指令的下拉菜单，默认选择第1个，不要不选

遥测表的配置需要缓存，这样没有数据时候的页面能够快速显示， 当然有有效期。

遥控/遥控页面，左侧指令列表的树，单击树目录展开和点击数目录左侧的箭头展开，这两个是同一个操作还是可以分开的两个操作？


遥控/遥控页面，目录点击和箭头点击分开操作。
选中目录后，把当前目录下的所有命令，同时在中间 循环的显示出来。 相当于中间是个列表了。
展开后，选中具体的一个命令，中间只显示这一个命令。

指令序列页面的树展开逻辑不需要修改。

中间区域的滚动条和  内容的边框碰到了，滚动条往右移动5px，但不要出中间区域。
搜索指令代码的时候，进行筛选的时候，如果选中的是目录，中间区域也需要进行过滤，没有的时候，需要在中间区域进行文字提示（没有选中前，中间区域没有内容，本身有控件显示了提示文字，直接复用）。


遥控/遥控页面，
<div class="panel panel-detail">  这个div 的
<div data-v-d3a07bc2="" class="panel panel-detail" style="
    padding-right: 5px;
">
原来我在F12的css页面时12px，
增加了 padding-right，5这样看上去合理。
你帮我加到vue文件对应的css中。




数据模拟的通用数据发送模拟 加入tooltip
帧组装类型， 如何解析帧头帧尾，目的是为了获取帧的有效数据
帧解析类型，帧的有效数据的编解码
上面的文字描述需要帮我润色。
新建连接的窗口 组装器，解释器
首页列表中的 组装器，解释器
都要加入相同的tooltip

首页的三个新建按钮，放到 设备列表的设备连接标题右边。
新建can，新建udp连接窗口各自独立到文件，参考新建串口，不要放在首页。

这个提示，放在标题右边，缩小，下对其 ：<div class="hint">当前已打开的
表格样式参考 在线用户 界面， 比如标题有独立背景色，行交替背景色，鼠标移上去效果等。

下面这些是表格的标题，没有进行任何修改或者样式修改没有效果。
类型
设备 ID
连接信息
来源
组装器
解释器
打开时间
操作

<div class="app-container device-service-page">  不需要边框，不需要背景色。



更新doc目录，根据最新的改动更新文档


调试/数据模拟
选择透传，xl单板遥测，
发送：EB 90 00 FF 93 90 00 91 00 01 00 01 00 BF 3A FF 35 02 02 00 02 00 02 00 00 00 47 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 58 00 30 00 00 00 31 00 00 00 32 00 00 00 33 00 00 00 34 00 00 00 35 00 00 00 36 00 00 00 37 00 00 00 38 00 00 00 39 00 00 00 3A 00 00 00 3B 00 00 00 3C 00 00 00 3D 00 00 00 3E 00 00 00 3F 00 00 00 40 00 00 00 41 00 00 00 42 00 00 00 43 00 00 00 44 00 00 00 45 00 00 00 46 00 00 00 47 00 00 00 48 00 00 00 49 00 00 00 4A 00 00 00 4B 00 00 00 4C 00 00 00 4D 00 00 00 4E 00 00 00 4F 00 00 00 50 00 00 00 51 00 00 00 52 00 00 00 53 00 00 00 54 00 00 00 55 00 00 00 56 00 00 00 57 00 00 00 58 00 00 00 59 00 00 00 5A 00 00 00 5B 00 00 00 5C 00 00 00 5D 00 00 00 5E 00 00 00 5F 00 00 00 60 00 00 00 61 00 00 00 62 00 00 00 63 00 00 00 64 00 00 00 65 00 00 00 66 00 00 00 67 00 00 00 68 00 00 00 69 00 00 00 6A 00 00 00 6B 00 00 00 6C 00 00 00 6D 00 00 00 6E 00 00 00 6F 00 00 00 70 00 00 00 71 00 00 00 72 00 00 00 73 00 00 00 74 00 00 00 75 00 00 00 76 00 00 00 77 00 00 00 78 00 00 00 79 00 00 00 7A 00 00 00 7B 00 00 00 7C 00 00 00 7D 00 00 00 7E 00 00 00 7F 00 00 00 80 00 00 00 81 00 00 00 82 00 00 00 83 00 00 00 84 00 00 00 85 00 00 00 86 00 00 00 87 00 00 00 88 00 00 00 89 00 00 00 8A 00 00 00 8B 00 00 00 8C 00 00 00 8D 00 00 00 8E 00 00 00 8F 00 00 00 90 00 00 00 91 00 00 00 92 00 00 00 93 00 00 00 94 00 00 00 95 00 00 00 96 00 00 00 97 00 00 00 98 00 00 00 99 00 00 00 9A 00 00 00 9B 00 00 00 9C 00 00 00 9D 00 00 00 9E 00 00 00 9F 00 00 00 A0 00 00 00 A1 00 00 00 A2 00 00 00 A3 00 00 00 A4 00 00 00 A5 00 00 00 A6 00 00 00 A7 00 00 00 A8 00 00 00 A9 00 00 00 AA 00 00 00 AB 00 00 00 AC 00 00 00 AD 00 00 00 AE 00 00 00 AF 00 00 00 B0 00 00 00 B1 00 00 00 B2 00 00 00 B3 00 00 00 B4 00 00 00 B5 00 00 00 B6 00 00 00 B7 00 00 00 B8 00 00 00 B9 00 00 00 BA 00 00 00 BB 00 00 00 BC 00 00 00 BD 00 00 00 BE 00 00 00 BF 00 00 00 C0 00 00 00 C1 00 00 00 C2 00 00 00 C3 00 00 00 C4 00 00 00 C5 00 00 00 C6 00 00 00 C7 00 00 00 C8 00 00 00 C9 00 00 00 CA 00 00 00 CB 00 00 00 CC 00 00 00 CD 00 00 00 CE 00 00 00 CF 00 00 00 D0 00 00 00 D1 00 00 00 D2 00 00 00 D3 00 00 00 D4 00 00 00 D5 00 00 00 D6 00 00 00 D7 00 00 00 D8 00 00 00 D9 00 00 00 DA 00 00 00 DB 00 00 00 DC 00 00 00 DD 00 00 00 DE 00 00 00 DF 00 00 00 E0 00 00 00 E1 00 00 00 E2 00 00 00 E3 00 00 00 E4 00 00 00 E5 00 00 00 E6 00 00 00 E7 00 00 00 E8 00 00 00 E9 00 00 00 EA 00 00 00 EB 00 00 00 EC 00 00 00 ED 00 00 00 EE 00 00 00 EF 00 00 00 F0 00 00 00 F1 00 00 00 F2 00 00 00 F3 00 00 00 F4 00 00 00 F5 00 00 00 F6 00 00 00 F7 00 00 00 F8 00 00 00 F9 00 00 00 FA 00 00 00 FB 00 00 00 FC 00 00 00 FD 00 00 00 FE 00 00 00 FF 93 DA 0A 0D
提示了两遍 未知或不可用的解析器: xl_board_tm
给我一串正确的测试数据，刚才的数据是错误的。

单板测试的三个页面的遥测信息表格，加入
数据时间: 2026-07-30 13:34:59.202
刷新时间: 2026-07-30 13:54:09.885
热控电机和zk界面，收到遥测数据后会显示，但过1秒就不显示数据了，被刷新没了。
我看到刷到数据恢复有rows字段，下一秒的没有rows字段，就变成了默认的。这个要参照遥测的。
{
    "code": 200,
    "msg": "操作成功",
    "data": {
        "type": "RKDJ",
        "name": "RKDJ-热控电机",
        "ts": "2026-07-30 13:53:19.939",
        "dataId": 1785390799939,
        "changed": true,
        "connected": true,
        "dataKind": "tm",
        "dataSub": "RKDJ",
        "srcKind": "http",
        "srcParam": "http:devtest",
        "dataSource": "http:devtest",
        "parserId": "xl_board_tm",
        "rows": [
            {


根据我的经验，最好把 首页/遥测/0xFF：B-1主要包，遥测下的几个页面， 这个页面的内容做成通用的遥测表格功能页面。
遥测页面加载使用它， 单板中的三个页面直接加载这个功能页面。
需要把功能页面的<div class="tm-header">  这个的样式  做成两种，
遥测页面一种，间隔大，这是一整个页面，空间大，上下padding大没问题，
还有一种是小区域的，几乎没有上下padding，占据了右边的下半部分，空间小，不能留太多的空白。
然后只要指定用哪个遥测表格，遥测类型，剩下的逻辑都是一样的（获取数据，更新等），需要统一。
首页/遥测 下的逻辑都是测试通过的，单板三个页面的遥测功能如果和首页/遥测有冲突，服从首页/遥测的功能。


1. 遥测的标题部分，不同使用方式的界面需要统一，优先全部使用遥测页面的，比如类型，来源，数据时间，刷新时间，统一使用遥测页面的。
2. 功能修改，tm-title 这部分显示统一规则，可以是标题，也可以是下拉菜单，后面部分ui所有页面都一样。
这样在把遥测传入的遥测参数改成数组，比如相机页面传入的数组有两项，其他页面只有1项（但也传入数组），
显示规则：超过1个就用下拉菜单，如果传入的是一个（也用数组参数，但是数组长度只有1个），就直接使用标题， 这个不区分页面。
ruoyi-fastapi-frontend/src/components/Payload/PayloadTelemetryTable.vue 的样式我有修改，在我基础上优化。
3. 还有不同页面padding大小现在合适，但传入PayloadTelemetryTable的参数，改成传入类型t1，t2，t3（类似于标题的h1, h2）,对应不同的head部分样式。，预定义好多种样式。

上面这样修改后，title部分是不是代码规整了，if-else分支最少。


http://localhost/telemetry/curve
首页/遥测/遥测曲线  和 遥测归档数据 界面，
标题部分界面优化，
遥测表 和 起始时间， label 右对齐，然后 下拉菜单和时间输入框都是200px宽。
遥测量  和 结束时间，也是 右对齐，现在就是对齐的，不能把它改掉。





遥测库更新了，新增了api和解析字段calc_val。
遥测曲线使用新增的解析字段画曲线  calc_val, 后端返回的时候修改下。
class TeleMetryLine:
    err:  bool   = False
    id:   str    = ""
    name: str    = ""
    show: str    = ""
    unit: str    = ""
    hex:  str    = ""
    # Numeric value after formula (if any), before value-map lookup for show.
    # Type follows fmt / dataType: int for integer formats, float for float formats.
    calc_val: int | float = 0
    val:  Number = field(default_factory=Number)



调试菜单下新增 “遥测计算”，更新菜单sql，帮我更新数据库。
姐买你，遥测表和遥测字段的选择下拉菜单，Hex文本输入框，计算按钮，点击计算得到结果，显示在下方表格。
表格的样式参考遥测表格，标题列数都参照，tooltip也需要，在最后行放入时间，这个表格相当于历史记录。
每计算一次，新增一行，插入在表格行首，比如我连续计算jgb001， 这个就会连续新增多行。
最大100条，在redis缓存， tooltip也是，这是历史记录。
只有在计算的时候，后台收到计算请求的时候，需要判断字段在不在。

使用遥测库新增的 parse_line_hex 可以方便的获取值
单字段解析：`parse_line`、`parse_line_hex`
test\TeleMetry的库代码已经更新。


遥测 遥测计算， 解析失败: 字段解析返回错误，  这个还是要把值返回前端，然后提升还在，然后前端还是显示，缓存还是添加。
Hex输入框前端加入缓存

前端编号列，文字 不要蓝色，不要下划线

前端 下拉菜单也缓存。
然后hex输入框，发送前，先把hex格式化 按照数据收发页面，串口发送二进制的规则格式化。

增加复选框，位数不够的时候，前面补零 还是 后面补零，现在是后面补零。
帮我选个复选框的文本，默认选中，后面补零。 也加入前端缓存
在hex输入框后

刚才的修改还原，这个补零不是前端操作。
让后端去补。
比如JGB008， 是4字节，但前端只给了 33 01 02  三个字节，前补零是 00 33 01 02， 后补零是 33 01 02 00。
{
  "no": 8,
  "id": "JGB008",
  "name": "广播时刻（秒）",
  "bytepos": 13,
  "bits": 32,
  "bitpos": 0,
  "showType": 0,
  "formula": "D+8*3600",
  "unit": "",
  "fmt": "%time",
  "value": {},
  "dataType": "UINT32",
  "variableName": "unBroadcastTimeUtcSec"
}

复选框增加tooltip


xl单板遥测数据解析，
固定为0xEB90
“数据长度”~“校验和”之间的数据长度， 这个不包含数据长度这个本身的长度。 原来的计算没问题，我修改了ruoyi-fastapi-backend\module_payload\parsers\xl_board_tm.py 的 parse_frame提示，
CPA驱动板0x93
上位机星务0x90
XXX字节数据内容
参考地检遥测表
为“帧头”～“校验码”之间的数据按字节进行累计求和的结果  ： 这个不包含帧头 ，我修改了ruoyi-fastapi-backend\module_payload\cfg\xl_board_telecontrol_assembler.py 的assemble_xl_board_order 函数。

遥控指令
固定为0xEB90
单帧0x0A
CPA驱动板0x93
具体内容见遥控参数表99XX
为“帧头”～“校验和”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后： 这个不包含帧头

帮我检查下我的修改对不对。还有没有遗漏的。




1. 遥控指令，指令生成的时候，如果是复合帧，需要对复合帧的长度进行检查， 发现错误，需要修改长度为正确的值，并返回正确的指令，并进行提示。当前长度写在了固定字段中，可能写错了。
字段名称	字节数	说明
帧头	2	固定为0xEB90
数据类型	1	复合帧0x0F
数据长度	2	“数据长度”~“校验和”之间的数据长度
设备编号	1	CPA驱动板0x93
指令码	2	具体内容见遥控参数表99XX
参数	XX（>6）	具体内容见遥控参数表
校验码	1	为“帧头”～“校验码”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后


2. 调试-配置文件页面，单个文件的重载配置没有效果，需要全部重新加载才有效。

3. 单板测试的，相机，热控电机，ZK的遥控窗口，遥控title 后面，加入导出按钮，文字按钮，比遥控字体要小，下边框对齐。
导出json格式数据，对象数组， 当前所有指令的预览的数据的列表，直接在前端的数据上导出，可以不通过后端。
对象包括：
"id": "D1516",
"name": "刹车模式",
hex：“EB 90 00 05 0F 92 AA 10 FF 5F”
len ：“hex的字节数， 10”

4. 调试-配置文件页面，每一行后，加入导出按钮，导出所有指令的对象列表，同上，只是这次值都是用默认值，上面的使用的是页面已经预览的值。这个需要后端导出。


1. 单板遥控「导出」按钮位置在向下移动5px。
2. 对于错误长度的数据，预览和发送，会提示复合帧长度字段已纠正，但输入控件修改值，修改了预览，但不提示。这两个有什么不一样吗？  还有这个纠正错误，是改了配置还是只修改了当前的临时输出？ 这条不用修改，回答就行。
3.单文件重载，不要兼容旧别名，去掉兼容。



遥测数据测试使用下面规则：
每种类型（can，各种单板），比如平台收到每秒1000份数据，缓存0.5秒，每秒处理2次，在数组中，它只需要对最新的一份数据，进行遥测数据的解析，因为网页刷新显示帧率也就1。
其他的数据不需要表格显示，但这些数据会被拿去画曲线，不需要完整解析，进行点的解析。
持久化保存进数据库，数据库新增字段：原始数据（二进制保存）， ，新增解析的点数据字段（json）。
实时曲线仍读 Redis，查历史/跨长时间窗口才主要用payload_tm_frame，获取解析的点数据字段，
 删除 payload_tm_field_num 表。

 持久化写入数据库payload_tm_frame的时候，parsed_json这个字段需要解析出来，显示的时候，解析了最新的，存入redis够用了。

结合这个实际情况，进行优化。

test\TeleMetry代码已经更新,根据新的库接口说明调整代码。

TeleMetry这个使用方式不对，直接传bytes给parse。
payload_hex = ' '.join(f'{b:02X}' for b in payload)


存储的二进制数据，是提取的有效数据frame.payload，也就是给TeleMetry 传入的bytes。
我想要达到的效果是，当前如果有多种类型连接着，每种类型的缓存数据，最新的一条一定要完整解析。
然后所有数据需要解析曲线点。

入队的数据，是什么类型的数据，是frame吗？
frame，解析了所有曲线点和一帧完整的，解析好的数据放入了入队的数据的对象种吗？没放入是不是会在归档 worker 中二次解析？

一定要base64吗，redis能二进制吗？
不能的话，就转成hex格式代替base64， AABB 这种格式。
然后数据库，raw_bin  还原回原来的raw_hex, 存完整复合帧的hex，不是有效载荷。


所有的can，serial，udp的 不同功能的默认连接信息写在配置。
cfg_device_connect.json 对象，不同连接一个key:obj, 比如相机的控制，图像串口等， 新建连接中的来源的唯一标识。
放在后端config目录。前端去加载。

去掉配置中home部分，首页不限制。
其他配置是在其他页面中，新建的时候，需要限制。


can的库更新了，根据新的库，使用can_protocol_client接入协议biu和xl。
新建can连接的时候，原来的组装器是透传，现在新建can连接，只有这两个新的类型，CAN-BIU和CAN-XL，这两个是can专属，其他连接也不能使用他们。

解释器名字修改：CAN遥测复合帧 改成 BIU-CAN遥测复合帧。
新增 XL-CAN遥测复合帧， 先复制XL单板遥测的协议实现。


首页的新建can连接，有透传选项，方便进行can测试，对应的传入can_protocol_client的类型就是none。
  can_biu: 'tm_can_yc',  改成 tm_can_biu, 传入 can_protocol_client的类型就是 biu
  can_xl: 'xl_can_tm',  改成 tm_can_xl, 传入 can_protocol_client的类型就是 xl




1. 遥测曲线的遥测下拉菜单， 前面放XL或BIU 进行分栏， XL放前面。

2. 遥测页面，这些遥测页面删除，
0xFF:B-1主要包
0xFD:B-2捕跟...
0xFB:
0xF9:B-4-1指...
0xF7:B-4-2星...
0xFE:
0xFC:算轨异...
改成两个，名字遥测表BIU和遥测表XL，页面通过遥测表下拉菜单选择不同的遥测表，参考遥测曲线的遥测下拉菜单。  这里的页面应该是同一个，只是请求参数不一样。

3. 遥控菜单，原来的遥控子菜单改成遥控指令BIU ， 新增 遥控指令XL。 这里的页面应该是同一个，只是请求参数不一样。
在遥控指令列表上方，放入新建CAN连接-A，新建CAN连接-B，按钮样式和操作习惯，参考单板的新建串口连接，配置好标识，更新cfg_device_connect.json文件，新增can的两类参数。
两个新建按钮边上，放当前发送can口，选择哪个发送，就标识指令使用哪个can口发送。
需要在一行内搞定，看下选择使用哪个ui控件，需要考虑只连接了一个时候。

4. 遥控菜单，控制开关 改成 控制-BIU，新增控制-XL。 旧的协议路径名字需要修改， 需要和新增的有统一格式的路径，方便代码规整，整齐。
参考test\pygpcan 下的 DemoBIU.py 和 DemoXL.py 。
demo页面最顶部的连接参数和业务参数线缆不需要，参考 遥控指令列表上方的can按钮组，复用。 遥控指令BIU页面 和 控制BIU


can连接，删除目标地址。

菜单：
遥控指令BIU 改名 遥控指令-BIU
遥控指令XL 改名 遥控指令-XL

遥测表BIU  改名 遥测表-BIU
遥测表XL  改名 遥测表-XL

BIU菜单遥控连接区域，新增下拉菜单，目标地址下拉菜单  0x0D：激光终端B， 0x0C：激光终端A


遥测表页面，只读取 BIU-TeleMetryCfg.json  和 XL-TeleMetryCfg.json 。两个文件中内部key是唯一的，但跨文件不保证唯一，程序中使用key的时候，尤其是redis，需要多层，比如BIU:FF  XL:FF

（已实现）
- 遥测表/曲线下拉仅来自上述两文件；API page.key = BIU:FF / XL:FF（localKey 仍为 FF）
- Redis：payload:tm:BIU:FF:latest / payload:tm:BIU:FF:curve:{field}；归档 data_sub 同
- TeleMetryParser 仍用文件内本地 key（FF）
- PayloadTelemetryTable 跳转曲线只需传 type=BIU:FF，不必再拼 family（此前 fam 是为区分跨配置同名 key）



test/pygpcan 代码已更新，测试过， v502和usb pro，双通道同时打开没问题，新版库已经按照。所以你的修复代码是不是方向就错了。
详细扫描下test/pygpcan 代码 和  测试用例， test.py等，看下使用帮助。

can sdk 没更新前，正确，更新后，can的连接逻辑没有变，所以这块错了，是不是修改过度了。
最近所有改动都在 SHA-1: 8d958cc7efff62ecb751f7ae93121eee16061925 中，检查后端的代码，是不是改错了。

（核查结论）
- test/pygpcan 新库已用 DeviceRefTable 正确支持同卡双通道（见 test.py / tests/test_sdk_channels.py）；后端 venv 里仍是旧 whl（二次 OpenDevice），方向不该打 V502 补丁。
- 已删除 can_v502_multichannel_patch.py；process_manager 回退为原热开逻辑，仅保留「已有其它通道时热开失败不杀进程」。
- 已用 test/pygpcan 源码 force-reinstall 到 venv；厂商列表兼容新 CanVendorInfo。
- 会话僵尸清理保留（后端重启后遥控按钮假「已连接」）。


当前的can通道是写死的，新版的sdk，已经提供通道数量，

can连接窗口，如果 设备索引号 的 下拉菜单只有1项的时候，这个disable掉，不用选择。
遥控菜单下，来源，需要区分biu cana， 还是xl can-a。，需要修改成 biu_can_a, xl_can_a

对于已经连接的，使用了现有的连接，需要提示 已使用现有can卡并绑定本页参数，而不是现在的 “设备已打开”， 和串口处理一个逻辑。 还有，比如 首页已打开这个设备， “CAN    can:1:0:0   vendor=1 · 卡0 · 通道0  首页    透传（默认）    BIU-CAN遥测复合帧   2026-08-10 14:12:32”，在can连接页面需要提示 已经连接， 像串口一样。
当然 can的连接提示， 需要复杂点，在 厂商 有 已连接 提示，情况下， 设备，通道 对应的也需要有提示。


新建can连接窗口，删除 线缆 下拉菜单。
首页新建的时候，不指定线缆，CanProtocolClient的参数cable_param 就是None
新建窗口的时候，点击新建can连接-a， 创建的时候，就是A线缆。


当前发送切换的时候，发送历史不要切换，
需要修改成 发送历史是这个页面的历史，包括cana + canB的数据。
还有在发送历史的具体条目，OK 状态，改成 使用哪个ch发送的。写 CAN-A ,或 CAN-B.


遥控菜单目录结构修改，
遥控下， 改成BIU， XL 两个子目录，这两个子目录下，有控制，遥控，指令序列，
对应的路径之类的都需要修改，通过路径 ，就能很好的区分项目。
在该项目下，比如指令序列，就需要用查询xl项目的，如果想在不能区分xl，biu项目，指令序列数据库表就需要修改。
数据库目录修改的补丁脚本，直接帮我执行了，我是使用mysql
我本地的测试数据库是： mysql -h192.168.100.100 -uroot -p123456 ruoyi-fastapi
我本地的redis：192.168.100.100:16379


新建can连接窗口中，通道号0: CAN1  改成 0:CAN0

遥控界面打开的 新建can窗口，组装器 不能修改，而且 biu打开的默认选择biu，xl打开的默认xl，解释器也是。
还有遥控界面打开的 新建can窗口， 波特率限制500Kbps， 不能修改， 如果波特率不匹配，不能选择。

首页，can的连接信息中，也需要加入 115200bps 波特率，放在最后，vendor=1 · 卡0 · 通道1 · 115200bps，只需要修改这个地方，其他地方不需要加上。

遥测表页面中，不使用 遥测表 和 它的下拉菜单，删除它，因为页面需要留更多的空间显示表格。
src\components\Payload\PayloadTelemetryTable.vue  这个页面支持传入列表，它自身有下拉菜单功能


首页增加 关闭所有连接 的按钮，放在刷新的右边。点击按钮，需要确认弹窗。

BIU和XL的遥控的控制页面，增加系统区域。
原来can的demo也有，test/pygpcan/DemoSDK.py DemoXL.py。
biu：只有一个按钮，can重置
xl有下拉菜单选项。

当前的关闭所有连接， 是通过一个个close，会出现 数据正在处理，请勿重复提交。
修改参数传数组，或者新增一个api。


XL的协议更新， 数据类型的顺序上移了一位，放在了帧头下，数据长度前（原来是数据长度后）。
这样数据长度的计算也有变化了。
但是类型的位置和遥控单帧的格式统一了，变成帧头，数据类型。

表格10 遥控指令帧格式（>8字节）
序号	字段名称	数据类型	字节数	说明
1		帧头	unsigned short	2	固定为0xEB90
2		数据类型	BYTE	1	复合帧0x0F
3		数据长度	unsigned short	2	“数据长度”~“校验和”之间的数据长度
4		设备编号	BYTE	1	CPA驱动板0x93
5		指令码	unsigned short	2	具体内容见遥控配置表
6		参数	BYTE	XX（>6）	具体内容见遥控参数表，内部多字节整数需要大端
7		校验码	BYTE	1	为“帧头”～“校验码”之间的数据按字节进行累计求和的结果，高字节在前，低字节在后

→ 已做（不改上文旧协议记录，仅实现新布局）：
1. `xl_board_telecontrol_assembler.py`：复合帧改为 `EB90 | 0x0F | len(2) | … | chk`；类型固定索引2（与单帧一致）；长度在索引3–4，值为「长度字段之后～校验前」字节数（不含类型）。
2. `XL-RKDJ-TeleControlCfg.json` / `XL-ZK-TeleControlCfg.json`：复合帧组件顺序与长度已按新协议迁移。
3. 单测与分类逻辑已同步；遥测帧、CAN 遥控（`XL-TeleControlCfg`）未改。
4. 配置重载后生效。



调试-配置文件， 对表格分组。
规则：以第一个-分割文件名，前缀分组。
cfg_device_connect.json, 这个没有-，就放入其他。
当前就有 XL，BIU，其他，三组。
分组显示，最好是在一张表格分成三组，显示顺序大概是下面所示：
BIU
表格行
XL
表格行
其他
表格行

→ 已做：
1. 前端 `debug/config/index.vue`：同一张表插入分组行，顺序 BIU → XL → 其他；文件名取第一个 `-` 前为组名，无 `-` 归「其他」。
2. 后端列表补充 `cfg_device_connect.json`，否则「其他」组为空。


discover_files, 我觉得 可以扫描这个目录下所有的json文件，
然后显示方面，BIU，XL，其他，左对齐，放在表格行最左边，换一个颜色，

→ 已做：
1. `discover_files` 改为扫描 config 目录下全部合法 `*.json`。
2. 分组行标题左对齐靠最左，主色文字 + 浅主色底。

现在的BIU等的背景色太亮，刺眼，可以不加或者改成不刺眼的。

→ 已做：分组行改为浅灰底（`--el-fill-color`）+ 次要文字色，去掉刺眼主色底。


cfg_device_connect.json  配置文件，也添加一个字段     "datetime": "2026-07-27 16:55:28", 写入的时候添加。
然后 这个配置中 的can， 这个应该是区分  biu，xl的，需要有biu_can_a, biu_can_b, xl_can_a 这样的。
还有  can的保存属性 下面几个都 不需要了， 因为这里配置的是 新建连接的时候，这几个属性是限制死了，直接使用这里的值，不让用户修改，    "cableFlag": 1,     "canIndex": 1,    "devIndex": 0   。
can还需要新增assemblerId 和 parserId， baudChoices 属性， 这个对于biu和 xl是限制死的，当然首页的新建can连接窗口不会限制。 baudChoices  只有500。

→ 已做：
1. `cfg_device_connect.json`：根级 `datetime`；CAN 改为 `biu_can_a/b`、`xl_can_a/b`；去掉 cableFlag/canIndex/devIndex；增加 assemblerId/parserId/baudChoices=[500]。
2. 配置文件保存 `cfg_device_connect.json` 时自动刷新 `datetime`。
3. 遥控 CAN 工具栏按 source key 读配置；首页 CAN 对话框仍不锁定。


首页/单板/相机测试 中 新建控制串口连接， 我配置中 baudChoices 是两个，但实际显示只有1个，波特率不能选。
    "camera_ctrl": {
        "label": "相机控制串口",
        "kind": "serial",
        "baudrate": 2000000,
        "baudChoices": [2000000, 11000000],
        "dataBits": 8,
        "stopBits": 1,
        "parity": "O",
        "flowControl": "NONE",
        "assemblerId": "passthrough",
        "parserId": "camera_sc_link41ep"
    },

→ 已做：控制串口此前 `baudEditable` 写死 false。现改为 `baudChoices` 多于 1 个时可在列表内选择，并按白名单匹配已开串口。



XL的遥控配置文件配置字段新增。
对于每一条指令，component字段中的对象，新增属性formula 和  dataTypeUI。
dataType是指令生成时候，最终数据的格式，比如FLOAT， 4个字节， 生成指令需大端。
新增的 dataTypeUI，是给前端 ui限制输入用的， 如果这个字段不存在或存在为空，则使用dataType，旧配置兼容。
新增 formula字段，如果字段不存在或为空，都按照 formula是空处理。

比如下面的，dataTypeUI是FLOAT，前端允许用户输入float， 后端收到后，需要计算公式formula （如果公式存在，非空）得到新的值， 然后再把这个值转换成 dataType的类型。
minVal，maxVal 限制的是输入的范围，是给ui限制用的，旧版本配置，只有dataType，限制的也是显示输入框的限制值，
新版本也是限制前端输入框传过来的值。 这样前端ui可以根据minVal，maxVal 直接限制输入值。
如果minVal或maxVal 存在， 如果为空字符串，则不进行限制。
{
    "title": "幅值",
    "componentType": "number",
    "dataType": "BYTE",
    "unit": "",
    "minVal": "",
    "maxVal": "",
    "defaultVal": "",
    "options": {},
    "formula": "D*100",
    "dataTypeUI": "FLOAT"
}

当前只有XL的 D1503 指令配置了 这两个字段。

公式计算使用遥测扩展包 exec_formula 函数，这个函数返回的都是float。
公式的使用方式参考测试用例：test\TeleMetry\tests\test_tinyexpr.py

→ 已做：
1. 后端 `encode_component`：number 先 `exec_formula`（formula 非空），再按 `dataType` 大端组帧。
2. 前端 `XlBoardPage`：输入类型用 `dataTypeUI`（缺省回退 `dataType`）；`minVal`/`maxVal` 空串不限制。
3. `XL-RKDJ` D1503 与 ZK 对齐（INT32 + formula + dataTypeUI）。


这个改动所有的遥控相关的页面都涉及到，用到遥控配置文件 ***TeleControlCfg.json  的功能都会用到。
还有遥控指令生成，所有配置文件的规则都是统一的，配置文件本身格式和解析都是使用一套方式的。
后端遥控配置的使用，最好封装成一个类，类构造参数是遥控配置json对象或json文件路径，
内部解析配置，提供对外API，如：
获取配置列表，
生成指令，传入key（如：D1503），传入参数列表，返回生成结果。
等现在配置相关的功能用到的api进行统一。
当然这个相同指的是遥控指令json文件格式，指令格式，指令生成规则，ui显示规则，这些都是相同的，
但设计到具体业务，比如BIU，遥控的协议具体格式和 XL的协议格式，sum计算等，肯定是不一样的。

还可以封装manager， 管理所有的遥控配置的类对象，这个你看实际情况需不需要。
可以理解为这是一个功能重构，先写计划，


 kind：can_bus | xl_board | camera（由文件名/注册表推断），
按 kind 调协议策略，返回现有字段（hex、length、tip/frameType 等）
这里有点不理解，



计划补充，
XL-RKDJ-TeleControlCfg.json
整个项目中，使用这个配置功能的唯一id，可以统一成 xl-rkdj-tc, 转成小写。
XL-Camera-TeleControlCfg.json 就是 xl-camera-tc
BIU-TeleControlCfg.json  就是 biu-tc

→ 说明（计划已按此更新）：
1. **cfgId** 与 **protocol** 分开：cfgId=`xl-rkdj-tc` 标识哪份 JSON；protocol=`can_bus`/`xl_board`/`camera` 是组件拼完后用哪套封帧/校验（现有三套，不合并）。原先写的 kind 指的是 protocol，不是配置 ID。
2. 「返回现有字段」= 仍调用现在的 assemble，返回继续带 `hex`/`length` 及该协议原有 tip/frameType 等，不换字段名。
3. 统一 cfgId：`biu-tc`、`xl-tc`、`xl-rkdj-tc`、`xl-zk-tc`、`xl-camera-tc`。HTTP 的 family/board 可保留，内部映射到 cfgId。

→ 已做（TeleControlCfg 统一封装）：
1. 新增 `module_payload/cfg/telecontrol_cfg.py`：`TeleControlCfg` + `TeleControlCfgManager`，cfgId/protocol 分离。
2. Loader/reload、telecontrol/xl_board/camera/export 走 Manager；HTTP 兼容。
3. 前端 `telecontrolComponent.js` 接到单板/相机/遥控指令页；assemble 传 family。
4. 单测 `tests/test_telecontrol_cfg.py`。


以代码审核的角度，看下刚才的重构功能有没有问题，有没有需要改进的


序列编辑页 还需要补充一点，原来是值能直接还原的，现在遇到有公式的字段，没有还原的公式，通过指令的hex得不到原值，这里就用默认值了。
上面提到的全部修改吧。


→ 已做（按审核项 + 公式还原规则）：
1. **序列编辑页**：assemble 传 `family`；接入 `telecontrolComponent`（`dataTypeUI`/min·max）；有 `formula` 的字段无法从 hex 反推，还原一律用 `defaultVal`。
2. **CONFIG_DIR** 单源：`telecontrol_cfg` 引用 Loader 的 `CONFIG_DIR`。
3. **缺文件**：`_load_json` 打日志并抛 `ServiceException`；`get_order`/`list_orders` 深拷贝。
4. **assemble 分支**精简；XL 单板/相机 controller 统一走 `TeleControlCfgManager`。
5. **protocol** 只读注册表；同步 Loader 缓存失败打 `warning`；单测补 reload 别名 / 缺文件 / 协议选择。


首页/遥控/***/遥控， 指令序列界面， 输入控件修改后，类似于单板界面，直接调用预览组帧，

→ 已做：序列编辑页改参 change 后立即预览组帧（showLoading=false，与 XL 单板一致）；去掉 text 输入的逐字 input；手动「预览组帧」仍保留。

首页/遥控/BIU/遥控  这个界面也需要修改，还有XL的。

→ 已做：BIU/XL 遥控指令页（command/index）改参后立即预览组帧（showLoading=false）；与序列/单板一致。


遥控指令， 搜索指令代号的过滤输入框，当前规则不变，
搜索的范围还需要新增，在当前的基础上， 还需要遥控配置中每个字段的titile。
只要这条的id + name （原规则）， 或  component 数组下的有一个title中匹配上，都是可以的。
匹配规则不变。
最好把这个遥控的匹配规则封装下，现在单板菜单下几个界面，遥控菜单下几个界面 都是相同的规则。

→ 已做：抽出 `telecontrolOrderMatch.js`（空格分词；命中 id/name/component.title）；接到遥控指令、指令序列、XL 单板、相机遥控搜索。


首页/遥测/遥测归档数据  的 遥测表 下拉菜单，需要参考 遥测曲线界面，这两个是一样的。

→ 已做：归档页遥测表下拉与曲线页对齐（XL/BIU 分组、可搜索、宽度 280、loadFields 带 family）。

遥测曲线和 遥测归档数据  xl分组，需要新增单板的三个界面的遥测数据，一共4份，相机有2份。

→ 已做：曲线/归档 XL 组合并 4 份配置——XL 总线 + RKDJ + ZK + 相机（相机 D8/D9 两表）；单板/相机表键与 Redis data_sub 一致；前端按 page.family 拉字段。


首页/单板/相机测试 页面，
修改图片保存按钮位置，放到 图片刷新按钮后。
在原图片保存按钮位置，新增复选框显示质心位置， 选中显示质心位置，就在图片中，用红色的十字星，十字星的横线，10px长，1px宽， 竖线 10px长，1px宽。 十字星的位置就是质心坐标（这个坐标不是图像缩放后的坐标系，需要根据缩放系数转换）。

新增功能。
在 图片显示的 帧率 下新增一行，这一行的每个元素长度也是固定的，参数帧率这一行，
内容包括
坐标：D8.CAM004, D8.CAM005  (遥测表中取值， 没有的时候空)   D9.CAMF004，CAMF005
光斑能量(dBm)：D8.CAM009   D9.CAMF009
过阈值像元数：D8.CAM006   D9.CAMF006
饱和像元数：D8.CAM007  D9.CAMF007
平均灰度值：D8.CAM008  D9.CAMF008


上面的数据可以在 全窗模式下慢遥应答帧 D8 和快遥测的D9 中找到，看那张表的时间新，就用那张表的数据。

→ 已做：相机测试页—保存按钮移至刷新后；原位复选框显示质心（红十字星，按缩放换算）；帧率行下新增 D8/D9 遥测统计行；质心取 D8/D9 更新时间较新表坐标。



这个文件src\components\Payload\CameraImageView.vue 的布局，当前界面有部分元素显示不全。
重新设计界面布局
分为左右水平两部分，
右边是图像，左边数操作按钮和数据展示部分。
左边部分，垂直布局，
上是操作按钮， 就是分辨率下拉菜单这一行。
下是水平布局的两张表格。
表格1，帧率这一行， 两列，  第一列是标题
表格2， 坐标，光斑能量这一行， 两列，  第一列是标题

→ 已做：CameraImageView 改为左右布局（左：操作栏+两列表格；右：图像区）；表格1 帧率行数据，表格2 遥测统计行，均为标题|值两列。


修改ui布局，把左边部分，改成垂直布局。
左边中的左边，操作按钮，垂直一排分布，分辨率，下拉菜单需要两行，每个元素一行。
左边中的右， 表格合并成1张表格，现在的第二张表格合并到第一张后。

→ 已做：左侧改为操作栏（纵向每项一行，分辨率标题+下拉分行）|单表格并列；两表合并为一张。


需要修改成分辨率一行，分辨率的下拉菜单一行，现在两个是一个 el-form-item， 可以拆开。
图像序号也是。
图片刷新，图片保存按钮可以宽度减小，尽量给右边表格更大宽度。
右边图像区域，宽高是421*414， 宽度可以减少7px。做成正方形。

→ 已做：分辨率/图像序号标题与下拉拆为独立行；刷新/保存按钮收窄；右侧图像区 aspect-ratio 1:1 保持正方形。


单板-相机界面的遥控指令和信息 区域变大了好多，大小应该和其他界面的一致，比如 单板-热控电机 这个界面。

→ 已做：相机页左右栏比例与热控电机对齐（grid 1fr:2fr，遥控 flex 1.4）。

把 滚轮缩放·拖拽平移·双击复位 放到左边最顶部，不放在图片上，
图片刷新按钮 保存按钮和 下拉菜单一样宽。
表格区域现在又空余空间了，
 表格和操作按钮区域之间留更多空白，表格刚好够就行，剩余的宽度，给图片显示区域

→ 已做：操作提示移至左侧顶部；刷新/保存与下拉同宽 96px；表格固定刚够宽度并与操作栏加大间距，剩余宽度给图像区。


滚轮缩放 · 拖拽平移 · 双击复位   右对齐。
表格 宽度刚好情况下，出现了水平滚动条。

→ 已做：操作提示右对齐；表格去掉水平滚动条（列宽/容器对齐）。

单板-相机界面
当前 表格中，比如坐标会显示  D8 x,y
新增一行，在坐标行前，title 遥测表， 内容 D8:慢遥测(全窗) / D9:快遥测(开窗)
然后下面的列，不需要显示D8 开头的数据。

→ 已做：坐标行前增加「遥测表」行（D8:慢遥测(全窗) / D9:快遥测(开窗)）；下方数值不再带 D8/D9 前缀。

行的值是 D8:慢遥测(全窗) / D9:快遥测(开窗)  二选一，需要根据当前是从那张遥测表获取值在显示，都没有，就显示空

→ 已做：「遥测表」行按 dataId 较新的 D8/D9 二选一显示；都无则空；下方数值与质心同源。


我需要把表格的两列宽改成 120  160


遥测表格切换显示的时候，采用哪个表格的时间，需要看 数据时间: 2026-08-11 16:55:22.253， 不是接收时间。

→ 已做：择表改为比较 D8/D9 的「数据时间」`ts`（与界面「数据时间」同源），不用接收/刷新时间，也不再用 dataId 比新旧。


在图片刷新按钮的上一行，新增 复选框 自动拍照， 默认选中，
选中后，图片刷新按钮点击后， 需要先发送串口控制消息
CAM_A10 - 拍照 - 13 字节， 控件参数：  缓存数量 1， 缓存间隔(帧) 0.
帮我自定组件消息，因为每次发送，有个自增长的计数器，不能写死。

图片刷新按钮上，在新增一个按钮，刷新一次 按钮， 这个按钮是点击一次，就刷新一次图片，不是连续刷新。

→ 已做：图片刷新上方增加「自动拍照」（默认勾选）与「刷新一次」；勾选后点图片刷新先组帧发送 CAM_A10（seq 自增，数量1/间隔0）再连续采集；「刷新一次」启采集取一帧后停止。



发送串口控制消息 后 需要间隔10ms后，在开始获取图像数据，
发送串口控制消息的 缓存数量  根据图像序号 获取。
这个串口消息，也需要加入到日志中去，算是发送串口消息。

→ 已做：自动拍照 CAM_A10 缓存数量取图像序号(1–64)；发送成功后间隔 10ms 再启图像采集；走与手动发送相同的 telecontrol/send，写入控制串口传输 IO 日志。


图片刷新的逻辑有问题。
一次刷新，发送指令后，在执行一次刷新，刷新图片需要传图串口传输完整的帧，收到图片后才是一次完整流程， 这时候按钮才能亮起来。
连续刷新，也是同样道理，在一次图片流程完成后，需要继续同样的流程。
这样是不是后端传图的流程也需要修改。
如果选中了自动拍照，
流程是 拍照指令，sleep 10ms， 开始传图， 收到图片，显示。前端在继续这个流程。
没有选中自动拍照， 流程是 开始传图，收到图片，显示。
没修改前，后端是不是有一个取图的线程，一致在获取数据不停的。
现在是不是需要插入发送指令的过程，需要打断原来的逻辑。

→ 说明与已做：
- 修改前：`camera_start` 后采集进程 `tick` 里会不停 `_acquire_image_once`（连续拉图），前端只是定时读 Redis。
- 自动拍照在控制串口，必须插在两轮传图之间，因此改为「一次完整收图」编排，不能再让后端无停连拉。
- 后端新增 `once=true`：采完整一张写入 Redis 后自动停，不清掉这张图。
- 前端单次/连续都走同一轮：`(可选 CAM_A10 → sleep 10ms) → start(once) → 等到新图显示`；连续则收完后再开下一轮；按钮在整轮完成（或停止）后才恢复。

自动拍照，发送的参数，现在从左边的遥控指令列表的CAM_A10 - 拍照 控件中获取。 如果控件不存在，就按照参数 缓存数量 64， 缓存间隔(帧) 0 发送，不从图像序号取数据。

→ 已做：自动拍照参数改取左侧 CAM_A10 的 `valuesForOrder`；无 component 控件时回退 `0x01 / 64 / 0`，不再用图像序号。

自动拍照复选框，加入tooltip， 发送的参数设置在 CAM_A10 - 拍照 上 设置，
帮我重新组织这个tip的提示语言，大意是如此。

→ 已做：「自动拍照」增加 tooltip：勾选后刷新前先发左侧「CAM_A10 - 拍照」；参数在该指令控件中设置。


串口消息发送，遥控指令那边，会提示发送成功，然后刷新预览帧列表。
但自定刷新的指令发送后，预览帧这里，也需要刷新，不需要提示发送成功。

→ 已做：自动拍照发送后仍更新左侧 CAM_A10「指令参数」HEX 预览，不再弹「发送成功」；失败仍提示。


开始刷新前，发送了指令，提示 如果有自动刷新，提示开始刷新并获取图片， 如果没有自动刷新， 提示开始获取图片。
自动刷新和刷新一次，都需要提示，自动刷新每次都要提示

→ 已做：每轮传图（连续/一次）在开始拉图前 ElMessage 提示——有自动拍照为「开始刷新并获取图片」，否则「开始获取图片」；连续每轮都会提示。

使用下面的样式提示

→ 已做：上述提示改为 `ElMessage.success`（与「串口 发送成功」同款绿色勾选样式）。

当前 遥测表格 D8/D9 第一次切换的时候，从d8切换到d9，
会把坐标， 光斑能量(dBm)， 过阈值像元数， 饱和像元数， 平均灰度值，
这些数据清空，过一会就正常。
不应该清空，如果D9没有数据，就保持d8的数据。
而且，这个界面，d8和d9需要都请求，现在应该都是。

→ 已做：D9 无统计值时继续显示 D8；空壳遥测行不再覆盖已有有效快照；D8/D9 仍由 `refreshTmStats` 双请求。

串口，如果串口已经打开情况下，这时候拔掉usb串口，硬件设备没有了，但是后台没有刷新串口状态，认为串口还连接，但是发送数据是失败的。
系统需要获取串口列表，根据串口是否还存在，判断串口的打开关闭状态，这个在后端做，前端的所有接口都不用变。

→ 已做（仅后端）：
- 采集进程：约 1s 对照 `list_ports`；USB 拔出 / SerialException 时写断开状态并退出进程。
- `list_serial_opened`（含 snapshot）：对照系统串口列表，端口已消失则自动 stop+关会话；前端接口形状不变。


连续刷新的时候，前端提示修改，从 开始刷新并获取图片 变成 第 {n} 次拍照并获取图片
刷新一次的提示不修改，从 开始刷新并获取图片 改成 开始拍照并获取图片 。

→ 已做：连续刷新提示「第 n 次拍照并获取图片」；刷新一次提示「开始拍照并获取图片」（勾选自动拍照时）。



相机测试界面，遥测数据显示窗口，需要根据获取到的遥测数据，自动切换d8 还是d9 显示。
d8 或 d9 同一时间，只会有一种数据会刷新（只会有一种有有效数据，虽然同时获取了，但数据一个是没有的）。如果同时都来数据，按照数据时间，显示切换到最新时间的。
这是因为不同的开窗模式（分辨率）， 设备只会返回其中的一种， 400*400， 是D8， 其他分辨率都返回D9。
根据最新的遥测数据（D8 D9中，找最新的有效数据），获取分辨率值， 然后根据实际分辨率，设置分辨率下拉菜单，
如果在自动刷新过程中，下一帧的自动刷新，使用新的分辨率。

→ 已做：按 D8/D9 最新有效数据自动切遥测表；分辨率从 CAM027/CAM029（及收图宽高）同步下拉，连续/单次刷新下一轮用新分辨率。

收图的宽高是不准的，它是你要多少分辨率的，图片就会给多少分辨率。

→ 已做：分辨率下拉不再用收图宽高回写；只跟遥测开窗字段（CAM027/CAM029）同步。

收图的宽高是不准的，它是你要多少分辨率的，图片就会给多少分辨率。


自动切换后，现在人不能手动切换遥测表了。
只需要这样的情况，自动切换，原来是D8的有效数据，后面来了d9有效数据，自动切换。如果已经d9数据了，在来d9就不要自动切换了。
同理，现在是d9数据，来了d8，自动切换，d9情况下来d9不用自动切换。
简单说是有效数据类型变了，才需要自动切换，

还有现在的请求密密麻麻的，这个页面这么多请求，说明下每个请求的作用。
能不能把遥测表请求的参数，改成数组传输，参数还是原来的参数，只是改成参数对象的数组。
目的是减少请求次数。

table?type=D9&datald=1786445452612
io-log?deviceld=source%3Acamera_ctrl&sinceSeq=50809&limit=200
table?datald=1786444431769&needCfg=false&tableKey=D8
table?datald=1786445453131&needCfg=false&tableKey=D9
table?type=D9&datald=1786445453131
table?datald=1786444431769&needCfg=false&tableKey=D8
snapshot?parts=serialOpened
io-log?deviceld=source%3Acamera_ctrl&sinceSeq=50860&limit=200
table?datald=1786445453657&needCfg=false&tableKey=D9
table?type=D9&datald=1786445454681
table?datald=1786444431769&needCfg=false&tableKey=D8
table?datald=1786445454681&needCfg=false&tableKey=D9
table?type=D9&datald=1786445455224
io-log?deviceld=source%3Acamera_ctrl&sinceSeq=50887&limit=200
table?datald=1786445454681&needCfg=false&tableKey=D9
snapshot?parts=serialOpened
table?datald=1786445456230&needCfg=false&tableKey=D9
table?datald=1786444431769&needCfg
table?datald=1786444431769&needCfg=false&tableKey=D8
io-log?deviceld=source%3Acamera_ctrl&sinceSeq=50936&limit=200
table?datald=1786445457268&needCfg=false&tableKey=D9
table?type=D9&datald=1786445457268
table?datald=1786444431769&needCfg=false&tableKey=D8
snapshot?parts=serialOpened
table?datald=1786445457268&needCfg=false&tableKey=D9

http://localhost/dev-api/payload/telemetry/table?type=D9&dataId=1786445796767
http://localhost/dev-api/payload/device/io-log?deviceId=source%3Acamera_image&sinceSeq=22728&limit=200
http://localhost/dev-api/payload/device/snapshot?parts=serialOpened

→ 已做 / 说明：

**自动切表**：仅当有效类型 D8↔D9 **发生变化** 时才改下拉；同类型新数据不再强切，可手动切换查看。

**原请求作用（改造前为何密）**：
- `/payload/telemetry/table?type=D8|D9`：遥测表组件自己轮询当前选中表
- `/payload/camera/telemetry/table?tableKey=D8|D9`：页面为统计/切表再各拉一遍 D8、D9（与上重复）
- `/payload/device/io-log`：传输信息收发日志（控制/图像串口）
- `/payload/device/snapshot?parts=serialOpened`：串口是否仍打开（含拔线核对）
- 另有：采图 `/camera/image`、遥控 assemble/send、开关串口等（按操作触发）

**减请求**：
- 新增 `POST /payload/camera/telemetry/table/batch`（及通用 `POST /payload/telemetry/table/batch`），`items: [{ dataId, needCfg, tableKey }]`
- 相机页改用 batch 一次拉 D8+D9；遥测表 `externalFeed` 不再自己轮询，由页面喂数


PayloadTelemetryTable.vue  这个控件有自动拉取遥测数据的功能吗？
如果没有，最好是做在这个页面中，因为遥测数据显示，这个页面是统一的，数据获取也可以有这个页面接口控制，而且数据都是在redis，也是统一的。这个页面，传入的是数组（当前1个也是数组吧，我记得是这样的），就由这个页面批量取拉取。
其他页面的遥测数据拉取请求，都应该废弃掉。
你看下这个功能重构，先做个计划，看看需要改哪些？
除了这个界面需要请求外，其他是不是都能废弃掉了。



更新计划，
一共两个拉取api，批量和单独，但这两个的服务器api，路径要差不多，不能相差很多。
/payload/telemetry/table/batch
/payload/telemetry/table
现在是这两个吗，如果是的话，这个是合理的。

然后单独是留给 telecontrol/control/index.vue， 这类功能使用的。
批量是遥测表封装使用的。

遥测表的封装PayloadTelemetryTable，新增自动切换的逻辑。
就是刚才的相机页面的切换逻辑，“自动切换后，现在人不能手动切换遥测表了。只需要这样的情况，自动切换，原来是D8的有效数据，后面来了d9有效数据，自动切换。如果已经d9数据了，在来d9就不要自动切换了。同理，现在是d9数据，来了d8，自动切换，d9情况下来d9不用自动切换。简单说是有效数据类型变了，才需要自动切换，”。
现在只有相机页面需要开启。默认false，变量自动切换表格，true | false。切换的规则就是相机的规则。


批量拉取的时候，原来好像会传上次数据的时间，这个不能丢弃。不然批量拉取，每次都是满表格的数据。
大部分情况下，只更新了一张表格，所以就算批量拉取，数据和一张表格差不多。


更新计划：
PayloadTelemetryTable 需要会缓存数据，如果外部UI需要使用数据，可以提供对外api，返回遥测表格的数据。
可以返回整张表，所有表，指定表+指定key等。
这个现在有吗？没有的话补充进计划。
然后需要删除的代码及ui，api也需要写完全。
比如现在的相机，想要获取遥测表数据，就可以通过api获取。

→ 已做（遥测表拉取统一到 PayloadTelemetryTable）：

**HTTP API（仅保留这两条拉表）**
- 批量：POST /payload/telemetry/table/batch，items: [{ type, dataId, needCfg }] — 仅 PayloadTelemetryTable 使用；每 type 带上次 dataId，未变不全量回表
- 单独：GET /payload/telemetry/table — 留给 telecontrol/control 等非表格页

**组件**
- PayloadTelemetryTable：按 types 数组 batch 自拉 + snapByType 缓存
- autoSwitchType（默认 false；相机页 true）：仅有效类型 D8↔D9 变化时切表
- expose 读缓存：getAllSnaps / getTable / getField / getFields / getActiveType / getEffectiveType；事件 @snaps-change
- 已删：externalFeed / applyExternalData

**相机页**
- 经 ref + @snaps-change 同步本地 tmSnap 做统计/质心/分辨率；不再父级 HTTP 拉表

**已删除的重复入口**
- 前端：getCameraTelemetryTable、getCameraTelemetryTableBatch、getXlBoardTelemetryTable
- 后端：GET/POST /payload/camera/telemetry/table(+batch)、GET /payload/board/{board}/telemetry/table 及对应 VO

**空表骨架**：通用 PayloadTelemetryService.get_table 无热层字段时按 cfg 填空行（与原相机 table 行为一致）

请求 URL
http://localhost/dev-api/payload/telemetry/table/batch
请求方法
POST
状态代码
422 Unprocessable Content

→ 已修：batch 的 dataId 来自 Redis 为数字，VO 原只收 str 导致 422；后端改为 str|int|None 并转 str，前端发送时 String(dataId)。

遥测表-XL页面，没有数据的，每次都会返回配置表，有数据的后面都会简化。"needCfg":false 传了好像没用。
请求http://localhost/dev-api/payload/telemetry/table/batch
{"items":[{"type":"XL:FF","needCfg":false},{"type":"XL:7E9B","needCfg":false},{"type":"RKDJ","needCfg":false},{"type":"ZK","dataId":"1786428941589","needCfg":false},{"type":"D8","dataId":"1786445546343","needCfg":false},{"type":"D9","dataId":"1786445796767","needCfg":false}]}
响应的数据每次都是 完整的表格（可能是空的配置行，但每一行都在），每一张表格的rows很多。

→ 已修：无 Redis 热层时，空配置 rows 仅在 needCfg=true 回一次；needCfg=false 且无 data 则 changed=false、不回 rows（前端保留本地骨架）。有 dataId 且未变仍走增量。

我在相机页面，打开了串口，这时候获取遥测数据。
但我离开了相机页面，切到了遥测-xl页面，这时候开始获取遥测数据。
问题：这两个页面同时在获取遥测数据，每次都能看到两次请求遥测数据。都走批量接口。

→ 已修：keep-alive 缓存页切走不 unmount，PayloadTelemetryTable 在 onDeactivated 停轮询、onActivated 恢复；相机页 linkTimer/连续刷新同样 deactivated 停。

还有iolog也是，页面切换了，还是保留着在请求
再看下其他页面是不是也有这种情况。

→ 已修（keep-alive 切页停轮询）：
- 组件：PayloadTransferInfo(io-log)、IoLogPanel、CanConnectToolbar、PayloadTelemetryTable（此前已修）
- 页面：camera/XlBoard linkTimer、telecontrol control 状态轮询+广播、sequence 运行轮询、debug xfer/simulate、lvds engineering
- 原本已有：curve、command


相机测试页面，控制串口收到了大量的数据 704280 多。
read_and_parse 只卡到一次断点，
data = self._read_serial(waiting) 收到了大量数据，data这么大，704280， 然后这么多数据中，1帧54字节。
self._push_io('recv', data) 执行明显慢。
我用其他串口工具软件打开过，设备一直在出串口数据，
但是后台系统只10都分钟后又卡到了断点，数据长度 2099000 . 断点在read_and_parse的data = self._read_serial(waiting) 行.

→ 已修：根因是 read(in_waiting) 一把读光 + _push_io 整包转 HEX 写 Redis，采集环路阻塞后驱动缓冲更大。串口默认 RX 按 4KB×最多32块/tick 排空；IO 日志 HEX 截断至前 256 字节（len 仍为真实长度）。


for _ in range(MAX_RX_CHUNKS):
    waiting = self._in_waiting()
    if waiting <= 0:
        break
    data = self._read_serial(min(waiting, MAX_RX_CHUNK))
    if not data:
        break
    self._push_io('recv', data)
    self._rx_count += 1

这里waiting 有2092226， 是还没有取出的数据吗？ 能不能加快？

我当前串口的波特率是 2000000，这个数据大吗？

→ 说明 / 已加快：
- waiting/in_waiting = 驱动缓冲里**尚未 read 走**的字节，不是「已解析未显示」。2092226≈2MB 积压。
- 2Mbps + 8O1 约 11bit/字节 → ~182KB/s；2MB 约等于十来秒没排空（断点/慢 _push_io 都会堆）。对持续满流来说流量不小，但对单次读缓存可以很大。
- 积压≥64KB 时：块改 16KB、每 tick 最多 128 块（约 2MB）、IO 日志每 16 块写 1 次；ingest 仍每块做，优先追上缓冲。


是不是redis收发的网络压力很大。


传输数据改成保存文件日志,bin格式,文件名以标志开头连接的标志， 然后再紧接着日期时间,时间到毫秒 xl_can_b_20260708_112233_321.bin  使用这样的日期格式。。
文件创建规则满足最小100兆, 至少1分钟,比如当前文件已经保存了超过1分钟，而且大小超过了100兆，需要切换成一个新的文件保存。
文件的大小，程序内自己统计，就是插入了多少个字节。保存logs_data。
关闭连接的时候，文件也可以关闭文件句柄
所有数据，包括can、串口和lvds数据保存文件，只有can数据需要同时保存数据库。
文件保存功能封装成一个类，参数是连接标记，文件保存类负责时间和大小的计算，新文件的切换等。文件写入需要异步执行。
不同连接创建不同的文件保存类对象。关闭后，可以销毁这个对象，但这个对象如果有文件还没有保存，注意数据不能被丢弃。
快速的新建连接关闭连接的问题也要处理好，不要打开就创建文件，如果没有数据，直接多次打开关闭就一大堆空文件，需要有数据了才开始创建文件。
还有比如串口，比如首页创建的，这个时候有一个文件保存对象。这时候这个连接被热控使用了，又有新的保存了，这个时候的保存对象注意切换，数据来源不一样，不能混淆。
还有数据保存，最终路径是 logs_data/20260708/xl_can_b_20260708_112233_321.bin .


修改计划，
can的接收数据， 改成文本文件日志，后缀txt, xl_can_b_20260708_112233_321_recv.txt。

can的保存格式是 时间 id [hex]，每行一条消息，然后 组包后，还有一条消息，但这条消息的id部分用8个空格代替，需要对齐， 内容是拼接好后的消息。
具体如下示例如下：
20250102144321 00000769 [00 BF 3A FF 33 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 45 00]
20250102144321 0000076A [DC 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 09 08 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 6E 4C 71 A2 05 97 00]
20250102144321 0000076A [81 00 00 00 02 11 01 C8]
20250102144321 0000076A [0C B1 42 70 00 00 3F 2D]
20250102144321 0000076A [74 BE 44 C3 61 9A 41 6E]
20250102144321 0000076A [BF 80 00 00 6D C3 80 26]
20250102144321 0000076A [00 00 55 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 01 00 02 00 21 1F]
20250102144321 0000076A [AA AA AA AA 00 00 00 00]
20250102144321 0000076A [00 00 30 FF 0C 00 FC 00]
20250102144321 0000076A [00 10 00 00 00 00 00 00]
20250102144321 0000076A [03 00 CC 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076A [00 00 00 00 00 00 00 00]
20250102144321 0000076B [00 4C]
20250102144321          [00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C]

can 发送也需要日志文件，xl_can_b_20260708_112233_321_send.txt，格式也同接收。
相当于一个硬件打开，有两个文件需要保存。文件保存类初始化，传参的时候，需要注意接收和发送日志。

其他硬件的发送日志文件， 也是使用文本格式日志，serial_COM4_20260708_112233_321_send.txt
格式如下：一次发送一行，时间 [hex]
20250102144321 [00 BF 3A FF 33 00 00 00]
20250102144321 [00 00 00 00 00 00 45 00]

其他硬件的接收还是bin格式，bin格式是纯裸拼流,xl_can_b_20260708_112233_321_recv.bin。

→ 已做（传输落盘）：
- 类：ConnectionTransferLogger（一连接双文件 _recv/_send，懒创建，≥1分钟且≥100MB 切卷，异步队列写，close flush）
- 路径：logs_data/{YYYYMMDD}/{tag}_{YYYYMMDD}_{HHMMSS}_{mmm}_{recv|send}.{bin|txt}；tag 优先会话 source，home 用设备 id
- CAN：收发均为 txt；单帧「时间 id [hex]」；组包行 id 位 8 空格（can_collector feed 出包后写）
- 串口/网口：recv 裸 bin，send txt「时间 [hex]」
- 挂点：BaseCollector._push_io 旁路；session_changed 切换 logger；teardown/关通道 flush
- Redis 预览与 CAN MySQL 归档保留；LVDS 仍为 demo，预留同接口

我觉的下面这个处理不好，kind不需要判断在不在这里面吧，只要不是can，是不是就都按照非can流程走？不要下次新增硬件，还要来修改这个文件？
self.kind = (kind or 'serial').strip().lower()
if self.kind not in ('can', 'serial', 'net', 'lvds'):
    self.kind = 'serial'
当然我没有完全审阅全，不知道我这里理解对不对。

→ 已修：kind 只区分 can / 非 can（is_can）；非 can 统一裸 bin 收 + txt 发，不再维护 serial/net/lvds 白名单。


我觉的下面这个处理不好，kind不需要判断在不在这里面吧，只要不是can，是不是就都按照非can流程走？不要下次新增硬件，还要来修改这个文件？
self.kind = (kind or 'serial').strip().lower()
if self.kind not in ('can', 'serial', 'net', 'lvds'):
    self.kind = 'serial'
当然我没有完全审阅全，不知道我这里理解对不对。


当前保存文件名： zk_20260812_085044_573_send.txt， zk这个标记是不是太简单了，
有更详细的吗？

→ 已改：文件名前缀改为 `{source}_{设备id}`，例如 `zk_serial_COM4_20260812_..._send.txt`；首页 home 仍只用设备 id（如 `serial_COM4_...`）。需重新开连接后生效。


所有硬件的发送的日志文件，文件名 20250102 以日期结束，相当于一天一个文件。
can 接收的日志 文件名，也是改成一天一个。xl_can_b_can_1_0_1_20260812_send.txt
注意隔日的文件名切换规则。
其他硬件接收的保持不变。

→ 已改：
- 所有 send、CAN recv：`{tag}_{YYYYMMDD}_{send|recv}.txt`，一天一个；隔日自动切到新日目录/文件；同日重连追加
- 非 CAN recv：仍为带时分秒毫秒的 `_recv.bin` + 满1分钟且≥100MB 切卷
（示例里 CAN 接收后缀应为 `_recv.txt`）


单板相机测试，我刚才把保存数据库的操作删减了，现在控制串口接收数据后，处理的还是非常慢。
ruoyi-fastapi-backend\module_payload\collectors\base_collector.py run函数的while self._running  这个执行，1分钟都不会进一次断点。 运行到self.read_and_parse() 这个函数后，运行1分钟以上。
read_and_parse的 waiting0 = self._in_waiting()  waiting0超过了 20万。 说明数据还是多的处理不过来。但波特率才2M。
和我详细说明下，获取到数据后，read_and_parse这个函数做了什么操作？比如解析、比如存数据库。
详细说明是在当前子进程的当前线程，其他线程等

→ 说明（控制串口 read_and_parse 路径，见对话）：采集子进程主线程同步做读串口、Redis io-log、assembled、拆 D8/D9；MySQL 不在此线程；落盘写文件在 logger 后台线程；遥测字段解析/曲线/归档入队在 0.5s Timer 线程。waiting0=20万 ≈ 1 秒积压；主线程若单次处理 >1s 就永远追不上 2Mbps。

我现在是快遥测，前端D8的数据，10s才更新一次，前端从redis获取数据，后端慢，但数据为什么刷新的这么慢？
我直接查redis这个key， payload:serial:COM3:assembled:latest 更新 10s 一次 。这个key更新后，为什么前端的遥测页更新也会在5s后，比redis慢5s， 遥测请求每秒都在做吧。

→ 说明：前端不读 assembled:latest，读的是 payload:tm:D8:latest / payload:tm:D9:latest。快遥应看 D9；D8 本就是慢遥，10s 一帧是协议周期不是前端轮询。assembled 10s 一次=采集主线程卡住。assembled 之后还要 0.5s 批处理+整批 parse 才写 tm:latest，大批量时会再晚数秒，所以页面比 assembled 慢约 5s。

前端正常，就是redis payload:tm:D8:latest 更新慢。 快眼慢摇都是 20m的速率，1秒发上千次。

→ 已修：D8/D9 千帧/秒时不再等 0.5s 整批 parse 才写 latest。入队即限频（20Hz）parse 当前帧写入 tm:*:latest；曲线/归档 0.5s 抽样。溢出丢旧不在主线程全量解析。assembled 限频、session 缓存 1s。


redis当前提交是批量的还是一条条的，特别是解析出的曲线数据。

http://localhost/dev-api/payload/camera/image?port=COM4
为什么1s有4次请求？

→ 说明：连续/单次收图时 `runImageCycle` 在等 Redis 出图，循环里 `getCameraImage` + `sleepMs(200)`，约 5 次/秒，加上请求耗时看起来就是 ~4 次/秒。不是后台定时器，停刷新后应停止。

修改成500ms请求1次

→ 已改：`runImageCycle` 等图轮询改为 `sleepMs(500)`。


遥测表格控件修改，遥测量修改了，是红色，但是下一帧遥测数据是空的（没变），这时候，不应该刷新遥测表格，表格的元素如果涂红了，应该还是红色的，现在是这些颜色没有了。
如果有数据返回，是一样的，红色去掉应该的。没有数据（数据时间没有变），就不要刷新表格了。

→ 已修：PayloadTelemetryTable 轮询时若当前表 `changed=false`（无新 rows），跳过 `paintActiveFromSnap`，保留变红；有新数据再重绘，值未变则去掉红色。


单板测试-相机业中，初始图像默认是414px， 这个修改成400*400

→ 已改：CameraImageView 无图时黑方逻辑分辨率固定 400×400（不再用视口高度≈414）；有图仍按视口高度铺满正方形。


修改了配置ruoyi-fastapi-backend\assets\config\XL-Camera-TeleMetryCfg.json，  配置重载无效， 全部和文件单个重载都无效。

单板相机页面强制刷新(ctrl+f5)好几次，遥测表格还是旧版的配置。是不是网页当前有遥测配置缓存，所以不更新？
还是遥测表返回的数据，解析就没有更新？
遥测配置不是有一个时间吗，是不是能利用这个时间。
我关闭串口，在打开，还是没有更新。
我过了几分钟再去看，更新了。

→ 根因（三层缓存叠在一起）：
1. **浏览器 localStorage**：`telemetryCfgCache`（`payload:tmCfg:v1:*`）默认 **1 小时** TTL。Ctrl+F5 **不会**清 localStorage，所以硬刷新仍画旧表头。
2. **有 Redis 热数据时**：表格行来自解析结果字段（名称/行序），会盖住刚拉到的 cfg 骨架；关串口若不重启采集进程，子进程里 TeleMetryCfgManager 仍是旧配置。
3. **后端「重载配置」**原先只清 API 进程内存；**采集子进程**不感知，解析继续用旧 JSON。过几分钟才变，多半是 TTL 到期或进程碰巧重启。

→ 已改：
- 表接口每次带回 `cfgDatetime` / `cfgMtime`；前端与缓存比对，不一致则重新拉 cfg。
- 表格展示：**行序/名称/单位以 cfg 为准**，数值按 id 叠 Redis。
- 配置调试页重载/保存遥测配置时 `clearAllTelemetryCfg()`。
- 重载通知采集进程 `reload_tm_cfg`；解析器按文件 mtime 自动重新 init；关开串口（session_changed）也会重置解析器。


ruoyi-fastapi-backend\module_payload\service\payload_camera_service.py 中，
start函数中，
        if not alive:
            device_id, _already = mgr.start_serial(
                body.port,
                {
                    'baudrate': 2_000_000,
                    'source': 'camera_image',
                    'resolution': body.resolution,
                    'image_no': body.image_no,
                },
            )
这里波特率写死了 2_000_000， 是不是不对，就算要用也是上一次连接过的配置？

→ 对，不该写死。正常应由页面先 open（弹窗里选的波特率），start 只发 `camera_start`。已去掉该兜底 `start_serial`：串口未打开时直接报错「请先连接后再采图」，避免用错误波特率抢开串口。


单板测试-相机，保持图片按钮下，新增按钮图片上传，支持上传png和bmp图片，不传到后台，浏览器获取图片数据后，用于在图片显示区域显示，同时更新分辨率。

→ 已加：相机页「图片保存」下增加「图片上传」，仅本地选 PNG/BMP，FileReader 读成 data URL 显示，不请求后端；按图片宽高更新显示区分辨率与下拉（如 400×400）。


图片上传后，默认以图片像素大小显示，不进行缩放。当前上传后变成了满屏

→ 已改：上传图走 CameraImageView `nativeSize`，按图像宽高 1:1（CSS 像素=图像像素）居中显示，不再铺满视口；设备采图仍按原正方形铺满。滚轮缩放仍可用。

设备采图和本地上传，都需要根据原来的缩放比例，位置显示，相当于图像内容替换，其他什么都不变。
如果新上传或从后台新获取的设备采图图片的分辨率不一样，先重置位置和尺寸，在显示。

→ 已改：采图与上传统一按像素尺寸显示。同宽高只换图，保留缩放/平移；分辨率变化则复位到 1:1 居中再显示。

窗口刷新，默认的第一张图是黑色的，默认尺寸是400*400， 我上传400*400，也会被重置。

→ 已改：默认黑方按 400×400 计入上一帧尺寸。上传/采图同为 400×400 时只换内容，不复位缩放和位置。


把设备采图的图片进行浏览器缓存，缓存有效期10分钟。 有新的设备采图，就刷新缓存。

→ 已加：设备采图写入 localStorage（`payload:camera:deviceImage:v1`），TTL 10 分钟；新采图覆盖。页面刷新未过期则恢复显示。本地上传不写入该缓存。


token有效期太短，需要改长，改成24小时。

→ 已改：JWT 本身已是 1440 分钟；真正提前失效的是 Redis 会话 `JWT_REDIS_EXPIRE_MINUTES`（原 30 分钟），已改为 1440（24 小时）。需重启后端生效。


单板测试-相机，鼠标滚轮进行图片缩放时候，缩放的锚点有误，我希望是当前鼠标位置为锚点进行缩放，
就是鼠标只想区域的图片像素内容就一定在那里，比如当前图片显示内容是一个小圆圈，我鼠标指向它，进行缩放，这个圆形就一直在我的鼠标下。。

→ 已改：滚轮缩放以鼠标位置为锚点，调整 offset 使该点屏幕坐标不变；指向的像素（如小圆）会留在光标下。



编写一个单独的串口数据收发程序，模拟的是单板相机传图的功能。
pyqt界面程序，
界面整体是垂直布局。

第一行，连接区域，水平布局，串口列表下拉菜单，刷新按钮，波特率下拉菜单（只有两项），连接按钮（连接成功变成关闭）连接后，其他控件disable。

第二区域，选择文件按钮（选择png或bmp，）， 生成图片按钮，分辨率列表。
生成图片要求，随机生成一份根据选择的分辨率的数据, 数据的值范围是200-255， 然后随便找一个区域，大小为n*n的像素区域，填充值0。可以借助numpy， 数据单字节，范围0-255之间。
n: 最小值10， 最大值： 图片像素的1/2 和 50的最小值。最大值和最小值之间的随机数。
选择或生成后，放在预览区域。

第三行， 发送进度，根据收到的请求，显示提示文本。

接下来，图片预览区域。


脚本放在ruoyi-fastapi-backend\scripts目录。
程序的请求，只识别 传图请求帧，其他全部丢弃。

然后根据请求序号，读取这里面的数据，可能不会全部用完。
然后以图像下传应答帧进行回复。

使用pyqt6 ，不要使用Pillow，只依赖pyqt6就行，不想再安装其他扩展。
需要识别请求帧的分辨率，根据请求帧的帧标识，请求帧的帧数量计算规则，计算出分辨率，然后计算出尾帧需要填充多少内容。

参考日志文件：
test/serial_test_data_64x64.txt
test/采图1次的收发日志.txt

测试的时候，单独运行这个程序，后台发送指令，就可以获取到数据。

→ 已加：`ruoyi-fastapi-backend/scripts/camera_image_serial_sim.py`（PyQt6）。只应答 D6 传图请求（10B），按序号切本地图回 266B；尾帧用 seq+1 反推分辨率并计算填充。串口 8O1，波特率 2000000/11000000。需 `pip install PyQt6`，用虚拟串口对连接地检「图像串口」。


单个图片刷新按钮，等待图像超时太久了。
http://localhost/dev-api/payload/camera/image?port=COM1
这个请求了20多遍以上，返回的都是
{
    "code": 200,
    "msg": "操作成功",
    "data": {
        "image": {
            "meta": {},
            "data": "",
            "format": "png"
        },
        "status": {
            "deviceId": "serial:COM1",
            "connected": true,
            "message": "图像采集失败(首帧)",
            "state": "running"
        }
    },
    "success": true,
    "time": "2026-08-13T08:54:31.416891"
}

后端尝试失败了已经停止，前端获取的状态不对。优化后端状态记录，如果已经不在重试了，用上新的状态，前端也有对应的提示。

→ 已改：单次采图失败且不再重试时，image meta 写 `phase=failed`（串口仍 `running` 以免误判断开）。前端轮询见到 failed 立即停并弹出失败原因，不再空等到 90 秒。




ruoyi-fastapi-backend\scripts\camera_image_serial_sim.py
这个推算分辨率的计算方式不对，首帧推算不出来的。首帧，中间帧都是满数据发送。
尾帧才能推算出分辨率。推算不出来，直接从数据0开始取数据。

→ 已改：首帧/中间帧不推算分辨率，按 seq 从图像开头切满 256 字节；仅尾帧用 seq+1 反推分辨率并计算填充。尾帧推不出则从偏移 0 取满 256 字节。

分辨率能推算出来的，分辨率都是n*n， 尾帧看下已发送总和，然后从1开始遍历出n的值，n有最大值，就是当前（seq+1）*256 的 sqrt，这个是总像素的最大值。

→ 已改：尾帧用已发送 seq×256 与上限 (seq+1)×256，n 从 1 遍历到 floor(sqrt(上限))，取剩余像素落入本帧的最大 n（正方形 n×n）。推不出则仍从偏移 0 取满 256。


n*n 需要大于 seq*×256
在界面上增加，接收指令，指令是否正确等提示信息。
等待传图请求，单独一行，这一行就是提示行。

→ 已改：尾帧条件明确为 n×n > seq×256。界面单独一行提示：未连接 / 等待传图请求 / 接收指令正确（含 HEX）/ 接收指令不正确（原因）。


读取 test/camera_400x400_no1_20260812_154849.png  报错，
提示 PyQt6.sip.voidptr object has an unknown size。  这是400*400， 保存的图，但我不知道保存的时候是灰度还是rgb颜色。

→ 已改：不是 PNG 灰度/RGB 的问题。相机页保存只是把当前 `imageSrc` 另存为 PNG（设备图一般是后端灰度 PNG；本地上传可能是 RGB）。模拟器读图时本来就会 `convertToFormat(Format_Grayscale8)`，两种都能用。真正报错是 PyQt6 的 `QImage.constBits()` 返回 `sip.voidptr` 没有长度，`numpy.frombuffer` 读不了。已改为先 `asarray(sizeInBytes())` / `sip.voidptr(ptr, nbytes)` 再拷成灰度矩阵。

这个脚本需要处理好缓存相关问题，当前我测试发送下面的指令，不正确。
EB 90 D6 04 00 01 00 00 01 DC

→ 已改：这条本身是合法首帧（校验 DC 正确）。原先组帧缓存有问题：找不到完整 `EB 90` 会把半截 `EB` 清掉；解析失败又一次丢 10 字节，把后面的真请求吃掉；上次 266 字节应答残留/回显也会被当成「长度 0x0101 不是 0x0001」。现已：打开串口清驱动收发缓存；按 EB 同步，半截帧等待；优先取出缓存里完整合法请求；应答帧整帧静默丢弃。请重新连接串口后再发这条指令。



当前脚本，收到串口指令后，就断开串口连接了。

→ 已改：应答写失败或处理异常不再自动关串口，只在提示行报错并继续等待请求；仅当端口已不存在/已关闭时才断开。写超时加到 5 秒。请重新连接后再发指令。



单板测试-相机 界面的分辨率选择是 64*64，400*400， 然后选择 刷新图片， 然后这个分辨率突然变成256*256.

→ 已改：刷新时 `imageOnceBusy`/`imageRefreshing` 为真，遥测 CAM027（设备当前开窗常是 256×256）会覆盖刚选手动分辨率。现改为：用户手选后不再用遥测改下拉；清空选择后才重新跟 CAM027/CAM029。



双击重置图像，是缩放变成1，按照实际像素显示，位置正中，现在双击重置是 铺满屏幕

→ 已改：无图黑方原先按视口最短边缩放，双击 scale=1 就会铺满。现与有图一样：始终 宽×高×缩放（1 CSS 像素 = 1 图像像素）居中；双击复位为缩放 1、偏移 0。


ruoyi-fastapi-backend\scripts\camera_image_serial_sim.py
的提示文字，提示区域固定两行高，用文本区域进行提示，不然界面或抖动。
提示文字示例：
接收指令正确 EB 90 D6 01 00 01 02 70 01 4B尾帧 seq=624图像序号=1→按行400x400推算400x400(nxn=160000>已发送159744)，尾帧有效256字节、填充0字节，已应答

→ 已改：提示改为只读 QTextEdit，高度固定两行，长文换行、超出可滚动，预览区不再跟着文字高低跳。

刷新按钮和选择图片按钮在串口连接后不disable。 还是可以继续操作。但操作后获取的数据，如果没有在传输中，直接替换。
如果在传输中等本次传输结束替换当前数据，先缓存起来。
如果传输过程中，多次刷新，只替换缓存数据。

→ 已改：连接后「刷新 / 选择文件 / 生成图片 / 分辨率」仍可操作。空闲则立刻换发送图；传图中（首帧到尾帧）新图只写入缓存（多次操作只保留最后一张），本轮应答完再替换。当前这一轮仍用首帧时的快照，不会中途换像素。

数据缓存，界面不要刷新，需要传输完成在刷新界面上显示的图片。
然后启动的时候，界面显示的随机图片没有铺满全屏，点击刷新后图片就铺满全屏。

→ 已改：传图中换图只写入缓存，预览仍显示当前正在发送的图，本轮结束后才刷新预览。启动后在窗口 show/布局完成时再按预览区尺寸缩放，避免 __init__ 时控件还没撑开导致随机图很小。


当前还是点击生成图片，立即刷新预览区域了。 是不是有没有在传输过程中的判读有问题？

→ 已改：原先 GUI 只看排队过来的 `xfer_begin`，且工作线程只在首帧才发这个信号；中间帧已经在传时标志仍可能是假，生成图片就会立刻刷新预览。现在以工作线程里的传输快照为准：任意帧开始会话就置 `in_xfer`，GUI 同步查询该标志；首帧重试不再重新抓图；只有尾帧才结束会话并替换预览。


还是不对，是不是在传输中，通过判断尾帧收到，就是传输结束状态。还有其他的判断吗？

→ 已改：传输状态只剩两步——收到首帧/中间帧进入传输，只有收到尾帧才结束。去掉 GUI 信号、`_xfer_arr is None` 等其它结束判据。传输中点生成只写缓存；预览强制钉在本轮快照上，尾帧应答完才换成缓存图。请重新启动模拟器脚本后再试。


还是不对。这有这么难吗？
点击生成图片，生成了数据，如果遇到传输中（状态遍历，封装函数，在通过函数获取状态是否在传输中），就不更新图片。
生成图片，是主线程处理。是否在传输中是函数调用，和信号量这些有什么关系？
大不了是状态需要跨线程。

→ 已改：按这个做了。`TransferState` 是窗口上的共享状态（锁保护），串口线程收到请求置忙、收到尾帧清忙。主线程点生成只调用 `is_transferring()`，忙则只缓存不画预览，空闲才更新图片。判据不再走 Qt 信号。



首页/遥测/遥测曲线
曲线界面，我曲线的数值范围也就在108-109波动（y轴），如果我勾选了X轴缩放或Y轴缩放，  y轴范围就变成了1~15000.
这个不合理，不知道是如何计算的。
勾选x轴缩放，是为了滚轮能够缩放x轴。
勾选y轴缩放，是为了滚轮能够缩放y轴。
两张截图是勾选x轴缩放前和勾选后的。

→ 已改：原先一个 dataZoom 同时绑 X/Y，时间窗的 startValue/endValue 被套到 Y 轴，量程就飞到几千上万。现拆成 X、Y 两套滚轮缩放：勾选只决定滚轮作用在哪根轴，不再改当前 Y 量程；未勾选 Y 时 Y 轴仍按数据自动（108–109 这种）。


修改后，界面的Y轴量程变成35000，不知道这个数值如何来的，导致显示区域，我100多的数值，全部贴在0轴附近。
需要修改成，显示区域的y轴是最适合当前量程的。
增加按钮，坐标轴自适应，总动计算适配当前显示区域数值的y轴量程，放在重置按钮后

→ 已改：去掉绑在 Y 轴上的 dataZoom（它会把量程撑到 3 万这类“整齐”刻度）。Y 轴改为按当前时间窗内的数据 min/max 加边距自适应。重置右侧增加「坐标轴自适应」按钮，按当前显示区域重新计算 Y 量程。勾选「Y轴缩放」后滚轮才缩放 Y。


增加曲线的时候，如果是在新的遥测表上增加曲线，和就有的曲线数据不是同一张表格，
需要弹窗提示，类似“遥测表类型更换可，，，旧的曲线和数据会被清理，”

在重置按钮前新增一个按钮，就是把当前拖动过的时间窗口 移到 最新时间点，然后随时间移动。
重置按钮会修改窗口大小，新增的按钮是不修改窗口大小，相当于把窗口平移到最新位置。顺被给按钮取个名字，放在重置按钮前。

→ 已改：换表再点「增加曲线」会先确认，确认后清空旧表曲线再添加。重置前增加「跟随最新」：保持当前窗口宽度，平移到最新时间并继续跟随；「重置」仍恢复默认窗口大小。


取消选中x轴缩放，鼠标按下，拖动x轴方向的功能没有了。

→ 已改：「X轴缩放」只控制滚轮缩放时间轴。取消勾选后仍可按住拖动平移 X；截取模式下才禁用拖动。


界面增加选择表格和选择曲线，复选框状态的缓存。
时间不需要缓存，按照原来的规则来。

→ 已改：曲线页记住遥测表、遥测量、自动刷新 / X轴缩放 / Y轴缩放（localStorage）。起始时间和时间窗不缓存，仍按进入页面后的原规则对齐。从遥测表跳转带参时仍以路由为准。


把 「坐标轴自适应」按钮， 记住遥测表、遥测量，X轴缩放 / Y轴缩放 起始时间，结束时间， 功能加入到 遥测归档数据 页面。

→ 已改：归档页重置后增加「坐标轴自适应」。记住遥测表、遥测量、X/Y 轴缩放，以及起始/结束时间（localStorage）；下次进入直接带回。


当前首页/遥测/遥测曲线界面，点之间的连线，是直线，
但首页/LVDS/工程遥测界面的连线 sin形状的曲线 是如何画的？
不用修改代码，

→ 说明：两边都是 ECharts `type: 'line'`，都没有开 `smooth`，点与点之间其实都是直线。工程遥测看起来像正弦，是因为演示数据本身用 `sin/cos` 算出来，而且点很密（约 500 点、间隔 2ms），折线连起来肉眼就像光滑曲线。遥测曲线是慢遥测，点稀疏，直线段就看得出来。


单板相机测试界面，自动拍照，采图前的指令生成修改，
如果图像索引的数值 大于 CAM_A10 - 拍照 指令的 缓存数量 ，
需要把 缓存数量设置成图像索引的数值。

→ 已改：自动拍照组 CAM_A10 时，若图像索引大于「缓存数量」，把缓存数量改成该索引（同时改左侧控件），再组帧发送。




首页/调试/数据模拟 帧解析类型 增加 相机SC-LINK41EP(D9) 类型

→ 已改：解析器列表增加「相机SC-LINK41EP(D9)」（`camera_sc_link41ep_d9`），只拆快遥 D9 帧。模拟页选透传 + 该类型即可注入 D9。


我在模拟页面，选择相机SC-LINK41EP(D8)，发送下面数据，提示 已写入 Redis · 组装 1 · 解析 1 · 类型 0xD8 · 相机-慢遥测(全窗) · 字段 38 · 2026-08-13 15:09:05.727
EB 90 D8 00 00 2D 65 52 AA AA 01 3A 13 80 05 FF 00 10 4B 9E 06 05 01 00 10 00 00 00 09 E7 02 58
01 4A 00 01 01 14 07 C8 0D 48 03 90 0A 6A 00 00 00 00 32 01 32 32

然后把数据第三个字节改成D9， 也能成功，提示 已写入 Redis · 组装 1 · 解析 1 · 类型 0xD8 · 相机-慢遥测(全窗) · 字段 38 · 2026-08-13 15:09:39.523
校验和没生效？
EB 90 D9 00 00 2D 65 52 AA AA 01 3A 13 80 05 FF 00 10 4B 9E 06 05 01 00 10 00 00 00 09 E7 02 58
01 4A 00 01 01 14 07 C8 0D 48 03 90 0A 6A 00 00 00 00 32 01 32 32

→ 已改：原先帧类型/校验对不上时，会把前 45 字节当 D8 数据区硬解析，所以改成 D9 仍显示成功。现已去掉这条兜底；D8 拆帧也校验和。改类型或改校验后应报「未找到有效的相机遥测帧」。


D8 和 D9 的解析需要分开，两个的协议不一样。
慢遥D8 帧头是 EB90 ， 帧类型是 D8
但快遥D9 的帧头是 EB， 帧类型是 D9

→ 已改：模拟页 D8 只认 `EB90`+类型 D8，D9 只认 `EB`+类型 D9，互不兜底。控制串口仍绑定 D8 解析器时，采集侧按两种协议分别拆帧（全窗 D8 / 开窗 D9），不会把 D9 当 D8 数据区。


不能把相机的解释器拆成快遥，慢遥。不然相机只能解析一种数据。
我把刚才两次的修改代码都还原了。

但通用数据发送模拟 中，
正确的数据：
EB 90 D8 00 00 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 0A 6A 00 00 00 00 32 01 32 0F

错误的数据：
EB 90 D8 00 01 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 0A 6A 00 00 00 00 32 01 32 0F

python报错了index out of range
2026-08-13 15:36:31.004 |  |  |  | 36876-44b618 | ERROR    | exceptions.handle:exception_handler:71 - index out of range
  + Exception Group Traceback (most recent call last):
  |   File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\starlette\_utils.py", line 79, in collapse_excgroups
  |     yield
  |   File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\starlette\middleware\base.py", line 192, in __call__
  |     async with anyio.create_task_group() as task_group:
  |                ~~~~~~~~~~~~~~~~~~~~~~~^^
  |   File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\anyio\_backends\_asyncio.py", line 799, in __aexit__
  |     raise BaseExceptionGroup(
  |         "unhandled errors in a TaskGroup", self._exceptions
  |     ) from None
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\starlette\middleware\errors.py", line 164, in __call__
    |     await self.app(scope, receive, _send)
    |   File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\middlewares\transport_crypto_middleware.py", line 53, in __call__
    |     await self.app(scope, receive, send)
    |   File "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend\middlewares\trace_middleware\middle.py", line 44, in __call__
    |     await self.app(scope, handle_outgoing_receive, handle_outgoing_request)
    |   File "e:\plat\PayloadGroundTest\ruoyi-fastapi-backend\venv\Lib\site-packages\starlette\middleware\base.py", line 191, in __call__
    |     with recv_stream, send_stream, collapse_excgroups():
    |                                    ~~~~~~~~~~~~~~~~~~^^
    |   File "D:\tools\Python\Lib\contextlib.py", line 162, in __exit__
    |     self.gen.throw(value)

还有，如果改其他数据，报D8 校验和错误，  需要和其他校验和报错的信息格式一样。有校验和提示。
该错误的数据：
EB 90 D8 00 00 2D 34 8A AA AA 01 63 3C 7F 8D FF 00 10 66 9E 06 05 01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 0A 6A 00 00 00 00 32 01 32 0F


d9的校验和提示也一样，需要修改。

→ 已改：未拆 D8/D9 解释器。长度字段超出实际帧长时改为报「帧长不符」，不再 IndexError。D8/D9 校验和改为「计算：xx， 帧内：xx」，与单板遥测一致。


相机遥测数据解析错误，
会在redis 中 的 payload:error:tm 和 payload:error:camera  同时插入记录。
看下是不是重复了？

→ 已改：重复了。`error:camera` 只留给图像组装；相机 D8/D9 解析失败与其它遥测一样只写 `error:tm`。


现在数据模拟的报错信息，重复显示，显示了2次一样的，看了http请求，只有一次。
还有 CAN的遥控符合帧的提示格式也改成D8的格式， 把 D8 帧长不符: 数据长度：301， 解析总长度：310，实际总长度：54
现在是 声明帧长过长: dataLen=60304 realSize=60307 > 512， 明显不如D8的，最好是统一成一个提示文本。
在看下http模拟数据页面，其他的提示，是不是也统一下。

→ 已改：模拟页不再二次弹出（axios 拦截器已提示）。CAN/相机/单板/工程遥测的帧长、校验和改成同一套文案：`…帧长不符: 数据长度：x， 解析总长度：y，实际总长度：z`；`…校验和错误: 计算：xx， 帧内：xx`。


现在需要对前端，后端，各加个版本号，登录后首页， 设备服务前，增加版本号栏，页面：1.0.0.****  服务：1.0.0.****
版本号v1.0.1.20260813  这样可以吗？ 还是说有更好的版本号规则？
前后端配置文件分开，但文件名，变量名一样。

→ 已改：采用 `主.次.修订.YYYYMMDD`（现为 `1.0.1.20260813`），配置里不加 `v`。前后端各一份 `version.json`，字段同为 `appVersion`。首页设备服务前显示「页面 / 服务」。改号后前端重新编译、后端重启即可。

version文件，不放在config目录，放各自项目根目录，如果不要求前后端都是用json，前端可以使用js，后端可以使用py，你看下如何修改？

→ 已改：版本文件改到项目根目录。前端 `version.js`、后端 `version.py`，变量名仍为 `appVersion`。



1. 数据库文件 ruoyi-fastapi-mysql.sql 被我重命名成 ruoyi-fastapi-my.sql了，已经修改，通知你下。
2. 调试遥测计算界面 - 遥测表下拉菜单，更新成和 遥测界面的下拉菜单一样。

3. docker运行版本前端报错。
index-CsjJL4a6.js:85 errAxiosError: timeout of 10000ms exceeded
index-Dev6XS96.js:1 Uncaught (in promise) AxiosError: timeout of 10000ms exceeded
    at g.ontimeout (index-CsjJL4a6.js:82:6580)
    at pu.request (index-CsjJL4a6.js:84:2097)
    at async P (index-Dev6XS96.js:1:10395)

4. 串口打开失败: Could not configure port: (5, 'Input/output error')
连续提示两次。

→ 说明：`ruoyi-fastapi-mysql.sql` 已更名为 `ruoyi-fastapi-my.sql`，compose / 文档均已指向新文件，无需再改。

→ 已改：调试「遥测计算」遥测表下拉改为与遥测曲线/归档相同的 XL / BIU 分组。

→ 已改：Docker 前端 Axios / 传输加密超时由 10s 提到 30s；nginx 代理读写超时 60s；Docker 关闭外网 IP 归属查询；路由守卫不再对超时二次弹窗。前端镜像需重新编译。

→ 已改：串口打开失败只由 axios 拦截器提示一次（对话框 catch 不再重复弹出）。`Could not configure port: (5, 'Input/output error')` 仍是端口/权限问题，Docker 需正确映射串口设备。


build.bat 前端 zip 加入 version.js 版本号，如 html_1.0.1.20260813.zip

→ 已改：从 `ruoyi-fastapi-frontend/version.js` 读取 `appVersion`，产物为 `dist/html_<版本>.zip`。后端打包仍待补。


补全后端部分，后端部分要求打包成whl格式，
参考：test\TeleMetry\build.bat， 这个脚本是打包whl格式的
打包完成后，需要删除生成的临时换成文件。
version 从 version.py 中获取。

→ 已改：后端按 TeleMetry 方式打 wheel，版本取 `version.py` 的 `appVersion`。产物 `dist/ruoyi_fastapi_backend_cli-<版本>-py3-none-any.whl`；打完删除 `build/`、`*.egg-info`、`.eggs`、`__pycache__`。

扩展改名成 pgt，ruoyi-fastapi-backend-cli 太长了。

→ 已改：wheel 包名改为 `pgt`，产物为 `dist/pgt-<版本>-py3-none-any.whl`。`ruoyi` 命令名不变。


打包出来的whl，把依赖添加进去了吗？
如何运行prod版本的配置？
.env.prod的配置会打包进去吗？

→ 说明：没有。wheel 只含 `cli` 包，`pyproject.toml` 未声明 dependencies，FastAPI/Redis 等仍靠现场 `requirements.txt`。`.env.prod` 也不会打进 wheel。prod 用法：在后端目录执行 `ruoyi app run --env=prod`，运行时从当前目录读 `.env.prod`。


在docker版本部署中，参考ruoyi-fastapi-backend\Dockerfile.my
后端执行了# 将当前项目安装为包，生成全局可执行的 ruoyi 命令。
RUN pip install --no-cache-dir .

现在我不能部署docker版本，但我还是想要将我的代码打包成whl，直接pip install 这个包，安装好了所有环境。
不然我每次复制代码，也不方便。
打包需要包含项目的代码，依赖，配置等。

我调试启动是：python app.py --env=dev
我需要发布启动就是， python app.py, 或 "ruoyi app run"

还有 ruoyi cli 是什么，和我平时 python app.py --env=dev  有什么差别？

→ 已改：`pgt` wheel 现包含后端代码、遥测/遥控 JSON、SQL、`.env.*`、依赖声明（含 TeleMetryParser / gpcan）。安装：`pip install --find-links dist dist/pgt-<版本>-py3-none-any.whl`。发布：`ruoyi app run` 或 `python app.py`（默认 prod）。调试：`python app.py --env=dev`。`ruoyi` 是同一套后端的命令行入口，`app run` 内部仍是执行 `app.py`。

做成 whl 后，后台改 config、上传文件还能生效吗？build.bat 拆成前后端各一份。

→ 说明：源码运行仍写项目目录。安装 wheel 后，配置和上传改写 `%LOCALAPPDATA%\pgt`（可用 `PGT_DATA_DIR` / `PAYLOAD_CONFIG_DIR` 覆盖），不写进 site-packages，重装包不会丢。包内 JSON 仅作首次默认拷贝。

→ 已改：`ruoyi-fastapi-frontend/build.bat`、`ruoyi-fastapi-backend/build.bat` 产物到上一级 `dist/`；根目录 `build.bat` 依次调用二者。

如果 whl 里配置比外部目录新，如何处理？

→ 已改：按 JSON 根字段 `datetime` 比较。包内更新则把外部文件备份为 `*.json.bak` 再覆盖；外部相同或更新则不动。新文件仍直接拷贝。


大部分情况下，不会修改json配置的。配置都是在编码阶段生成的。
现在做这些规则：
1. 默认不复制内部文件到外部
2. 如果whl包内和外部的文件，一模一样，删除外部文件。
3. 如果whl包内更新了，外部版本旧，把外部的改名.datetime.bak  例如：aa.json.20280506121112.bak，重命名后，相当于这个文件没了。
4. 只有后台修改，才可能在外部生成文件，其他都不会在外部保存配置。
5. 读取配置，改成路径搜索的方式，先查找外部文件，在查找内部文件， 相当于把获取配置目录封装成函数。
6. 调试-配置界面，移到文件名上时，显示tooltip，显示文件完整路径，注意windows和linux的不同路径显示。

→ 已改：默认不向外部拷贝。读取 `resolve_config_file` 外部优先、包内兜底。内容相同则删外部；包内 datetime 更新则外部改名为 `aa.json.YYYYMMDDHHMMSS.bak`。仅后台保存写入外部。配置页文件名 tooltip 显示本机完整路径。


刚才配置文件的路径查找，刚才已经很详细了。
1. 配置文件的文件列表，比如列出当前所有的配置，会列举一个目录（外部或内部），还是两个目录合并，还是先搜索外部，在查找内部，遇到相同文件以外部为准？ 我希望时最后的方式。
2. 把所有配置路径相关的函数，都封装在一个文件内，比如获取配置，传入配置json文件名，返回数据。比如理出文件名，比如查文件属性等等，所有根配置相关的，都需要通过这个统一封装的文件。
比如修改保存配置，上传配置 都通过这个封装文件进行。
不然多个文件都有相关的代码，不好维护。
3. vf_admin，如果 whl包的外部路径需要改成和config一样，就是不能在whl包内部生成文件。
4. logs， log_data 这两个目录，因为只有写， 也相同的处理，放外部目录。
5. 还有其他涉及到外部路径的吗？

→ 已改：
1. 配置列表是两个目录按文件名合并：先扫外部、再扫包内，同名以外部为准（`config/paths.py` 的 `list_config_file_info` / `resolve_config_file`）。
2. JSON 配置的解析、列表、属性、读写、保存都走 `config/paths.py`；业务层只做校验和重载缓存。
3. `vf_admin`（上传/下载/代码生成）写到数据根，wheel 下是 `%LOCALAPPDATA%/pgt/vf_admin`，不写进 site-packages。
4. `logs`、`logs_data` 同样落到数据根。
5. 其它可写目录：`caches`、SQLite 的 `.db`（相对路径时）。源码运行仍写项目目录。Alembic `versions` 只在开发生成迁移时写，运行时不写。



调试的时候，是在ruoyi-fastapi-backend 目录下，还是和 ruoyi-fastapi-backend同级别？
现在，vf_admin，logs，目录，在这两个地方都能看到？

→ 说明：调试写在 `ruoyi-fastapi-backend/` 下（`python app.py` 会把 cwd 切到这里，数据根就是包根）。不是仓库根、也不是和 frontend 同级。`vf_admin` 要上传/代码生成才会建；`logs` / `logs_data` / `caches` 启动就会在 backend 下。仓库根若还有同名目录，是以前相对 cwd 留下的，可以删，当前代码不会再往那儿写。



我生成的whl包，安装后代码都在 site-packages 下，10多个目录都在这个下面，污染了python环境。需要变成 site-packages\pgt\module_task 这样的目录层次。

→ 已改：wheel 安装到 `site-packages/pgt/`（`module_payload`、`cli` 等为其子目录）。业务导入不用改；`pgt/__init__.py` 把该目录加入 `sys.path`。入口改为 `ruoyi = pgt.cli.main:main`。调试仍是在后端目录 `python app.py --env=dev`。

whl包 CaptchaService 的 font_path 会不会出问题？

→ 已改：会。原先用 `cwd()/assets/font/Arial.ttf`，仓库里也没有该字体，wheel 更找不到。现改为包根 `get_package_root()/assets/font/Arial.ttf`，没有则用系统 Arial，再没有用 PIL 默认字体。


我在代码中搜索 Path.cwd() ，还有好几处地方用到，排查下问题。
ruoyi-fastapi-backend\cli\utils.py(111):         current_dir = Path.cwd().resolve()
ruoyi-fastapi-backend\cli\completion\doctor.py(87):             'projectDir': str(Path.cwd().resolve()),
ruoyi-fastapi-backend\cli\completion\providers.py(98):         return Path.cwd().resolve()
ruoyi-fastapi-backend\cli\metadata\option_specs.py(27):         resolved_project_dir = (project_dir or Path.cwd()).resolve()
ruoyi-fastapi-backend\cli\runtime\base.py(34):         current_dir = Path.cwd().resolve()
ruoyi-fastapi-backend\cli\runtime\ops\support.py(227):                 'userDir': os.getcwd(),
ruoyi-fastapi-backend\config\env.py(29):     for base in (Path.cwd(), _PROJECT_ROOT, Path(__file__).resolve().parent):
ruoyi-fastapi-backend\module_admin\service\server_service.py(45):         user_dir = str(await anyio.Path.cwd())
ruoyi-fastapi-backend\module_generator\service\gen_service.py(355):             return os.path.join(os.getcwd(), GenConfig.GEN_PATH, TemplateUtils.get_file_name(template, gen_table))
ruoyi-fastapi-backend\module_payload\collectors\redis_sync.py(16): for _base in (Path.cwd(), _BACKEND_ROOT, _BACKEND_ROOT / 'config'):
ruoyi-fastapi-backend\utils\template_util.py(29):             template_dir = os.path.join(os.getcwd(), 'module_generator', 'templates')

→ 已改：wheel 下 cwd 不是包根。CLI 项目根统一走 `get_backend_dir()`（cwd 像后端根才用 cwd，否则 `get_package_root()`）。
- 会错：`providers` SQL/Alembic 补全、`doctor.projectDir`、`discover_env_names`（现扫包根和 `config/.env.*`）、代码生成模板目录、`gen_path=='/'` 时再拼 cwd。
- 保留 cwd：监控里的 `userDir`（进程工作目录）；`complete_output_paths`（导出相对用户当前目录）；`.env` 查找仍允许 cwd 覆盖（见下）。


我关闭了验证码功能，数据库配置的。
问题：刚才whl包的验证码显示报错，导致登录页出错，

但实际上我验证码关闭了，就算验证码出错，也不应该把登录页搞坏，导致现在不能登录。
还有我关闭了，就不应该请求验证码了吧，直接隐藏验证码区域。


  我看到redis的查找.env 的路径没有统一？
还是所有查找.env 的路径都没有统一封装。

→ 已改：
- 关闭验证码时 `/captchaImage` 只返回开关，不画图、不写 Redis。生成失败也返回 200 并降级 `captchaEnabled=false`，登录页仍可用。前端默认隐藏验证码区，接口失败同样隐藏。登录页仍会打一次该接口以读取库里的开关（否则前端不知道关了）；关掉后不再生成验证码图片。
- `.env` 查找统一到 `config/paths.py` 的 `resolve_dotenv_path` / `dotenv_search_dirs`（cwd → 包根 → `config/`）。`env.py`、采集进程 Redis、CLI 环境快照、环境名补全都走它。





20260817

功能优化
首页/遥控/XL/控制， 首页/遥控/BIU/控制
BIU控制界面，http://localhost/telecontrol/biu/control ， 遥测区域，在定时遥测按钮前，
添加遥测类型的下拉菜单，和发送遥测请求按钮，点击，生成一个遥测请求，并发送。下拉菜单参考，test/pygpcan/DemoBIU.py
BIU的 原子钟校时 / 通信速率 去掉，完全复制XL的时间同步。
BIU新增 发送数据 区域，复制XL的，具体内容参考test/pygpcan/DemoBIU.py

XL的控制界面, 参考biu， 新增遥测区域，包括单独发送，和定时发送开关， 间隔时间设置。 间隔时间设置前没有biu的下拉菜单。
XL的时间同步区域，载荷时间，页面刷新，默认值是当前时间，参考test/pygpcan/DemoXL.py，把时间同步的相关提示补上。

→ 已改（控制页 `telecontrol/control/index.vue`）：
- BIU 遥测：类型下拉（FF/FD/FB/F9/F7/FE/FC，与遥测表名一致）+「发送遥测请求」（`build_telemetry_request`）放在定时遥测按钮前；间隔仍走原来的定时遥测参数。
- BIU 去掉原子钟校时/通信速率，时间同步与 XL 同布局（载荷时间、偏差、定时广播）；无 GNSS 勾选（BIU 帧无此位）。
- BIU 新增发送数据：Hex、发送遥控指令、发送广播。
- XL 新增遥测区：单独发送、定时发送开关、间隔；无类型下拉（默认一类轮询 0x01）。
- XL 载荷时间进入/刷新页默认当前 UTC；补了时间同步说明（载荷=系统+偏差、单次不下发偏差、定时广播叠加、GNSS 无效位、历元）。







1. XL的遥测有两种，0x01一类轮询-速变遥测， 0x02二类轮询-缓变遥测， 具体查看 test/pygpcan/DemoXL.py， ui和biu的一样。，除了下拉菜单内容不一样。

2. 遥测的定时发送，需要后端定时，不要前端定时。打开的时候，后端打开定时发送，xl和biu都是这样的规则。
删除 xl和biu的 间隔输入框，不需要。
xl的后端定时规则是：
每隔1s发送1次 速变遥测， 第5s，不发送速变，改发送 缓变遥测。
biu的后端定时规则是：
每个0.5s发一次，相当于1s发两次，
奇数次， 相当于1s内的第一次，一定发测请求1
偶数次， 相当于1s内的第二次，发（2-5 轮流）

3. xl和biu的时间同步参考 test/pygpcan/DemoXL.py  时间同步相关的ui控件都需要，截图就算效果图。
时间同步功能分为两块，
设置载荷时间是独立的，相当于同步一次。
设置时间同步的起始时间，
定时同步广播。
跟着效果图，这样分区域，提示也要分开。

→ 已改：
- XL 遥测下拉与 BIU 同布局：`0x01` 一类轮询-速变、`0x02` 二类轮询-缓变；手动发送走 `build_telemetry_request`。
- 去掉间隔输入；定时遥测改采集进程后端定时。XL：每 1s 速变，第 5/10/… 秒改发缓变。BIU：每 0.5s，奇数次固定 FF（类型1），偶数次轮流 FD/FB/F9/F7（类型2–5）。
- 时间同步按截图分区：载荷时间（单次，不受起始/偏差影响）｜起始时间 + 偏差（设置后回填偏差，重置清零）｜定时同步广播（后端每秒「系统时间+偏差」）+ GNSS。起始/偏差/广播状态写在采集进程 `TimeSync`。


1. 定时遥测，定时广播，后端开启后，如果所有can关闭了，也要关闭，如果开了2个can，关了1个，还是要发。
2. BIU的时间同步没有 时间同步GNSS 复选框。
3. 设置时间同步的起始时间，设置报错，“未知控制操作: biu.timeSync.setOffset”。
4. 时间广播，设置载荷时间按钮，如果定时开启了，设置载荷时间就不能点，但设置时间同步的起始时间还是能用的。
如果只打开了cana 或can b， 都用打开的can发送；
如果同时打开了canA 和 can B：xl，
定时广播发送规则：两个can 轮流发送定时广播，比如 这次canA  下次canB  下次又canA。
比如当前只打开了canA， 就一直用canA 发定时广播。
这是canB 又打开了， 下次发送时，检查上次发送到是canA， 然后获取已连接can列表，这时候获取列表中canA的下一个（需要循环检查，比如上一个can刚好是列表最后一个，下一个就是列表的索引0），用下一个发送.

→ 已改：
- 定时遥测/定时广播改为采集进程级开关：关光全部 CAN 自动停；只关其中一路则继续在剩余通道发。定时遥测每次对当前所有已开 CAN 发同一拍；定时广播按已开 CAN 列表环形轮流（仅 A 则一直 A；A 后再开 B，下次从 A 的下一个起）。
- BIU 去掉「时间同步 GNSS 有效」；XL 保留。
- `biu.timeSync.setOffset` / `setStart` 等走 `parse_timer_op`，不再落到「未知控制操作」。
- 定时广播打开时禁用「设置载荷时间」；起始时间/偏差仍可设。



设置 时间同步的起始时间(UTC0时区)， 不会引起时间同步，最终是设置了一个偏差值。
设置按钮，
未知控制操作: biu.timeSync.setStart
未知控制操作: xl.timeSync.setStart
未知控制操作: xl.timeSync.setOffset
未知控制操作: xl.timeSync.resetStart
未知控制操作: biu.timeSync.resetStart

设置起始时间，点击设置，
start_ms = _datetime_epoch_ms_floor_sec(self._edit_start_time)
dt = QDateTime.fromMSecsSinceEpoch(start_ms, QTimeZone.utc())
TimeSync.set_payload_time(start_ms)
重置，就是把  TimeSync.set_offset(0)， 偏差输入框变成 0
设置系统时间偏差，点击设置，调用 TimeSync.set_offset(offset_ms)
设置后，后端都需要返回偏差值，把这个值设置到输入框。

→ 已改：
- 设置起始时间只调用采集进程 `TimeSync.set_payload_time`（秒取整），不算/不发对时帧；返回 `offsetMs` 回填偏差框。
- 重置改为 `TimeSync.set_offset(0)`，起始时间输入框不动，偏差框置 0。
- 设置系统时间偏差调用 `TimeSync.set_offset`，同样回填返回值。
- `parse_timer_op` 按 `biu|xl` + `setStart/setOffset/resetStart` 子串识别，避免再落到「未知控制操作」。



1. gpcan-1.0.2, can库更新，时间同步相关函数修改，
TimeSync.  这样直接调用废弃，
如 TimeSync.set_payload_time(start_ms) ，需要根据不同的协议设置，修改成 TimeSyncManager.find(CanProtocolType.BIU).set_payload_time(start_ms)
TimeSync类下的原来直接调用的函数都需要这样修改，我查到了下面这些，
            TimeSync.set_payload_time(payload_ms)
                'offsetMs': int(TimeSync.offset_ms),
            TimeSync.set_offset(int(timer.get('offsetMs') or timer.get('offset_ms') or 0))
                'offsetMs': int(TimeSync.offset_ms),
            TimeSync.set_offset(0)
                'offsetMs': int(TimeSync.offset_ms),
        sys_ms = int(TimeSync.get_system_time_ms())
具体可以查看biu协议的用法，test\pygpcan\tests\test_protocol_builder_biu.py


2. 时间同步 中的功能，偏差值,起始时间，页面刷新需要从后台取获取。没有就用默认值。时间是当前时间，偏差是0.

→ 已改：
- gpcan 1.0.2：采集进程一律 `TimeSyncManager.find(CanProtocolType.BIU|XL)`，BIU/XL 偏差隔离。
- 设置起始时间会记下 UTC；`biu|xl.timeSync.get` 回传 `utc` + `offsetMs`。页面进入/刷新/切通道时向后台取，没有则起始时间=当前 UTC、偏差=0。



定时遥测， 有多个打开的can通道，以打开定时遥测的时候，网页指定的当前选中的can通道为定时发送方。
如果选中的这个被关掉了，选择没有关掉的那个，如果都关闭了，定时遥测就停止，相应的状态网页也要同步。
如果选中的被关闭了，后面又打开了，继续用初始选中的那个发送。
在定时遥测 关闭按钮后面，加入一个label，显示当前发送定时遥测的can口。
修改这个规则的时候，时间广播的规则没有变，还是是几个串口轮流发送的，这次不需要修改时间广播的发送规则。

→ 已改：
- 定时遥测只走打开时「当前发送」那一路；该口关掉则改走剩余口；原口再开则回到原口。全部关掉则停止，前端 1s 同步开关和「当前发送：CAN-A/B」标签。
- 定时同步广播仍按已开 CAN 环形轮流，未改。


打开can，过了一段时间了，发送第一条can消息很慢，但后续消息就没受影响。







2026.09.01
暂不做： 需要超详细的补全后端的测试用例代码，放tests目录下。
