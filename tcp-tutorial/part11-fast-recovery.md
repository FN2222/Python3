# 第 11 章 Fast Recovery（快速恢复）

## 1. 为什么需要这个机制（以及它为什么总被和快速重传混为一谈）

再强调一次两者的分工：

> **Fast Retransmission**：如何快速**发现并重传**丢失的数据。（第 10 章）
> **Fast Recovery**：检测到丢包之后，TCP 如何**调整拥塞窗口并继续传输**。（本章）

丢包被视为拥塞信号，cwnd 必须降。但怎么降是有讲究的：如果像 RTO 那样 cwnd=1 重新 Slow Start，那么一次轻微丢包就摧毁整条流的速度。Fast Recovery 的洞察是：**既然 Dup ACK 还在源源不断到达，说明网络仍在向接收方交付数据——管道没断，只是溢了一下**。所以只需"降一半（或七成）继续跑"，不必推倒重来。

## 2. 没有它会发生什么

Tahoe 时代（1988，只有快速重传没有快速恢复）：每次丢包 cwnd 归 1。高 BDP 链路上单次丢包后要几十个 RTT 才能爬回来，长流吞吐对丢包率极度敏感。Reno（1990）加入 Fast Recovery 后，单包丢失的代价从"推倒重来"降为"半窗继续"。

## 3. 核心原理

### 3.1 经典 Reno 流程（教学基线）

触发（= 快速重传那一刻）：

```
ssthresh = max(FlightSize/2, 2×MSS)     ← 记住出事点的一半
cwnd     = ssthresh + 3×MSS             ← 3 个 DupACK 证明 3 段已离网（窗口膨胀）
```

恢复期内：每收到一个额外 Dup ACK ⇒ `cwnd += 1 MSS`（又一段离网），若额度允许可发**新**数据——保持管道不空。
退出：收到覆盖恢复点（进入恢复时的 SND.NXT）的 ACK ⇒ `cwnd = ssthresh`，进入 Congestion Avoidance。
NewReno 补丁：**部分 ACK**（前进了但没到恢复点）⇒ 说明还有下一个洞 ⇒ 立即重传下一个洞，不退出恢复。

### 3.2 Linux 现实：PRR（RFC 6937，默认）

Reno 式"一步砍半"有两个生产问题：① 砍完的瞬间发送完全停顿（等 BiF 降到新 cwnd 以下）；② 若 ACK 大量丢失，恢复结束时 cwnd 远低于 ssthresh。Google 提出并推动的 **PRR（Proportional Rate Reduction）**成为 Linux 默认（`tcp_congestion_recovery` 逻辑内建）：恢复期内按"每收 2 个 ACK 发 1 段"的比例**平滑地**把 BiF 从旧值滑降到 ssthresh，避免停顿和过冲。抓包表现：**恢复期内发送节奏减半但不断流**——不要把 PRR 的减速误读成"卡住了"。

### 3.3 不同拥塞控制算法的降窗差异（必须分别说明）

| 算法 | ssthresh 设定 | 恢复期行为 | 2026 年地位 |
|---|---|---|---|
| Reno/NewReno | 0.5×cwnd | 窗口膨胀 + 部分ACK逐洞 | 教学基线，真实部署极少 |
| **CUBIC** | **0.7×cwnd**（β=0.7） | PRR 平滑降至 0.7 倍，随后三次曲线回升 | Linux/Win/mac 默认 |
| BBR 系列 | 不由丢包直接驱动 ssthresh | 丢包不必然降窗（v1 几乎无视丢包；v2/v3 有 2% 丢包率目标与 inflight 上限） | Google 生产、树外补丁 |
| DCTCP | 按 ECN 标记比例缩窗 | 数据中心专用 | RFC 8257 |

**方法论结论：看到"丢包后 cwnd 掉到 70%"不要写成"异常，教科书说是 50%"——先 `ss -ti` 看算法。**

## 4–5. 关键变量与数学关系

进入恢复时的 FlightSize、ssthresh、恢复点（recovery point = 进入时 SND.NXT）、部分 ACK、PRR 的 sndcnt。Reno：`退出时 cwnd = ssthresh = FlightSize/2`；CUBIC：`= 0.7 × W_max`。

## 6. 数值案例：完整过程逐 RTT 推演 【教学模拟案例】

MSS=1460，RTT=40ms，CUBIC+PRR（Linux 默认组合），丢包时 cwnd=400 段、BiF=400 段：

| 时刻 | 事件 | cwnd | ssthresh | 发送行为 |
|---|---|---:|---:|---|
| t0 | DupACK#3，快速重传洞1 | 400（名义） | **280**（=0.7×400） | PRR 开始限流 |
| t0~t0+RTT | 恢复期：Dup ACK 流入 | 有效发送额度从400滑向280 | 280 | 每2个ACK发1段+补洞 |
| t0+RTT | 收到部分 ACK（还有洞2） | ~340 | 280 | 立即重传洞2（SACK 记分板早已标好） |
| t0+~2RTT | 覆盖恢复点的 ACK 到达 | **280** | 280 | 退出恢复 → CA |
| t0+3RTT | CA/CUBIC 回升段 | 283 | 280 | 三次曲线爬向 W_max=400 |
| …约数秒后 | 接近 400 | 395–400 | 280 | 平台试探，再缓慢超越 |

对照【丢包前 cwnd=400 → 恢复中滑降 → 退出=280 → CUBIC 回升 → 平台 → 超越】，这条曲线就是第 15 章大联动图 5 与综合案例中反复出现的标准形状。

## 7. TCP Timeline

```
      cwnd 400 ─────────┐
                         \   PRR 平滑滑降（不是悬崖）
                          \_______ 280 ──── CA/CUBIC ______/‾‾‾ 平台(≈400) ‾→ 继续
      ↑t0 DupACK#3        ↑退出恢复(覆盖恢复点的ACK)         ↑接近W_max减速
```

## 8–10. 实验（EXP-07）

```bash
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms loss 0.5%
# 同时跑 EXP-09 的 cwnd 采样 + 抓包，10 秒即可采到多次恢复事件
```

观察点：`ss` 日志里成对出现的 `cwnd 下降 / ssthresh 更新`，与 pcap 里 `fast_retransmission` 事件时间对齐（±10ms）。

## 11–13. Wireshark 抓包图与 Frame-by-Frame

恢复期在抓包上的三个可观测面（cwnd 本身不可见！）：

```
No.    Src  Info                                        观测面
520    S    Ack=100000 SACK=101448-115928 DupACK#3       触发点
521    C    Seq=100000 Len=1448 [Fast Retransmission]    补洞
522    S    Ack=100000 SACK=101448-117376 DupACK#4       恢复期继续收DupACK
523    C    Seq=131024 Len=1448                          ① 新数据仍在发（管道不空）
524    S    Ack=100000 SACK=... DupACK#5
525    C    Seq=132472 Len=1448                          ② 但节奏≈每2个DupACK发1段(PRR)
...
540    S    Ack=118824                                   部分ACK(若还有洞) 或
541    S    Ack=133920                                   覆盖恢复点⇒退出恢复
```

- **观测面①**：恢复期内发送方持续发出**高于恢复点的新 Seq**——Fast Recovery 区别于 RTO 的最直接抓包证据（RTO 期间是静默）。
- **观测面②**：数一下 Dup ACK 与新数据帧的比例 ≈ 2:1 ⇒ PRR 指纹。
- **观测面③**：BiF 曲线从 400×MSS 平滑滑向 280×MSS（Wireshark `[Bytes in flight]` 逐帧读出）。

## 14–15. ss 分析

恢复期采样（真实字段样例）：

```
cubic ... cwnd:287 ssthresh:280 ... unacked:395 retrans:2/17 lost:3 sacked:118 ...
```

判读：`sacked:118` 大量段被 SACK、`lost:3` 记分板判丢 3 段、`retrans:2/17` 两段重传在途；`cwnd:287≈ssthresh:280` ⇒ 恢复已近尾声。**内核把整个恢复期状态摊开给你看**——这是 ss 相对抓包的信息优势（④层数据）。

## 16–18. 特征与指纹

**Fast Recovery 指纹**：FastRetx 之后 (a) 新数据不断流但节奏减半；(b) BiF 平滑滑降至 ~0.7×；(c) 覆盖恢复点的 ACK 后节奏恢复。
**异常**：恢复期内再丢重传段（retransmission of retransmission）⇒ 经典栈只能 RTO 兜底（RACK 可救，第 13 章）——抓包指纹：同一 Seq 出现 **3 次**。
**不能据此判断**：吞吐减半 = 链路带宽减半（那是发送方自律，不是网络变小）。

## 19–20. Filter 与 Stream Graph

```
tcp.analysis.fast_retransmission || tcp.analysis.retransmission
tcp.analysis.bytes_in_flight        # 配合 IO Graph 画 BiF 滑降
```
tcptrace 图：恢复期数据阶梯斜率减半、SACK 色块持续、Ack 线在恢复点处一次跃升；Throughput 图呈"V 字缓坡"而非"断崖归零"（后者是 RTO，第 12 章对照）。

## 21. 2025–2026 真实业务应用

恢复行为直接决定用户体感：视频卡顿率（恢复期吞吐掉 30% vs RTO 的归零几百 ms，体感天差地别）、大文件下载的"速度抖一下 vs 卡死几秒"。CDN/云厂商选择拥塞算法时，"丢包后的恢复曲线"是核心评测维度（Dropbox 的 BBRv1/v2/CUBIC 对比、Google BBRv3 的 YouTube 数据都在比这条曲线，第 14 章）。

## 22–23. 真实生产案例与证据链

**【真实生产案例】PRR：Google 生产测量驱动的恢复算法（RFC 6937，Linux 默认）**
**事实**：PRR 由 Google 基于其 Web 服务器生产测量提出（IMC 2011 论文 *Proportional Rate Reduction for TCP* 报告了对 Google 前端流量的改进：恢复期超时减少、延迟降低），2013 年成为 RFC 6937（2024 年更新为 RFC 9782 实验→标准路径），并早已是 Linux 默认恢复行为。**推断**：你在任何现代 Linux 抓包中看到的恢复期"2:1 减速不断流"形态都源于此；用 Reno"悬崖式砍半"模型核对现代抓包必然对不上——对不上的是模型，不是网络。
**案例来源**：RFC 6937；Dukkipati et al., *Proportional Rate Reduction for TCP*, ACM IMC 2011。

## 24. 生产排障思路

吞吐周期性下探：① 对齐 pcap 事件与 `ss` 的 cwnd/ssthresh 时间线；② 每次下探对应 fast_retransmission 还是 RTO（指纹见第 12 章对比表）——前者查丢包源，后者性质更严重（尾丢/突发）；③ 下探深度对不上 0.7 倍 ⇒ 确认算法（bbr？）或是否多次丢包叠加；④ 恢复后爬升慢 ⇒ 看是否高 RTT 下的 CUBIC 正常速度，别急着怪网络。

## 25. 常见误判

- Fast Retransmission 和 Fast Recovery 是两件事：前者修数据，后者管窗口。
- 恢复期吞吐下降 ≠ 故障加重（PRR 的自律减速）。
- cwnd 未回到丢包前 ≠ 没恢复完（CUBIC 要先平台试探）。
- BBR 流丢包后吞吐几乎不掉 ≠ 数据没丢（v1 设计如此；看 retrans 计数）。

## 26. 与其他机制联动

入口=快速重传（第 10 章）；期间靠 SACK 记分板决定补哪些洞（第 9 章）；ssthresh 的新值决定未来 SS/CA 换挡点（第 8 章）；恢复失败（重传再丢、ACK 断流）坠入 RTO（第 12 章）。

## 27. 分析练习

Linux CUBIC 流，`ss` 采样序列（间隔 200ms）：
`cwnd:600 ssthresh:520` → `cwnd:604` → `cwnd:437 ssthresh:422 retrans:1/40 sacked:80` → `cwnd:424 retrans:0/41` → `cwnd:429` → `cwnd:436`。
1) 第 3 个采样点前后发生了什么？2) ssthresh:422 怎么来的？3) 第 4 点 retrans 从 1/40 变 0/41 说明什么？4) 第 5、6 点的增长是什么阶段？5) 若第 4 点后出现 `cwnd:1 ssthresh:422`，又说明什么？

## 28. 详细答案

1) 检出丢包进入 Fast Recovery：cwnd 从 604 滑向 ssthresh，且出现在途重传与大量 SACK。2) 604×0.7≈422（CUBIC β=0.7）。3) 在途重传段被确认（cur 1→0），累计+1（40→41）⇒ 补洞成功。4) 退出恢复后的 CUBIC 回升段（CA）。5) 恢复失败触发了 RTO（cwnd 归 1）——大概率重传段本身又丢了或 ACK 断流；转第 12 章指纹核对。

## 29. 本章总结

Fast Recovery 让丢包的代价从"归零重来"变成"降三成继续"，PRR 让降窗平滑不断流。但它的前提是 **Dup ACK 还在流入**。如果连 Dup ACK 都没有——最后一段丢了、窗口太小、ACK 全丢——TCP 只剩最后的保险丝：RTO。
