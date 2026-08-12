# 第 16 章 Wireshark TCP 分析：能看见什么、看不见什么

## 1. 本章定位

前 15 章建立了机制模型，本章系统化 Wireshark 这台"显微镜"本身：它的每个 TCP 分析标记是**怎么推导出来的**、什么时候会**推导错**、五种 Stream Graph 各自回答什么问题。核心纪律只有一条：

> **方括号里的一切都是 Wireshark 的观点，不是报文的事实。**

## 2. 可见性总表（全书判断的地基）

| 数据 | Wireshark 是否直接可见 | 说明 |
|---|---|---|
| Seq / Ack | 是 | 报文字段 |
| Advertised Window（原始值） | 是 | 报文字段 |
| Window Scale 因子 | 可由握手获得 | 没抓到握手 ⇒ 未知 |
| Calculated Window | 可以计算 | 依赖上一行 |
| MSS / SACK_PERM / Timestamps | 是（握手） | |
| SACK Block | 是 | 报文字段 |
| Bytes in Flight | 推导 | 依赖抓包点看全双向 |
| RTT（iRTT/ack_rtt） | 推导 | 抓包点位置影响巨大 |
| Dup ACK 计数 / Retransmission / Out-of-Order / Window Full / ZeroWindow | 推导（启发式） | 会错，见 §4 |
| **cwnd** | **否** | ④层内核状态 → ss |
| **ssthresh** | **否** | 同上 |
| Socket Buffer 占用 | 否 | ss -tm |
| App Read/Write Speed | 否 | 应用侧观测 |
| Kernel pacing state / delivery_rate | 通常否 | ss -ti |
| 内核丢包点 / qdisc 队列 | 否 | eBPF（第 17 章） |

**对于看不到的数据，必须换工具**：cwnd/ssthresh/rto → `ss -ti`；缓冲 → `ss -tm`；内核丢包 → `bpftrace/tcpdrop`；应用速度 → strace/profiler。"Wireshark 里没有"不等于"不存在"，更不等于"没问题"。

## 3. Expert Info 标记的判定逻辑（以及何时出错）

| 标记 | 判定启发式（简化） | 常见误标场景 |
|---|---|---|
| Retransmission | 该 Seq 区间已见过，且非乱序时间窗内 | capture loss（ACK 没抓到）、offload 复制 |
| Fast Retransmission | 重传 + 此前 ≥2 个 Dup ACK + 时间近 | RACK 早触发时可能只标普通 Retransmission |
| Out-of-Order | 已见过更高 Seq，时间差小于乱序阈值(3ms/iRTT) | 抓包点靠近接收端时乱序/重传难分 |
| Spurious Retransmission | 重传的数据已被对端 ACK 覆盖 | 抓包点在接收侧、ACK 先于重传被看到 |
| Dup ACK #n | 同 Ack/Win/无数据 重复第 n 次 | ZWP 应答、Window Update 边缘情况 |
| ZeroWindow / Window Full / Window Update | 见第 3、4 章 | scale 未知时 Window Full 会漏/错 |
| ACKed unseen segment | 对端确认了没抓到的数据 | **几乎总是 capture loss 的自白** |

`ACKed unseen segment` 值得单独记住：它说明抓包点漏包了（内核丢弃/镜像口过载），此时**同一 pcap 里的所有 Retransmission 标记都要打问号**——先修抓包，再谈分析（第 18 章）。

## 4. 判定链示范：同一现象的三种真相

看到 `[TCP Retransmission] Seq=5000`：

1. 对端后续 `Ack=6460` 且从无 Dup ACK/D-SACK ⇒ 可能原包丢了、重传成功（真丢包）。
2. 对端回 `SACK=5000-6460 (< Ack)` ⇒ D-SACK ⇒ 原包其实到了 ⇒ 假重传（乱序/RTT 突增）。
3. pcap 里同时有 `ACKed unseen segment` ⇒ 抓包缺帧 ⇒ 这个"重传"可能是 Wireshark 没看到原包的正常传输。

**一个标记，三种结论，取决于旁证。这就是为什么禁止"从 Wireshark 可以看到发生丢包"这种句式。**

## 5. Statistics 菜单的正确用法

- **Conversations**：按流的字节/包/时长排序找主角；勾选 "Limit to display filter" 配合过滤。
- **Endpoints**：谁在制造流量/重传（配合 `tcp.analysis.retransmission` 过滤再开）。
- **Protocol Hierarchy**：确认流量构成（TLS 占比、是否有意外协议）。
- **I/O Graph**：把 `tcp.analysis.retransmission`、`tcp.analysis.duplicate_ack`、吞吐画在同一时间轴上——事件与吞吐的相关性一图定案。

## 6. 五种 TCP Stream Graph（逐图说明轴与拐点）

菜单：Statistics → TCP Stream Graphs（按当前版本实际名称为准）。**所有图都是单向的**：先选对方向（数据方向），否则一片空白。

| 图 | X/Y 轴 | 读什么 | 异常形态 |
|---|---|---|---|
| Time Sequence (Stevens) | 时间 / 相对Seq | 斜率=吞吐 | 水平段=停顿（RTO/ZW/无数据）；回落点=重传 |
| Time Sequence (tcptrace) | 时间 / Seq | 数据阶梯、ACK线、窗口线三线关系 | 阶梯贴窗口线=rwnd受限；悬空SACK块=缺口；阶梯与ACK线距离=BiF |
| Throughput | 时间 / bps(+goodput) | 吞吐波形 | 锯齿=丢包周期；深坑=RTO；规律小凹=BBR PROBE_RTT |
| Round Trip Time | 时间(或Seq) / RTT | RTT 基线与漂移 | 缓坡上爬=队列膨胀(bufferbloat)；针刺=瞬时抖动 |
| Window Scaling | 时间 / 字节 | 绿线=对端通告窗口，蓝点=BiF | 蓝点贴绿线=rwnd受限；绿线触底=ZeroWindow；蓝点锯齿=cwnd受限 |

判读要领（tcptrace 图为例）：X 轴时间、Y 轴序号；下方阶梯每级=一簇发送；上方细线=对端 Ack 线；最上方线=Ack+Win（右边缘）。**三线间距就是本教程的三个核心量**：阶梯到 Ack 线 = BiF；Ack 线到窗口线 = 剩余 rwnd 额度；阶梯撞上窗口线 = Window Full。

## 7. 常用 Filter 速查（按排障问题组织）

```
# 这条流健康吗？
tcp.stream eq N && tcp.analysis.flags && !tcp.analysis.window_update
# 丢包/重传类
tcp.analysis.retransmission   tcp.analysis.fast_retransmission
tcp.analysis.duplicate_ack_num >= 3      tcp.analysis.out_of_order
tcp.analysis.spurious_retransmission
# 流控类
tcp.analysis.zero_window      tcp.analysis.window_full     tcp.analysis.window_update
# 时延类
tcp.analysis.ack_rtt > 0.2    tcp.time_delta > 0.2         tcp.analysis.initial_rtt > 0.1
# 抓包质量
tcp.analysis.ack_lost_segment          # ACKed unseen segment
# 握手与选项
tcp.flags.syn==1               tcp.options.sack_perm        tcp.options.wscale.shift
```

## 8. 抓包点位置如何扭曲每个观测值

| 观测值 | 发送侧抓包 | 接收侧抓包 |
|---|---|---|
| RTT(ack_rtt) | ≈全路径 RTT | ≈0（数据到达与ACK发出几乎同时）——**在接收侧测不出网络RTT** |
| BiF | 接近发送方真实 | 系统性偏小 |
| 丢包表现 | 能看到被丢的原包 + 重传 | 只看到"缺口+重传到达"，原包不存在 |
| 乱序 vs 重传 | 易区分（有无 DupACK 前史） | 易混淆 |

结论：**性能分析优先在发送侧抓包；丢包定位需要两侧同时抓**（第 20 章）。

## 9. 练习

某 pcap 只有 t=30s 之后的数据（无握手），你看到 `Win=250` 且 Wireshark 未显示 Calculated 值，同时大量 `[TCP ACKed unseen segment]`。1) 能断言对端窗口只有 250 字节吗？2) 大量 Retransmission 标记可信吗？3) 给出让分析可信的两个操作。

**答案**：1) 不能。无握手 ⇒ WS 未知，真实窗口可能是 250×2^S（S 最高 14）；需从行为（BiF 上限）反推或在 TCP 首选项手工设定因子。2) 不可信。ACKed unseen segment 证明抓包缺帧，部分"重传"可能是没抓到原包。3) ① 重新抓包并包含握手、确认 tcpdump 无 kernel drop；② 若无法重抓，用 `tcp.analysis.ack_lost_segment` 统计缺帧密度，将其作为所有结论的置信度折扣，并改以 ss/nstat 计数器交叉验证。

## 10. 本章总结

Wireshark 直读①②层、推导③层、对④层（cwnd/ssthresh/缓冲/pacing）无能为力。下一章补齐④层工具链：ss、tcpdump/tshark 与 eBPF。
