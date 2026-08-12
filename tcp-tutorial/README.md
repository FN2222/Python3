# TCP 滑动窗口、拥塞控制、重传机制、抓包分析与真实生产案例完整实战教程

本教程不是认证考试教材，只围绕一件事展开：

**TCP 原理 + 操作系统实现 + Wireshark/tcpdump/ss 等工具 + 抓包分析 + 性能分析 + 真实生产案例 + 故障排查。**

教程的主线是一条完整的逻辑链：

> 滑动窗口 → rwnd → cwnd → Slow Start → Congestion Avoidance → Packet Loss → Dup ACK/SACK → Fast Retransmission → Fast Recovery → RTO Retransmission → 再次恢复

学完之后，你应该能够拿到一个陌生的 TCP pcap，独立完成从"确定 TCP Stream"到"定位到底是 Client / Server / Application / LAN / WAN / Firewall / Load Balancer / Cloud Network 哪一层出问题"的完整分析（分析流程见[附录 B](appendix-b-陌生pcap分析checklist.md)）。

---

## 案例标签体系（全书强制执行）

本教程中的每一个案例都带有以下三种标签之一：

| 标签 | 含义 |
|---|---|
| 【真实生产案例】 | 来自公开、可核验的真实生产环境资料（工程团队博客、RFC、论文、官方文档），文末附"案例来源"，并区分**事实**与**分析推断** |
| 【公开实验/官方实验】 | 来自官方或学术机构公开发表的实验数据（如 Dropbox 的 BBRv2 评测、Cloudflare 的内核实验） |
| 【教学模拟案例】 | 为讲解原理而人工构造的数值推演或在实验环境（netns + tc netem）中复现的流量，**不是**生产抓包 |

**绝对禁止把教学模拟数据描述成真实生产抓包。** 凡是标记为【真实生产案例】的内容，都经过联网检索核验，来源与年份在案例末尾明确标注；如果某个机制找不到 2025–2026 年的公开可信案例，会如实使用更早的经典案例并标明真实年份，不会把老案例包装成"2026 年案例"。

时间基准：**2026 年 8 月**。所有"当前 / 现代 / 最新"的技术结论均以此时间点联网核验（核验记录见各章"案例来源"与 [第 21 章](part21-真实生产案例集.md)）。

---

## 目录

### 第一篇：数据传输的地基

| 章节 | 文件 | 核心问题 |
|---|---|---|
| 第 0 章 | [重构方案与工作流](00-重构方案与工作流.md) | 本教程是如何按 Step 1–15 工作流设计出来的 |
| 第 1 章 | [TCP 数据传输基础与 Seq/Ack](part01-数据传输基础与seq-ack.md) | 字节流如何被编号、确认 |
| 第 2 章 | [MSS 与 Window Scaling](part02-mss与window-scaling.md) | 一个 Segment 能装多少、窗口能开多大 |
| 第 3 章 | [TCP 滑动窗口](part03-滑动窗口.md) | 为什么 Stop-and-Wait 低效，窗口如何滑动 |
| 第 4 章 | [rwnd 与流量控制、Zero Window](part04-rwnd流量控制与zero-window.md) | Receiver 如何限制 Sender |
| 第 5 章 | [Bytes in Flight](part05-bytes-in-flight.md) | 线路上到底有多少未确认数据 |

### 第二篇：拥塞控制

| 章节 | 文件 | 核心问题 |
|---|---|---|
| 第 6 章 | [cwnd 与拥塞控制总览](part06-cwnd与拥塞控制总览.md) | TCP 到底允许发送多少数据：min(rwnd, cwnd) 及其局限 |
| 第 7 章 | [Slow Start](part07-slow-start.md) | 为什么不能一开始就把链路打满 |
| 第 8 章 | [Congestion Avoidance 与 AIMD](part08-congestion-avoidance.md) | 为什么不能永远指数增长 |

### 第三篇：丢包检测与恢复

| 章节 | 文件 | 核心问题 |
|---|---|---|
| 第 9 章 | [丢包检测：Duplicate ACK 与 SACK](part09-丢包检测-dupack与sack.md) | Receiver 如何"告状" |
| 第 10 章 | [Fast Retransmission](part10-fast-retransmission.md) | 如何快速发现并重传丢失数据 |
| 第 11 章 | [Fast Recovery](part11-fast-recovery.md) | 丢包后 cwnd 如何调整并继续传输 |
| 第 12 章 | [RTO 超时重传（含 FastRetx vs RTO 对比实验）](part12-rto超时重传.md) | Dup ACK 救不了的时候怎么办 |
| 第 13 章 | [现代 TCP Loss Recovery：RACK-TLP/PRR/DSACK/F-RTO](part13-现代loss-recovery.md) | 2026 年的 Linux 早已不是教科书上的 Reno |

### 第四篇：现代 TCP 与工具链

| 章节 | 文件 | 核心问题 |
|---|---|---|
| 第 14 章 | [现代拥塞控制：CUBIC/BBR/ECN/AccECN/L4S](part14-现代拥塞控制.md) | 传统教材模型 vs 2026 年现代 TCP Stack |
| 第 15 章 | [TCP 各种机制到底是怎样联动工作的（大联动）](part15-tcp机制大联动.md) | 一条连接 11 个阶段的完整推演 |
| 第 16 章 | [Wireshark TCP 分析](part16-wireshark-tcp分析.md) | Packet List、Expert Info、Stream Graphs、能看见什么看不见什么 |
| 第 17 章 | [Linux 工具链：ss / tcpdump / tshark / eBPF](part17-linux工具链.md) | 抓包看不到的 cwnd/ssthresh 用什么看 |
| 第 18 章 | [NIC Offload 与抓包误判](part18-nic-offload与抓包误判.md) | 超大 Segment、Checksum 错误的真相 |

### 第五篇：性能分析与定位

| 章节 | 文件 | 核心问题 |
|---|---|---|
| 第 19 章 | [三种"下载慢"与 rwnd-limited vs cwnd-limited 对比](part19-性能分析与对比案例.md) | 同样是慢，根因完全不同 |
| 第 20 章 | [多点抓包与云环境抓包限制](part20-多点抓包与云环境.md) | 用 Seq 在多个 pcap 中追踪同一个 Segment |

### 第六篇：真实生产与综合案例

| 章节 | 文件 | 核心问题 |
|---|---|---|
| 第 21 章 | [真实生产案例集（带来源核验）](part21-真实生产案例集.md) | Cloudflare/Dropbox/Netflix/Google/Comcast 等真实案例 + 证据链 |
| 第 22 章 | [大型综合案例 1–7](part22-大型综合案例1-7.md) | 高速下载、跨地域、CDN、移动网络、Zero Window、数据中心、多点定位 |
| 第 23 章 | [最完整综合案例（案例 8）](part23-最完整综合案例.md) | 一条 TCP 连接从建立到两次丢包恢复的全程追踪 + 完整证据链 |

### 附录

| 附录 | 文件 |
|---|---|
| 附录 A | [可复现实验环境搭建（netns + tc netem + iperf3）](appendix-a-实验环境搭建.md) |
| 附录 B | [陌生 pcap 独立分析 Checklist](appendix-b-陌生pcap分析checklist.md) |

---

## 每章统一结构

核心机制章节尽量采用统一的 29 节结构（详见各章）：

1. 为什么需要这个机制 → 2. 没有它会发生什么 → 3. 核心原理 → 4. 关键变量 → 5. 数学关系 → 6. 数值案例 → 7. TCP Timeline → 8. 实验拓扑 → 9. 如何制造这种流量 → 10. 抓包位置 → 11. Wireshark 抓包图 → 12. 图中标注 → 13. Frame-by-Frame 分析 → 14. 操作系统内部状态 → 15. ss -ti 分析 → 16. 正常特征 → 17. 异常特征 → 18. 抓包指纹 → 19. Wireshark Filter → 20. TCP Stream Graph → 21. 2025–2026 真实业务应用 → 22. 真实生产案例 → 23. 生产案例证据链 → 24. 如果在生产环境我怎么排查 → 25. 常见误判 → 26. 与其他 TCP 机制如何联动 → 27. 分析练习 → 28. 详细答案 → 29. 本章总结

## 全书铁律

1. **禁止"可以明显看到""由此可知""显然"式的结论。** 任何结论必须回答：为什么？根据哪个 Frame？根据哪个字段（Seq / Ack / SACK / Window / Time Delta / RTT / Bytes in Flight / ss 中的 cwnd）？
2. **不把现代 TCP 简化成 Reno。** 分析真实案例前必须先确认操作系统、Kernel、拥塞控制算法与 Loss Recovery 机制。
3. **明确区分五层可见性**：协议层概念（rwnd）/ TCP Stack 内部状态（cwnd、ssthresh）/ Wireshark 直接可读字段 / Wireshark 推导数据 / 仅靠抓包无法得到的数据。
4. **每个真实案例必须区分"来源明确提供的事实"与"根据公开信息进行的技术推导"。**
