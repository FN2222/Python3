# 第 1 章 TCP 数据传输基础与 Seq / Ack

## 1. 为什么需要这个机制

IP 网络只提供"尽力而为"的分组投递：报文可能丢失、重复、乱序、延迟。应用程序想要的却是一条**可靠、有序、无重复的字节流**。TCP 用两个 32 位字段把不可靠的分组网络变成可靠的字节流：

- **Sequence Number（Seq）**：本报文携带的数据在整条字节流中的起始位置编号。
- **Acknowledgment Number（Ack）**：接收方期望收到的**下一个**字节的编号（累积确认）。

后面所有章节——滑动窗口、rwnd、cwnd、重传——全部构建在这两个字段之上。**读不懂 Seq/Ack，就读不懂任何一张 TCP 抓包图。**

## 2. 没有它会发生什么

没有序号：乱序到达的分组无法重组，重复分组无法去重，丢失的分组无法被识别。没有确认号：发送方永远不知道哪些数据安全到达，只能要么盲目重发一切，要么什么都不重发。

## 3. 核心原理

### 3.1 字节编号，不是报文编号

TCP 给**每个字节**编号，而不是给每个报文编号。一个携带 1460 字节、Seq=1000 的 Segment，占据字节区间 [1000, 2459]，所以：

```
Next Seq = Seq + Len = 1000 + 1460 = 2460
```

这是全书使用频率最高的公式。Wireshark 的 `Next Sequence Number` 字段就是这样算出来的（它是 Wireshark 的**推导值**，不是报文里的字段——五层可见性区分从这里就开始了）。

特例：SYN 和 FIN 各占用 1 个序号，但不携带数据字节。这就是为什么三次握手后第一个数据字节的 Seq 是 ISN+1。

### 3.2 ISN 与相对序号

每个方向的起始序号（ISN, Initial Sequence Number）是随机的（防序号预测攻击，RFC 6528）。Wireshark 默认显示**相对序号**（把 ISN 归一为 0），本教程所有教学案例也使用相对序号。分析真实 pcap 时要知道：`tcp.seq` 显示的是相对值，`tcp.seq_raw` 才是线上的真实值。两个抓包点对同一条流看到的 raw seq 一致——这是第 20 章多点抓包追踪的基础。

### 3.3 累积确认

Ack=N 的含义是："**N 之前的所有字节我都收齐了**，请从 N 继续发。"它不表示"我刚收到了编号 N-1 的报文"。这个语义有两个直接推论：

1. 一个 ACK 可以确认多个 Segment（配合 Delayed ACK，这是常态）。
2. 中间缺了一块时，Ack 会**停在缺口左边**不动——不管后面又收到多少数据。这就是 Duplicate ACK 的来源（第 9 章）。

### 3.4 Delayed ACK 与 ACK Compression

接收端通常不会每收一个 Segment 就立刻回 ACK。RFC 5681 允许延迟确认：最多延迟 500ms、且每收到两个满 MSS 的 Segment 必须回一个 ACK（实际 Linux 延迟通常是 40ms 量级，且有 quickack 等启发式）。所以抓包中"两个数据包对一个 ACK"是**正常现象**，不是丢 ACK。

ACK Compression：ACK 在返回路径上被路由器排队后成串到达，发送方会在瞬间收到一批 ACK，导致突发发送。现代 Linux 用 pacing（fq）平滑这种突发（第 14 章）。分析 RTT 图时要意识到：被压缩的 ACK 会让个别样本的 RTT 观测值失真。

## 4. 关键变量

| 变量 | 含义 | 在哪里能看到 |
|---|---|---|
| Seq | 本段数据首字节编号 | 报文字段，Wireshark 直读 |
| Ack | 期望的下一字节 | 报文字段，Wireshark 直读 |
| Len | TCP 载荷长度 | Wireshark 由 IP/TCP 头长度推导 |
| Next Seq | Seq+Len | Wireshark 推导值 |
| ISN | 初始序号 | 握手报文中可见（raw） |

## 5. 数学关系

- 数据完整到达且有序时：对端的 Ack 应等于你发出的最大 Next Seq。
- `对端Ack < 你的最大NextSeq` 的差值 = 尚未被确认的数据量 = **Bytes in Flight** 的下界（第 5 章精确化）。

## 6. 数值案例 【教学模拟案例】

Client 向 Server 发送 4000 字节（相对序号，MSS=1460）：

| 方向 | Seq | Len | Next Seq | 对端回应 Ack |
|---|---:|---:|---:|---:|
| C→S | 1 | 1460 | 1461 | — |
| C→S | 1461 | 1460 | 2921 | S 回 Ack=2921（Delayed ACK 一次确认两段） |
| C→S | 2921 | 1080 | 4001 | S 回 Ack=4001 |

注意第 1 段没有单独的 Ack=1461——被 Delayed ACK 合并了。这不是异常。

## 7. TCP Timeline

```
Client                                Server
  |--- Seq=1    Len=1460 ------------->|
  |--- Seq=1461 Len=1460 ------------->|  (收满 2×MSS，立即回 ACK)
  |<------------------- Ack=2921 ------|
  |--- Seq=2921 Len=1080 ------------->|  (不足 2×MSS，delayed ack 定时器到期后回)
  |<------------------- Ack=4001 ------|   ← 注意这个 ACK 与数据之间有 ~40ms Time Delta
```

## 8–10. 实验拓扑 / 制造流量 / 抓包位置

使用附录 A 的 netns 环境（`ns-client` ↔ `ns-server`，veth 直连）。制造流量：

```bash
# server
ip netns exec ns-server iperf3 -s
# client：只发 4000 字节即断开
ip netns exec ns-client bash -c 'head -c 4000 /dev/zero | nc 10.0.0.2 5201'
# 抓包点：veth 的 client 侧
ip netns exec ns-client tcpdump -i veth-c -w seq-ack.pcap 'tcp port 5201'
```

## 11–13. Wireshark 抓包图与 Frame-by-Frame 分析 【教学模拟案例·可复现】

复现后 Packet List 应形如（相对序号）：

```
No.  Time      Src        Dst        Info
1    0.000000  10.0.0.1   10.0.0.2   [SYN] Seq=0 Win=64240 Len=0 MSS=1460 WS=128 SACK_PERM
2    0.000041  10.0.0.2   10.0.0.1   [SYN,ACK] Seq=0 Ack=1 Win=65160 Len=0 MSS=1460 WS=128 SACK_PERM
3    0.000063  10.0.0.1   10.0.0.2   [ACK] Seq=1 Ack=1 Win=64256 Len=0
4    0.000121  10.0.0.1   10.0.0.2   [PSH,ACK] Seq=1 Ack=1 Len=1460
5    0.000135  10.0.0.1   10.0.0.2   [PSH,ACK] Seq=1461 Ack=1 Len=1460
6    0.000158  10.0.0.2   10.0.0.1   [ACK] Seq=1 Ack=2921 Win=64128 Len=0
7    0.000190  10.0.0.1   10.0.0.2   [PSH,ACK] Seq=2921 Ack=1 Len=1080
8    0.040213  10.0.0.2   10.0.0.1   [ACK] Seq=1 Ack=4001 Win=64128 Len=0   ← Time Delta ≈ 40ms
```

逐帧：

- **Frame 1**：SYN 占 1 个序号。相对 Seq=0，说明 Wireshark 已把 ISN 归零。`Len=0` 但 Next Seq=1。
- **Frame 4**：第一个数据字节 Seq=1（= ISN+1，因为 SYN 消耗了序号 0）。Next Seq=1461。
- **Frame 5**：Seq=1461 恰好等于 Frame 4 的 Next Seq——数据连续，没有缺口。
- **Frame 6**：Ack=2921。为什么不是先回 Ack=1461？因为收满两个 MSS 触发了"每两段必回"的规则，一个 ACK 累积确认了两段。**证据**：Frame 6 的 Ack 值等于 Frame 5 的 Next Seq。
- **Frame 8**：Ack=4001，Time Delta ≈ 40ms。为什么慢？只剩 1080 字节（< 2×MSS），Delayed ACK 定时器到期才发。**证据**：Time Delta 接近 Linux 默认 delack 定时器，且期间无其他数据到达。

## 14–15. 操作系统内部状态 / ss 分析

```bash
ip netns exec ns-client ss -ti dst 10.0.0.2
```

关注 `bytes_acked`（应为 4001）、`segs_out`、`rtt`。此时还看不出 cwnd 的作用——数据太少，连接远没到窗口限制（第 6 章展开）。

## 16–18. 正常特征 / 异常特征 / 抓包指纹

**正常**：每段的 Seq 等于上一段 Next Seq；Ack 单调不减；两段一 ACK。
**异常**：Seq 跳跃（中间有段没被抓到或真的丢了——注意区分！第 18 章）；Ack 长时间停在同一值且伴随后续数据（Dup ACK 前兆）；同一 Seq 出现两次（重传或抓包重复）。
**指纹**：`Seq 不连续` 本身**不能**直接判丢包——可能是 capture loss、乱序或 offload 合并。下一步：看对端 ACK 是否照常推进（照常推进 ⇒ 数据其实到了，是抓包问题）。

## 19. Wireshark Filter

```
tcp.stream eq 0                     # 锁定一条流
tcp.seq == 2921                     # 找特定字节位置
tcp.analysis.ack_rtt > 0.2          # ACK RTT 异常样本
tcp.len > 0                         # 只看带数据的段
```

## 20. TCP Stream Graph

本章数据量太小，Stream Graph 意义不大；从第 3 章起使用。先记住入口：Statistics → TCP Stream Graphs → Time Sequence (Stevens)，X 轴时间，Y 轴相对 Seq，斜率 = 发送速率。

## 21–23. 真实业务应用与生产案例

Seq/Ack 是所有后续生产案例的语言，本章不单列 Level 3 案例；但要指出一个真实工程事实：**多点抓包用 raw Seq 对齐同一条流**是 CDN/云厂商网络团队定位丢包的标准做法（第 20 章、综合案例 7 给出完整流程与来源）。

## 24. 如果在生产环境我怎么排查

拿到任何 pcap 的前三步永远是：① `Statistics → Conversations` 找到目标流；② 确认 Client/Server（谁发 SYN）；③ 沿 Seq/Next Seq 链检查连续性。不要先看 Expert Info 的红字——先建立字节流的"地图"。

## 25. 常见误判

- 看到"两个数据包只有一个 ACK" ≠ ACK 丢失（Delayed ACK 是常态）。
- 看到 Wireshark 相对 Seq 从 1 开始 ≠ 线上序号真是 1（那是归一化显示）。
- 看到 `TCP Previous segment not captured` ≠ 网络丢包（也可能是抓包点丢包，第 18 章）。

## 26. 与其他 TCP 机制如何联动

Ack 推进 ⇒ 滑动窗口右移（第 3 章）⇒ 释放发送额度；Ack 停滞 ⇒ Dup ACK（第 9 章）⇒ Fast Retransmission（第 10 章）。Ack 到达的节奏就是 ACK Clock，驱动 cwnd 增长（第 7 章）。

## 27. 分析练习

给定 Packet List（相对序号）：

```
Frame  Src→Dst  Seq    Ack   Len
201    C→S      5001   1     1460
202    C→S      6461   1     1460
203    S→C      1      7921  0
204    C→S      7921   1     500
205    S→C      1      8421  0
```

问题：1) 谁在发数据？2) Frame 203 确认了哪些字节？3) Frame 204 之后 Client 还有多少字节未被确认？4) Frame 205 的 Ack 为什么是 8421？

## 28. 详细答案

1) Client（C→S 方向 Len>0）。2) Ack=7921 表示 7921 之前全部收齐，即累计确认到字节 7920，覆盖 Frame 201/202（5001–7920）及更早数据。3) Frame 205 到达前：最大 Next Seq=7921+500=8421，最新 Ack=7921，未确认 500 字节；Frame 205 到达后为 0。4) 因为 Frame 204 的 Next Seq=8421，Server 收齐后期望下一字节就是 8421。

## 29. 本章总结

Seq 给字节编号，Ack 做累积确认，`Next Seq = Seq + Len` 是贯穿全书的推导工具。Delayed ACK 让"两段一 ACK"成为常态。从下一章开始，我们回答"一个 Segment 能装多少字节、窗口字段最大能表达多大"。
