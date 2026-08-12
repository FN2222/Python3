# 第 14 章 现代拥塞控制：传统 TCP 教材模型 vs 2026 年现代 TCP Stack

> 本章全部"现状"结论按提示词要求于 **2026 年 8 月**联网核验，逐条附来源；凡无法核验的一律标注为推断。

## 1. 为什么需要这一章

传统教材的世界：Reno，丢包=拥塞，AIMD 锯齿。2026 年的真实世界：**丢包不再是唯一信号**（延迟、ECN 标记、交付速率模型都在用），**cwnd 不再是唯一执行器**（pacing_rate 同样重要），**同一路径上不同算法共存博弈**。分析生产流量的第一步永远是：**这条流跑的是什么算法？**（`ss -ti` 第一列，或对端不可控时从行为指纹推断。）

## 2. 算法版图（2026-08 核验）

### 2.1 CUBIC —— 仍然的王座

- **事实**：RFC 9438（2023-08）将 CUBIC 升级为 Standards Track，并记载其为 **Linux、Windows、Apple 三大栈的默认** TCP 拥塞控制；Linux mainline 2026 年默认仍是 CUBIC。机制回顾见第 8 章（三次曲线、β=0.7、HyStart）。
- 来源：RFC 9438, https://www.rfc-editor.org/rfc/rfc9438 。

### 2.2 BBR 系列 —— Google 的模型驱动路线

分类学：CUBIC/Reno 是 **loss-based**（丢包驱动窗口）；BBR 是 **model-based / rate-based**——持续估计路径的两个参数：瓶颈带宽 BtlBw（取 delivery_rate 滑窗最大值）与最小往返 RTprop（滑窗最小 RTT），控制目标是 `inflight ≈ BDP = BtlBw × RTprop`，执行器以 **pacing_rate 为主、cwnd 为上限护栏**。

版本与状态（核验）：

| 版本 | 关键变化 | 2026-08 状态 |
|---|---|---|
| BBRv1 (2016) | 带宽+RTT 模型；基本无视丢包 | **Linux mainline `bbr` 模块至今仍是 v1**；Google 官方标记 obsolete/deprecated |
| BBRv2 (2019) | 加入丢包率上限（~2%）与 ECN 反应、inflight 上限、公平性修补 | 被 v3 取代 |
| BBRv3 (2023) | v2 的 bug 修复+参数调优 | **Google 内部生产（google.com/YouTube）**；开源于 google/bbr v3 分支（树外补丁，需自编内核）；IETF CCWG 标准化中：draft-ietf-ccwg-bbr **-06（2026-07）**；尚未合入 Linux mainline |

来源：google/bbr v3 README, https://github.com/google/bbr/blob/v3/README.md ；IETF 119 CCWG slides *BBRv3: Overview and Google's deployment*（2024-03，含"计划提交 mainline、bbr 模块将原地升级到 v3"的声明——**注意：截至 2026-08 此计划仍未完成**）；bbr-dev 邮件列表（维护者持续为新内核 rebase v3）；datatracker draft-ietf-ccwg-bbr。

**BBR 行为指纹（抓包/ss 判读）**：启动后周期性出现 `PROBE_RTT`（约每 10s 把 inflight 降到 4×MSS 持续 ~200ms——吞吐图上规律性小凹槽）；丢包后吞吐几乎不掉（v1）；`ss -ti` 显示 `bbr` 且 pacing_rate 与 delivery_rate 高度相关。**误判警告**：BBRv1 流在浅缓冲下丢包率可以很高却依然满速——"重传多=有问题"对 BBR 流不成立（见下 Dropbox 数据）。

### 2.3 ECN → AccECN → L4S：不丢包的拥塞信号

- **经典 ECN（RFC 3168）**：路由器把 IP 头 CE 位置 1 替代丢包；接收方以 TCP ECE 回传，发送方按"等同一次丢包"减窗。每 RTT 只能反馈一次拥塞。
- **AccECN（draft-ietf-tcpm-accurate-ecn）**：per-segment 精确回传 CE 计数（ACE 三比特+选项）。**核验状态**：文稿 -34 已过 IESG、处于 RFC Editor 队列（2026）；**Linux 自 6.15 起分批合入，Linux 7.0（2026-04）起对入站连接默认启用**（`tcp_ecn` 默认从 2 改为 5：入站接受 AccECN/ECN，出站仍默认不主动请求——防协议僵化的谨慎姿态）。来源：LWN, *More accurate congestion notification for TCP*, https://lwn.net/Articles/1058666/ ；LWN AccECN patch series, https://lwn.net/Articles/1028208/ ；datatracker。
- **L4S（RFC 9330/9331/9332，2023）**：架构 = Scalable CC（DCTCP 系/Prague/BBRv3-ECN）+ DualQ 双队列 AQM + AccECN 反馈；目标是把排队时延压到毫秒级同时不牺牲吞吐。ECT(1) 标识 L4S 流量。
- **DCTCP（RFC 8257，2017）**：数据中心专用 Scalable CC，按 CE 标记**比例**微调 cwnd（不是一刀砍半）；RFC 记载 Microsoft 自 2012 年起在其数据中心大规模部署。**只可用于受控环境**（对 Reno/CUBIC 过于强势）。

### 2.4 pacing 与发送路径

现代栈默认不"窗口一开就突发怼满"：Linux 的 fq qdisc / 内核内置 pacing 按 `pacing_rate`（SS 期 ≈2×cwnd/RTT，CA 期 ≈1.2×）匀速发出；TSQ 限制每 socket 压队字节。抓包影响：包间距均匀化，I/O Graph 的"梳齿"变"平台"——**看不到突发 ≠ 没有窗口机制**。

## 3. 传统教材模型 vs 2026 现实：对照表

| 教材断言 | 2026 现实 | 核验依据 |
|---|---|---|
| 丢包 ⇒ cwnd 砍半 | CUBIC ×0.7；BBR 不必然降；DCTCP 按比例 | RFC 9438/8257，google/bbr |
| 3 Dup ACK 触发重传 | Linux 默认 RACK 时间判丢 | 第 13 章 |
| 慢启动冲到丢包为止 | HyStart/HyStart++ 提前退出 | RFC 9406 |
| 拥塞信号只有丢包 | +ECN/AccECN/L4S、+延迟模型 | RFC 9330-9332, LWN |
| cwnd 决定发送节奏 | pacing_rate 共同决定 | 内核 fq/pacing 文档 |
| 全网行为可用一个模型解释 | 至少 CUBIC/BBR/DCTCP/Prague 共存 | 上述全部 |

## 4. 哪些系统在用什么（核验快照，2026-08）

- **Linux mainline 默认**：CUBIC（可选 bbr=v1、dctcp 等模块）。
- **Windows 11 / Server**：CUBIC 默认 + HyStart++；RACK/TLP 可用。
- **Apple**：CUBIC 默认（RFC 9438 记载）；iOS 16+/macOS Ventura+ 支持 L4S（Comcast 部署材料记载 FaceTime 已用）。
- **Google**：BBRv3（google.com/YouTube；QUIC 与 TCP 均有）。
- **Netflix**：FreeBSD RACK 栈 + 自选 CC 策略（第 13 章）。
- **Comcast（接入网）**：L4S/低时延 DOCSIS 商用（下详）。
- **不要默认推断**：任何具体系统"一定"用某算法——`ss -ti`/厂商文档核实后再下结论（本教程铁律）。

## 5. 实验（EXP-10：CUBIC vs BBR 同剖面对比）

```bash
# 环境：RTT 40ms + 瓶颈 100Mbit + 0.5% 随机丢包
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms loss 0.5% rate 100mbit
modprobe tcp_bbr
ip netns exec ns-client sysctl -w net.ipv4.tcp_congestion_control=cubic && iperf3 ... # 跑1次
ip netns exec ns-client sysctl -w net.ipv4.tcp_congestion_control=bbr   && iperf3 ... # 再跑1次
```

预期（教学复现，mainline bbr=v1）：0.5% 丢包下 CUBIC 吞吐被 Mathis 公式压到 ~15–25 Mbps；BBRv1 接近 90+ Mbps 且 `retrans` 计数不低——**同样的网络，两种算法给出完全不同的"体检报告"**。判读生产问题前先问算法，就是这个原因。

## 6. 真实生产案例（联网核验）

**【真实生产案例】Google：BBR 从 B4 广域网到 google.com/YouTube（2016–2026）**
**事实**：BBR 论文（ACM Queue/CACM 2016–2017）记载其在 Google B4 WAN 上取代 CUBIC 后吞吐提升 2–25 倍（部分链路 133 倍）；IETF 119（2024-03）材料记载 BBRv3 已部署于 google.com 与 YouTube，动机数据包括"较 v1 更好的 Reno/CUBIC 共存、更低丢包率、短请求更低延迟（吞吐与 v1 相差 1% 内）"；2026-07 标准草案推进至 draft-ietf-ccwg-bbr-06。**推断**：Google 侧连接（含 YouTube 边缘）的抓包应按 BBR 指纹解读（PROBE_RTT 凹槽、丢包不降速）；但任何非 Google 服务器不能默认 BBR。
**来源**：Cardwell et al., *BBR: Congestion-Based Congestion Control*, CACM 60(2), 2017；IETF 119 CCWG slides（2024）；datatracker draft-ietf-ccwg-bbr-06（2026-07）。

**【公开实验/官方实验】Dropbox Edge：BBRv1 生产四年的得与失 + BBRv2 评测（2017–2020）**
**事实**：Dropbox 边缘网络 2017 年起生产使用 BBRv1（其博客记载桌面客户端下载 goodput 显著提升）；Netdev 0x14 论文（2020）记载生产观测：**BBRv1 宿主机丢包率最高达 6%，同期 CUBIC 宿主机约 0.5%**，且存在对 loss-based 流的不公平与 BBR 流间 RTT 不公平；BBRv2 评测显示丢包率、公平性大幅改善，接近可替代 CUBIC/DCTCP。**推断**：这是"BBRv1 无视丢包"的最佳量化生产证据——也解释了为何 v2/v3 引入 2% 丢包目标；评估切换算法必须同时看吞吐**和**丢包外部性。
**来源**：Dropbox Tech Blog, *Evaluating BBRv2 on the Dropbox Edge Network* (2019)，https://dropbox.tech/infrastructure/evaluating-bbrv2-on-the-dropbox-edge-network ；同名 Netdev 0x14 论文（2020），https://netdevconf.info/0x14/pub/papers/16/0x14-paper16-talk-paper.pdf 。

**【真实生产案例】Comcast：L4S 低时延 DOCSIS 商用（2025–2026）**
**事实**：Comcast 2025-01-29 官宣全美首个 L4S 低时延接入商用（合作方 Apple FaceTime、Meta、NVIDIA GeForce NOW、Valve Steam），首批城市含亚特兰大、芝加哥、费城、旧金山等；IETF 部署报告（draft-livingood-low-latency-deployment-15）记载：截至 2026-01 覆盖超 **1000 万户**，下行 99 分位加载时延从 ~65ms（无 AQM）→ ~33ms（AQM）→ **~18ms（L4S/NQB 低时延队列）**，上行 ~20ms。**推断**：接入网时延剖面正在改变——分析家宽用户"卡顿"时，L4S 覆盖区的基线预期应更新；ECT(1)/CE 标记在家宽抓包中将越来越常见。
**来源**：Comcast 新闻稿 2025-01-29，https://corporate.comcast.com/press/releases/comcast-introduces-nations-first-ultra-low-lag-xfinity-internet-experience-with-meta-nvidia-and-valve ；draft-livingood-low-latency-deployment-15（2026）。

**【真实生产案例】AccECN 进入 Linux 并默认启用（2025–2026）**
**事实**：AccECN 补丁系列（Bob Briscoe 设计、Nokia/Chia-Yu Chang 实现，Eric Dumazet 等审阅）自 Linux 6.15 起合入，**Linux 7.0（2026-04）将 `tcp_ecn` 默认改为 5**——服务器端默认接受 AccECN 协商；文稿处于 RFC Editor 队列。**推断**：随 Linux 7.0 铺开，"被动端支持 AccECN"将成为常态，主动端（客户端）开启仍需显式配置；抓包中 SYN 的 AE/CWR/ECE 位组合将出现新形态，老工具可能误读——升级 Wireshark。
**来源**：LWN, https://lwn.net/Articles/1058666/ （2026）；https://lwn.net/Articles/1028208/ （2025）；draft-ietf-tcpm-accurate-ecn-34。

**【真实生产案例】Microsoft：DCTCP 数据中心部署（2012 起，RFC 8257 记载）**
**事实**：RFC 8257 记载 DCTCP 自 2012 年起部署于 Microsoft 数据中心，处理拍字节级流量；Windows Server 与 Linux 均有实现。**推断**：数据中心内部抓包见到 CE 标记密集 + cwnd 微调（而非砍半）属正常；DCTCP 流量泄漏到公网才是事故。
**来源**：RFC 8257 (2017)，https://www.rfc-editor.org/rfc/rfc8257 。

## 7. 生产排障思路

跨算法环境的性能问题四步：① 两端 `ss -ti` 指认算法；② 按算法校准预期（CUBIC：丢包敏感、Mathis 适用；BBR：看 PROBE_RTT/公平性/浅缓冲丢包；DCTCP：看 ECN 配置完整性）；③ 混跑场景查公平性（BBRv1 压制 CUBIC 是已知问题——Dropbox/学术测量均记载）；④ ECN 相关异常（协商失败、CE 被中间盒清洗）用双点抓包对比 IP ToS 字节。

## 8. 常见误判

- "重传率高=网络烂"对 BBRv1 流不成立（设计性无视丢包）。
- "吞吐周期性小凹槽"≠ 故障（BBR PROBE_RTT）。
- "没有突发"≠ 窗口小（pacing 抹平了）。
- "TCP 都一样"——2026 年同一瓶颈上可能同时有 CUBIC/BBRv1/BBRv3/Prague 四种响应函数在博弈。
- BBRv3 ≠ Linux 自带（mainline bbr 仍是 v1，树外补丁才是 v3——版本要核实）。

## 9. 练习

某视频源站丢包率 0.8%（随机、非拥塞），RTT 60ms，MSS 1448。1) CUBIC 单流吞吐量级估计？2) 换 BBRv1 预期？3) 换之前该做哪两项风险评估？4) 抓包如何验证切换生效？

**答案**：1) Mathis：1.22×1448×8/(0.06×√0.008) ≈ **2.6 Mbps** 量级——被随机丢包锁死。2) BBRv1 按带宽/RTT 建模，随机丢包 0.8% 远低于其容忍度，可接近链路可用带宽（但重传字节 ≈0.8% 照付）。3) ① 对同瓶颈 CUBIC 流的挤压（公平性）；② 浅缓冲下自致丢包率上升（Dropbox 6% 教训）。4) `ss -ti` 算法列；抓包看丢包后吞吐不再深 V、周期性 PROBE_RTT 凹槽出现。

## 10. 本章总结

2026 年的拥塞控制是"CUBIC 守成、BBR 扩张、ECN/L4S 换信号"的三线格局；分析任何 cwnd 行为前先指认算法与信号类型。至此所有单机制讲完——下一章把它们放回**同一条连接**里，看它们如何接力与联动。
