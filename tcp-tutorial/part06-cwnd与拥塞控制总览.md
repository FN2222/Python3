# 第 6 章 cwnd 与拥塞控制总览：TCP 到底允许发送多少数据？

## 1. 为什么需要这个机制

rwnd 保护的是**接收方**。但报文从发送方到接收方要穿过一串路由器、交换机、无线基站，每一跳都有有限的队列。1986 年 10 月，ARPANET 出现了历史上著名的"拥塞崩溃"：LBL 到 UC Berkeley 的有效吞吐从 32 kbps 跌到 40 bps——千分之一。原因：所有发送方只看 rwnd 拼命发，网络丢包，大家超时重传，重传进一步加剧拥塞。Van Jacobson 由此提出：发送方必须自己维护一个对**网络容量**的估计——**Congestion Window（cwnd）**。

于是本教程的核心问题有了完整答案的骨架：

> **Sender 当前到底可以发送多少未确认数据？**
>
> ```
> 可发送额度 ≈ min(rwnd, cwnd) − Bytes in Flight
> ```
> rwnd：接收方还能接多少（对方告诉你的，写在报文里）。
> cwnd：网络还能载多少（你自己猜的，只存在于你的内核里）。

## 2. 没有它会发生什么

拥塞崩溃的机制值得拆开看：网络过载 ⇒ 队列满 ⇒ 丢包 ⇒ 超时重传 ⇒ **注入的总流量不减反增**（原始+重传）⇒ 更多丢包。正反馈循环，直到几乎没有"新"数据能穿过网络。cwnd + AIMD 把它变成负反馈：丢包 ⇒ 减窗 ⇒ 网络减压。今天互联网没有天天崩溃，是因为几乎每台主机都在跑这套机制。

## 3. 核心原理

### 3.1 cwnd 是什么、由谁维护、为什么不在 TCP Header 中

- cwnd 是**发送方 TCP Stack 的私有变量**（Linux 中 `tcp_sock->snd_cwnd`，单位是"段"）。
- 它**不需要**告诉对方：rwnd 必须通告（只有接收方知道自己的缓冲），而 cwnd 是发送方对网络的**本地估计**，对方知道了也没用——所以 TCP Header 里从来没有 cwnd 字段。
- 因此 **Wireshark 无法像读 rwnd 一样直接读取 cwnd**。抓包只能看到 cwnd 的"投影"：发送节奏与 Bytes in Flight。BiF 是 cwnd 的影子，但影子≠本体（application-limited 时 BiF ≪ cwnd）。

### 3.2 cwnd 怎么变：状态机总览

后续四章展开的机制，先给全景图：

```
            ┌──────────── Slow Start ────────────┐
   连接建立→ │ cwnd 从 IW 起，每 RTT ≈ ×2          │ cwnd ≥ ssthresh
            └────────────────────────────────────┘──────┐
                     ▲                                   ▼
        RTO 超时:     │                     ┌── Congestion Avoidance ──┐
        ssthresh=cwnd/2│                     │ 每 RTT 约 +1 MSS (AIMD)  │
        cwnd=1, 回SS   │                     └──────────────────────────┘
                     │                                   │ 3 Dup ACK / RACK 判丢
            ┌────────┴───────┐              ┌────────────▼─────────────┐
            │      RTO       │◀─恢复失败────│ Fast Retransmit + Fast   │
            └────────────────┘              │ Recovery: ssthresh=cwnd/2│
                                            │ (CUBIC: ×0.7)，PRR 平滑   │
                                            └────────────┬─────────────┘
                                                恢复完成 → 回 Congestion Avoidance
```

### 3.3 简化公式之外：实际实现还受什么限制

`min(rwnd, cwnd)` 是**下限正确、上限天真**的模型。真实 Linux 发送路径上，每一步都可能是瓶颈：

| 因素 | 作用 | 观测手段 |
|---|---|---|
| application write speed | 应用不写，窗口再大也空转 | `ss -ti` 无 `notsent` 积压 + BiF 小 |
| socket send buffer（tcp_wmem/SO_SNDBUF） | 装不下足够的在途+待发数据 | `ss -tm` skmem t/tb 顶满 |
| Nagle（默认开） | 小包合并，未确认小包时暂扣新小包 | 交互流延迟 40ms 量级；`TCP_NODELAY` 对照 |
| Delayed ACK（对端） | 与 Nagle 相互作用产生经典 40ms 卡顿 | Time Delta 指纹 |
| pacing（fq qdisc / 内核内置） | 不许突发怼满窗口，按速率匀速发 | `ss -ti` pacing_rate |
| TSO/GSO | 内核把 64KB 大段推给网卡切分，影响突发粒度与抓包形态 | 第 18 章 |
| TCP Small Queues (TSQ) | 限制每 socket 压在 qdisc/驱动里的字节，防 bufferbloat | 高速单流吞吐异常时排查 |
| 拥塞控制算法本身 | BBR 直接以 pacing_rate 为主、cwnd 为辅 | `ss -ti` 算法名 |
| 操作系统实现差异 | Windows/FreeBSD/移动端行为不同 | 先确认 OS 与算法再分析 |

**方法论**：诊断"发不快"，永远按 `应用 → 发送缓冲 → cwnd → rwnd → 网络` 的顺序排除，每一步都有独立证据源，不允许跳步下结论。

### 3.4 五层可见性（全书反复使用的表）

| 层 | 例子 | 获取方式 |
|---|---|---|
| ① 协议层字段（线上可见） | Seq、Ack、Window Size Value、SACK、MSS/WS 选项 | Wireshark 直读 |
| ② 握手推导（需抓到握手） | Window Scale 因子、Calculated Window | Wireshark 推导 |
| ③ 流状态推导 | Bytes in Flight、Dup ACK 计数、RTT 样本、"Fast Retransmission" 等 Expert 标记 | Wireshark 沿流推导（方括号字段） |
| ④ TCP Stack 内部状态 | **cwnd、ssthresh**、SRTT/RTTVAR、RTO、pacing_rate、delivery_rate、notsent | `ss -ti`、tcp_info、eBPF |
| ⑤ 抓包与内核都难直接给出 | 应用为什么读/写慢、中间盒队列深度 | 应用剖析、设备侧数据 |

**记住：Wireshark 的每个方括号字段都是推导，不是协议事实。**"Wireshark 说 Fast Retransmission"≠"报文里有个 Fast Retransmission 标志"（第 10、16 章）。

## 4–5. 关键变量与数学关系

```
可发送额度 = min(rwnd, cwnd) − BiF        （教学基线）
cwnd 单位：Linux 中为段（×MSS 得字节）
吞吐 ≈ min(rwnd, cwnd, 应用供数, BDP+队列) / RTT
```

## 6. 数值案例 【教学模拟案例】

MSS=1448，RTT=40ms，rwnd=512KB 恒定。看 min() 的"接力"：

| 阶段 | cwnd | min(rwnd,cwnd) | BiF | 限制者 |
|---|---:|---:|---:|---|
| SS 第2轮 | 40段=57.9KB | 57.9KB | 57.9KB | cwnd |
| SS 第5轮 | 320段=463KB | 463KB | 463KB | cwnd |
| SS 第6轮 | 640段=926KB | **512KB** | 512KB | **rwnd 接管** |
| 丢包恢复后 | 250段=362KB | 362KB | 362KB | cwnd 又接管 |

同一条连接的瓶颈在 rwnd 和 cwnd 之间来回切换——**"谁限制了我"是个随时间变化的问题**，这正是第 15 章大联动的主线。

## 7–13. 实验：亲眼看到 cwnd（EXP-09）

cwnd 在报文里不可见，所以本章实验的主角是 `ss -ti`：

```bash
# 采样脚本（0.1s 一次，含时间戳）
ip netns exec ns-client bash -c '
while true; do
  echo "$(date +%s.%N) $(ss -ti dst 10.0.0.2 | tail -1)"
  sleep 0.1
done' > cwnd.log &
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 15
```

真实输出样例（附录 A 环境，netem 40ms、无丢包，字段为 Linux iproute2 实际格式）：

```
cubic wscale:7,7 rto:244 rtt:40.6/1.2 mss:1448 pmtu:1500 rcvmss:536 advmss:1448
cwnd:512 ssthresh:409 bytes_sent:96738304 bytes_acked:96011776 segs_out:66822
segs_in:33461 data_segs_out:66820 send 146Mbps lastsnd:4 lastrcv:12888 lastack:4
pacing_rate 175Mbps delivery_rate 144Mbps delivered:66305 app_limited busy:12884ms
unacked:502 rcv_space:14480 rcv_ssthresh:64088 notsent:1303200 minrtt:40.1
```

逐字段解读（本教程后续章节的"仪表盘"）：

| 字段 | 含义 | 用法 |
|---|---|---|
| `cubic` | 拥塞控制算法 | **分析 cwnd 行为前必看** |
| `cwnd:512` | 拥塞窗口（段） | ×mss=741KB |
| `ssthresh:409` | 慢启动阈值（段） | cwnd>ssthresh ⇒ 已在 CA 阶段 |
| `rtt:40.6/1.2` | SRTT/RTTVAR (ms) | RTO 的原料（第 12 章） |
| `rto:244` | 当前 RTO (ms) | 下限 200ms（Linux TCP_RTO_MIN） |
| `unacked:502` | 在途段数 | ≈BiF/mss；贴着 cwnd ⇒ cwnd-limited |
| `pacing_rate 175Mbps` | 匀速发送速率上限 | fq/内核 pacing |
| `delivery_rate 144Mbps` | 实测交付速率 | BBR 的核心输入 |
| `bytes_acked / bytes_sent` | 累计确认/发送 | 差值≈BiF 字节 |
| `retrans:X/Y`（丢包时出现） | 当前/累计重传 | 第 10–12 章 |
| `notsent:1303200` | 应用已写、TCP 未发 | >0 ⇒ 不是应用瓶颈 |
| `app_limited` | 出现过应用受限 | delivery_rate 样本打折标记 |

把 `cwnd` 列随时间画出来（`gnuplot`/Python 均可），与 Wireshark 的 BiF 曲线叠加：无丢包时两线几乎重合并单调爬升，到达 rwnd 或 BDP 后走平——你就"看见"了 cwnd。

## 16–18. 特征与指纹

- `unacked ≈ cwnd` 且 `notsent > 0` 且 rwnd 富余 ⇒ **cwnd-limited**（指纹）。
- `cwnd` 锯齿+`retrans` 增长 ⇒ 丢包驱动（转第 10–12 章）。
- `cwnd` 很大但吞吐低且 `app_limited` ⇒ 应用供数不足。
- **不能据此判断**：cwnd 小 ⇒ 网络差。cwnd 小也可能因为流刚启动、长时间空闲后被重置（`tcp_slow_start_after_idle=1`）、或算法保守。

## 19–20. Filter 与图

Wireshark 无 cwnd 过滤器（④层数据）。用 BiF 近似：`tcp.analysis.bytes_in_flight`。Stream Graph 中 cwnd 的影子 = tcptrace 图里数据阶梯离 ACK 线的距离包络。

## 21–23. 2025–2026 真实业务应用与生产案例

现代生产环境的 cwnd 管理者（截至 2026-08 联网核验）：

- **CUBIC**：Linux/Windows/Apple 三大栈默认（RFC 9438，2023 年 Standards Track 化时明确记载；2026 年 Linux mainline 默认仍是 CUBIC）。
- **BBR 系列**：Google 在 google.com/YouTube 生产部署 BBRv3 并推动 IETF 标准化（draft-ietf-ccwg-bbr，2026-07 已到 -06 版）；Linux mainline 的 `bbr` 模块仍是 BBRv1，BBRv3 以 google/bbr 树外补丁形式提供。
- **CDN/云**：Dropbox Edge 自 2017 年生产使用 BBRv1（其公开评测记录 BBRv1 宿主机丢包率最高 6% vs CUBIC 0.5%，促成 BBRv2 评估）；Netflix CDN 全量使用自研 FreeBSD RACK 栈配合自己的 CC 策略。
详细来源与证据链见第 14 章与第 21 章（案例 R3/R4/R5）。

## 24. 如果在生产环境我怎么排查

"服务器发不快"标准五步：① `ss -ti` 确认算法、cwnd、unacked、notsent、pacing_rate；② notsent≈0 ⇒ 应用瓶颈，结束网络侧怀疑；③ unacked 贴 rwnd ⇒ 对端/收侧；④ unacked 贴 cwnd 且 retrans 涨 ⇒ 路径丢包（转证据链抓包）；⑤ cwnd 高 BiF 高吞吐仍低 ⇒ 查 RTT 是否被队列拉高（bufferbloat，看 rtt 与 minrtt 差值）。

## 25. 常见误判

- Wireshark 窗口字段正常 ≠ cwnd 正常（④层不可见，必须 ss）。
- "窗口"一词出现时先问是哪个窗口：rwnd？cwnd？send buffer？
- cwnd 单位是段不是字节（对比时要 ×MSS）。
- min(rwnd,cwnd) 是教学模型：pacing/TSQ/应用随时可能才是真瓶颈。

## 26. 与其他 TCP 机制如何联动

cwnd 的增长靠 ACK Clock（第 7、8 章），削减靠丢包/ECN 信号（第 10–14 章），它与 rwnd 在 min() 中竞争限制权（第 19 章 Case A/B 对比），它的全部生命周期在第 15 章大联动中完整走一遍。

## 27. 分析练习

`ss -ti` 输出：`cubic ... rtt:82/3 mss:1448 cwnd:64 ssthresh:64 unacked:64 retrans:0/213 notsent:8388608 ...`，对端通告窗口 2 MB。问：1) 处于哪个拥塞阶段？2) 限制吞吐的是谁？3) 吞吐估计？4) `retrans:0/213` 说明什么？5) 下一步收集什么证据？

## 28. 详细答案

1) cwnd==ssthresh=64，处于 CA 边界（刚从恢复回到 CA 的典型形态）。2) unacked==cwnd=64 段≈92.7KB ≪ rwnd=2MB，且 notsent 有 8MB 积压 ⇒ cwnd-limited。3) 92.7KB/82ms ≈ 9 Mbps。4) 当前无在途重传，但历史重传 213 段 ⇒ 这条流经历过丢包，cwnd 被压低是丢包史的后果。5) 抓包确认丢包位置与形态（Dup ACK/SACK 序列），并按第 20 章双点法定位丢包段。

## 29. 本章总结

cwnd 是发送方对网络容量的私有估计，抓包永远看不见，只能看 ss。`min(rwnd,cwnd) − BiF` 是发送额度的教学骨架，真实栈还叠加 pacing/TSQ/应用等约束。接下来两章回答：cwnd 是**怎么长**的——先指数（Slow Start），后线性（Congestion Avoidance）。
