# 第 10 章 Fast Retransmission（快速重传）

## 1. 为什么需要这个机制

RTO 定时器的等待以百毫秒计（Linux 下限 200ms，常见值秒级），而 Dup ACK 在**一个 RTT 内**就能送达丢包证据。Fast Retransmission 的定义：

> **不等 RTO 到期，凭 3 个 Duplicate ACK（或 SACK/RACK 等价证据）立即重传疑似丢失的段。**

它只回答"**何时重传、重传哪段**"。丢包之后拥塞窗口如何调整、传输如何继续，是 Fast Recovery（第 11 章）的职责——**本教程刻意把这两章分开，因为混讲它们是多数教材让人"学完仍看不懂抓包"的直接原因。**

## 2. 没有它会发生什么

每个丢包都付出一次 RTO：几百 ms 静默 + cwnd 归 1 + 重新 Slow Start。在 0.1% 丢包的跨国链路上，长流吞吐会呈周期性深坑（第 12 章对比实验的 Case B 就是这种感受）。

## 3. 核心原理：逐包走一遍

沿用第 9 章场景：MSS=1460，发出四段：

```
Seq=1000 Len=1460   → 到达
Seq=2460 Len=1460   → 丢失
Seq=3920 Len=1460   → 到达
Seq=5380 Len=1460   → 到达
（窗口内还有后续段继续发出）
```

**Receiver 侧**（每一步为什么）：

1. 收到 1000–2459 ⇒ 期望 2460 ⇒ 回 **Ack=2460**。
2. 收到 3920–5379：期望的是 2460，来的是 3920 ⇒ 乱序段 ⇒ **立即**回 Ack=2460 + `SACK=3920-5380` ⇒ 发送方视角 **Dup ACK #1**。
3. 收到 5380–6839 ⇒ Ack=2460 + `SACK=3920-6840` ⇒ **Dup ACK #2**。
4. 收到 6840–8299 ⇒ Ack=2460 + `SACK=3920-8300` ⇒ **Dup ACK #3**。

**Sender 侧**：

- Dup ACK #1、#2：**不动**（可能只是乱序）。但每个 Dup ACK 证明有一段离开了网络——这是第 11 章窗口膨胀/PRR 的依据。
- **Dup ACK #3 到达 ⇒ 判定 Seq=2460 大概率丢失 ⇒ 立即重传 Seq=2460 Len=1460**。同时移交拥塞管理给 Fast Recovery（第 11 章）。
- 重传到达后，Receiver 缺口填补 ⇒ **Ack=8300**（大跳，直接确认到已收最右端）——快速重传成功的收据。

### SACK 开启后分析方式的不同

- **无 SACK（今天已罕见）**：发送方只知道"缺口左沿=2460"，若一窗内丢了多段，只能重传一段、等下一个部分 ACK 再猜下一段（NewReno 式，一 RTT 补一个洞）。
- **有 SACK**：`记分板（scoreboard）`直接标出所有洞。多包丢失时可在同一恢复期连续补多个洞；已被 SACK 覆盖的段绝不重传。抓包判读差异：有 SACK 时你能**从 Dup ACK 本身读出要重传哪些段**，并可预测重传顺序（按洞的 Seq 从左到右）。
- **RACK（Linux 默认，第 13 章）**：其实已不数"3 个"——按时间序（被 SACK 的段的发送时间 + 乱序窗）判丢。表现：重传可能在第 1–2 个 Dup ACK 后就发生。本章按经典模型教学，读现代抓包时用 RACK 模型校准预期。

## 4–5. 关键变量与数学关系

dupthresh=3；重传目标 = 缺口左沿（=Dup ACK 的 Ack 值）；触发时延 ≈ 缺口后第 3 段的到达时间 ≈ **1×RTT 量级**（对比 RTO 的数百 ms）。

## 6. 数值案例

见 §3（数值即案例）。补一个"能不能触发"的边界计算：缺口后必须还有 ≥3 段**能够发出且到达**。若丢的是倒数第 2 段，后面只剩 1 段 ⇒ 最多 1 个 Dup ACK ⇒ 经典模型触发不了 ⇒ 只能靠 TLP/RTO（第 12 章 Case B 的题眼）。

## 7. TCP Timeline

```
t=0        C: 发 1000/2460/3920/5380 (2460丢)
t≈RTT      C: 收 Ack=2460（正常）
t≈RTT+ε    C: 收 DupACK#1 (SACK 3920-5380)
t≈RTT+2ε   C: 收 DupACK#2 (SACK 3920-6840)
t≈RTT+3ε   C: 收 DupACK#3 (SACK 3920-8300)  ⇒ 立即重传 2460
t≈2RTT+3ε  C: 收 Ack=8300                    ⇒ 恢复完成信号
总代价 ≈ 1 个 RTT + 3 段的发送间隔
```

## 8–10. 实验（EXP-05）

附录 A 环境 + 第 9 章的 iptables 精准单包丢弃；或 `netem loss 0.3%` 抓一段长流后在 Wireshark 里 filter 出事件。抓包点：发送侧（能同时看到原始段、Dup ACK 流入、重传段发出的完整时序）。

## 11–12. Wireshark 抓包图与标注

【图 10-1 Fast Retransmission 全事件链】（12 要素标注）

```
No.   Time      Src  Seq/Ack/Len                SACK           Expert          标注
201   2.00010   C    Seq=1000 Len=1460                                          ①原始正常数据
202   2.00012   C    Seq=2460 Len=1460                                          ②丢失Segment(发侧可见)
203   2.00014   C    Seq=3920 Len=1460                                          ①
204   2.00016   C    Seq=5380 Len=1460                                          ①
205   2.00018   C    Seq=6840 Len=1460                                          ①
206   2.04051   S    Ack=2460 Len=0                                             ⑧正常ACK(对201)
207   2.04055   S    Ack=2460 Len=0             3920-5380      DupACK#1         ③
208   2.04059   S    Ack=2460 Len=0             3920-6840      DupACK#2         ④
209   2.04063   S    Ack=2460 Len=0             3920-8300      DupACK#3         ⑤
210   2.04065   C    Seq=2460 Len=1460                         Fast Retrans     ⑥同Seq再现!
211   2.08110   S    Ack=8300 Len=0                                             ⑦Ack大跳=修复收据
```

⑦Sequence Number 视角：Frame 210 与 202 Seq 完全相同——"同 Seq 再次出现"是一切重传的原始定义；⑨TCP Len 相同（整段重传）；⑪Window 各帧未变（rwnd 无异常，排除流控干扰）；⑫Time Delta：210−209 = 20µs（**收到第 3 个 Dup ACK 后立即**，这个"立即"正是与 RTO 的本质区别）。

## 13. Frame-by-Frame 分析

- **Frame 209→210 间隔 20µs**：证明重传由 Dup ACK 触发而非定时器（定时器最少 200ms）。这就是判定 Fast Retransmission 的**时间证据**。
- **Frame 210 为什么 Wireshark 标 Fast Retransmission？** 启发式三条件：出现过更高 Seq、此前 ≥2 个 Dup ACK、距原段时间很短。若条件不满足会退化标成普通 Retransmission 或 Out-Of-Order——**标记是推导，Seq/时间才是事实**（第 16 章展开）。
- **Frame 211 Ack=8300 一跳到顶**：8300 = 已收最右端（Frame 205 的 NextSeq），证明缺口只有一个且已补上。若此时 Ack 只跳到 5380 ⇒ 还有第二个洞 ⇒ 恢复期继续（多洞场景见第 11 章）。

## 14–15. ss 分析

事件瞬间连续采样可见：`retrans:1/1`（在途重传 1）→ 恢复后 `retrans:0/1`；`lost:1` 短暂出现；cwnd/ssthresh 的变化属于第 11 章，此处按下不表。

## 16–18. 特征与指纹

**Fast Retransmission 抓包指纹**（完整版）：
```
≥3 × [同Ack值 + SACK扩张] → 同Seq数据帧再现(与DupACK#3几乎零间隔) → Ack大跳
```
**看到什么**：上述三段式。**为什么出现**：中间段丢失且后续数据充足。**不能据此直接判断**：丢包发生在哪一跳（需双点）、是否拥塞丢包（也可能是链路误码/设备故障——拥塞通常还伴随 RTT 抬升，看 tcptrace 图）。**下一步查**：丢包频率（`tcp.analysis.fast_retransmission` 计数/时长）、是否集中于特定时段或对端、RTT 有无同步抬升。

## 19. Wireshark Filter

```
tcp.analysis.fast_retransmission        tcp.analysis.retransmission
tcp.analysis.duplicate_ack_num >= 3     tcp.seq == 2460 && tcp.len > 0   # 追某个段的所有出现
```

## 20. TCP Stream Graph

tcptrace 图上的 Fast Retransmission：数据阶梯上一段**低于当前前沿的孤立小方块**（重传补洞），Ack 线随即垂直跃升。与 RTO（第 12 章）的图形区别：FastRetx 前后数据流几乎不断流；RTO 则有一段肉眼可见的水平真空。

## 21. 2025–2026 真实业务应用

任何有非零丢包的路径都依赖它：互联网（尤其无线/移动最后一公里）、跨区云互联、CDN 边缘到用户。经验数据点：Dropbox 公开的边缘网络测量给出 BBRv1 宿主机丢包最高 6%、CUBIC 0.5%（第 14 章案例）——在这样的环境里，快速重传路径（而非 RTO）承担了几乎全部丢包修复。

## 22–23. 真实生产案例与证据链

**【真实生产案例】RFC 8985 对 Dup ACK 计数模型缺陷的生产总结（2021，Google/Linux 经验）**
**事实**：RFC 8985（RACK-TLP，作者来自 Google）系统记载了纯 Dup ACK 计数式快速重传在生产中的三大盲区：应用受限的小飞行窗（凑不齐 3 个 Dup ACK）、重传本身再丢失（计数法无法检测）、以及乱序环境下的误触发；并以此为动机设计了基于时间的 RACK-TLP，成为 Linux 默认。**推断**：这三个盲区正好对应运维中"为什么明明丢包了却等了好久才重传"的绝大多数工单场景；分析此类问题时先查 `ss -ti` 的 `rto`、`lost`，再对照第 12/13 章的 TLP/RTO 指纹。
**案例来源**：RFC 8985 (2021-02), https://www.rfc-editor.org/rfc/rfc8985 ；Linux 内核文档 `tcp_recovery`（默认 0x1 = RACK 启用），https://docs.kernel.org/networking/ip-sysctl.html 。

## 24. 生产排障思路：看到 TCP Retransmission 先做什么

**不要立即通知运营商。**按序排除：

1. **是否 Capture Loss**：`tcpdump` 结束时的 "dropped by kernel" 计数、`capinfos`；抓包丢了 ACK 会让 Wireshark 误标一堆重传。
2. **是否 NIC Offload 假象**：超大 Segment、结账式 ACK（第 18 章），在主机上抓包尤其常见。
3. **是否 Out-of-Order**：缺口自愈？有 D-SACK？
4. **是否 ACK Path Loss**：数据其实到了、ACK 丢了 ⇒ 表现为发送方重传但接收方回 D-SACK。
5. **确认方向**：谁重传 ⇒ 丢包在**数据流出**的方向。
6. **是否仅一条流/一个对端/一条链路**：Statistics→Conversations 分组统计；全局性 vs 单流性结论完全不同。
7. 以上排除后，才进入**双点抓包**定位丢包段（第 20 章）。

## 25. 常见误判

- Wireshark "TCP Fast Retransmission" ≠ TCP Header 有此标志（是推导标签，还可能标错）。
- 重传率 1% ≠ 灾难（要区分快速重传修复 vs RTO；前者代价小得多）。
- 看到重传 ≠ 网络设备丢包（capture loss / offload / 乱序 / ACK 丢失四大假象先排除）。
- 重传帧在抓包中存在 ≠ 它到达了对端（看 Ack 是否大跳）。

## 26. 与其他机制联动

触发自 Dup ACK/SACK（第 9 章）；触发同时进入 Fast Recovery 管理 cwnd（第 11 章）；触发不了时由 TLP 兜底、再不行 RTO（第 12–13 章）；恢复完成回到 CA（第 8 章）。第 15 章大联动阶段 7 完整重演本章。

## 27. 分析练习

```
Frame  Time     Src  Info
301    5.1000   C    Seq=40000 Len=1000
302    5.1001   C    Seq=41000 Len=1000
303    5.1002   C    Seq=42000 Len=1000
304    5.1003   C    Seq=43000 Len=1000
305    5.1404   S    Ack=41000
306    5.1406   S    Ack=41000 SACK=42000-43000
307    5.1408   S    Ack=41000 SACK=42000-44000
308    5.1409   C    Seq=44000 Len=1000
309    5.1810   S    Ack=41000 SACK=42000-45000
310    5.1811   C    Seq=41000 Len=1000
311    5.2212   S    Ack=45000
```

1) 丢的是哪段（帧号+区间）？2) 三个 Dup ACK 分别是哪些帧？3) Frame 310 是 Fast Retransmission 吗？给出两条独立证据。4) 为什么 311 是 45000 而不是 42000？5) 若 306–309 都不带 SACK，发送方的行为会有何不同？

## 28. 详细答案

1) Frame 302，区间 [41000,42000)。2) 306(#1)、307(#2)、309(#3)；305 是正常 ACK。3) 是。证据一：Seq=41000 与 302 相同（同 Seq 再现）且此前有 3 个 Dup ACK；证据二：310−309=0.1ms，远小于任何 RTO（≥200ms），只能是事件驱动。4) 重传填补唯一缺口后，Receiver 已连续持有 40000–44999，累积确认直达 45000（Ack 大跳）。5) 无 SACK 时发送方只知缺口左沿：行为相同（重传 41000），但若还有第二个洞，就须等 311 这样的部分 ACK 才能发现下一个洞，恢复期被拉长（NewReno 逐洞修补）。

## 29. 本章总结

Fast Retransmission = "3 个 Dup ACK（或 SACK/RACK 证据）⇒ 立即补洞"。但重传只是修数据，**网络刚才丢包意味着拥塞信号已经拉响**——窗口该怎么降、恢复期怎么继续发数据？下一章 Fast Recovery。
