# 第 18 章 NIC Offload 与抓包误判：你抓到的不是线上的包

## 1. 为什么必须有这一章

现代主机把大量 TCP 分段/合并/校验工作卸载给网卡。而 **tcpdump 的抓包点（AF_PACKET tap）在协议栈与网卡之间**：

```
应用 → TCP/IP 栈 → [tap:发送方向抓包点] → qdisc → 驱动 → 网卡(TSO分段/校验计算) → 线路
线路 → 网卡(LRO/GRO合并) → 驱动 → [tap:接收方向抓包点] → TCP/IP 栈 → 应用
```

所以：**发送方向你抓到的是"分段前"的包，接收方向抓到的是"合并后"的包**。线路上的真实形态两头都看不见。不懂这一点，现代主机上的 pcap 会让你"发现"一堆不存在的异常。

## 2. 各类 Offload 与它制造的抓包假象

| 技术 | 做什么 | 抓包假象 |
|---|---|---|
| **TSO**（TCP Segmentation Offload，发送） | 栈交给网卡最大 64KB 的"巨段"，网卡按 MSS 切 | pcap 里出现 `Len=11584` 甚至 `Len=64240` 的段，**远超 MSS**；I/O 图突发形态失真 |
| **GSO**（Generic SO，发送） | 软件版 TSO，qdisc 之后才分段 | 同上 |
| **GRO**（Generic Receive Offload，接收） | 内核把连续小段合并成大段再上送 | 接收侧 pcap 段数比线上少、单段巨大；ACK 看起来"一个确认好几万字节" |
| **LRO**（Large Receive Offload，接收，网卡硬件） | 硬件合并（比 GRO 激进，可能破坏转发） | 同上且转发场景可致真实故障 |
| **Checksum Offload**（发送） | 栈不算校验和，网卡发出前才填 | 发送侧 pcap 中本机发出的包 **checksum 全错**（Wireshark 红色 "Incorrect checksum"）|

## 3. 三大经典误判与自检方法

### 误判一："TCP 段大于 MSS，一定有问题！"

在**本机**抓包看到 Len=8688（6×1448）：这是 TSO/GRO 的正常产物，线路上仍是标准 MSS 段。**自检**：段大小是否总是 MSS 的整数倍、是否只出现在本机收发方向、`ethtool -k eth0 | grep -E 'tso|gro|gso'` 是否 on。**何时当真**：在交换机镜像口/中间设备上看到超 MSS 段才是真异常（MTU/隧道问题）。

### 误判二："Incorrect TCP Checksum，报文损坏！"

只要错的是**本机发出**的包且 Checksum Offload 开着，这是预期现象（抓包时校验和还没算）。**自检**：错的是否全是本机源地址的包；对端抓包同一报文校验和是否正确。Wireshark 可关闭校验（Preferences→TCP→Validate checksum）。**何时当真**：**接收**方向出现校验错误且伴随该段被栈丢弃（对端重传同段）——真损坏，查线缆/光模块/网卡（`ethtool -S` 的 crc/rx_errors 计数）。

### 误判三：把 GRO 合并当成"对端发了巨包"或把突发当 pacing 失效

接收侧 pcap 的时间戳是**合并后上送**的时刻，微观时序（包间隔、到达突发度）已被抹掉。测 pacing、微突发、包间隔，必须在**交换机镜像/独立 tap** 上抓，或关掉 offload。

## 4. 抓包位置不同为什么看到不同的世界

| 抓包点 | 段大小 | 时间戳精度 | 校验和 | 适用 |
|---|---|---|---|---|
| 发送主机 | 巨段(TSO前) | 栈时刻(非线上时刻) | 本机发出=错 | 逻辑分析、Seq/Ack 链 |
| 接收主机 | 巨段(GRO后) | 合并后时刻 | 正常 | 逻辑分析 |
| 交换机镜像/TAP | 真实 MSS 段 | 线上真实 | 正常 | 微观时序、丢包定位、取证 |

**这些超大 Segment 是否真的在线路上传输？——没有。** 线路上永远是 ≤MSS 的标准段（除非路径 MTU 允许 jumbo）。两点抓包对比时（第 20 章），一侧巨段、一侧标准段是正常差异，用 **Seq 范围**（而非包个数）对齐两侧。

## 5. 实验（EXP-11：开关 GRO/TSO 对比）

```bash
ip netns exec ns-server ethtool -K veth-s gro off tso off gso off
ip netns exec ns-client ethtool -K veth-c gro off tso off gso off
# 重跑 iperf3 + 抓包，对比：
#   开启时: 单帧 Len 可达 65160；关闭后: 全部 ≤ MSS
# 注意：veth 的 offload 默认全开，这个实验也解释了为何 netns 实验里常见巨段
```

顺带的性能观察：关闭 offload 后 CPU 软中断占用明显上升——offload 存在的意义（40G/100G 时代没有 TSO/GRO，CPU 根本喂不饱网卡）。**生产环境不要为了抓包好看关 offload**，要真实线路形态去镜像口抓。

## 6. Capture Loss：抓包器自己丢包

高速链路上 tcpdump/内核缓冲跟不上时会丢帧——pcap 里出现**假缺口**：

- 指纹：`ACKed unseen segment`（对端确认了 pcap 里不存在的数据）+ `Previous segment not captured`，但业务与 ss 计数一切正常。
- 自检：tcpdump 结束时的 `packets dropped by kernel`；`capinfos` 看抓包速率是否接近磁盘/CPU 极限。
- 对策：加 `-s 128` 只抓头、收窄 BPF 过滤器、`-B 4096` 加大缓冲、或改用镜像口专业采集。
- 纪律：**capture loss 非零的 pcap，其"重传/丢包"结论一律降级为待证**。

## 7. 生产排障思路

主机 pcap 分析前的三项例行体检：① `ethtool -k` 记录 offload 状态；② tcpdump 退出统计 kernel drop；③ filter `tcp.analysis.ack_lost_segment` 计数。三项都干净，才进入正式分析。凡向他人移交 pcap，附上这三项信息——省掉对方半天误判。

## 8. 练习

同事给你一个在应用服务器上抓的 pcap："你看，服务器发的包全是 checksum error，而且有 64KB 的巨型包，网卡肯定坏了，所以用户下载慢。"pcap 里另有零星 `ACKed unseen segment`。请给出三点反驳与一个正确的下一步。

**答案**：① checksum 错误只出现在本机发出的包上 ⇒ Checksum Offload 的预期现象，非损坏；② 64KB 巨段是 TSO 抓包点位置造成，线路上是标准 MSS 段，不存在"巨型包上网"；③ ACKed unseen segment 说明该 pcap 本身有 capture loss，其一切缺口/重传证据需降级；网卡坏的假设没有任何一条证据支持（真硬件问题应看 `ethtool -S` 错误计数与**接收**方向校验错误）。正确下一步：在交换机镜像口或对端同时抓包，配合 `ss -ti`（cwnd/rwnd_limited/retrans）先定位下载慢是 rwnd/cwnd/丢包哪一类（第 19 章流程）。

## 9. 本章总结

主机 pcap 天生带三种失真：巨段（TSO/GRO）、假校验错（offload）、假缺口（capture loss）。识别失真之后，我们才有资格进入性能对比分析——下一章：三种"下载慢"与 rwnd/cwnd 受限的对照实验。
