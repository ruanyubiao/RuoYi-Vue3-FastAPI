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

→ 已改：8ms 地板来自每帧碰磁盘：``TmMgrFileCache`` 2s 内不 stat；采集只收完整 D8/D9（噪声不再当遥测解析）；``_get_cam_tm_mgr`` 不再 f-string ``_ResolvedCfg``（``__str__`` 每次 ``resolve_config_file``+``is_file``，约 0.35ms/帧）。单板表名改为按文件缓存，不再每帧扫描全部 TeleMetryCfg。组装结果/错误 Redis 改 pipeline。性能断言在 ``tests/test_session_ingest_perf.py``。生产代码未留计时。





这是一段真实的数据，帮我完善单板相机的测试用例。
慢遥测
EB 90 D8 00 00 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 0A 6A 00 00 00 00 32 01 32 0F

快遥测
EB D9 AC AD AA 01 FF FF FF FF 00 00 08 AD 00 07 D5 0C 4E EB

→ 已改：样例写入 ``tests/test_camera_sc_link41ep.py``。校验帧长/校验和、D8 38 项与 D9 11 项关键字段（指令正确、质心、坐标、光斑、温度、CAMF011=07D50C4E），以及粘包混流、坏校验。CAMF011 按序号低 3 位译码未做，见下条。



波特率是 2000000，ruoyi-fastapi-backend\module_payload\collectors\serial_collector.py 的MAX_WAITING 设置成多少合理？
我需要设置成 5秒的缓存数据。

→ 已改：8O1 下 2Mbps 约 182KB/s，5 秒 ≈ **909091** 字节（旧值 10KB 只够约 55ms）。``MAX_WAITING`` 按波特率+起止/校验位计算；打开串口时驱动 RX 缓冲不小于该值（11Mbps 则为 5MB）。这是 ``in_waiting`` 积压上限，不是业务解析缓存。




test\性能测试.txt  这是我自己进行测试的时间统计，测试的代码是在
ruoyi-fastapi-backend\module_payload\collectors\serial_collector.py 中。
下面是测试代码，我的疑惑是，为什么时不时会出现10倍或20的耗时？
                if data:
                    # start_time = time.perf_counter_ns()
                    self._try_session_ingest(data, self.device_id, SRC_KIND_SERIAL)
                    # end_time = time.perf_counter_ns()
                    # duration = (end_time - start_time) / 1000000  # 转换为毫秒
                    # print(f"try_session_ingest 耗时: {duration:.2f}ms， data长度: {len(data)}")

→ 说明：540 字节=10 帧 D8，0.11ms 是拆帧入队。约每 50ms 一次（``LATEST_MIN_INTERVAL_S``）在采集线程里 ``TeleMetryParser.parse`` + JSON + 两次 Redis SET，变成 1~2.5ms，所以是 10~20 倍而不是变慢 bug。再叠上 0.2s 组装 Redis、0.5s 曲线线程抢 GIL/Redis，会出现 2ms 尖峰。``print`` 不计入这次计时，但会拖慢下一轮读。要让每次都 ~0.1ms，需要把 latest 解析/写 Redis 挪出串口线程。


每 50ms解析一次遥测数据合理，能接受。
但这里的曲线数据解析、流数据保存文件会被遗漏吗？
曲线数据是需要所有帧的数据，不能出现遗漏。
redis大概会存多少秒的曲线帧数据？

→ 已改：原先曲线/归档每 0.5s 最多抽 40 帧，缓冲超 200 还丢旧帧；现改为后台逐帧 ``parse_calc``，满 200 刷写不丢。50ms 只影响表格 latest。收流 ``_recv.bin`` 每包都写（积压时不再跳过文件）；队列满 8192 仍会丢最旧块。Redis 每字段最多 **50000** 点：秒数 = 50000/帧率。10Hz≈83 分钟，80Hz≈10 分钟；帧率再高窗口更短，旧点被挤掉，不是漏解析。


步骤1：遥测的解析，可以改成0.5s解析一帧，存redis，多了前端也看不过来。
步骤2：曲线点的解析，一帧都不能丢，解析后存redis， 这个是实时看的，可以批量提交到redis，但批量的时候，时间不能是同一个。
步骤3：本地数据存储，所有数据都需要保存，一个字节都不能丢。
步骤1、步骤2、步骤3需要分开处理。
步骤2：cpu密集型（解析） + io密集型（redis），可以放入一个单独的线程或进程。
步骤3是io密集的，也需要异步或单独线程。
你看下如何合理安排

还有 更长历史看遥测历史曲线， 这个已经不保存数据库了，改成读文件了，这个现在不用修改，后续会修改。

→ 已改：采集线程只拆帧入队。``tm-table-latest`` 每 0.5s ``parse`` 一帧写表格 Redis。``tm-curve-flush`` 逐帧 ``parse_calc``，一批 pipeline 写曲线，同一毫秒帧 ts+1。落盘仍走 ``ConnectionTransferLogger`` 写盘线程，入队改为阻塞不丢包；``_push_io`` 先落盘再写 Redis 预览。历史曲线读文件未动。


再次进行性能测试相关代码编写，测试发送数据就用 ruoyi-fastapi-backend\logs_data\20260824\camera_ctrl_serial_COM3_20260824_145550_829_recv.bin
这个文件。
给出总结报告，然后看看还能不能优化代码，能优化就直接优化，最后在去掉性能测试代码。
优化的时候，不能把功能改掉，比如原来所有数据都需要存储，改成筛选存储。

→ 已改：用该 ``recv.bin``（5,766,660 B，**106790** 帧 D8、0 帧 D9）压过采集入队+曲线解析。优化前：整文件 ``collect_prepared`` ~235ms，曲线+归档 ``process_prepared_sync`` ~8.0s，4KB 分块入队 ~7.26s（中位 0.40ms、尖峰 58ms，~775KB/s）。瓶颈是每帧 ``parse_calc``（必须保留）、以及曲线线程里 10.7 万次 HEX/JSON 入 MySQL 归档队（历史已改读文件）。优化后（不丢帧、不筛存储、落盘不变）：采集侧批量入队、缓存 D8/D9 表名、曲线 Redis 键拼一次、``hex(' ')``；采集曲线路径**不再** ``enqueue_sync``（HTTP ``immediate`` 仍归档）。结果：拆帧 165ms，曲线 5.48s 且 lpush=0，分块入队 5.91s（中位 0.18ms、尖峰 24ms，~953KB/s）。剩余时间几乎全在 TeleMetryParser。一次性 bench 已删；``tests/test_camera_sc_link41ep.py`` 保留对该 bin 的帧数回归（缺文件则 skip）。


去掉串口、udp等渠道遥测解析数据mysql归档的功能，以后只有can的遥测数据会存mysql。
除了can，以后都会从本地文件解析（这次不做这个功能）。

→ 已改：``payload_tm_frame`` 只收 CAN 遥测。串口/UDP/TCP 解析结果不再入 MySQL 归档队，队列里残留的非 CAN 事件落库时也会跳过。CAN 采集曲线路径会入队；HTTP 注入仅 ``tm_can_biu`` / ``tm_can_xl`` 仍归档，相机/单板注入不归档。遥控 TX 日志、Redis 曲线/表格、原始流落盘未改。从本地文件反解历史这次不做。


先再次完善后端测试用例。
然后 再次进行性能测试相关代码编写，测试发送数据就用 ruoyi-fastapi-backend\logs_data\20260824\camera_ctrl_serial_COM3_20260824_145550_829_recv.bin
这个文件。
给出总结报告，和上次的报告对比，然后看看还能不能优化代码，能优化就直接优化，最后在去掉性能测试代码。
优化的时候，不能把功能改掉，比如原来所有数据都需要存储，改成筛选存储。

→ 已改：补了 CAN 才归档、``push_many`` 满 200 不丢帧、相机/单板串口 ingest 不入 MySQL、recv.bin 首尾帧对齐等用例。同一 ``recv.bin``（106790 帧 D8）对比上次：拆帧 165ms→**123ms**（跳过无 D9 扫描、缓存 mgr/表名）；曲线 ``parse_calc`` 5.48s→约 **5.6s**（波动，仍全部 4058020 个 zadd、lpush=0）；4KB 入队中位 0.181ms→**0.144ms**，吞吐仍 ~950KB/s。剩余时间几乎全在 TeleMetryParser，再砍就要少解析字段。一次性 bench 已删。



ruoyi-fastapi-test  这个文件夹的下是什么测试，帮我分析下。

除了python后端不能用容器，需要在pc上开启，但mysql，redis，nginx这三个docker容器和镜像都已经安装，这几个容器也测试正常。
帮我改一套适合我的测试代码。
ruoyi-fastapi-test\docker 目录是我的prod部署的时候容器的启动脚本，帮我改成适配当前测试端口等配置。
不要和我本地已有的容器冲突。可以通过 docker 命令查询。我本地的是开发用的，测试的时候，up一套新的容器，容器名字以test-开始，用完删除。
启动的env 是不是可以新增一套.env.test，或者借用 .env.dockermy， 但不能使用.env.prod和.env.dev的。

→ 已改：新增 ``.env.test``（PC 后端 19099，连 test-mysql:13307 / test-redis:16380）。``docker/compose.yml`` 只起 ``test-mysql`` / ``test-redis`` / ``test-nginx``（18080，``/prod-api`` 反代到宿主机 19099），不启后端镜像。开发用的 ``mysql8``/``redis``/``nginx`` 及 ``docker/*/compose.yml`` 未改端口。Playwright 打 ``localhost:18080`` 与 ``19099``。用完 ``docker compose -f docker/compose.yml down -v``。


ruoyi-fastapi-test\README.md  这个文件完善。
然后每次运行的时候 ruoyi-fastapi-test\docker\mysql\sql\ruoyi-fastapi-my.sql  这个文件需要替换成最新的，我修改 docker的文件映射，你看下对不对。
docker目录下的其他的无用的componse文件删除。
然后mysql，redis的数据我已经修改成不映射了。测试结束的时候，方便清理redis，docker等产生的data数据。
帮我检查下，现在整套流程对不对。
环境我已经安装好，还有不要污染我的开发docker环境。
然后测试执行，直接写一个run_test.bat 脚本放在了ruoyi-fastapi-test，完善它。

→ 已改：SQL 映射改为 ``../../ruoyi-fastapi-backend/sql/ruoyi-fastapi-my.sql``（原先 ``../ruoyi-fastapi-backend`` 会指错目录）。MySQL/Redis 不挂数据卷，``down -v`` 即清。删掉 ``docker/*/compose.yml`` 和旧的 ``docker-compose.test.*.yml``。``run_test.bat`` 只 up/down 本 compose，杀 ``--env=test`` 后端，不动 ``mysql8``/``redis``/``nginx``。



ruoyi-fastapi-test  我的新增功能的测试项完善。

→ 已改：补了 ``ruoyi-fastapi-test/payload/``。页面冒烟覆盖遥控/遥测/单板/LVDS/重构/调试菜单（含首页设备服务），不点开串口或 CAN。接口测配置读取、组帧、遥测计算、指令序列 CRUD，不执行序列、不 open 设备。README 已写如何只跑 ``pytest payload``。



单板相机的 快遥应答帧，有个特殊的功能还没有做，
ruoyi-fastapi-backend\assets\config\XL-Camera-TeleMetryCfg.json 中的CAMF011（模组工作状态反馈）字段的解析，内容的有效意义，是根据帧序号（D9帧的索引2的字节）的最低三位决定，

下面是相关文档说明
比如 EB D9 AC AD AA 01 FF FF FF FF 00 00 08 AD 00 07 D5 0C 4E EB
索引2的字节是AC，二进制 1010 1100 的低三位 100。
文档：
3位对应值	4字节数据字节数	数据内容
0	1	有效光斑阈值
	2	BOOT软件版本号
	1	数据处理控制

1	4	曝光时间

2	2	高增益阈值
	2	低增益阈值

3	1	增益
	1	TEC温控开关
	1	TEC温控模式
	1	TEC目标温度

4	2	探测器温度
	2	模组内部温度

5	2	疵点阈值1
	2	疵点阈值2

6	1	缓存图像个数
	1	缓存图像大小
	1	当前加载分区号
	1	开窗模式

7	2	开窗起始点X坐标
	2	开窗起始点Y坐标


修改方向一：
遥测表的配置是固定的不修改的，
不修改当前通用遥测表页面的显示逻辑。
 遥测表展示的通用页面不能直接增加相机的解析代码，通用页面时通用的规则，不然后续功能多了，代码就乱，
 增加传入回调函数功能，on_tm_data_recv，有这个函数，执行，
 如果返回新的遥测表数据，就使用新的，如果没有返回，就使用后端返回的，
 这样通用页面只修改了数据处理部分，改动不多。
 相机页面可以提供回调函数。 通用遥测界面收到遥测数据后，调用这个回调函数，
 这个回调函数在返回完整的遥测数据（对于相机，在后端返回基础上，合并了特殊的解析数据）.
 相机页面需要缓存D9的几个特殊字段的值
 遥测表页面在根据返回值进行显示。这样只改了数据部分。数据刷新部分没有修改。


修改方向二：
遥测表的配置把上面8个区域的20个字段增加到现有D9配置后面。
把相机遥测数据解析的功能做成插件。
在插件中，判断如果是D9类型的数据，一般D9的数据发送的频率超高，一般每次从串口读取的数据超过8帧（可以在插件中缓存最近的8帧也可以，这样新获取的和旧的缓存，肯定都能找到完整的0-7对应的数据），拿出最后一帧额数据，然后倒查遍历数据，把所有0-7的索引的最后一个字节都找到。提取出最后一帧的有效载荷部分（传递给遥测解析部分数据），然后把找到的0-7的索引数据拼接。
然后在调用遥测解析，这样其他地方都不用修改。




计划修改，
配置表增加，单元格名字尽量参考D8表格的，也就是两边最好名字统一。
最新8个数据获取就是，先查这次从串口获取的数据列表中，如果不够，再去缓存查找，还不够就填0.
原来的功能函数的代码修改尽量小，新增的修改尽量在单独的函数中处理数据。






test\单板-相机-遥测D9.txt  每一行都是一帧D9的遥测数据，
根据需要，取合适数量的数据，写入到单例测试中去，进行完整组帧测试，给出的遥测结果对比，
 至少进行2轮（16帧以上）完整的取数据，解析出结果。

→ 已改：从该文件取 seq B0–BF 共 16 帧（两轮完整 mux0–7）写入 ``test_camera_sc_link41ep.py``。每轮 8 帧一次 ingest，校验拆帧、本帧 CAMF001–011，以及拼接后的 CAMF012–031（两轮 mux 四字节相同，扩展字段一致）。


取数据太规范了，直接取前面30行。真实数据来的时候，可不会从索引0开始。
camera_sc_link41ep.py 给加上详细的注释，现在注释太少了。函数需要，函数内部关键节点也需要注释。

→ 已改：单测改为文件前 30 行（seq AE 起 mux=6），两轮各 15 帧 ingest。``camera_sc_link41ep.py`` 补了模块/函数说明，以及拆帧、mux 本批→缓存→0、48B 拼接等关键节点注释。


首页/单板/相机测试 的 页面，遥测表切换的时候，这时候分辨率应该是需要改变的。
前端原来从d8取数据的几个类型，切换到d9了，也要从d9的几个新增类型取数据，比如分辨率。
d9新增CAMF012-CAMF031

→ 已改：相机页分辨率跟当前遥测表走。D8 仍用 CAM036/CAM038；切到 D9 用 CAMF029（开窗模式）/ CAMF027（缓存图像大小），不再回落到 D8。



完善注释，增加从git  16e823021e8603df744ad55f34155a72b4fcc837 以来新增功能的注释，
包括类、函数、成员变量、和函数内的关键节点。

→ 已改：自该提交起新增的地检 payload 生产代码补了中文注释（类/函数 docstring、成员说明、拆帧/mux/全双工/溢出清理/组帧公式等关键节点）。覆盖采集、解析、组帧、配置、服务、控制器与相机/遥测/遥控前端页。测试脚本未逐条加 docstring。


曲线显示界面，已有曲线情况下，切换到其他遥测表界面，再次页面带参数跳转到曲线界面时，
虽然表不一样，但不需要显示确认提示，直接清理旧数据，显示新的曲线。

→ 已改：从遥测表双击带 ``from=table`` 跳入曲线页时，跨表直接清空旧曲线再加载，不再弹「更换遥测表」确认。本页点「增加曲线」换表仍保留确认。





菜单 遥测曲线 改名  遥测实时曲线
菜单 遥测归档数据 改名 遥测历史曲线
新增遥测文件曲线
新增

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






