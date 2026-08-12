# 第 8 章 Congestion Avoidance 与 AIMD

## 1. 为什么需要这个机制：为什么不能永远指数增长？

Slow Start 每 RTT 翻倍。翻倍意味着：**上一轮刚好够用的网络，这一轮就被超载一倍**。当 cwnd 已接近瓶颈容量时，再翻一倍注入的过量数据 ≈ 整个 BDP，瓶颈队列必然溢出、成串丢包。所以 TCP 需要第二档变速箱：接近估计容量后，从"每 RTT ×2"切换为"每 RTT +1 MSS"，用微小步长贴着容量边缘行走——这就是 Congestion Avoidance（CA）。

## 2. 没有它会发生什么

只有 Slow Start 的 TCP 是"冲撞式"探测：涨到丢包 → 腰斩 → 再指数冲到丢包。丢包事件高频发生，吞吐呈剧烈锯齿，瓶颈队列反复被打爆，殃及共享链路的所有流。

## 3. 核心原理

### 3.1 ssthresh：两档之间的换挡点

**ssthresh（slow start threshold）的语义：TCP 记住的"上次出事时的安全容量估计"。**

- `cwnd < ssthresh` ⇒ Slow Start（指数）。
- `cwnd ≥ ssthresh` ⇒ Congestion Avoidance（线性）。
- 每次检出丢包：`ssthresh = 当时 cwnd 的一半`（Reno；CUBIC 为 ×0.7）——把"出事点的一半（或七成）"记为下次的换挡点。

ssthresh 和 cwnd 一样是 ④ 层内核状态：抓包不可见，`ss -ti` 可见。

### 3.2 AIMD：加性增、乘性减

CA 的经典规则（Reno）：

```
每个 ACK:  cwnd += MSS × (MSS / cwnd)      → 累计一个 RTT 约 +1 MSS（Additive Increase）
检出丢包:  ssthresh = cwnd / 2;  cwnd 按恢复算法收缩（Multiplicative Decrease）
```

为什么必须是"加性增+乘性减"？Chiu & Jain（1989）证明：在多流共享瓶颈时，只有 AIMD 能同时收敛到**高效率**（总量贴容量）与**公平**（各流均分）。乘性减让占大头的流让出更多，加性增让所有流等速回填——反复几轮，份额自动趋同。

### 3.3 从 Reno 到 CUBIC（你在 2026 年实际抓到的 CA）

Reno 的 +1 MSS/RTT 在高 BDP 下太慢：100ms RTT、10 Gbps 链路，从半窗恢复到满窗需要 ~4 万个 RTT ≈ 68 分钟。CUBIC（RFC 9438，Linux/Windows/macOS 默认）用三次曲线替代线性：

```
W(t) = C × (t − K)^3 + W_max      K = ∛(W_max×β/C)
```

丢包后从 0.7×W_max 出发，先快速回升，接近上次出事点 W_max 时进入平台（小心翼翼），确认没事后再加速探索。**增长速率与 RTT 解耦**（按绝对时间 t），高 BDP 恢复快得多，RTT 公平性也更好。分析 Linux 抓包时看到"恢复后快速回升→平台→再上探"的 S 形，那是 CUBIC 不是教材里的直线——**用 Reno 模型解释 CUBIC 曲线是最常见的教材式错误**。

## 4. 关键变量

cwnd、ssthresh、W_max（CUBIC）、β（CUBIC 0.7 / Reno 0.5）、RTT。

## 5. 数学关系

```
Reno CA:  cwnd(t+RTT) = cwnd(t) + MSS
稳态锯齿平均窗口 ≈ 0.75 × W_max（Reno）
Mathis 公式: Throughput ≤ (MSS/RTT) × (C/√p)   C≈1.22，p=丢包率
```

Mathis 公式（第 19 章验证实验）说明：**丢包率决定了 loss-based CA 能维持的窗口上限**——p=0.01% 与 p=1% 的吞吐差 10 倍。

## 6. 数值案例：SS→CA 切换与一次完整锯齿 【教学模拟案例】

MSS=1460，RTT=40ms，ssthresh=300 段（前次丢包遗产），rwnd 充足，Reno：

| RTT 轮 | 阶段 | cwnd(段) | 增量 |
|---:|---|---:|---|
| 1 | SS | 10 | ×2 |
| 2 | SS | 20 | ×2 |
| 3 | SS | 40 | ×2 |
| 4 | SS | 80 | ×2 |
| 5 | SS | 160 | ×2 |
| 6 | SS→CA | 320→**300 封顶后转 CA** | 到达 ssthresh 换挡 |
| 7 | CA | 301 | +1 |
| 8 | CA | 302 | +1 |
| … | CA | … | +1/RTT |
| 107 | CA | 400 | 假设此时丢包 |
| 108 | 恢复 | ssthresh=200，cwnd≈200 | 乘性减 |
| 109+ | CA | 201, 202, … | 从新 ssthresh 直接 CA（无 SS）|

时间感受：第 7→107 轮走了 100×40ms = **4 秒**才涨 100 段——CA 的"慢"与 SS 的"快"差两个数量级。这解释了：**高 BDP 链路上一次丢包的吞吐伤害要用几秒甚至几十秒偿还**（CUBIC 缩短但不消除这个代价）。

## 7. TCP Timeline（换挡瞬间）

```
RTT n   : cwnd 160→320 (每ACK+1，一轮翻倍)      ← SS 最后一轮
RTT n+1 : cwnd 320 ≥ ssthresh=300
          此后每ACK: cwnd += 1448×(1448/cwnd字节) ← 一轮合计 ≈ +1 段
抓包表现: 簇尺寸从"每轮翻倍"突变为"每轮多一段"，I/O Graph 斜率骤降
```

## 8–13. 实验与抓包分析（EXP-01 延长版）

无丢包环境里 ssthresh 是无穷大，看不到换挡。制造一次换挡最简单的方法：先造一次丢包（netem loss 瞬时开关），让 ssthresh 有值：

```bash
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms loss 1%   # 3秒后
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms           # 关掉
```

`cwnd.log`（EXP-09 采样）预期形态：指数段 → 掉落 → 从 ssthresh 附近开始的缓坡/S 形（cubic）。Wireshark I/O Graph 上斜率同步变化。Frame 级证据：CA 段内每 RTT 簇尺寸 +1 段（用时间列按 RTT 分组数段数即可验证）。

## 14–15. ss 分析

```
cubic ... cwnd:305 ssthresh:300 ...     ← cwnd≥ssthresh：CA 阶段
cubic ... cwnd:80  ssthresh:300 ...     ← cwnd<ssthresh：SS 阶段（恢复后重爬）
```

连续采样看增速才是硬证据：Δcwnd/ΔRTT ≈ 1 段 ⇒ CA；≈ cwnd 本身 ⇒ SS。

## 16–18. 特征与指纹

**正常（长流稳态）**：cwnd 呈锯齿/CUBIC 之 S 形；周期 = 两次丢包间隔；BiF 同步。
**异常 A**：CA 里 cwnd 长期纹丝不动 ⇒ 到达 min(rwnd, BDP+队列) 封顶，或 app-limited（CUBIC 不再上探）。
**异常 B**：锯齿周期极短（秒级反复腰斩）⇒ 持续随机丢包，Mathis 公式主导吞吐 ⇒ 转第 19 章 Case 2 流程。
**不能据此判断**：cwnd 平稳 ⇒ 一切正常（可能被 rwnd 压住，见第 19 章 Case A）。

## 19–20. Filter 与 Stream Graph

Throughput Graph（Statistics → TCP Stream Graphs → Throughput）：Y 轴吞吐随锯齿波动，均值 ≈ 0.75×峰值（Reno）。Stevens 图 CA 段是近似直线（斜率=吞吐），与 SS 段的上凸加速形成肉眼可辨的拐点——**这个拐点就是 ssthresh 在图上的影子**（抓包看不到 ssthresh 的值，但看得到它的效果）。

## 21. 2025–2026 真实业务应用

一切长流：对象存储 GET/PUT、数据库备份跨区复制、视频源站回源、大模型权重分发。工程上"长流吞吐"由三要素锁定：`min(rwnd, cwnd_稳态)/RTT`，其中 cwnd 稳态由丢包率经 Mathis/CUBIC 响应函数决定——所以跨国专线 0.1% 的"轻微"丢包足以让单流吞吐掉一个数量级（第 19 章实测）。

## 22–23. 真实生产案例与证据链

**【真实生产案例】CUBIC 成为三大操作系统默认并标准化（RFC 9438，2023；2026 年仍为 Linux 默认）**
**事实**：RFC 9438（2023-08，Standards Track）记载：CUBIC 已被 Linux、Windows、Apple 栈采为默认 TCP 拥塞控制，"currently the most widely deployed standard for TCP congestion control"；其前身 BIC 2005 年即为 Linux 默认。截至 2026-08，Linux mainline 默认仍为 CUBIC（BBRv3 未合入 mainline，见第 14 章）。**推断**：没有额外信息时，把 2026 年抓到的服务器流量按 CUBIC 行为解读是最合理的默认假设——但仅是假设，`ss -ti` 第一列一秒就能证实/证伪，别省这一步。
**案例来源**：RFC 9438, https://www.rfc-editor.org/rfc/rfc9438 ；google/bbr README（BBRv3 树外状态），https://github.com/google/bbr/blob/v3/README.md 。

## 24. 生产排障思路

长流吞吐不达标：① `ss -ti` 确认算法与 cwnd 稳态值；② 吞吐≈cwnd×MSS/RTT 是否自洽（自洽 ⇒ 问题就在 cwnd 上不去）；③ 查 retrans 增速，估 p，代入 Mathis 看是否解释得通；④ 解释得通 ⇒ 转"丢包在哪"（第 20 章双点法）；解释不通 ⇒ 查 rwnd/pacing/队列 RTT 膨胀。

## 25. 常见误判

- 把 CUBIC 的 S 形恢复当成"两次丢包"（平台期不是二次降窗）。
- 用 Reno 的 0.5 系数去核对 Linux 抓包（CUBIC 是 0.7）。
- cwnd 不涨 ≠ 算法故障（app-limited 时 CUBIC 冻结上探是设计行为）。
- "CA 阶段" ≠ 不会再 Slow Start（RTO 会把你打回去；idle 重置也会）。

## 26. 与其他机制联动

ssthresh 是丢包事件写给未来的备忘录：Fast Recovery（第 11 章）设置它，下次 SS 在它处换挡。CA 的+1 与恢复的×0.5/0.7 合成 AIMD 锯齿——第 15 章大联动的主旋律。ECN/AccECN（第 14 章）允许"不丢包也减窗"，把锯齿变得更温和。

## 27. 分析练习

`ss` 连续采样（每 1s）：`cwnd:100 ssthresh:1e9` → `cwnd:800` → `cwnd:801`？？？→ `cwnd:420 ssthresh:560` → `cwnd:430` → `cwnd:445` → `cwnd:452`。RTT=50ms，cubic。1) 第 1→2 秒处于什么阶段？2) 第 2→3 秒之间发生了什么（两件事）？3) 3→7 秒的增长形态说明什么？4) ssthresh:560 是怎么来的？

## 28. 详细答案

1) SS（cwnd≪ssthresh 且秒级从 100→800，指数量级）。2) ① 到达/越过某个容量点后发生丢包检出；② 执行乘性减：cwnd 420 ≈ 800×0.525、ssthresh=560=800×0.7——0.7 是 CUBIC 的 β，420 低于 560 是 PRR 恢复过程的中间态（第 11 章）。3) 每秒 +10~15 段、先快后慢 ⇒ CUBIC 恢复段（快速回升趋向 W_max=800 前的平台），不是 Reno 直线。4) 丢包时 cwnd=800，×0.7=560。

## 29. 本章总结

ssthresh 是换挡点，AIMD 是公平与稳定的数学保证，CUBIC 是 2026 年你实际面对的 CA。至此 cwnd 的"涨"讲完了；接下来三章讲"跌"——网络怎么告诉你丢包了（第 9 章），你怎么快速补救（第 10 章），以及补救期间窗口怎么管理（第 11 章）。
