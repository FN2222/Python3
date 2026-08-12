# 第 12 章 RTO / 普通超时重传（含 Fast Retransmission vs RTO 对比实验）

## 1. 为什么需要这个机制

Fast Retransmission 依赖一个前提：**丢包之后还有足够的后续数据到达接收方，从而产生 Dup ACK**。这个前提在四类常见场景下不成立：

1. **最后一个数据包丢失**（尾丢，tail loss）：后面没有数据了，一个 Dup ACK 都不会有。请求-响应型流量（HTTP、RPC）的响应尾段最典型。
2. **窗口太小**：cwnd/rwnd 只有一两段，丢一段后在途所剩无几，凑不齐 3 个 Dup ACK。
3. **ACK 本身丢失**：数据都到了，回程 ACK 全丢——发送方视角与数据全丢无异。
4. **严重拥塞/成串丢包**：一窗数据几乎全丢，接收方收不到任何越过缺口的段。

这些场景必须有一个与对端反馈无关的兜底机制：**定时器**。发出数据后启动 RTO（Retransmission TimeOut）定时器；到期还没确认 ⇒ 无条件重传，并把网络假定为严重拥塞。

## 2. 没有它会发生什么

上述四类场景中的任何一个都会让连接**永久挂死**——双方各自等待，谁也不会先动。RTO 是 TCP 可靠性的最后一道保险丝：一切智能检测都失效时，时间仍然流逝。

## 3. 核心原理

### 3.1 RTO 怎么算（RFC 6298）

```
SRTT    = (1-α)·SRTT + α·RTT样本          α=1/8   （平滑均值）
RTTVAR  = (1-β)·RTTVAR + β·|SRTT-RTT样本|  β=1/4   （平滑抖动）
RTO     = SRTT + 4·RTTVAR                 （均值+四倍抖动）
```

- 直觉：RTO 要显著大于"正常 RTT 的波动上界"，否则会大量假超时（Spurious RTO）。
- Linux 实现：`RTO ∈ [200ms, 120s]`（TCP_RTO_MIN=200ms——所以**局域网里 RTT 0.2ms 的连接 RTO 也是 200ms**，尾丢代价高达千倍 RTT，这正是 TLP 诞生的动机，第 13 章）。
- 每次超时重传后 **RTO 翻倍**（指数退避：200ms→400ms→800ms…），连续失败达到 `tcp_retries2`（默认 15，约 15–20 分钟）后放弃连接。
- Karn 算法：被重传过的段的 RTT 样本不用于更新 SRTT（无法分辨 ACK 对应原包还是重传）；Timestamps 选项（RFC 7323）解除了这一限制。

### 3.2 RTO 触发后发生什么（代价全表）

```
ssthresh = FlightSize / 2        ← 与快速恢复相同
cwnd     = 1 MSS (Linux: tcp_retries 起点 lost 状态)   ← 与快速恢复完全不同！
状态     = 重新 Slow Start（从头爬）
```

RTO 是 TCP 里代价最高的事件：静默等待（≥200ms）+ cwnd 归 1 + 指数重爬。**吞吐图上的"深坑"几乎都是它**。

### 3.3 现代补丁预告（第 13 章展开）

现代 Linux 并不会坐等 RTO：**TLP** 在 ~2×SRTT 时主动发探测包制造反馈，把多数尾丢转化为快速恢复；**F-RTO** 检测假超时并撤销惩罚；**RACK** 用时间序判丢减少对计数的依赖。分析 2026 年的抓包时：纯教科书式 RTO 序列多见于"TLP 也丢了"或 Windows 老栈/嵌入式栈。**不能机械地按几十年前的 TCP 模型解释现代系统行为**——先确认栈与参数，再套模型。

## 4–5. 关键变量与数学关系

RTT 样本、SRTT、RTTVAR、RTO、退避指数、`ss -ti` 的 `rto:`/`rtt:X/Y`（X=SRTT，Y=RTTVAR）、`backoff:`。

## 6. 数值案例 【教学模拟案例】

RTT 样本序列 40, 42, 41, 80(突增), 40 ms，α=1/8, β=1/4，初始 SRTT=40, RTTVAR=20：

| 样本 | SRTT | RTTVAR | RTO=SRTT+4·RTTVAR |
|---:|---:|---:|---:|
| 40 | 40.0 | 15.0 | 100 → 取下限 200ms |
| 42 | 40.3 | 11.7 | 200ms（仍触下限） |
| 41 | 40.4 | 8.9 | 200ms |
| 80 | 45.3 | 15.4 | 206.9ms |
| 40 | 44.6 | 12.9 | 200ms 附近 |

要点：① 单次 RTT 突增主要抬 RTTVAR（4 倍权重进 RTO）——**RTO 对抖动比对均值敏感**；② 低 RTT 环境 RTO 恒被 200ms 下限托住。

## 7. TCP Timeline（尾丢触发 RTO）

```
t=0        C: Seq=99001 Len=1000 (整个响应的最后一段) ──X 丢
t=0~208ms  （寂静。没有后续数据 ⇒ 没有 Dup ACK ⇒ 无事发生）
t=208ms    C: RTO到期 ⇒ 重传 Seq=99001 Len=1000
           ssthresh=FlightSize/2, cwnd=1
t=248ms    S: Ack=100001    ← 修复，但已付出 ~5×RTT 的静默
t=248ms+   C: cwnd=1 起步重新 Slow Start（若还有数据要发）
```

## 8–10. 实验：Fast Retransmission vs RTO 对比（EXP-05 vs EXP-06）

**这是本教程指定的成对对比实验。两个 Case 只差一个变量：丢的是"中间段"还是"最后一段"。**

```bash
# Case A（中间丢一段）：长流中随机丢一个非尾段 —— 见第 10 章 EXP-05
# Case B（尾丢）：客户端发 10 段后停止；丢最后一段
ip netns exec ns-wan iptables -A FORWARD -p tcp --dport 5201 \
  -m statistic --mode nth --every 10 --packet 9 -j DROP     # 丢第10段（示意，按实际计数微调）
ip netns exec ns-client bash -c 'head -c 14480 /dev/zero | nc -q 5 10.0.0.2 5201'
# 建议同时开启对照：sysctl net.ipv4.tcp_early_retrans（TLP 开关，见第13章，先关闭以观察纯RTO）
```

## 11–13. Wireshark 抓包对照与 Frame-by-Frame

**Case A：中间段丢失 → Fast Retransmission**（第 10 章图 10-1，摘要）

```
209  2.04063  S  Ack=2460 SACK=3920-8300 [DupACK#3]
210  2.04065  C  Seq=2460 Len=1460 [Fast Retransmission]   ← 与#3间隔 20µs
211  2.08110  S  Ack=8300
```

**Case B：最后一段丢失 → RTO**

```
No.   Time      Src  Info                                          标注
601   3.00000   C    Seq=10001 Len=1448                             ①
602   3.00002   C    Seq=11449 Len=1448                             ①
603   3.00004   C    Seq=12897 Len=1024  ← 最后一段，线上被丢          ②
604   3.04010   S    Ack=11449                                      ③正常ACK
605   3.04012   S    Ack=12897                                      ④对602的ACK——之后一片寂静
                     ↕ 时间空洞 ≈ 210ms：无数据、无ACK、无DupACK       ⑤★RTO指纹
606   3.25470   C    Seq=12897 Len=1024 [TCP Retransmission]        ⑥同Seq再现
607   3.29481   S    Ack=13921                                      ⑦修复
```

- **Frame 605→606 之间 210ms 空洞**是 RTO 的决定性时间证据（对照 Case A 的 20µs）。为什么是 ~210ms？`ss -ti` 显示该连接 rto:208 ⇒ 吻合。
- **中间没有任何 Dup ACK**：603 之后再无数据段到达接收方，Receiver 无从"告状"。
- Wireshark 只标通用 `Retransmission`（没有 DupACK 前史，不会标 Fast Retransmission）——标记逻辑与本质原因在这里对齐。

## 对比总表（本教程指定表格）

| 项目 | Fast Retransmission | RTO Retransmission |
|---|---|---|
| 触发依据 | 3×Dup ACK / SACK-RACK 证据（事件驱动） | 定时器到期（时间驱动） |
| Dup ACK | 必有（≥3 或等价） | 无或不足 3 个 |
| SACK | 通常伴随、指明缺口 | 通常无（无后续段可 SACK） |
| 等待时间 | ≈1 RTT 量级 | ≥RTO（Linux ≥200ms），且指数退避 |
| cwnd 影响 | ssthresh=½/0.7×，PRR 平滑滑降，**不归 1** | ssthresh=½×，**cwnd=1**，重新 Slow Start |
| 性能影响 | 吞吐短暂下探 ~30–50% | 吞吐断崖归零数百 ms + 缓慢重爬 |
| 抓包特征 | DupACK 串 + 与#3零间隔的同Seq重现 + Ack大跳 | 时间空洞 + 无DupACK + 同Seq重现 |
| Stream Graph | 阶梯几乎不断流，小 V 坑 | 水平真空段 + 从谷底重新加速 |

## 14–15. ss 分析

```
# RTO 事件前后：
rto:208 rtt:41/2.1 ... cwnd:87 ssthresh:1e9        # 事件前
rto:416 backoff:1 ... cwnd:1 ssthresh:43 lost:1    # 定时器已退避一次、cwnd归1
rto:208 ... cwnd:5 ssthresh:43                     # 恢复后重新SS爬坡
```

`backoff:` 字段直接暴露退避次数——抓包看不到的④层证据。

## 16–18. 特征与指纹

**RTO 抓包指纹**：`一段明显等待时间（≈rto值） + 无DupACK/不足3个 + 相同Seq再次发送（+ 若继续超时：间隔翻倍的同Seq序列）`。
**看到什么**：时间空洞+重传。**为什么出现**：反馈通道断了（无后续数据/ACK 丢/全丢）。**不能据此直接判断**：网络一定严重拥塞（单纯尾丢也触发；ACK 路径丢包也触发——方向要分清）。**下一步查**：丢的是不是流的最后一段（看后无数据）；对端是否其实收到了（接收侧抓包 or D-SACK）；RTO 前的 RTT 是否突增（假超时，查 F-RTO 痕迹）。

## 19–20. Filter 与 Stream Graph

```
tcp.analysis.retransmission && !tcp.analysis.fast_retransmission
tcp.analysis.rto        # Wireshark 对 RTO 类重传的推导标记（新版本）
tcp.time_delta > 0.19   # 找 200ms 级空洞
```
tcptrace 图：RTO = **水平真空 + 谷底重启的小台阶**（cwnd=1 起步只有一两段），随后指数加宽——与 Zero Window 的平台区分：RTO 平台末尾是**旧 Seq 重发**，ZW 平台末尾是 Window Update 后**新 Seq 继续**（第 4 章）。

## 21. 2025–2026 真实业务应用

RTO 高发的真实场景：① 请求-响应尾丢（API/HTTP 响应最后一段——TLP 的目标场景）；② 移动网络切换/信号骤降造成的突发全丢；③ 高 RTT 卫星/跨洋链路上的突发拥塞；④ 微服务间小窗口短流（在途只有 1–2 段，永远凑不齐 Dup ACK）。谷歌在 RFC 8985/TLP 相关材料中给出的生产测量：其 Web 服务器上**约 70% 的重传由 RTO 完成而非快速重传**（短流主导的流量剖面）——这就是 2010 年代以来一系列 loss recovery 现代化工作的直接动因（来源见第 13 章）。

## 22–24. 生产案例与排障思路

生产案例与 TLP/RACK 一体，集中在第 13 章与第 21 章（案例 R5/R6）。值班排查要点：吞吐图深坑 ⇒ 对每个坑回答三问：坑前有无 DupACK 串？空洞时长是否 ≈ ss 的 rto 值？重传的是不是当时的最高 Seq（尾丢特征）？三问答案组合即可归类：尾丢 / ACK 路径丢 / 突发全丢 / 假超时。

## 25. 常见误判

- 时间空洞 ≠ 网络断了（也可能应用没数据可发——看 notsent 与 PSH 边界）。
- RTO 重传成功 ≠ 问题不大（一次 RTO 的性能代价 ≈ 数百次快速重传）。
- RTT 突增引发的假超时（Spurious RTO）会出现"重传后原 ACK 到达 + D-SACK"——是抖动问题不是丢包问题。
- Linux 里看到 200ms 整的等待 ≠ 巧合（那是 TCP_RTO_MIN 下限）。

## 26. 与其他机制联动

RTO 与快速重传构成"事件驱动/时间驱动"双保险；RTO 后回到 Slow Start（第 7 章）从 cwnd=1 重爬、ssthresh 记住教训（第 8 章）；TLP 在 RTO 之前抢跑（第 13 章）；RTO 阈值的原料 SRTT/RTTVAR 来自 RTT 测量——所以**RTT 抖动大的网络里 RTO 天然偏大，尾丢代价更高**。

## 27. 分析练习

```
Frame  Time     Src  Info
801    9.0000   C    Seq=50000 Len=1448
802    9.0001   C    Seq=51448 Len=1448
803    9.0402   S    Ack=52896
804    9.0403   C    Seq=52896 Len=800    (PSH, 流的最后一段)
805    9.4610   C    Seq=52896 Len=800   [Retransmission]
806    9.5011   S    Ack=53696
```

1) 804–805 之间发生了什么？依据哪两个证据？2) 805 时刻该连接 cwnd 是多少？3) 若 805 之后 806 迟迟不来、且 10.30 出现第三次 Seq=52896，间隔说明什么？4) 若 806 同时携带 `SACK=52896-53696`（低于 Ack），如何改判？5) TLP 开启的系统里，805 的时间戳会有什么不同？

## 28. 详细答案

1) 尾段丢失触发 RTO。证据一：804 后无任何 Dup ACK（它是最后一段，没有后续段制造 Dup ACK）；证据二：805−804 ≈ 421ms 的空洞，量级符合 RTO（非事件驱动）。2) 1 MSS（RTO 惩罚）。3) 第三次若在 ~10.30，即 9.461+0.84≈两倍间隔 ⇒ RTO 指数退避（backoff=2）。4) Block(52896-53696) 完整落在 Ack=53696 之内 ⇒ D-SACK ⇒ 原包其实到了、ACK 或时序出了问题 ⇒ 假超时（Spurious RTO），应查 RTT 突增/回程丢 ACK，而不是数据路径丢包。5) TLP 会在 ~2×SRTT（约 9.12s）就发探测（可能是重发 52896 或新数据），比 421ms 的 RTO 早得多——第 13 章展开。

## 29. 本章总结

RTO 是反馈完全断绝时的时间兜底，代价是静默+归 1+重爬。四类 Dup ACK 失效场景（尾丢、小窗、ACK 丢、全丢）是它的主场。但 2026 年的 Linux 早已给它配了三个"抢跑者"——RACK、TLP、F-RTO。下一章进入现代 loss recovery。
