# 第 9 章 丢包检测：Duplicate ACK 与 SACK

## 1. 为什么需要这个机制

发送方看不见网络内部，它只能从 **ACK 流的形态**里推断哪些数据没送到。本章讲 TCP 的两套"告状语言"：

- **Duplicate ACK**：接收方反复重复同一个 Ack 值——"我还在等 N，你后面发的我收到了但没法确认"。
- **SACK（Selective Acknowledgment，RFC 2018）**：在 Dup ACK 上附加"但我已经收到了 [X,Y) 区间"——把"缺口在哪"说清楚。

它们是 Fast Retransmission（第 10 章）的触发器，也是你在 Wireshark 里判断丢包最重要的原始证据。

## 2. 没有它会发生什么

只剩 RTO 超时（第 12 章）一种检测手段：每次丢包至少等几百 ms、且 cwnd 归 1 重新 Slow Start。1% 的丢包率就能把连接打成"走走停停"。

## 3. 核心原理

### 3.1 Dup ACK 的产生机制（接收方视角）

规则（RFC 5681）：**收到乱序段（比期望 Seq 大）时，立即（不延迟）重发一个 Ack=期望值 的 ACK**。

- 缺口不补上，Ack 就钉在缺口左沿——不管后面又到了多少数据。
- 每个"越过缺口"的后续段都触发一个 Dup ACK ⇒ **Dup ACK 数量 ≈ 缺口之后到达的段数**。这个对应关系是逐帧分析的核心线索。

### 3.2 为什么门限是 3 个 Dup ACK

轻微乱序（相邻两包换位）也会造成 1–2 个 Dup ACK。若 1 个就重传，会大量假阳性（Spurious Retransmission）。经典折中：**3 个 Dup ACK（即累计第 4 次同值 ACK）才判丢**——乱序深度 ≥3 的情况相对少见。代价：不足 3 个时判不了（第 12 章 RTO 的地盘）；现代 RACK（第 13 章）用时间阈值替代计数阈值，兼顾两头。

### 3.3 SACK：把缺口说清楚

握手时双方交换 `SACK Permitted` 选项后启用。Dup ACK 的 TCP Option 里携带最多 3–4 个 **SACK Block** `[left, right)`，报告已收到的非连续区间：

```
Ack=2460, SACK=3920-5380     含义: 2460之前收齐; 3920–5379 也到了; 缺 2460–3919
```

对发送方的价值：① 精确知道**哪些段**要重传（多包丢失时不用一轮猜一个）；② 已被 SACK 的段不必重传；③ RACK 用 SACK 的到达时间做时间序推断。第一个 Block 永远描述**最近触发本 ACK 的那个段**，后续 Block 是历史区间的重申——读多 Block SACK 时先看第一块。

### 3.4 D-SACK（RFC 2883）：接收方举报"你重传多余了"

若接收方收到**重复**数据（原包和重传都到了），它用 SACK 的第一个 Block 报告这个重复区间（特征：**Block 落在 Ack 覆盖范围之内**）。发送方由此得知刚才的重传是 Spurious（假重传，通常因乱序或 RTT 突增），可以撤销窗口惩罚（Linux `tcp_dsack` 默认开，配合 Eifel/F-RTO 恢复 cwnd）。**判读口诀：SACK Block < Ack ⇒ 这是 D-SACK，不是新缺口。**

### 3.5 Packet Loss vs Out-of-Order：抓包上如何区分

两者初始形态一模一样（Seq 跳跃 + Dup ACK）。区别在**结局**：

| | 乱序 | 真丢包 |
|---|---|---|
| 缺口段随后自己到达 | ✅（无需重传） | ❌ |
| Dup ACK 数量 | 少（1–2 个居多） | 持续增长直到重传 |
| 是否出现原 Seq 的重传 | 若发生了假重传会有，且随后见 **D-SACK** | 有，且无 D-SACK |
| Wireshark 标记 | Out-Of-Order（启发式：两帧间隔 < 乱序阈值） | Retransmission / Fast Retransmission |

Wireshark 的 Out-Of-Order/Retransmission 判定是**启发式**（基于时间差与是否见过更高 Seq），在抓包点靠近接收端、或 offload 干扰时会标错——永远用 Seq/Ack/SACK/时间自己复核（第 16、18 章）。

## 4–5. 关键变量与数学关系

Dup ACK 计数、dupthresh(=3)、SACK Block（≤3 个，带 Timestamps 时）、缺口 = `[Ack, 第一个SACK块left)`；`Dup ACK 数 ≈ 缺口后到达段数`。

## 6. 数值案例 【教学模拟案例】

发送 6 段，MSS=1460，Seq 起点 1000；**Seq=2460 丢失**：

| 事件 | 接收方动作 | 发送方看到 |
|---|---|---|
| 收到 1000–2459 | Ack=2460 | 正常 ACK |
| 2460 丢失 | — | — |
| 收到 3920–5379 | **Ack=2460, SACK=3920-5380** | Dup ACK #1 |
| 收到 5380–6839 | Ack=2460, SACK=3920-6840 | Dup ACK #2（Block 右沿扩展）|
| 收到 6840–8299 | Ack=2460, SACK=3920-8300 | Dup ACK #3 → 触发快速重传（下一章）|
| 收到重传的 2460–3919 | **Ack=8300**（缺口填上，一跃到顶） | 恢复 |

注意最后一行：填补缺口后 Ack **跳跃式**前进到已收数据的最右端——"Ack 大跳"是重传成功的指纹。

## 7. TCP Timeline

```
Sender                                          Receiver
  |-- 1000(1460) --->✔                           |
  |-- 2460(1460) --X  丢                          |
  |-- 3920(1460) --------------------------->✔   | 期待2460却来了3920
  |<----------- Ack=2460 SACK=3920-5380 ---------|  DupACK#1
  |-- 5380(1460) --------------------------->✔   |
  |<----------- Ack=2460 SACK=3920-6840 ---------|  DupACK#2
  |-- 6840(1460) --------------------------->✔   |
  |<----------- Ack=2460 SACK=3920-8300 ---------|  DupACK#3
  |            （第10章：此刻触发 Fast Retransmission）
```

## 8–10. 实验（EXP-05 / EXP-08）

```bash
# 精准丢一个包（比 netem loss 更可控）：丢掉第 37 个数据包
ip netns exec ns-wan iptables -A FORWARD -p tcp --dport 5201 \
  -m statistic --mode nth --every 1000 --packet 37 -j DROP
# 或者乱序实验（EXP-08）：
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms reorder 5% gap 3
```

乱序实验的观察目标：Dup ACK 出现但**没有**重传、缺口段自行到达、若有假重传则后随 D-SACK。

## 11–12. Wireshark 抓包图与标注

【图 9-1 Dup ACK 与 SACK Block 演化】

```
No.   Time    Src  Info                                                    标注
101   1.2001  C    Seq=1000 Len=1460                                       ①正常
102   1.2002  C    Seq=2460 Len=1460      ← 线上被丢（发送侧抓包能看到它！）  ②
103   1.2003  C    Seq=3920 Len=1460                                       ③
104   1.2404  S    Ack=2460 Win=xxx                                        ④对101的正常ACK
105   1.2406  S    Ack=2460 SACK=3920-5380 [TCP Dup ACK 104#1]             ⑤
106   1.2408  C    Seq=5380 Len=1460                                       ⑥
107   1.2809  S    Ack=2460 SACK=3920-6840 [TCP Dup ACK 104#2]             ⑦
```

⑫Time Delta 注意点：④与⑤几乎同时到达（都是 40ms 后）——因为 101 和 103 是背靠背发出的。**在发送侧抓包能看到 Frame 102**（它是出了主机之后才被丢的）——所以"抓包里有这个包"≠"对端收到了这个包"，判定要看 ACK/SACK（第 20 章多点抓包的立足点）。

## 13. Frame-by-Frame 分析

- **Frame 105 为什么是 Dup ACK？** Ack 值与 Frame 104 相同（2460）且不带数据、窗口未变。Wireshark 标 `Dup ACK 104#1`：104 是原 ACK 帧号，#1 是第一次重复。
- **Frame 105 的 SACK=3920-5380 说明什么？** Receiver 已收到 3920–5379（正是 Frame 103），而 Ack 停在 2460 ⇒ 缺口 = [2460, 3920) ⇒ **恰好就是 Frame 102** 的区间。据此可精确断言：丢的是 102 这一段，而不是"发生了一些丢包"。
- **Frame 107 的 Block 右沿从 5380 扩到 6840**：Frame 106 到达的证据。缺口左右沿都没变 ⇒ 仍只缺 102 那一段（单包丢失）。

## 14–15. ss 分析

丢包事件在 ss 里的即时痕迹：`sacked:N`（当前被 SACK 的段数）、`lost:N`（判丢段数）、`retrans:cur/total`、进入恢复后 cwnd/ssthresh 变化（第 11 章跟踪）。

## 16–18. 特征与指纹

**Dup ACK 指纹**：同 Ack 值连续出现、Len=0、通常带 SACK、时间间隔 ≈ 后续段到达节奏。
**看到什么**：Ack 停滞+SACK 区间扩张。**为什么出现**：缺口后仍有数据到达。**不能据此直接判断**：① 一定丢包（可能乱序——看缺口是否自愈）；② 丢在哪个方向的哪一跳（要双点抓包）；③ Dup ACK 很多 = 丢包很多（一个缺口+一大窗后续数据就能产生几十个 Dup ACK）。**下一步查**：缺口段是否重传、重传后是否 Ack 大跳、有无 D-SACK。

## 19. Wireshark Filter

```
tcp.analysis.duplicate_ack            tcp.analysis.duplicate_ack_num >= 3
tcp.options.sack.count > 0            tcp.analysis.out_of_order
tcp.flags.ack==1 && tcp.len==0 && tcp.options.sack_le   # 带SACK的纯ACK
```

## 20. TCP Stream Graph

tcptrace 图是 SACK 的最佳视角：数据阶梯上方出现**悬空的 SACK 色块**（Wireshark 以不同颜色画出被 SACK 的区间），Ack 线在缺口处走平——"平台上漂浮色块"就是单包丢失的图形指纹。

## 21–23. 真实业务应用与生产案例

SACK 自 2000 年代起几乎全网启用（握手 `SACK_PERM` 缺失反而是异常，常见于老旧中间盒剥离）。现代意义上最重要的"生产案例"是 SACK 成为 RACK-TLP 的基础设施：

**【真实生产案例】Netflix：以 SACK 为地基的 RACK 栈承载全部 CDN 流量**——FreeBSD RACK 栈（Netflix 出资开发，2018 年合入 FreeBSD，commit rS334804）用"SACK + 时间"取代 Dup ACK 计数；该栈明确"**不支持 SACK 的连接会被踢回默认栈**"——SACK 从优化变成了前提。FreeBSD Journal（2024）记载 Netflix 生产全量使用 RACK 栈。**事实**：上述提交与部署记载。**推断**：当你分析视频 CDN 流量时，Dup ACK 计数模型可能根本不是对端的真实判丢逻辑，重传可能比"3 Dup ACK"更早出现——不要把提前的重传误判为异常。
**案例来源**：FreeBSD rS334804 (2018-06)，https://reviews.freebsd.org/rS334804 ；FreeBSD Journal, *RACK and Alternate TCP Stacks for FreeBSD*, 2024，https://freebsdfoundation.org/our-work/journal/browser-based-edition/networking-10th-anniversary/rack-and-alternate-tcp-stacks-for-freebsd 。（详见第 13 章与第 21 章案例 R5。）

## 24. 生产排障思路

看到大量 Dup ACK：① 先确认方向（谁在发 Dup ACK ⇒ 缺口在**到它**的方向）；② 数缺口个数（看 SACK 左右沿），单缺口大量 Dup ACK ≠ 大量丢包；③ 追每个缺口的结局（自愈=乱序 / 重传+Ack 大跳=真丢 / 重传+D-SACK=假重传）；④ 真丢 ⇒ 双点抓包定位段（第 20 章）；⑤ 全程记住：Dup ACK 本身零成本，不构成故障，**成规模的真丢包才是**。

## 25. 常见误判

- Duplicate ACK ≠ 一定 Packet Loss（乱序、ACK 复制、ZWP 应答都可能形似）。
- SACK 区间大 ≠ 丢得多（恰恰说明**收到得多**，只是缺口没补）。
- 抓包里看到被丢的那个包 ≠ 没丢（发送侧抓包在丢包点之前）。
- 没有 SACK 选项 ≠ 对端不支持（可能被中间盒剥离——对比两侧握手）。

## 26. 与其他机制联动

Dup ACK#3 触发 Fast Retransmission（第 10 章）；SACK 决定恢复期"还要补发哪些"（第 11 章）；Dup ACK 不足时只能靠 TLP/RTO（第 12、13 章）；D-SACK 反馈给 Eifel/F-RTO 撤销假惩罚（第 13 章）。

## 27. 分析练习

```
Frame  Src  Info
70     C    Seq=10000 Len=1000
71     C    Seq=11000 Len=1000
72     C    Seq=12000 Len=1000
73     C    Seq=13000 Len=1000
74     S    Ack=11000
75     S    Ack=11000 SACK=12000-13000
76     S    Ack=11000 SACK=12000-14000
77     S    Ack=14000
(无任何 C 的重传帧)
```

1) 缺口是哪段？2) Frame 75/76 各由哪帧触发？3) 为什么没有重传就出现了 Frame 77？4) 这是丢包还是乱序？Wireshark 大概率给 Frame 71 什么标记？5) 若 Frame 77 之后出现 `Ack=14000 SACK=10000-11000`，说明什么？

## 28. 详细答案

1) [11000,12000)，即 Frame 71 的数据未按期到达。2) 75←Frame 72 到达；76←Frame 73 到达（Block 右沿 13000→14000）。3) Frame 71 的数据**迟到自愈**：它晚于 72/73 到达，填上缺口后 Receiver 直接 Ack=14000。4) 乱序。Frame 71 若被抓包点看到晚于 72/73（接收侧抓包）会标 Out-Of-Order；发送侧抓包则 71 位置正常，只能从"无重传而 Ack 跳到 14000"推出乱序发生在路径上。5) 那是 D-SACK（Block 10000-11000 < Ack=14000）：说明发送方其实**重传过** 71（本抓包片段没截到或抓包点没看到），且原包与重传都到达——提示假重传/深乱序，应查 RTT 抖动与路径负载均衡（per-packet ECMP）。

## 29. 本章总结

Dup ACK 报告"有缺口"，SACK 报告"缺口在哪"，D-SACK 报告"你多传了"。3 Dup ACK 之后发送方会做什么？下一章：Fast Retransmission。
