# 第 2 章 MSS 与 Window Scaling

## 1. 为什么需要这个机制

两个问题决定了 TCP 传输的"颗粒度"和"上限"：

1. **一个 Segment 最多装多少字节？** —— MSS（Maximum Segment Size）。
2. **窗口字段只有 16 位（最大 65535），高速长距离链路怎么办？** —— Window Scaling（RFC 7323）。

这两个参数都在**三次握手时一次性确定**，之后不能改。分析任何 pcap 时，如果没抓到握手，你就不知道 Window Scale 因子，Wireshark 会把窗口算错——这是实际排障中最常见的坑之一。

## 2. 没有它会发生什么

没有 MSS 协商：发送 IP 分片，任何一片丢失整段重传，且许多网络设备对分片不友好。没有 Window Scaling：窗口上限 64 KB；在 RTT=100ms 的链路上吞吐上限 = 65535 B / 0.1 s ≈ **5.2 Mbps**——不管你的链路是 1 Gbps 还是 100 Gbps。

## 3. 核心原理

### 3.1 MSS

`MSS = MTU − IP头 − TCP头`。以太网 MTU 1500 ⇒ MSS = 1500 − 20 − 20 = **1460**（无 TCP Option 时的载荷上限；带 Timestamps 选项时每段实际载荷 1448）。MSS 在 SYN 和 SYN/ACK 中各自通告，双方取对方通告值与本地能力的较小者，两个方向可以不同。隧道/VPN/云 Overlay（VXLAN 减 50 字节、IPsec、PPPoE 减 8 字节）会压低 MTU，因此生产环境常见 MSS=1360、1400、1412 等值；负载均衡器和防火墙常做 **MSS Clamping**（改写 SYN 中的 MSS）——所以两个抓包点看到的 MSS 可能不一样，这是正常的设备行为而非篡改攻击。

### 3.2 Window Scaling

TCP Header 中 Window 字段 16 位。RFC 7323 在握手中加入 Window Scale Option：通告一个 0–14 的移位因子 S，此后本方通告的窗口真实值 = `Window字段 × 2^S`。三个关键点：

1. **只在 SYN/SYN·ACK 中出现**，连接中途不可变。
2. 双方因子独立，方向不同因子可以不同。
3. 抓包没抓到握手 ⇒ Wireshark 不知道 S ⇒ `Calculated Window Size` 不可信（Wireshark 会假设 -1/未知，可用 `Preferences → Protocols → TCP → Scaling factor` 手工指定）。

由此必须区分三个概念（rwnd 一章会用真实抓包展示）：

| 名称 | 是什么 | 谁提供 |
|---|---|---|
| Window Size Value | 报文里的 16 位原始值 | 线上字段，直读 |
| Window Scale | 握手中协商的移位因子 | 握手报文，直读 |
| Calculated Window Size | Value × 2^Scale | **Wireshark 推导** |

### 3.3 BDP：为什么需要大窗口

**BDP（Bandwidth-Delay Product）= 带宽 × RTT**，是"填满管道"所需的在途字节数。要跑满链路，必须满足：

```
有效窗口 ≥ BDP = Bandwidth × RTT
吞吐上限 ≈ Window / RTT        （窗口受限时）
```

| 链路 | RTT | BDP | 64KB 窗口能跑多少 |
|---|---:|---:|---:|
| 1 Gbps 城域 | 2 ms | 250 KB | 262 Mbps |
| 1 Gbps 跨国 | 150 ms | 18.75 MB | 3.5 Mbps |
| 10 Gbps 跨region | 70 ms | 87.5 MB | 7.5 Mbps |

这张表解释了为什么"同一台服务器，内网下载很快、跨国下载极慢"常常与丢包无关——纯粹是窗口没开够（第 19 章 Case 1）。

## 4. 关键变量

MSS（双向、握手确定）、MTU、Window Scale 因子 S（双向、握手确定）、BDP、`tcp.window_size_value` / `tcp.options.wscale.shift` / `tcp.window_size`（Calculated）。

## 5. 数学关系

```
MSS = MTU − 40 (IPv4，无选项)        真实窗口 = Window字段 × 2^S
最大可表达窗口 = 65535 × 2^14 ≈ 1 GiB
窗口受限吞吐 = min(rwnd, cwnd) / RTT
```

## 6. 数值案例 【教学模拟案例】

东京→新加坡，1 Gbps，RTT 70ms。BDP = 1×10⁹/8 × 0.07 = 8.75 MB。
- 无 WS：吞吐 ≤ 65535/0.07 ≈ 7.5 Mbps（链路利用率 0.75%）。
- WS=7（×128）：最大窗口 8 MB，吞吐 ≤ 8MB/0.07 ≈ 915 Mbps ≈ 基本填满。
- 所需最小因子：8.75MB / 65535 ≈ 134 ⇒ S≥8。

## 7. TCP Timeline

```
Client                                            Server
  |-- SYN  MSS=1460 WS=7 SACK_PERM --------------->|
  |<-- SYN/ACK  MSS=1400 WS=9 SACK_PERM -----------|   ← 两个方向 MSS/WS 都可不同
  |-- ACK  Win=502 (真实=502×128=64256) ----------->|
```

此后 Client 报文里 Win=502 的真实含义是 64256 字节；Server 通告 Win=63 的真实含义是 63×512=32256 字节。

## 8–10. 实验拓扑 / 制造流量 / 抓包位置

附录 A 环境。观察 WS 的作用最直接的办法是关掉它对比：

```bash
# 制造 70ms RTT
ip netns exec ns-wan tc qdisc add dev veth-w1 root netem delay 35ms
ip netns exec ns-wan tc qdisc add dev veth-w2 root netem delay 35ms
# 基线
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 10
# 关闭 window scaling 后重跑（需在两端 netns 都执行）
ip netns exec ns-client sysctl -w net.ipv4.tcp_window_scaling=0
ip netns exec ns-server sysctl -w net.ipv4.tcp_window_scaling=0
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 10
```

预期：关闭 WS 后吞吐从数百 Mbps 跌到 ~7 Mbps 量级。若没跌，检查 netem 是否生效（`tc -s qdisc`）、RTT 是否真有 70ms（ping）。

## 11–13. Wireshark 抓包图与 Frame-by-Frame 【教学模拟案例·可复现】

```
No.  Src       Info
1    10.0.0.1  [SYN] Seq=0 Win=64240 Len=0 MSS=1460 WS=128 SACK_PERM TSval=...
2    10.0.0.2  [SYN,ACK] Seq=0 Ack=1 Win=65160 Len=0 MSS=1460 WS=128 SACK_PERM
3    10.0.0.1  [ACK] Win=64256 Len=0
...
57   10.0.0.2  [ACK] Ack=1048577 Win=3145728 Len=0     ← Calculated；原始字段其实是 24576
```

- **Frame 1**：`WS=128` 是 Wireshark 的友好显示，报文里实际是 shift=7。SYN 的 Win=64240 **不受** scale 影响（RFC 7323：SYN 本身的窗口不缩放）。
- **Frame 57**：展开 TCP 头看三行：`Window: 24576`（Window Size Value，线上字段）、`[Window size scaling factor: 128]`、`[Calculated window size: 3145728]`——后两行都带方括号，方括号在 Wireshark 中一律表示**推导值**。
- 若从 Frame 50 才开始抓（没有握手）：Frame 57 会显示 `[Window size scaling factor: -1 (unknown)]`，Calculated 值退化为 24576——**低了 128 倍**。用这个值判断 rwnd 限制会得出完全错误的结论。

## 14–15. 操作系统内部状态 / ss 分析

```
$ ip netns exec ns-client ss -ti dst 10.0.0.2
... cubic wscale:7,7 rto:274 rtt:70.3/0.5 mss:1448 cwnd:846 ...
```

`wscale:7,7` 分别是 snd_wscale, rcv_wscale。`mss:1448` 是扣掉 Timestamps 选项后的实际每段载荷——这解释了为什么抓包里数据段 Len=1448 而不是 1460。

## 16–18. 正常特征 / 异常特征 / 抓包指纹

**正常**：握手双方都带 WS；数据段 Len ≈ MSS。
**异常指纹 A（WS 被剥离）**：SYN 带 WS 而 SYN/ACK 不带 ⇒ 服务端不支持或**中间设备剥离了选项**（老旧防火墙/LB 的经典问题）⇒ 整条连接窗口封顶 64KB。
**异常指纹 B（MSS 黑洞）**：握手正常、小包正常、一发大文件就卡死，重传的全是满 MSS 段 ⇒ 路径 MTU 比协商 MSS 小且 ICMP Fragmentation-Needed 被防火墙拦截。下一步查 `tracepath`、检查隧道封装开销。
**不能据此直接判断**：窗口大 ≠ 吞吐高（可能 cwnd 受限，第 19 章）。

## 19. Wireshark Filter

```
tcp.flags.syn==1                          # 只看握手，检查 MSS/WS/SACK_PERM
tcp.options.wscale.shift                  # 有 WS 选项的报文
tcp.options.mss_val < 1460                # 被 clamp 过的 MSS
tcp.window_size_value != tcp.window_size  # 提醒自己两者的区别（scale>0 时恒真）
```

## 20. TCP Stream Graph

Window Scaling Graph（Statistics → TCP Stream Graphs → Window Scaling）：绿色线为对端通告窗口（Calculated），蓝点为 Bytes in Flight。X 轴时间、Y 轴字节。**窗口受限的形态**：蓝点持续贴着绿线顶。本章实验关闭 WS 后重画：绿线封顶在 65535，蓝点贴顶，吞吐钉死——这就是"窗口不够"的标准图形。

## 21–23. 2025–2026 真实业务应用与生产案例

**【真实生产案例】Cloudflare：为高 BDP 连接开大接收窗口，同时避免延迟尖峰（2022）**

Cloudflare 的边缘服务器同时服务全球客户端，跨洋连接 BDP 巨大。其工程博客给出的生产数据（事实，来源①）：早年为规避内核 `tcp_collapse` 造成的延迟尖峰，曾把 `tcp_rmem` 上限压到 4 MiB，代价是高 RTT 链路吞吐受限——文中给出"窗口 2 MiB 时吞吐随 RTT 的衰减曲线"；2022 年重新调优为 `tcp_rmem` max = 512 MiB + `tcp_adv_win_scale = -2`，使自动调优允许的最大接收窗口达到 128 MiB，既覆盖高 BDP 会话又控制 collapse 开销。

- **事实**（来源明确提供）：上述 sysctl 数值、tcp_collapse 机制、调优前后动机与效果。
- **分析推断**（本教程推导）：128 MiB 窗口按 RTT=150ms 折算可支撑约 7 Gbps 单流——对边缘↔源站的大流足够；这也说明**接收窗口上限是运营商级性能参数，不是"默认值够用"**。

**案例来源**：① Cloudflare Blog, *Optimizing TCP for high WAN throughput while preserving low latency*, 2022, https://blog.cloudflare.com/optimizing-tcp-for-high-throughput-and-low-latency/ ；② Cloudflare Blog, *The story of one latency spike*, 2015-11, https://blog.cloudflare.com/the-story-of-one-latency-spike/ 。（完整证据链见第 21 章案例 R2。）

## 24. 如果在生产环境我怎么排查

跨地域吞吐低：① 先抓握手，确认双方 WS/MSS；② `ss -ti` 看 `wscale` 与实际窗口；③ 算 BDP，对比 Window Scaling Graph 里绿线高度；④ 绿线贴 BDP 以下 ⇒ 调 `tcp_rmem`/应用 SO_RCVBUF；⑤ 绿线够高但蓝点上不去 ⇒ 不是 rwnd 的问题，转查 cwnd（第 6、19 章）。

## 25. 常见误判

- Wireshark 显示 Win=64 ≠ 窗口只有 64 字节（可能 scale 因子未知或未乘）。
- SYN 里 Win=64240 很大 ≠ 不需要 WS（SYN 的窗口不缩放，之后才需要）。
- 两个抓包点 MSS 不同 ≠ 报文被篡改（MSS Clamping 是常规操作）。
- Len=1448 ≠ MSS 协商成了 1448（是 1460 − 12 字节 Timestamps）。

## 26. 与其他 TCP 机制如何联动

MSS 决定 cwnd 的"步长"（cwnd 以字节计但按 MSS 粒度增长，第 7 章）；WS 决定 rwnd 的上限（第 4 章）；BDP 是判断"窗口够不够"的标尺（第 19 章）；抓不到握手 ⇒ WS 未知 ⇒ rwnd 分析全错（第 16 章反复强调）。

## 27. 分析练习

链路 500 Mbps，RTT 120ms。握手：Client `MSS=1460 WS=8`，Server 回 `MSS=1360`、**无 WS 选项**。问：1) 每段最大载荷？2) Client→Server 方向的最大通告窗口？3) 该方向吞吐上限？4) 要跑满链路需要多大窗口、S 至少多少？5) 抓包里应先检查哪一帧的哪个字段来确认这个问题？

## 28. 详细答案

1) 1360（取双方通告较小值；有 Timestamps 则 1348）。2) 一方不带 WS 则**双向都禁用**缩放（RFC 7323），最大 65535。3) 65535/0.12 ≈ 4.4 Mbps。4) BDP = 500e6/8×0.12 = 7.5 MB；7.5MB/65535≈115 ⇒ S≥7。5) SYN/ACK 帧的 TCP Options——确认是 Server 不支持还是中间设备剥离（对比 Server 侧抓包，第 20 章方法）。

## 29. 本章总结

MSS 定颗粒，Window Scaling 定上限，BDP 定需求。三者都在握手时定型，所以**抓包永远要从握手抓起**。下一章正式进入滑动窗口。
