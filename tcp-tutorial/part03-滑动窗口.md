# 第 3 章 TCP 滑动窗口（Sliding Window）

## 1. 为什么需要这个机制

第 1 章的模型有一个致命性能问题：如果发送方每发一段就停下来等 ACK（Stop-and-Wait），那么每个 RTT 只能发一段数据：

```
Stop-and-Wait 吞吐 = MSS / RTT = 1460 B / 40 ms ≈ 292 kbps
```

一条千兆链路被用成了 0.03%。解决办法：**允许发送方在收到确认之前，连续发送一"窗口"的数据**——这就是滑动窗口。窗口有多大，管道里就能同时"飞"多少数据。

## 2. 没有它会发生什么

所有传输退化为上面的 Stop-and-Wait：吞吐与带宽无关、只与 RTT 成反比。RTT 越长越惨——跨国链路上传一个 1 GB 文件需要 `1GB/1460B × 150ms ≈ 30 小时`。

## 3. 核心原理：窗口四区域

从**发送方**视角，整条字节流被三条边界切成四个区域：

```
        ┌ 窗口左边缘(Left Edge) = SND.UNA（最老的未确认字节）
        │                    ┌ SND.NXT（下一个要发送的字节）
        │                    │            ┌ 窗口右边缘(Right Edge) = SND.UNA + Window
        ▼                    ▼            ▼
┌───────┬────────────────────┬────────────┬──────────────────┐
│ ①已发送已确认  │ ②已发送未确认        │ ③可以立即发送  │ ④暂时不能发送       │
└───────┴────────────────────┴────────────┴──────────────────┘
        ◀━━━━━━━━━ 发送窗口(Send Window) ━━━━━━━━━▶
```

- **② 已发送未确认** = Bytes in Flight（第 5 章）。
- **③ 可以立即发送** = 窗口剩余额度 = Window − Bytes in Flight。
- **④ 暂时不能发送**：越过右边缘发送就是违反对端的流量控制声明。
- ACK 到达 ⇒ 左边缘右移（①扩大）；对端通告新窗口 ⇒ 右边缘随之右移 ⇒ ③重新出现。窗口就这样"滑"过整条字节流。

**接收方**同样维护一个接收窗口：`RCV.NXT`（期望的下一字节）到 `RCV.NXT + RCV.WND`。它把 RCV.WND 写进每个 ACK 的 Window 字段——这就是 **Advertised Window**，也就是下一章的 rwnd。

关键术语对齐：**Send Window** 是发送方视角的额度（本章先假设它完全由对端通告决定；第 6 章会引入 cwnd 后修正为 min(rwnd, cwnd)）；**Window Update** 是一个不带数据、但 Window 字段比之前大的 ACK；**Window Full** 是 Wireshark 的推导标记，表示"这一段发完后 Bytes in Flight == 对端通告窗口"——发送方额度用尽。

## 4. 关键变量

| 变量 | 含义 | RFC 793 名称 |
|---|---|---|
| 窗口左边缘 | 最老未确认字节 | SND.UNA |
| 下一个发送位置 | | SND.NXT |
| 窗口右边缘 | SND.UNA + 通告窗口 | |
| Advertised Window | 对端 ACK 中的 Window 字段（×2^S） | SND.WND |
| Bytes in Flight | SND.NXT − SND.UNA | |

## 5. 数学关系

```
可立即发送额度 = Advertised Window − (SND.NXT − SND.UNA)
              = rwnd − Bytes in Flight            （本章简化，未引入 cwnd）
吞吐上限      = Window / RTT
```

## 6. 数值案例：窗口一步一步滑动 【教学模拟案例】

设 MSS=1000（为了心算方便），rwnd 恒为 4000，发送 10000 字节。相对序号从 1 开始。

**T0：初始状态**（还没发任何数据）

```
字节:      1        1001      2001      3001      4001      5001 ...
           ├────────┼─────────┼─────────┼─────────┼─────────┤
区域:      │  ③可以立即发送(4000字节: 1–4000)      │ ④不能发送(4001–)
左边缘=1   SND.NXT=1                    右边缘=4001
```

**T1：连发 4 段（Seq=1,1001,2001,3001）**，窗口用满：

```
           │ ②已发送未确认(1–4000)                  │ ④不能发送
左边缘=1   SND.NXT=4001 = 右边缘        ← Bytes in Flight=4000，Wireshark 将标记 [Window Full]
```

**T2：收到 Ack=1001, Win=4000**。左边缘滑到 1001，右边缘滑到 5001：

```
① 1–1000 │ ② 1001–4000 (3000字节) │ ③ 4001–5000 (1000字节) │ ④ 5001–
左边缘=1001              SND.NXT=4001        右边缘=5001
```
⇒ 立刻可以发 Seq=4001 一段。**每来一个 ACK，窗口滑一格，放行一段**——这就是 ACK Clock。

**T3：收到 Ack=3001, Win=4000**（累积确认两段）。左边缘=3001，右边缘=7001：

```
① 1–3000 │ ② 3001–5000 (2000) │ ③ 5001–7000 (2000) │ ④ 7001–
```
⇒ 可连发两段（Seq=5001, 6001）。

**T4：收到 Ack=5001, Win=2000**（接收方应用没读，缓冲只剩 2000）。左边缘=5001，右边缘=5001+2000=**7001**——右边缘没动！

```
① 1–5000 │ ② 5001–7000 (2000) │ ③(空!) │ ④ 7001–
```
⇒ 窗口又满了。ACK 到达**不保证**能继续发送：右边缘 = Ack + Win，两者一起决定。这个细节是理解 rwnd 限速（第 4、19 章）的钥匙。

**T5：收到 Window Update：Ack=5001, Win=4000**（应用读走了数据，纯窗口更新，Len=0）。右边缘=9001，③重新出现 2000 字节额度，传输恢复。

## 7. TCP Timeline

```
Sender                                     Receiver
  |-- Seq=1    Len=1000 -->|
  |-- Seq=1001 Len=1000 -->|
  |-- Seq=2001 Len=1000 -->|
  |-- Seq=3001 Len=1000 -->|   [Window Full]
  |                        |<-- Ack=1001 Win=4000 --|
  |-- Seq=4001 Len=1000 -->|
  |                        |<-- Ack=3001 Win=4000 --|
  |-- Seq=5001 Len=1000 -->|
  |-- Seq=6001 Len=1000 -->|
  |                        |<-- Ack=5001 Win=2000 --|   ← 应用变慢，窗口缩小
  |        (被右边缘卡住，停止发送)                    |
  |                        |<-- Ack=5001 Win=4000 --|   ← [Window Update]
  |-- Seq=7001 Len=1000 -->|
```

## 8–10. 实验拓扑 / 制造流量 / 抓包位置

附录 A 环境，netem delay 20ms×2（RTT 40ms）。让窗口现象容易观察的关键是**压小接收缓冲**：

```bash
ip netns exec ns-server sysctl -w net.ipv4.tcp_rmem="4096 16384 16384"
ip netns exec ns-server iperf3 -s &
ip netns exec ns-client tcpdump -i veth-c -w slide.pcap &
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 5
```

抓包点在发送侧（能看到发送方视角的窗口用满/等待）。

## 11–12. Wireshark 抓包图与标注 【教学模拟案例·可复现】

【图 3-1 窗口用满与更新】复现后应看到如下模式（Len/数值随环境略有差异）：

```
No.   Time     Src      Info
 40   0.4012   client   Seq=13033 Len=1448                     ①正常数据
 41   0.4013   client   Seq=14481 Len=1448  [TCP Window Full]  ②额度用尽
 42   0.4213   server   Ack=15929 Win=0     [TCP ZeroWindow]   ③接收缓冲满
 43   0.6250   client   Seq=15929 Len=1    [TCP ZeroWindowProbe] ④探测
 44   0.6251   server   Ack=15929 Win=0    [ZeroWindowProbeAck]
 45   0.8092   server   Ack=15929 Win=14480 [TCP Window Update] ⑤应用读走数据
 46   0.8093   client   Seq=15930 Len=1448                      ⑥恢复发送
```

标注：① 正常段；② Wireshark 推导出 BiF==rwnd；③ Win 原始值 0；④ 1 字节探测（下一章细讲）；⑤ 不带数据的窗口更新；⑥ 注意恢复后 Seq 从 15930 继续——探测字节占了一个序号。

## 13. Frame-by-Frame 分析

- **Frame 41 为什么标 Window Full？** 证据：到此为止发送方未确认字节 = 15929−14481+1448×… 归纳为 SND.NXT−SND.UNA == Server 最近通告的 Calculated Window。这是 Wireshark 沿流状态推导的，报文里**没有** "Window Full" 标志位。
- **Frame 42 为什么 Win=0？** 我们把 `tcp_rmem` 压到 16KB，iperf3 服务端读取速度跟不上 40ms RTT 下的突发到达，缓冲塞满。
- **Frame 45 为什么算 Window Update？** 同一 Ack 值（15929）且 Win 从 0 变 14480、Len=0：不确认新数据、只更新窗口。

## 14–15. 操作系统内部状态 / ss 分析

发送侧 `ss -ti` 关注：`notsent` 有积压（应用想发发不出）而 `cwnd` 很大 ⇒ 卡在对端窗口而非拥塞。接收侧 `ss -tm` 关注 `skmem(rb...)` 与 `Recv-Q`：Recv-Q 顶满 rb ⇒ 应用读得慢（第 4 章展开这条判定链）。

## 16–18. 正常特征 / 异常特征 / 抓包指纹

**正常**：窗口随 ACK 平滑滑动，偶发 Window Full 后很快恢复。
**异常**：持续 Window Full/ZeroWindow 循环（接收端瓶颈）；通告窗口锯齿状剧烈波动（应用批处理式读取）；窗口大但发送节奏稀疏（瓶颈另在 cwnd 或应用，第 19 章）。
**指纹（Window Full）**：`tcp.analysis.window_full`；看到它的意思是"发送方被 rwnd 卡住"，**不能**据此判断网络拥塞，下一步查接收端 Recv-Q。

## 19. Wireshark Filter

```
tcp.analysis.window_full        tcp.analysis.window_update
tcp.analysis.zero_window        tcp.window_size < 10000 && tcp.len==0
```

## 20. TCP Stream Graph

Window Scaling Graph 是本章的主图：绿线（对端通告窗口）与蓝点（Bytes in Flight）。三种典型形态：

1. 蓝点长期贴绿线：**rwnd-limited**（本章实验的形态）。
2. 绿线高、蓝点低且呈锯齿：**cwnd-limited**（第 11 章形态）。
3. 蓝点稀疏且远低于绿线：**application-limited**（发送端没数据可发）。

## 21–23. 2025–2026 真实业务应用与生产案例

滑动窗口本身的"生产案例"就是一切高 BDP 传输：对象存储跨区复制、跨国专线备份、CDN 回源。具体的可核验生产案例集中在两类：接收窗口调优（第 2 章已给 Cloudflare 2022 案例）与接收窗口增长过慢——

**【真实生产案例】Cloudflare：Linux 接收窗口爬坡慢于预期（2022）**：Cloudflare 内核团队公开分析了 Linux 接收窗口并非一次开满：受 `rcv_ssthresh` 限制，窗口从 64 KiB 起步、随"好包"线性增长，需要多个 RTT 才能开到缓冲允许的最大值；文中实验显示填满 128 KiB 接收缓冲耗了 6 个 RTT、5 次 Window Update。**事实**：上述机制与实验数据（来源：Cloudflare Blog, *When the window is not fully open, your TCP stack is doing more than you think*, 2022, https://blog.cloudflare.com/when-the-window-is-not-fully-open-your-tcp-stack-is-doing-more-than-you-think/ ）。**推断**：对短连接（Web/API），窗口爬坡叠加 Slow Start，前几个 RTT 的传输额度远小于教科书估计——短流性能分析必须同时看 rwnd 爬坡和 cwnd 爬坡两条曲线。

## 24. 如果在生产环境我怎么排查

传输时快时停：① filter `tcp.analysis.window_full || tcp.analysis.zero_window`；② 有 ⇒ 转第 4 章接收端排查；③ 无但吞吐低 ⇒ 画 Window Scaling Graph 分辨三种形态；④ 蓝点贴绿线 ⇒ 收端；蓝点锯齿 ⇒ 拥塞；蓝点稀疏 ⇒ 发端应用。

## 25. 常见误判

- Window Full ≠ 故障（瞬时出现是正常的流量控制在工作；**持续**出现才是瓶颈信号）。
- ACK 到达 ≠ 一定能继续发（右边缘 = Ack+Win，Win 缩了右边缘可能不动，见 T4）。
- 窗口很大 ≠ 吞吐一定高（还有 cwnd、应用、pacing，第 6 章）。

## 26. 与其他 TCP 机制如何联动

滑动窗口是"额度框架"：rwnd（第 4 章）决定右边缘，cwnd（第 6 章）给出第二个更隐蔽的右边缘，实际发送额度 = 两者较小者减 Bytes in Flight（第 5 章）。丢包时左边缘停滞（Ack 不动）⇒ 窗口冻结 ⇒ 这就是丢包杀伤吞吐的窗口视角解释（第 10–12 章）。

## 27. 分析练习

MSS=1000，当前 SND.UNA=8001，SND.NXT=12001，最近收到 `Ack=8001 Win=6000`。问：1) Bytes in Flight？2) 还能立即发送多少字节？3) 此时收到 `Ack=10001 Win=4000`，左、右边缘各在哪？还能发多少？4) 若再收到 `Ack=10001 Win=8000, Len=0`，这是什么报文？

## 28. 详细答案

1) 12001−8001=4000。2) 6000−4000=2000（右边缘 8001+6000=14001，SND.NXT=12001）。3) 左=10001，右=10001+4000=14001；BiF=12001−10001=2000；可发 14001−12001=2000。右边缘没动——Win 缩小抵消了 Ack 前进。4) Window Update：Ack 未变、Win 变大、无数据。

## 29. 本章总结

滑动窗口四区域 + 三条边界解释了 TCP 的发送节奏：ACK 推左边缘，Ack+Win 定右边缘。窗口的右边缘由谁说了算？下一章先讲接收方的答案：rwnd。
