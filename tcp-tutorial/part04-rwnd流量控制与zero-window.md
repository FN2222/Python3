# 第 4 章 rwnd、流量控制与 Zero Window

## 1. 为什么需要这个机制

**rwnd 到底是谁控制的？——接收方，且只有接收方。**

发送方可以有千兆网卡和無限的发送欲望，但接收方的内存是有限的、应用读取速度是有限的。流量控制回答的问题是：**"接收方还能安全接住多少字节？"** 这与拥塞控制（"网络路径还能承载多少字节？"，第 6 章起）是两个完全独立的问题——教材把它们混为一谈是生产误判的重要来源。

## 2. 没有它会发生什么

发送方按自己的速度灌数据 ⇒ 接收缓冲溢出 ⇒ 接收方只能丢弃已经成功穿越整个网络的报文 ⇒ 发送方重传 ⇒ 继续溢出。带宽被"到达即丢弃"的数据浪费，越快越糟。

## 3. 核心原理

### 3.1 三个速度与一个缓冲

```
网络到达速度 ──▶ ┌──────────────────┐ ──▶ 应用 read() 速度
                │ socket receive buffer │
                └──────────────────┘
                 rwnd ≈ 缓冲区剩余空间（Linux 中还要打折，见 3.2）
```

- 应用读得比到达快 ⇒ 缓冲常空 ⇒ rwnd 稳定在大值。
- 应用读得慢（GC 停顿、磁盘 I/O、锁竞争、CPU 饱和）⇒ 缓冲堆积 ⇒ rwnd 逐步收缩 ⇒ 0。

**rwnd 是协议层概念**：它实实在在写在每个 ACK 的 Window 字段里，Wireshark 直读（乘上 scale 后）。这与 cwnd（纯内核内部状态）形成对照。

### 3.2 Linux 的实现细节（为什么通告值 < 缓冲剩余）

- 缓冲大小由 `net.ipv4.tcp_rmem = min default max` 与 `SO_RCVBUF` 决定；默认开启**自动调优**（`tcp_moderate_rcvbuf=1`），缓冲随流的 BDP 需求增长。应用一旦 setsockopt SO_RCVBUF，自动调优即关闭——生产中"手工调小了反而更慢"的常见原因。
- 内核要为每个报文存元数据（sk_buff 开销），所以只把缓冲的一部分用作通告窗口（`tcp_adv_win_scale`，新内核为 `scaling_ratio` 动态估计）。
- 通告窗口还被 `rcv_ssthresh` 压住，从 64 KiB 起步逐 RTT 线性放大（第 3 章 Cloudflare 案例）。
- **窗口不收缩原则**（RFC 7323 §2.4）：接收方不应把右边缘往回拉；窗口减小只能通过"Ack 前进而 Win 同步减小"实现。

### 3.3 Zero Window 机制链

1. 缓冲满 ⇒ 接收方通告 **Win=0**（Zero Window）。
2. 发送方冻结数据发送，启动 **Persist Timer**。
3. 定时发送 **Zero Window Probe（ZWP）**：通常是 1 字节数据（Linux）或纯探测，逼对方回 ACK 报告最新窗口；间隔指数退避。
4. 应用读走数据 ⇒ 接收方主动发 **Window Update**（Ack 不变、Win>0、Len=0）。
5. 若 Window Update 丢了怎么办？——正是 ZWP 存在的意义：没有探测机制，双方会永久死锁（发送方等窗口、接收方等数据）。

## 4. 关键变量

| 变量 | 层次 | 观测工具 |
|---|---|---|
| Window Size Value | 报文字段 | Wireshark 直读 |
| Window Scale | 握手字段 | Wireshark 直读（需抓到握手） |
| Calculated Window Size | 推导 | Wireshark（方括号字段） |
| Recv-Q | 内核状态 | `ss -tn` |
| skmem rb / r | 内核状态 | `ss -tm` |
| rcv_ssthresh / rcv_space | 内核状态 | `ss -ti` |

## 5. 数学关系

```
rwnd ≈ min(缓冲可用空间 × 折扣系数, rcv_ssthresh)
右边缘 = 最新Ack + 最新rwnd
rwnd 限制下的吞吐上限 = rwnd / RTT
```

## 6. 数值案例 【教学模拟案例】

RTT=40ms，网络无丢包、带宽充裕。接收应用每 100ms 才读一次、每次读 200 KB；到达速率试图维持 4 MB/s（=160 KB/RTT）。缓冲 512 KB：

| 时刻 | 缓冲占用 | rwnd 通告 |
|---|---:|---:|
| t=0 | 0 | 512 KB |
| t=40ms | 160 KB | 352 KB |
| t=80ms | 320 KB | 192 KB |
| t=100ms | 读走200KB→120 KB | 392 KB |
| …稳态 | 锯齿波动 | 锯齿波动 |

若应用停止读取 300ms：缓冲在 ~130ms 内填满 ⇒ Win=0 ⇒ 停流。**吞吐由读取速度决定（2 MB/s），与带宽无关**——这就是"网络没问题但传输慢"的第一种标准形态。

## 7. TCP Timeline（Zero Window 完整链）

```
Sender                                          Receiver(应用卡死)
  |-- Seq=90001 Len=1448 ------------------------>| 缓冲最后一点空间
  |<----------------- Ack=91449 Win=0 ------------|  ZeroWindow
  |          (Persist Timer ≈ RTO 启动)            |
  |-- Seq=91449 Len=1 [ZWP] --------------------->|
  |<----------------- Ack=91449 Win=0 [ProbeAck]--|
  |          (退避后再探测: 2×, 4×, ...)            |
  |-- Seq=91449 Len=1 [ZWP] --------------------->|
  |<----------------- Ack=91449 Win=0 ------------|
  |                                  (应用恢复读取) |
  |<----------------- Ack=91449 Win=63000 --------|  [Window Update]
  |-- Seq=91450 Len=1448 ------------------------>|  恢复
```

## 8–10. 实验拓扑 / 制造流量 / 抓包位置（EXP-04）

```bash
# server：收到连接后先读 1KB，然后 sleep 30 秒不读
ip netns exec ns-server python3 - <<'EOF' &
import socket,time
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(("10.0.0.2",5201)); s.listen(1)
c,_=s.accept(); c.recv(1024); time.sleep(30)
while True:
    d=c.recv(65536)
    if not d: break
EOF
ip netns exec ns-server tcpdump -i veth-s -w zerowin.pcap 'tcp port 5201' &
ip netns exec ns-client bash -c 'cat /dev/zero | head -c 50M | nc 10.0.0.2 5201'
# 同时在第三个终端观察内核视角：
watch -n1 'ip netns exec ns-server ss -tnm state established "( sport = :5201 )"'
```

预期 `ss` 输出中 `Recv-Q` 涨到与 `skmem rb` 同量级并保持——**Recv-Q 高位不动 = 应用不读**，这是内核侧的决定性证据（对照：Dell PowerScale KB 也用同一判据，见 §22）。

## 11–12. Wireshark 抓包图与标注

【图 4-1 Zero Window 事件链】

```
No.    Time      Src     Info                                          标注
 812   3.9921    client  Seq=1893601 Len=1448                          ①最后的正常数据
 813   3.9922    server  Ack=1895049 Win=1448                          ②窗口只剩一个MSS
 814   3.9923    client  Seq=1895049 Len=1448 [TCP Window Full]        ③额度将尽
 815   3.9925    server  Ack=1896497 Win=0   [TCP ZeroWindow]          ④停!
 816   4.2010    client  Seq=1896497 Len=1  [TCP ZeroWindowProbe]      ⑤第1次探测(~200ms后)
 817   4.2011    server  Ack=1896497 Win=0  [TCP ZeroWindowProbeAck]   ⑥仍为0
 818   4.6180    client  Seq=1896497 Len=1  [TCP ZeroWindowProbe]      ⑦第2次探测(退避≈2×)
 ...
 902  33.9987    server  Ack=1896497 Win=3145728 [TCP Window Update]   ⑧应用恢复
 903  33.9989    client  Seq=1896498 Len=1448                          ⑨传输恢复
```

⑫Time Delta 视角：816−815≈209ms、818−816≈417ms——指数退避是 ZWP 的时间指纹。

## 13. Frame-by-Frame 分析

- **Frame 815**：Win 原始值就是 0（不是 scale 换算问题——0×任何因子=0）。Wireshark 标 ZeroWindow 依据仅此字段。
- **Frame 816 为什么 Len=1？** Linux 的窗口探测携带窗口外的 1 个字节（Seq 恰为右边缘 1896497），若对方缓冲已有空间会顺便接收。**证据**：Frame 902 后恢复的数据从 1896498 开始，说明探测字节最终被接收并占用了序号。
- **Frame 817 与 815 的 Ack/Win 完全相同**，但它是对探测的强制应答（ProbeAck），不是 Dup ACK——判据：它是对**窗口外字节**的响应，且没有乱序数据到达的上下文。Wireshark 能正确区分两者，人工分析时别混。
- **Frame 902**：Ack 没变（没有新数据要确认）、Win 从 0→3145728、Len=0 ⇒ 教科书式 Window Update。

## 14–15. 操作系统内部状态 / ss 分析

接收侧三连：

```
ss -tnm   → Recv-Q: 3145728  skmem:(r3145728,rb3145728,...)   # 队列顶满缓冲
ss -ti    → rcv_space:...  rcv_ssthresh:...                   # 自动调优状态
pidstat / perf top -p <PID>                                    # 应用为什么不读？
```

发送侧 `ss -ti` 此时可见 `notsent` 巨大、`cwnd` 正常——**发送端一切健康**，这是把责任从"网络"移交给"接收应用"的内核证据。

## 16–18. 正常特征 / 异常特征 / 抓包指纹

**正常**：偶发几十 ms 的 Win=0（突发填满，很快 Update）。
**异常**：Win=0 持续秒级/反复出现；或 rwnd 长期贴着某个小值锯齿（缓冲配小了/自动调优被 SO_RCVBUF 关了）。
**抓包指纹（Zero Window）**：`Win=0 → ZWP(指数退避) → ProbeAck(Win=0) → … → Window Update`。
**看到什么**：接收方通告 0。**为什么出现**：缓冲满，根因几乎总在接收侧应用/主机。**不能据此判断**：网络拥塞（恰恰相反，Zero Window 期间网络是空的）。**下一步查**：接收端 Recv-Q → 应用线程栈/GC/磁盘。

## 19. Wireshark Filter

```
tcp.analysis.zero_window            tcp.analysis.zero_window_probe
tcp.analysis.zero_window_probe_ack  tcp.analysis.window_update
tcp.window_size == 0 && tcp.flags.reset == 0
```

## 20. TCP Stream Graph

Window Scaling Graph：绿线（通告窗口）阶梯式下降到 0、水平躺平、再跳回——"绿线触底"是 Zero Window 的图形指纹。Time-Sequence (Stevens)：数据斜线在 Win=0 期间变成水平——**时间在流逝而字节不前进**。对比第 12 章 RTO 的水平段：RTO 段末尾是同一 Seq 重发（竖直回落的 tcptrace 视图），Zero Window 段末尾是从新 Seq 继续——两种"平台"图形相似，判据完全不同。

## 21. 2025–2026 真实业务应用

Zero Window 在现代生产中的高发场景：代理/网关（Envoy、nginx）后端读取慢造成前端连接 rwnd 收缩；数据库客户端批量拉取结果集处理慢；对象存储客户端写盘慢；安全设备（TLS 解密盒）处理不过来；消费者堆积的消息队列客户端。Kubernetes 里典型形态是 Pod CPU limit 导致应用被 throttle，读 socket 变慢，表现为上游 Zero Window（第 22 章综合案例 5 完整展开）。

## 22–23. 真实生产案例与证据链

**【真实生产案例】Dell PowerScale：以 Recv-Q + Zero Window 判定接收应用瓶颈（厂商 KB，2023–2024 维护）**

Dell 官方 KB 000221738 描述其存储节点发送 Zero Window 更新导致客户端写延迟升高的排障方法。**事实**（来源提供）：节点侧统计 `0-win` 计数；判定规则为——Zero Window 伴随 `Recv-Q` 持续非零 ⇒ 接收应用（NFS/SMB 服务进程）读取不及时，应查应用/CPU/磁盘瓶颈；`Recv-Q` 为零却频发 Zero Window ⇒ 接收窗口相对 BDP 配置过小，才考虑 TCP 调优。**推断**（本教程）：该 KB 的两分支判定与本章 §14 的 ss 判据一致，可以作为通用方法使用，不限于存储设备。
**案例来源**：Dell Support KB 000221738, *Troubleshoot TCP zero window update packets sent by a PowerScale node*, https://www.dell.com/support/kbdoc/en-us/000221738/ 。

**【真实生产案例】OneUptime：Zero Window 解读与处置（2026-03）**：监控厂商 OneUptime 的工程博客（2026-03-20）给出与上文一致的生产处置顺序：先 `tcp.analysis.zero_window` 确认在线证据，再查接收应用 CPU/IO/strace 读调用延迟，最后才考虑调大 tcp_rmem；并强调"短暂 Zero Window 属正常，持续/频繁才是瓶颈"。来源：https://oneuptime.com/blog/post/2026-03-20-tcp-zero-window-packet-captures/view 。

**证据链模板**（生产判 Zero Window 根因）：
证据1 抓包 `Win=0` + ZWP 序列存在 → 证据2 Zero Window 期间无重传/无 Dup ACK（网络路径健康）→ 证据3 接收端 `Recv-Q ≈ rb` 持续 → 证据4 应用线程栈显示阻塞点（GC/IO/锁）→ 结论：接收应用瓶颈；网络无责。

## 24. 如果我现在在生产网络值班

看到"传输卡住"：① filter zero_window——有 ⇒ 这是流控不是拥塞；② 确认是**哪一侧**通告 0（Src 是谁）；③ 登录该侧 `ss -tnm` 看 Recv-Q；④ Recv-Q 高 ⇒ 查应用（strace read 间隔、GC 日志、iostat）；⑤ Recv-Q 低 ⇒ 查缓冲配置（SO_RCVBUF 是否锁死了自动调优）；⑥ 别急着调 sysctl——调大缓冲只是把堆积从 TCP 挪进内存，读得慢的根因还在。

## 25. 常见误判

- Zero Window ≠ 网络拥塞（方向相反：是端侧背压）。
- Zero Window ≠ 一定是 Bug（应用的瞬时忙碌本来就该让 TCP 刹车——这是机制在正常工作）。
- 调大 `tcp_rmem` ≠ 修复（多数情况只是延迟发作）。
- ZWP 的 ProbeAck ≠ Dup ACK（上下文完全不同，见 §13）。
- 发送慢 ≠ 接收方 rwnd 小（还可能是 cwnd/应用/pacing——先看 Window 字段再下结论）。

## 26. 与其他 TCP 机制如何联动

rwnd 是 min(rwnd,cwnd) 的第一元（第 6 章）；Zero Window 期间 cwnd 不衰减（Linux 中拥塞状态不因流控暂停而惩罚），恢复后不需要重新 Slow Start（但长时间空闲会触发 `tcp_slow_start_after_idle`，第 7 章）；rwnd 收缩会抑制 Dup ACK 产生所需的后续数据量，间接增加 RTO 概率（第 12 章）。

## 27. 分析练习

抓包片段（Server 是数据接收方）：

```
Frame  Time     Src  Info
50     10.000   C    Seq=52001 Len=1448
51     10.001   S    Ack=53449 Win=2896
52     10.002   C    Seq=53449 Len=1448
53     10.003   C    Seq=54897 Len=1448 [Window Full]
54     10.004   S    Ack=56345 Win=0
55     10.215   C    Seq=56345 Len=1
56     10.216   S    Ack=56345 Win=0
57     10.640   C    Seq=56345 Len=1
58     11.900   S    Ack=56345 Win=57920
59     11.901   C    Seq=56346 Len=1448
```

1) Frame 53 标 Window Full 的依据？2) Frame 55/57 是什么、时间间隔说明什么？3) Frame 56 是 Dup ACK 吗？4) 停顿总时长多少、责任在哪一侧？5) 下一步在接收端查什么命令？

## 28. 详细答案

1) Frame 51 通告右边缘 = 53449+2896 = 56345；Frame 52、53 发满 53449–56344 共 2896 字节，BiF==rwnd。2) Zero Window Probe；间隔 10.215→10.640 ≈ 2 倍退避，符合 persist timer 指数退避指纹。3) 不是。它与 Frame 54 同 Ack 同 Win，但它是对窗口外探测字节的强制应答（ProbeAck），无乱序上下文。4) 10.004→11.900 ≈ 1.9s；责任在 Server 侧（它通告 0）。5) `ss -tnm` 看 Recv-Q/rb，随后对应用 `strace -e read`/`perf top`。

## 29. 本章总结

rwnd 由接收方独家控制，反映"缓冲还能接多少"；Zero Window→Probe→Update 是完整的背压闭环。**它解释不了发送方"明明窗口很大却发得很慢"的情况**——那是另一个看不见的窗口在起作用：cwnd。第 5 章先把"在途数据"量化，第 6 章正式引入 cwnd。
