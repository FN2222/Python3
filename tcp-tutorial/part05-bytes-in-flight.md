# 第 5 章 Bytes in Flight（在途字节）

## 1. 为什么需要这个概念

前几章反复出现"已发送未确认"这个区域。给它一个正式名字：**Bytes in Flight（BiF）= SND.NXT − SND.UNA = 已发出但尚未被累积确认的字节数**。它是连接三大问题的枢纽量：

- 对照 rwnd：BiF == rwnd ⇒ Window Full（rwnd-limited）。
- 对照 cwnd：BiF ≈ cwnd 且远小于 rwnd ⇒ cwnd-limited（第 6、19 章）。
- 对照 BDP：BiF < BDP ⇒ 管道没填满，吞吐必然低于链路带宽。

**吞吐的第一性公式**：稳态下 `Throughput ≈ BiF / RTT`。诊断"为什么慢"，本质上就是诊断"是什么卡住了 BiF"。

## 2. 没有它会发生什么（分析层面）

不看 BiF 的分析只能罗列现象："有重传""窗口挺大""RTT 正常"。BiF 把它们串成因果：限制吞吐的必然是 rwnd、cwnd、应用供数、缓冲之一，而 BiF 曲线的形态直接指认凶手。

## 3. 核心原理与 Wireshark 的推导方式

BiF 是**发送方内核的状态**，报文里没有这个字段。两条获取途径：

1. **Wireshark 推导**：沿单条流累积（已发最大 Next Seq）−（对端最新 Ack），标注为 `[Bytes in flight: N]`（方括号=推导值）。前提：抓包点能看到该方向全部数据与回程 ACK。
2. **内核直读**：`ss -ti` 的 `unacked`（单位是段数，×MSS 近似字节）以及 `notsent`（应用已写入但尚未发出——**不算** BiF）。

**抓包位置的系统性偏差**：在发送端抓包，看到数据的时间早、看到 ACK 的时间晚，BiF 推导值偏向发送方真实状态；在接收端抓包，数据到达晚、ACK 发出早，推导出的 BiF 会系统性偏小。多点抓包时不要直接比较两点的 BiF 数值（第 20 章）。

## 4–5. 关键变量与数学关系

```
BiF = SND.NXT − SND.UNA
可再发送 = min(rwnd, cwnd) − BiF        （第 6 章完整版）
稳态吞吐 ≈ BiF / RTT
填满链路所需 BiF = BDP = BW × RTT
```

## 6. 数值案例 【教学模拟案例】

RTT=40ms，rwnd=512KB，链路 100 Mbps ⇒ BDP = 100e6/8×0.04 = 500 KB。

| 时刻 | cwnd | BiF 实际 | 吞吐 = BiF/RTT | 受限于 |
|---|---:|---:|---:|---|
| Slow Start 第3轮 | 40 KB | 40 KB | 8 Mbps | cwnd |
| 第6轮 | 320 KB | 320 KB | 64 Mbps | cwnd |
| 第7轮 | 640 KB | 500 KB | 100 Mbps | **链路/队列**（BDP 到顶）|
| 应用只写 10KB/40ms | 大 | 10 KB | 2 Mbps | 应用（application-limited）|

第 4 行提醒：BiF 低不一定是窗口问题——**应用不给数据，TCP 巧妇难为**。`ss -ti` 里 `notsent≈0` 且 BiF 小 ⇒ application-limited 的内核证据。

## 7–13. Timeline / 实验 / 抓包分析（EXP-09）

实验：附录 A 环境 RTT 40ms，iperf3 单流，同时每 100ms 采样 ss：

```bash
ip netns exec ns-client bash -c 'while true; do ss -ti dst 10.0.0.2 | grep -o "unacked:[0-9]*\|cwnd:[0-9]*"; sleep 0.1; done' > ss.log &
ip netns exec ns-client tcpdump -i veth-c -w bif.pcap &
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 10
```

对照方法：Wireshark 打开 bif.pcap，任选稳态中的一个数据帧，读 `[Bytes in flight]`；换算 ss 同时刻 `unacked×mss`，两者应吻合（±一个突发的误差）。若严重不符：检查抓包是否丢包（`capinfos`、`tcpdump` 退出时的 "packets dropped by kernel"）。

Frame-by-Frame 示例（稳态、cwnd-limited）：

```
Frame 300  C→S Seq=4200001 Len=1448  [Bytes in flight: 289600]   ← ≈200×MSS
Frame 301  S→C Ack=4058449 Win=3100000                            ← rwnd≈3MB 远大于 BiF
```

结论链：BiF(289600) ≪ rwnd(3100000) ⇒ 不是 rwnd 限制 ⇒ 结合 ss 的 cwnd:200 ⇒ cwnd-limited。**这两帧就是第 19 章 Case B 的浓缩版。**

## 16–18. 特征与指纹

- BiF 长期贴 rwnd ⇒ rwnd-limited（绿线压顶）。
- BiF 锯齿（涨→腰斩→再涨）⇒ 丢包驱动的 cwnd 调整（第 11 章）。
- BiF 周期性归零 ⇒ 应用间歇供数或请求-响应型流量（不是故障）。
- **不能据此判断**：BiF 大 ⇒ 吞吐高（若 RTT 也大，吞吐未必高；且 BiF 大可能只是路径队列在膨胀——bufferbloat）。

## 19–20. Filter 与 Stream Graph

```
tcp.analysis.bytes_in_flight > 1000000
```
Stevens 图斜率 = 吞吐；tcptrace 图中"数据阶梯"与"ACK 线"的垂直距离就是 BiF 的图形化——两线咬得紧 ⇒ BiF 小 ⇒ 每 RTT 只发一点。

## 21–26. 应用、案例与联动

BiF 是第 15 章大联动 10 图中的主角之一，也是 BBR 类算法的直接控制对象（BBR 以 inflight 逼近 BDP 为目标而不是逼近丢包点，第 14 章；Google BBR 论文与 IETF 材料以 "inflight" 为核心术语——同一个量）。联动：ACK 到达 ⇒ BiF 下降 ⇒ 额度释放；丢包 ⇒ Ack 停滞 ⇒ BiF 高位冻结 ⇒ 新数据发不出（第 10 章 Fast Retransmission 期间的"窗口冻结"感）。

## 27–28. 练习与答案

抓包（发送端视角，MSS=1448，rwnd 恒 1MB）：`t=0` 发出 Seq=100001..100001+289599（200段）；`t=38ms` 收到 Ack=245601。问：1) t=0+ 的 BiF？2) t=38ms+ 的 BiF？3) 若 ss 显示 cwnd:200，此刻还能发多少？4) 稳态吞吐估计？

答案：1) 289600。2) 389600−245601+... 直接算：已发最大 NextSeq=389601，BiF=389601−245601=144000。3) cwnd=200×1448=289600；min(rwnd,cwnd)−BiF=289600−144000=145600 ≈ 100 段。4) BiF/RTT≈289600/0.04≈58 Mbps（以满窗时 BiF 计）。

## 29. 本章总结

BiF 是把 rwnd、cwnd、BDP、吞吐连在一起的量。到目前为止 cwnd 一直是个"剧透"——下一章正式回答本教程的核心问题：**TCP 到底允许发送多少数据？**
