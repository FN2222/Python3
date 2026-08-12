# 第 15 章 TCP 各种机制到底是怎样联动工作的？（大联动）

> 这是整套教程最重要的章节之一。前面十四章把 rwnd、cwnd、Bytes in Flight、ACK、RTT、MSS、ssthresh、Slow Start、Congestion Avoidance、Packet Loss、Dup ACK、SACK、Fast Retransmission、Fast Recovery、RTO 逐一讲透；本章把它们**全部放回同一条 TCP Connection**，按时间轴走完一次完整的生命周期。
>
> **【教学模拟案例·可复现】**：本章数值为教学推演（可人工验算），并可用附录 A 的 EXP-12 配置完整复现（netem 制造两次丢包事件）。所有机制行为按 2026 年 Linux 默认栈（CUBIC + RACK-TLP + PRR + SACK + pacing）设定。

## 场景设定

Client（东京）从 Server（新加坡）下载一个 200 MB 文件。

```
参数：MSS = 1460 B（Timestamps 关闭以简化；实际环境为1448）
     RTT = 40 ms（基线，无排队时）
     瓶颈带宽 = 100 Mbps  ⇒  BDP = 100e6/8 × 0.04 = 500 KB ≈ 342 MSS
     rwnd = 512 KB（≈351 MSS，接收方缓冲充足且应用读取快）
     Initial cwnd = 10 MSS（Linux 默认 IW10）
     算法 = CUBIC（β=0.7）+ HyStart + RACK-TLP + PRR
数据方向：Server → Client。以下"发送方"= Server。
```

---

## 阶段 1：连接建立（t = 0 ~ 40ms）

```
Frame 1  C→S [SYN]      Seq=0  Win=64240 MSS=1460 WS=7(×128) SACK_PERM
Frame 2  S→C [SYN,ACK]  Seq=0 Ack=1 Win=65160 MSS=1460 WS=7 SACK_PERM
Frame 3  C→S [ACK]      Ack=1 Win=502 (Calculated=64256)
```

握手锁定了本连接终身的三件事：**MSS=1460**（颗粒）、**WS=7**（rwnd 可表达到 8MB，足够 512KB）、**SACK_PERM**（第 9–13 章全部现代恢复机制的入场券）。此刻 Server 内核：`cwnd=10, ssthresh=∞(2147483647), SRTT≈40ms, rto≈240ms`。

## 阶段 2：开始发送（t = 40ms）

Client 发出 HTTP GET；Server 应用把响应写入 socket。发送额度 = min(rwnd=351, cwnd=10) − BiF=0 ⇒ **首簇 10 段**（14.6 KB）一次性（pacing 匀速地）发出。

## 阶段 3：Slow Start（t = 40ms ~ 约 280ms）

每个 ACK：cwnd+1；每 RTT 翻倍。rwnd 纹丝不动（应用读得快），全部限制来自 cwnd：

| RTT 轮 | t | cwnd(MSS) | 本轮发送 | BiF 峰值 | 瞬时吞吐 |
|---:|---:|---:|---:|---:|---:|
| 1 | 40ms | 10 | 14.6KB | 14.6KB | 2.9 Mbps |
| 2 | 80ms | 20 | 29.2KB | 29.2KB | 5.8 Mbps |
| 3 | 120ms | 40 | 58.4KB | 58.4KB | 11.7 Mbps |
| 4 | 160ms | 80 | 116.8KB | 116.8KB | 23.4 Mbps |
| 5 | 200ms | 160 | 233.6KB | 233.6KB | 46.7 Mbps |
| 6 | 240ms | 256(HyStart截停) | 373.8KB | 373.8KB | 74.8 Mbps |

第 6 轮 HyStart 观测到 RTT 从 40ms 爬向 44ms（瓶颈队列开始有深度），**提前退出**指数增长：`ssthresh = cwnd = 256`。（若无 HyStart，cwnd 会冲到 320→640，在第 7 轮撞出一串丢包——这正是 HyStart 存在的意义，第 7 章。）

## 阶段 4：到达 ssthresh，进入 Congestion Avoidance（t ≈ 280ms 起）

换挡：从"每 RTT ×2"变为 CUBIC 的受控爬升（此处近似 +1~+3/RTT）。cwnd 256→300 用了约 20 轮（0.8s）。当 cwnd 超过 BDP=342 之前，吞吐已逼近 95 Mbps；cwnd 若继续涨，多出的部分只是在瓶颈**排队**（RTT 从 40 爬向 45ms——tcptrace RTT 图可见的缓坡）。

**此刻的联动快照（t=1.2s）**：`min(rwnd=351, cwnd=300)=300`；BiF≈300 MSS≈438KB；限制者=cwnd；RTT=44ms（含 4ms 队列）；吞吐≈87 Mbps。

## 阶段 5：出现一个 Packet Loss（t = 2.000s）

瓶颈队列瞬时溢出（或路径某处随机丢包），**Seq=24,090,001（Len=1460）被丢**。此时在途还有 ~299 段在它之后陆续到达 Client。

## 阶段 6：Receiver 收到 Out-of-Order Segment，开始发送 Dup ACK + SACK（t = 2.020s 起）

```
Frame 8001  C→S  Ack=24090001                                    ← 正常ACK(丢段之前的数据)
Frame 8002  C→S  Ack=24090001 SACK=24091461-24092921  [DupACK#1]
Frame 8003  C→S  Ack=24090001 SACK=24091461-24094381  [DupACK#2]
Frame 8004  C→S  Ack=24090001 SACK=24091461-24095841  [DupACK#3]
... (后续在途段继续到达，DupACK 持续，SACK 右沿持续扩张)
```

Ack 钉死在缺口左沿 24090001；SACK 右沿逐帧+1460——**每个 Dup ACK 都是"又一段安全到达"的回执**（这是 PRR 恢复期的燃料）。

## 阶段 7：触发 Fast Retransmission（t = 2.060s）

RACK：首个 SACK（Frame 8002）到达即启动 ~min_RTT/4=10ms 的重排窗定时器；经典模型：DupACK#3（Frame 8004）到达。两者都指向同一动作：

```
Frame 8005  S→C  Seq=24090001 Len=1460  [Fast Retransmission]   ← 与触发ACK间隔<1ms
```

## 阶段 8：进入 Fast Recovery（t = 2.060s ~ 2.140s）

拥塞管理接管：

```
ssthresh = 0.7 × 300 = 210 (CUBIC β)
PRR: 恢复期内每收~2个DupACK放行1段新数据，把 BiF 从 300 平滑滑向 210
```

抓包可见：恢复期 Server 仍在发**新** Seq（管道不空），但节奏减半；BiF（Wireshark 逐帧 `[Bytes in flight]`）从 438KB 滑向 307KB。重传段到达 Client 后：

```
Frame 8123  C→S  Ack=24528001        ← Ack 大跳（缺口填补，一跃确认全部已收数据）
```

## 阶段 9：恢复正常传输，回到 Congestion Avoidance（t = 2.140s 起）

覆盖恢复点的 Ack（Frame 8123）宣告退出恢复：`cwnd = ssthresh = 210`。CUBIC 从 210 快速回升、在 W_max=300 附近放缓（平台试探）、随后再缓慢上探。吞吐从 61 Mbps 爬回 ~87 Mbps，全程**没有一毫秒断流**。

## 阶段 10：一个无法靠 Dup ACK 发现的丢包 → RTO（t = 4.000s）

t=4.0s 应用层数据暂时见底（Server 磁盘读取抖动），在途只剩最后 3 段；路径突发劣化把这 3 段**全部丢掉**。

- 没有任何段越过缺口到达 ⇒ Client 发不出一个 Dup ACK。
- t≈4.088s：TLP（PTO≈2×SRTT=88ms）发出探测（重传最高 Seq 段）——**探测也被丢**（突发劣化未结束）。
- t≈4.296s：**RTO 到期**（rto≈208ms）：

```
Frame 9501  S→C  Seq=52,560,001 Len=1460 [TCP Retransmission]   ← 静默296ms后
内核: ssthresh = max(cwnd/2,2)=105（RTO时cwnd≈210），cwnd = 1，重新 Slow Start
```

抓包指纹回顾（第 12 章）：**时间空洞 + 零 Dup ACK + 同 Seq 再现**，与阶段 7 的"零间隔事件驱动"形成全书最重要的一组对照。

## 阶段 11：拥塞窗口再次变化，二次恢复（t = 4.3s ~ 5.5s）

重传陆续被确认，cwnd 从 1 指数重爬：1→2→4→…→105（ssthresh，t≈4.58s）→ 换挡 CA → CUBIC 缓升回 200+。吞吐曲线：断崖归零 296ms → 指数回升 → 缓坡。此后传输平稳直至 200MB 完成。

---

## 十份图证（本案例要求的全部观测面）

**图 1：TCP 时间线（全程浓缩）**

```
t(s)  0     0.28      1.2      2.0   2.06  2.14        4.0  4.30 4.58        5.5
      |--SS--|--CA(CUBIC爬升)--|--丢包--|FR/PRR|--CA回升--|静默+RTO|--SS--|--CA--|→
cwnd  10→256      256→300      300    →210   210→~300    →1     1→105  105→210+
```

**图 2：cwnd 随时间（ss 采样连线）**

```
MSS
300 ┤              ╭────────╮ ← W_max
256 ┤        ╭─────╯        │╭──平台──╮
210 ┤        │              ╰╯(PRR滑降)╰─╮
105 ┤   ╭────╯                            │      ╭─CA──
 10 ┤╭──╯(SS指数)                          │  ╭───╯(SS重爬)
  1 ┤╯                                     ╰──╯← RTO归1
    └┬────┬────┬────┬────┬────┬────┬────┬────┬──
     0   0.5   1   1.5   2   2.5  3.5   4   4.5  5  t(s)
```

**图 3：rwnd 随时间**：全程 ≈512KB 水平直线（应用读取快，接收缓冲从未成为瓶颈）——**这条"无聊"的直线本身就是证据**：本案例一切波动与流量控制无关。

**图 4：Bytes in Flight 随时间**：与图 2 几乎重合（cwnd-limited 的定义），仅两处偏离——恢复期 PRR 滑降段（BiF 先于 cwnd 名义值下降）与 RTO 静默段（BiF 冻结在 3 段后清零）。

**图 5：Sequence Number–Time（Stevens）**

```
Seq
     │                                    ╱ ← 斜率=吞吐
     │                     ╱╲小凹(FR事件) ╱
     │            ╱───────╯  ╰──────────╱
     │     ╱─────╯                 ────  ← RTO水平真空(296ms)
     │ ╱──╯(SS上凸加速)
     └──────────────────────────────────── t
```

**图 6：RTT 随时间**：40ms 基线 → CA 后期缓爬至 44ms（队列）→ 丢包事件后回落 → RTO 前突刺（突发劣化）→ 恢复 40ms。
**图 7：Throughput 随时间**：2.9→87 Mbps（SS/CA）→ 61（恢复期）→ 87 → **0**（296ms）→ 指数回升 → 80+。
**图 8：Wireshark Packet List 关键帧**：见各阶段代码块（Frame 1–3, 8001–8005, 8123, 9501）。
**图 9：TCP Stream Graph 判读**：tcptrace 图上依次可见——SS 的上凸加速、CA 直线、悬空 SACK 色块+小 V（阶段 5–8）、水平真空+谷底重启小台阶（阶段 10–11）。
**图 10：ss -ti 采样（四个关键时刻）**

```
t=0.1s  cubic wscale:7,7 rto:244 rtt:40.2/1.8 cwnd:40  ssthresh:2147483647 ...
t=1.5s  cubic rto:248 rtt:44.1/0.9 cwnd:300 ssthresh:256 unacked:299 delivery_rate 86Mbps
t=2.10s cubic rto:248 rtt:43.8/1.0 cwnd:245 ssthresh:210 unacked:280 sacked:118 lost:1 retrans:1/1
t=4.35s cubic rto:416 backoff:1 rtt:41/6 cwnd:4 ssthresh:105 retrans:0/5 lost:3
```

---

## 本章的唯一结论

对照十张图逐段回看：**滑动窗口、rwnd、cwnd、Slow Start、CA、Dup ACK、SACK、Fast Retransmission、Fast Recovery、RTO 不是十个独立知识点，而是同一条 TCP 连接在不同阶段的不同状态**。同一个 Ack 字段，在阶段 3 是 ACK Clock 的燃料、在阶段 6 是丢包告警、在阶段 8 是 PRR 的节拍器、在阶段 10 的缺席本身就是触发 RTO 的原因。

## 复现指引

附录 A EXP-12 完整配置给出两次丢包事件的 netem/iptables 时序脚本；复现后请依次导出：I/O Graph（吞吐）、tcptrace 图、`ss` 采样 cwnd 曲线，与本章十图逐一比对。

## 分析练习

1) 阶段 4 里 cwnd 若继续涨到 400，吞吐会超过 87 Mbps 吗？为什么？RTT 会怎样？
2) 阶段 6 中若 rwnd 只有 64KB，Dup ACK 的数量会怎样变化？对触发快速重传有何影响？
3) 阶段 10 中如果 TLP 探测没有被丢，时间线会怎样改写？cwnd 的结局有何不同？
4) 图 3 若不是直线而是周期性跌到 0，本章哪些阶段的解读要全部推翻？

**答案**：1) 不会。吞吐封顶于瓶颈 100 Mbps（实际 ~95），多余的 cwnd 只转化为瓶颈队列 ⇒ RTT 按 (cwnd−BDP)×MSS/带宽 线性上升（400 段时 RTT≈40+6.8≈47ms）——"窗口大于 BDP 后只买延迟不买吞吐"。2) rwnd=64KB≈44 段 ⇒ 在途最多 44 段 ⇒ 缺口后最多 43 段能制造 Dup ACK，仍远超 3 个，快速重传无碍；但若 rwnd 只有 4–5 段就危险了（第 12 章场景 2）。3) t≈4.088s TLP 探测到达 ⇒ Client 回 SACK 揭示缺口 ⇒ RACK 判丢 ⇒ 快速重传+PRR：无 296ms 空洞、cwnd 降到 0.7× 而非 1——这正是 TLP 的价值（第 13 章）。4) 阶段 3–11 的"限制者=cwnd"前提崩塌：rwnd 周期归零说明接收应用消费不动，应改用第 4 章 Zero Window 分析框架，两次"丢包"事件也需重新核对（rwnd 受限时在途少，Dup ACK 可能凑不齐）。
