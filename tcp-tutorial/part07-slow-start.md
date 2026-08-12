# 第 7 章 Slow Start（慢启动）

## 1. 为什么需要这个机制：为什么 TCP 不能一开始就把链路打满？

连接刚建立时，发送方对路径一无所知：瓶颈可能是 100 Gbps 的数据中心链路，也可能是 1 Mbps 的偏远蜂窝小区。如果上来就按 rwnd（可能几 MB）满窗突发：

- 瓶颈队列瞬间被灌满 ⇒ 成串丢包 ⇒ 刚出生的连接立刻掉进重传泥潭；
- 更糟的是伤及无辜：同一队列里其他人的流量一起被丢。

Slow Start 的策略：**从小额度起步，每收到一个 ACK 就加一个 MSS 的额度**——用 ACK 作为"网络成功消化了这么多数据"的回执，指数试探网络容量。"慢"是相对"直接满窗"而言；实际是每 RTT 翻倍的指数增长，一点也不慢。

## 2. 没有它会发生什么

1986 年拥塞崩溃（第 6 章）就是没有它的世界。微观版本：现代 CDN 若对每个新连接直接发 1MB 突发，接入网的浅缓冲（如无线设备几十 KB）会被单个连接击穿。

## 3. 核心原理

- **Initial cwnd（IW）**：RFC 6928 定为 10×MSS（IW10），2011 年由 Google 测量与推动，Linux 自 2.6.39 起默认。更早教材写 IW=1~4，分析现代抓包时不要按老书套。
- **增长规则**：每收到一个确认新数据的 ACK，`cwnd += 1 MSS`。一轮 RTT 内在途的 N 段都被确认 ⇒ cwnd 翻倍 ⇒ 指数增长。
- **ACK Clock**：增长节奏由 ACK 到达节奏驱动。RTT 越长，翻倍越慢——这就是高 RTT 链路"起速慢"的根源。
- **Delayed ACK 的折扣**：接收方两段回一个 ACK ⇒ 每 RTT 实际增长 ~1.5× 而非 2×。Linux 用 ABC（RFC 3465，按确认的字节数增长）修正大部分损失。教学推演用 2×，分析真实抓包时接受 1.5–2× 之间的形态。
- **退出条件**：① cwnd ≥ ssthresh ⇒ 转入 Congestion Avoidance（第 8 章）；② 检出丢包 ⇒ 转入恢复（第 10–12 章）；③ HyStart/HyStart++（RFC 9406）：观测 RTT 抬升提前退出，避免"冲过头撞出一队列丢包"（Windows 默认启用；Linux CUBIC 内置 HyStart，4.x 起亦有 HyStart++ 变体）。
- **首个 ssthresh**：连接之初 ssthresh 通常为"无穷大"（Linux 初值 `TCP_INFINITE_SSTHRESH`），所以第一段 Slow Start 一直冲到丢包或被 HyStart 掐停为止。

## 4. 关键变量

IW、cwnd、ssthresh、MSS、RTT、每轮在途段数、Delayed ACK 比率。

## 5. 数学关系

```
第 n 轮（从0计）cwnd ≈ IW × 2^n         （理想，无 delayed ack 折扣）
达到窗口 W 所需轮数 ≈ log2(W/IW)
第 n 轮吞吐 ≈ cwnd(n) / RTT
Slow Start 期间累计发送 ≈ IW × (2^(n+1) − 1)
```

## 6. 数值案例：逐轮推演 【教学模拟案例】

假设：**MSS=1460 B，IW=10 MSS，RTT=40ms，rwnd=512KB，无丢包，忽略 delayed-ack 折扣**。

| RTT 轮 | cwnd（段/字节） | 本轮允许发送段数 | 本轮末 Bytes in Flight | 本轮收到 ACK 数 | 瞬时吞吐 (cwnd/RTT) |
|---:|---|---:|---:|---:|---:|
| 1 | 10 / 14.6KB | 10 | 14,600 | 10 | 2.9 Mbps |
| 2 | 20 / 29.2KB | 20 | 29,200 | 20 | 5.8 Mbps |
| 3 | 40 / 58.4KB | 40 | 58,400 | 40 | 11.7 Mbps |
| 4 | 80 / 116.8KB | 80 | 116,800 | 80 | 23.4 Mbps |
| 5 | 160 / 233.6KB | 160 | 233,600 | 160 | 46.7 Mbps |
| 6 | 320 / 467.2KB | 320 | 467,200 | 320 | 93.4 Mbps |
| 7 | 640 / 934.4KB→**被 rwnd 夹断 350 段** | 350 | 512,000 | — | 102.4 Mbps（=rwnd/RTT 封顶） |

三个必须体会的点：

1. **前 3 轮只发了 70 段 ≈ 102KB**。一个 100KB 的网页响应整个生命周期都活在 Slow Start 里——短流性能 ≈ Slow Start 性能（§21）。
2. 吞吐逐轮翻倍不是平滑爬升：抓包上看是**一簇突发 → 静默 → 更大一簇突发**（有 pacing 时簇内被抹匀，簇间节奏不变）。
3. 第 7 轮 min(rwnd,cwnd) 切换了限制者——cwnd 继续涨已无意义（第 6 章 min() 接力）。

## 7. TCP Timeline（前 3 轮，逐段）

```
t=0ms    C→S: Seq=1..14600 共10段(突发)                    ← cwnd=10
t=40ms   S→C: Ack=1461,2921,...,14601 (10个ACK陆续到达)
         每个ACK: cwnd+=1  → 到 t=40ms+ε 时 cwnd=20
t=40ms+  C→S: Seq=14601.. 共20段
t=80ms   S→C: 20个ACK → cwnd=40
t=80ms+  C→S: 40段 ...
```

注意：每个 ACK 到达即释放 2 段（1 段因确认离场 + 1 段因 cwnd+1）——突发其实是"ACK 驱动的细流"，整轮看才是翻倍。

## 8–10. 实验（EXP-01）

```bash
# RTT 40ms，无丢包
ip netns exec ns-client tcpdump -i veth-c -s 96 -w ss-phase.pcap &
ip netns exec ns-client bash -c 'while true; do echo "$(date +%s.%N) $(ss -ti dst 10.0.0.2|grep -o "cwnd:[0-9]*")"; sleep 0.02; done' > cwnd.log &
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 5
```

预期 cwnd.log 前 300ms：10→20→40→80→…（40ms 一跳）。若看到 10→13→17 的缓坡：delayed ack + pacing 折扣，正常；若一直卡 10：检查 iperf3 是否真在发满（-l 参数、CPU）。

## 11–13. Wireshark 抓包图与 Frame-by-Frame

【图 7-1 Slow Start 突发节奏】I/O Graph（interval 10ms）呈现 40ms 间隔、高度翻倍的"梳齿"。Packet List 关键帧：

```
No.  Time     Src  Info
4    0.0002   C    Seq=1 Len=1448        ┐
...                                       ├ ①第一簇恰好10段 = IW10 的直接证据
13   0.0005   C    Seq=13033 Len=1448    ┘
14   0.0401   S    Ack=2897              ← ②第一个ACK（RTT≈40ms）
15   0.0401   C    Seq=14481 Len=1448    ┐ ③一个ACK放行2段
16   0.0401   C    Seq=15929 Len=1448    ┘   （1离场+1增长）
...
55   0.0803   S    Ack=…                 ④第二轮ACK群
56   0.0803   C    (20段的簇)             ⑤cwnd=20 的证据
```

**为什么说 Frame 4–13 证明 IW=10？** 三次握手完成后、任何 ACK 返回前（t<RTT），发送方只可能受 IW 约束；数出这一簇恰好 10 段（且 BiF=14480≈10×MSS），即为 IW10。——这是"从抓包反推内核参数"的第一个例子。

## 14–15. 操作系统内部状态 / ss

`ss -ti` 中 Slow Start 的标志：**cwnd < ssthresh**（或 ssthresh 缺省无穷大时，看 cwnd 是否仍在快速翻倍）。捕捉一次：`cwnd:80 ssthresh:2147483647` ⇒ 首段 Slow Start 进行中。

## 16–18. 特征与指纹

**正常指纹**：簇大小逐 RTT 翻倍；BiF 曲线指数上升；无重传。
**异常 A**：翻倍两三轮后突然大量 Dup ACK ⇒ Slow Start Overshoot（冲过瓶颈容量，撞出队列丢包）——HyStart 想避免的正是它。
**异常 B**：每轮只增不到 1.2× ⇒ 对端强 delayed-ack/LRO 聚合 ACK，或 pacing_rate 被限。
**不能据此判断**：起步慢 ⇒ 网络差（高 RTT 下指数增长也要很多轮；先算轮数再怀疑丢包）。

## 19–20. Filter 与 Stream Graph

```
tcp.time_relative < 0.5 && tcp.len > 0      # 只看起步阶段
```
Stevens 图起步段呈"指数弯曲"的上凸加速曲线；tcptrace 图中数据阶梯与 ACK 线距离逐轮拉大 = cwnd 的影子在长大。

## 21. 2025–2026 真实业务应用

Slow Start 决定**短连接**的一切：HTTP/1.1 与 HTTP/2 over TCP 的 API 响应、TLS 握手后的首批应用数据、CDN 小对象分发。工程含义（均可由 §6 表格推出）：① 100KB 响应在 RTT=80ms 移动网络上要 3–4 个 RTT 的 Slow Start，占总时延大头；② 连接复用（keep-alive/H2 多路复用）价值巨大——复用连接的 cwnd 已经张开；③ `tcp_slow_start_after_idle=1`（Linux 默认）会把闲置连接的 cwnd 重置回 IW，长连接低频推送场景常被它反噬（CDN 厂商普遍关闭它，属于公开的常规调优项）。

## 22–23. 真实生产案例与证据链

**【真实生产案例】Google：IW10 的标准化（2011→RFC 6928，至今生效）**
**事实**：Google 基于大规模生产测量提出把 IW 从 2–4 提到 10，论文 *An Argument for Increasing TCP's Initial Congestion Window*（SIGCOMM CCR 2010）报告 Web 延迟平均改善 ~10%；IETF 2013 年发布实验性 RFC 6928；Linux 2.6.39 起默认。**推断**：今天你抓到的任何一条 Linux 服务器连接首簇 10 段，都是这条 2010 年代生产优化的活化石；分析 2026 年的抓包时若首簇不是 10 段，应怀疑中间盒、非 Linux 栈或管理员改过 `ip route ... initcwnd`。
**案例来源**：Dukkipati et al., SIGCOMM CCR 40(3), 2010；RFC 6928 (2013)。

**【真实生产案例】HyStart++ 在 Windows 全量启用（RFC 9406，2023）**
**事实**：RFC 9406（2023-05）由 Microsoft 作者主导，文中明确 "HyStart++ is widely deployed... default-enabled for all TCP connections in the Windows operating system"（自 Windows 10 起逐步铺开）。动机：标准 Slow Start 在最后一轮平均 overshoot 瓶颈容量近一倍，造成成串丢包。**推断**：抓 Windows 服务器的流量，Slow Start 末段常见"翻倍减速成小步爬升再入 CA"的形态，不要误判为丢包降窗。
**案例来源**：RFC 9406, *HyStart++: Modified Slow Start for TCP*, 2023-05, https://www.rfc-editor.org/rfc/rfc9406 。

## 24. 生产排障思路

"首字节快、整页慢 / 小文件慢"：① 算 BDP 与所需轮数（log2(目标窗口/IW)）；② 抓包数首簇段数验证 IW；③ 看每轮是否如期翻倍（不翻倍 ⇒ 查丢包/HyStart/接收窗爬坡【第 3 章 Cloudflare 案例】）；④ 短流优化方向永远优先"少建连接、复用连接"，其次才是调参。

## 25. 常见误判

- "慢启动"名字 ≠ 增长慢（是指数）。
- 首簇 10 段 ≠ 所有系统（老内核/中间盒/BSD 可能不同；先验证再引用）。
- Slow Start 冲高后丢包 ≠ 网络故障（是探测机制的预期代价；HyStart 就是为此存在）。
- 长连接偶发"重新变慢" ≠ 对端重启（多半是 slow_start_after_idle）。

## 26. 与其他机制联动

Slow Start 的出口有三个，分别接到：CA（第 8 章，cwnd≥ssthresh）、Fast Retransmission/Recovery（第 10–11 章，Dup ACK/RACK）、RTO（第 12 章，超时后**回到 Slow Start 且 cwnd=1**——RTO 之后的世界又从本章开始）。

## 27. 分析练习

RTT=100ms，MSS=1448，IW=10，rwnd=1MB，目标：传完 800KB。忽略 delayed-ack 折扣与丢包。1) 需要几轮 Slow Start？2) 每轮末 cwnd 与累计发送量？3) 总耗时约多少？4) 若 RTT=20ms 呢？5) 由此说明什么工程结论？

## 28. 详细答案

1–2)：

| 轮 | cwnd(段) | 本轮发送 | 累计 |
|---:|---:|---:|---:|
| 1 | 10 | 14.5KB | 14.5KB |
| 2 | 20 | 29KB | 43.4KB |
| 3 | 40 | 57.9KB | 101.3KB |
| 4 | 80 | 115.8KB | 217.2KB |
| 5 | 160 | 231.7KB | 448.9KB |
| 6 | 320 | 351KB(剩余) | 800KB |

6 轮完成。3) ≈6×RTT+握手 1RTT ≈ 700ms。4) 同样 6 轮但 ≈140ms。5) 短流总时延 ≈ 轮数×RTT，与带宽几乎无关；降 RTT（就近接入/CDN）比加带宽有效得多。

## 29. 本章总结

Slow Start 用 ACK 回执做指数试探，IW10 起步，出口通向 CA、快速恢复或 RTO。cwnd 涨到 ssthresh 之后为什么、以及如何改为"小步慢走"——下一章 Congestion Avoidance。
