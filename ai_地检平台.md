指令序列，保存的时候，数据库需要保存输入控件的输入值，如果不保存，有些属性有公式计算，计算的结果才变成指令，计算的结果在需要还原的时候就不能还原了。界面还原的时候，就用这个保存的值。
如果保存的值在后续输入控件中没了或修改了，对不上的时候，还原的时候，需要符合最新的规则的，比如大小的限定。

→ 已改：序列 JSON 的 ``values`` 存输入控件原值（formula 组帧前）。保存时把当前编辑区一并写入。打开时按当前 component 还原；选项对不上或控件没了用最新默认值，数值超出 min/max 钳到范围内。



单板-相机测试，控制串口性能问题。
ruoyi-fastapi-backend\module_payload\collectors\serial_collector.py的 read_and_parse 函数，
waiting0 = 78680
waiting = 1106578
len(data) = 16384
max_chunks = 128
chunk_size = 16384
我卡断点看到接收数据太多，处理慢，影响了发送数据的处理，造成发送的时候前端都是超时。

进一步分析发现，ruoyi-fastapi-backend\module_payload\collectors\base_collector.py 的 run函数中，这两个函数的执行，self._consume_commands()  和 self.read_and_parse()， read_and_parse的慢速执行，导致run函数卡顿。
我觉得分情况，对于全双工的，收发可以分成两个线程。对于半双工的，收发当前这样处理没问题。

我在配置文件中ruoyi-fastapi-backend\assets\config\cfg_device_connect.json，新增了字段fullDuplex， true是全双工。  以后新增配置，can默认是半双工，网口和串口是半双工。
这个属性，在新建连接的时候，需要传入，然后base_collector的run被调用的时候，首先需要进行全双工和半双工的判断，然后根据不同状态，进行处理。
现在帮我优化代码。

→ 已改：打开连接把 ``fullDuplex`` 写入采集进程（前端传入，缺省按 ``cfg_device_connect.json`` 的 source，再缺省半双工）。``run`` 全双工时 RX 线程跑 ``read_and_parse``，主线程只处理控制/发送/心跳；半双工仍单循环。相机控制/图像/单板串口配置为全双工。


ruoyi-fastapi-backend\module_payload\collectors\serial_collector.py
增加了 MAX_WAITING，read_and_parse中的清理部分代码需要完善代码， 清理本地的缓存数据（组帧缓存），避免旧数据影响新数据处理

→ 已改：RX 积压超过 ``MAX_WAITING`` 时先 ``reset_input_buffer``，再 ``_reset_rx_framing`` 清空 assembler / demux / 插件组帧缓存，避免半截旧帧拼进新数据。



首页/单板/相机测试  页面的   表格中的图像索引，一直是0，
我看到 http://localhost/dev-api/payload/camera/image?port=COM4
返回的"imageNo": 0,  一直是0.

日志区，Recv 01 07 00 00 00 13 24 E5 02 D7 01 2C 01 01 01 14 07 E0 0C E4 03 90 0A ...   这里...的截断太早，在原来基础上增加10个字符的显示。

http://localhost/dev-api/payload/device/io-log?deviceId=source%3Acamera_ctrl&sinceSeq=60363&limit=200
请求返回的日志的，记录之间的间隔太短，下面的日志，记录的hex字段被我裁剪了，不然内容太多。5ms的间隔，太短，改成500ms的。

→ 已改：应答图像序号为 0 时 Redis ``imageNo`` 回退为本次请求索引。传输信息行截断加长 10 字符。Redis 预览 IO 日志同方向最少间隔 500ms，文件落盘仍每包写入。




需要超详细的补全后端的测试用例代码，放tests目录下。

→ 已改：补全 collectors 双工/RX 溢出组帧清理、相机 imageNo、D6 组帧、IO 日志 500ms 节流与 camera service 的后端测试，均放 ``ruoyi-fastapi-backend/tests``。


需要超详细的补全后端的测试用例代码，新增的代码都需要。从hash 16e823021e8603df744ad55f34155a72b4fcc837 开始的git提交都需要。

→ 已改：从 ``16e8230`` 起的 payload 新增逻辑补了后端单测（组帧、遥控公式/values、指令序列、网口 ID 无 ``net:``、fullDuplex、Redis key、CAN 遥测帧、配置加载、会话/配置文件、IO 落盘、网口采集、遥测服务等），均放 ``ruoyi-fastapi-backend/tests``。 CLI/打包/健康检查/相机双工等已有用例未重复。


不需要用真can测试，测试can通讯，使用demo厂商就行，但是不能再一个进程中进行收发

→ 已改：CAN 通讯测 gpcan 演示厂商（vendor=0），收发分两个进程（父进程 SDK 对采集子进程）。同一进程打不开同一条虚拟通道，不用真 CAN / 自发自收。


ruoyi-fastapi-backend\tests\test_can_yc_frame.py的test_hex_to_bytes_odd_nibble 函数，
hex_to_bytes('A B')  == bytes([0xAB]) 是不对的， 应该是， 0x0A 0x0B。
按照我在前端的hex文本的格式化的规则：
空白字符 是 16进制字符的分割
具体示例如下：
a b c -> 0A 0B 0C
ab c -> AB 0C
ab c de f -> AB 0C DE 0F
ab c d -> AB 0C 0D
aabbc  -> AA BB 0C
aabbc d -> AA BB 0C 0D
aabb c d  -> AA BB 0C 0D
aab ccd d eef 445 -> AA 0B CC 0D 0D EE 0F 44 05
11 23 4  44 ff dd ee d -> 11 23 04 44 FF DD EE 0D

具体还要参考前端ruoyi-fastapi-frontend\src\utils\payloadRawData.js 这里面的相关代码。

如果我要修改这个规则，影响了哪些功能？

→ 已改：HEX 按空白分 token（``A B`` → ``0A 0B``），与 ``payloadRawData.js`` 一致。共用 ``module_payload/cfg/hex_text.py``。
会改解析结果的入口：CAN 遥测 HEX 注入/解析、通用模拟注入、遥控 HEX 组件/广播判断、遥测计算、串口/网口/CAN 原始发送、发送 IO 日志。配置 demux 头、CAN 帧 ID 仍按连续数字，未改。已对齐模拟页、遥控自定义发送。


前端，遥控输入Hex的文本输入框，加入tooltip 图标，提示就是这个规则，规则帮我整理好，我的举例可能重复，不够整齐。
根据前端哪些页面使用了payloadRawData.js相关函数去查找输入框

→ 已改：规则收成 4 条 + 6 个不重复示例（分段、连续、奇数补 0），共用 ``HexInputTip``。挂在遥控发送 Hex、数据收发 CAN 数据/串口 UDP 的 HEX、遥测计算 Hex、模拟页两处 Hex 框。CAN 帧 ID 仍是连续数字，不加这条提示。







ruoyi-fastapi-backend\module_payload\collectors\serial_collector.py的 _try_session_ingest 函数，
需要进行性能测试相关代码，我自己写过时间统计代码，执行这个函数，会在
read_and_parse这个函数中调用 self._try_session_ingest(data, self.device_id, SRC_KIND_SERIAL)
前后加入time.perf_counter_ns()  进行统计，最后换算得到，耗时在8ms到900ms之间，当然这个和data长度相关，但最少8ms的耗时，肯定不合理，编写代码，进行性能测试，帮我看下主要耗时在哪里。然后进行优化，优化完成后再去掉时间统计相关代码。









曲线显示界面，已有曲线情况下，切换到其他遥测表界面，再次页面带参数跳转到曲线界面时，虽然表不一样，但不显示确认提示，直接显示新的曲线。

菜单 遥测曲线 改名  遥测实时曲线
菜单 遥测归档数据 改名 遥测历史曲线

遥测实时曲线，是通过redis获取的，里面所有遥测数据，有没有被丢弃过，比如单板的相机测试，它的数据在收到后有丢弃吗？
遥测历史曲线， 是从mysql获取曲线诗句，现在是不是只有can的数据在存mysql？


2026.08.19
遥测菜单下新增功能，遥测文件数据，遥测文件曲线，这两个新增的页面，和保存的log_data的数据回放有关。
遥测文件数据，具体功能：
1. 界面，垂直布局，界面不能出现滚动条。
第一行：顶部按钮栏：
遥测表选择，参考（遥测曲线页面的遥测表）
选中文件路径显示，
解析按钮，点击解析，开始解析数据。
上传文件按钮，点击，弹出上传窗口，用户选择文件，弹窗显示进度条，有关闭按钮，点击提示停止传输。上传完成后，在选中文件路径中显示路径，
选择文件按钮，点击弹窗，显示上传文件目录，本地日志目录， 这两项。点击其中一项，读取目录下所有文件和子目录，类似资源管理器的窗口展示，展示文件夹和文件，文件要求是文件名包含_recv 的 文件， 用户选择一个文件，点击确认就是选中了这个文件，把文件路径写入路径输入框。  这个弹窗单独一个文件，看看有没有现成的控件可以使用。
第二行，分3部分内容，内容水平布局
第一部分，占据1/2 区域的滑块控件，
第二部分：参考角色界面，表格下的 上一页， 当前页数字输入框， 下一页，这部分。
第三部分：自动播放复选框，默认不勾选，间隔输入框，默认1000ms， 加入toltip 和输入框placeholder提示。
第三行，遥测表显示，这个区域有滚动条。遥测表的封装页面，需要新增属性，隐藏title功能，只是ui隐藏，其他都不变。

后端逻辑，用户选择好文件，点击解析的时候，传入了遥测类型，文件路径，后台需要在一个进程中处理这个数据，
先确认数据是否符合要求，前面所有步骤都处理好后，根据文件类型（bin， hex文本， 后端自己判断），然后解析出第一帧，算出大概有多少帧（文件100M以内，找出所有帧，精确计算，超过100M的，根据一帧大小，总文件大小，大致估算就行）。然后返回前端。
后端解析先解析第一帧数据，存redis， 存redis的key 是 和文件路径有关，存的是所有解析的数据。
前端会指定获取第几帧数据，根据情况解析，这个过程后端需要等待redis出结果（超时1s就行）。
前端需要网页页面的变量缓存获取的结果，字典保存， 帧序号和内容，切换文件删除缓存，

文件的类型就是log_data下保存的recv的数据类型。  can是hex文本，其他是流。后端需要根据类型解析，以后上传的文件，也需要分析类型，进行解析。

生成mysql数据库的补丁文件，本地数据库直接执行。mysql -u root -p123456  -e "SELECT VERSION();"
切换文件，后端的进程可以不退出，然后重置现有数据，在开始新的流程。
上传文件，文件可能超过100M，上传的文件放在现在上传目录下的子目录log_data下，上传文件可以覆盖。
参考test\文件展示.png, 首页， 只有  上传文件  本地日志 两项。


遥测文件曲线，具体功能：
选择部分和遥测文件数据一样（第一行），重置等按钮，遥测曲线，参考 遥测历史曲线。






