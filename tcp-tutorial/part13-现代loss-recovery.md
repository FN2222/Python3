# 第 13 章 现代 TCP Loss Recovery：RACK-TLP、PRR、DSACK、F-RTO

> 本章所有"现状"结论以 **2026 年 8 月**联网核验为准，来源见文中及第 21 章。

## 1. 为什么需要这一章

第 9–12 章的经典模型（3 Dup ACK + RTO）来自 1988–1996 年的互联网。而 2026 年你抓包的对端大概率是：**Linux（默认 RACK-TLP + PRR + SACK/DSACK + F-RTO）**、**FreeBSD/Netflix（RACK 栈）**或 **Windows（RACK/TLP + HyStart++）**。用旧模型读新抓包，会把一系列**设计行为**误判为异常：

- 重传出现在只有 1 个 Dup ACK 之后（RACK 时间判丢）。
- 尾丢后 ~2×SRTT 出现一个"多余"的小包（TLP 探测）。
- RTO 之后 cwnd 惩罚被"撤销"（F-RTO + DSACK 判定假超时）。

## 2. 经典模型的三大生产盲区（RFC 8985 的动机数据）

RFC 8985（2021，作者来自 Google，基于其生产测量）明确指出 Dup ACK 计数模型失效的场景：

1. **Application-limited 小飞行窗**：在途只有 1–2 段，永远凑不齐 3 个 Dup ACK。Google 测量：其 Web 服务器约 **70% 的重传靠 RTO 完成**——短流为主的真实业务中，教科书主角"快速重传"其实是配角。
2. **重传本身丢失**：计数法对"重传的重传"无能为力，只能 RTO。
3. **乱序**：固定 dupthresh 在乱序网络（无线、per-packet ECMP）中要么误判要么迟钝。

## 3. RACK：用时间取代计数（RFC 8985，Linux 默认）

核心思想一句话：**如果某段的"发送时间"早于一个已被 SACK 确认的段，且早出一个"乱序窗口"以上，那么它丢了**——不管 Dup ACK 有几个。

```
判丢条件: segment.xmit_ts < newest_sacked.xmit_ts − reo_wnd
reo_wnd 初值 = min_RTT / 4，随观测到的乱序自适应放大
```

- 依赖每段发送时间戳 + SACK；不支持 SACK 的连接退回经典模型（Netflix RACK 栈干脆把无 SACK 连接踢回默认栈）。
- 解决盲区 2：重传段也有新 xmit_ts，再丢可再判。
- 解决盲区 3：reo_wnd 自适应，乱序环境自动变保守（配合 DSACK 学习）。
- **Linux 状态（核验）**：`net.ipv4.tcp_recovery` 默认 `0x1`（RACK 启用；内核文档明确 RACK 已是唯一支持的判丢算法，该位设 0 也不会回到纯 dupthresh）。

**抓包指纹**：重传时刻 ≈ 首个揭示缺口的 SACK 到达后一个 reo_wnd（~min_RTT/4），而非死等第 3 个 Dup ACK；乱序环境下反而比经典模型更沉得住气。

## 4. TLP（Tail Loss Probe）：把尾丢从 RTO 手里抢回来

尾丢时没人制造 Dup ACK，那就**自己制造反馈**：

```
PTO ≈ 2×SRTT（在途仅1段时加 delayed-ack 余量；下限保护）
PTO 到期仍无 ACK ⇒ 发送探测包：
  有新数据 ⇒ 发一段新数据；无新数据 ⇒ 重传最高 Seq 段
探测的 ACK/SACK 回来 ⇒ RACK 据此正常判丢 ⇒ 走快速恢复而非 RTO
```

代价对比（RTT=40ms，Linux）：纯 RTO 修复尾丢 ≥208ms + cwnd 归 1；TLP ≈ 80ms + 快速恢复（cwnd 不归 1）。**Linux 状态（核验）**：`tcp_early_retrans` 默认 3（TLP 启用），内核文档：*"Tail loss probe converts RTOs occurring due to tail losses into fast recovery (RFC 8985)"*。

**抓包指纹**：流的尾部、~2×SRTT 处出现一个孤立重传/新小段，随后要么正常 ACK（虚惊：只是 ACK 慢），要么 SACK 揭缺口 + 快速恢复。**不要把 TLP 探测算进"重传率"里恐慌**——它可能探测的是根本没丢的数据（此时对端回 D-SACK）。

## 5. PRR（RFC 6937）：恢复期的平滑降窗

已在第 11 章展开：恢复期按比例把在途量滑向 ssthresh，不断流、不过冲，Linux 默认。与 RACK/TLP 的关系：RACK/TLP 决定**何时**进入恢复、补**哪些**段；PRR 决定恢复期**发多快**。

## 6. DSACK（RFC 2883）与假事件撤销

D-SACK（第 9 章 §3.4）是"重复收到"的回执，现代栈用它做两件事：
① **Eifel/撤销**：判定 Spurious Retransmission / Spurious RTO 后回滚 cwnd/ssthresh 惩罚（Linux `tcp_dsack`、undo 机制，`ss -ti` 事后可见 `dsack_dups`、nstat 的 `TcpExtTCPDSACKRecv`、`TCPSpuriousRTOs`）。
② **RACK reo_wnd 学习**：收到 D-SACK 说明刚才判丢太急（其实是乱序）⇒ 放大 reo_wnd。

## 7. F-RTO（RFC 5682）：RTO 之后的"验尸"

RTO 到期后先重传一段，然后**观察后续 ACK 的形态**：若 ACK 推进覆盖了未重传的数据 ⇒ 原数据其实在路上（RTT 突增造成的假超时）⇒ 撤销 cwnd=1 惩罚。Linux `tcp_frto` 默认启用。移动网络（RTT 秒级抖动）是它的主战场。

## 8. 各机制协作总图（2026 年 Linux 默认栈）

```
丢包发生
  ├─ 有后续SACK反馈 ──▶ RACK 时间判丢 ──▶ 快速重传 + PRR 恢复
  ├─ 尾丢/无反馈 ──▶ PTO(≈2SRTT) ──▶ TLP探测 ──▶ 反馈回来 ──▶ RACK ↑
  │                                   └─ 探测也无回音 ──▶ RTO
  ├─ RTO 发生 ──▶ F-RTO 验证 ─┬─ 真超时: cwnd=1, 重新SS
  │                           └─ 假超时: 撤销惩罚
  └─ 事后 D-SACK ──▶ undo + reo_wnd 学习
```

## 9. 实验（EXP-06 变体：观察 TLP）

```bash
# 开/关对比：关闭 TLP 观察纯 RTO（tcp_early_retrans=0），再开回 3
ip netns exec ns-client sysctl -w net.ipv4.tcp_early_retrans=0   # 对照组
# 尾丢制造法同第 12 章 EXP-06；对比两组 pcap 中修复时延：~2×SRTT vs ~RTO
# 事件计数：
ip netns exec ns-client nstat -az | grep -Ei 'TLP|SpuriousRTO|DSACK|RACK'
```

`nstat` 的 `TcpExtTCPLossProbes`、`TcpExtTCPLossProbeRecovery` 直接给出 TLP 触发/成功次数——④层证据，抓包无法直接提供。

## 10. Frame-by-Frame：一次 TLP 拯救的尾丢 【教学模拟案例·可复现】

```
No.   Time      Src  Info
901   5.0000    C    Seq=88001 Len=1448
902   5.0001    C    Seq=89449 Len=728   ← 最后一段，被丢
903   5.0402    S    Ack=89449           ← 对901的ACK；此后静默
904   5.1210    C    Seq=89449 Len=728  [TCP Retransmission]   ← ★TLP: 距903≈2×SRTT(80ms)
905   5.1611    S    Ack=90177           ← 修复。全程 121ms，且 cwnd 未归1
```

判读要点：904 的间隔（80ms）既不是 0（非 DupACK 驱动）也不是 208ms+（非 RTO）——**2×SRTT 是 TLP 的时间签名**。`nstat` 里 `TCPLossProbes+1`、若探测目标其实没丢会再看到 DSACK 计数 +1。

## 11. 特征与指纹速查

| 事件 | 时间签名 | 伴随证据 | cwnd 后果 |
|---|---|---|---|
| RACK 快速重传 | SACK 揭口后 ~min_RTT/4 | SACK 必在 | PRR→0.7×（CUBIC） |
| TLP 探测 | 静默 ~2×SRTT 后单包 | 尾部、单发 | 无（探测本身不惩罚） |
| 真 RTO | 静默 ≥rto（200ms+，退避翻倍） | 无 DupACK | cwnd=1 |
| 假超时撤销 | RTO 重传后 ACK 异常快 + D-SACK | nstat SpuriousRTOs | 惩罚回滚 |

## 12. 真实生产案例

**【真实生产案例】Netflix：自研 FreeBSD RACK 栈承载全球 CDN（2018 起，2024 年记载全量使用）**
**事实**（来源①②③）：Netflix 出资开发的 RACK 栈 2018-06 合入 FreeBSD（rS334804），特性含 RACK 时间判丢、TLP、PRR、SACK 记分板重构与突发抑制；不支持 SACK 的连接自动踢回默认栈。FreeBSD Journal（2024）：Netflix 生产**只用** RACK 栈，且以 QoE 与 CPU 指标对每代栈做 A/B 后再切默认。FreeBSD 基金会案例研究记载该栈是 Netflix Open Connect 400 Gbps 级服务器软件体系的一环。
**推断**：流媒体业务对"尾部卡顿"极度敏感，时间驱动 loss recovery 直接改善 rebuffer 指标——这是"现代 loss recovery 值多少钱"的最佳工业注脚。
**案例来源**：① https://reviews.freebsd.org/rS334804 ；② FreeBSD Journal 2024, *RACK and Alternate TCP Stacks for FreeBSD*；③ FreeBSD Foundation Netflix Case Study (2024)。

**【真实生产案例】Google→Linux：RACK-TLP 默认化（2010s→RFC 8985, 2021）**
**事实**：RACK/TLP 由 Google 工程师设计、以其生产流量验证（70% 重传走 RTO 的测量、TLP 对尾延迟的改善），先落地 Linux（TLP 3.10+，RACK 4.4+ 实验/4.18 默认），后标准化为 RFC 8985；Linux `tcp_recovery=0x1`、`tcp_early_retrans=3` 至今默认。**推断**：这是"生产先行、RFC 追认"的典型路径——分析 Linux 抓包时，RFC 8985 比 RFC 5681 更接近对端真实行为。
**案例来源**：RFC 8985；Linux ip-sysctl 文档（tcp_recovery / tcp_early_retrans 条目）。

## 13. 生产排障思路

重传相关工单先跑一遍 `nstat -az | grep -Ei 'retrans|TLP|RACK|DSACK|SpuriousRTO'`：TLP 成功多 ⇒ 尾丢频发（查最后一跳/对端 delayed-ack）；SpuriousRTO/DSACK 多 ⇒ 乱序或 RTT 抖动（查 ECMP/无线），别去查"丢包"；真 RTO 多而 TLP 少 ⇒ 成串丢包或 ACK 通路问题。**计数器分诊在前，抓包深挖在后**——省掉 90% 盲抓。

## 14. 常见误判

- 只有 1 个 Dup ACK 就重传 ≠ 对端疯了（RACK 时间到了）。
- 尾部"多余"小包 ≠ Bug（TLP 探测）。
- 重传率含 TLP 探测与假重传 ⇒ 直接当"网络丢包率"用会高估。
- Windows/FreeBSD/老安卓行为各异：**先指认栈，再套模型**（本教程铁律 2）。

## 15. 练习

某 Linux 服务器 `nstat` 一小时增量：`TcpRetransSegs 48200, TcpExtTCPLossProbes 31400, TcpExtTCPLossProbeRecovery 9800, TcpExtTCPDSACKRecv 18700, TcpExtTCPSpuriousRTOs 1200, TcpExtTCPFastRetrans 4100`。1) 真实"网络丢包修复"大约占重传的多少？2) 主要问题形态是什么？3) 下一步查什么？

**答案**：1) TLP 探测 31400 + DSACK 揭示的假重传 18700 占了大头；扣除后真丢包相关重传 ≈ 48200−31400−(部分假重传) ≈ 万级以下，且其中 FastRetrans 仅 4100 ⇒ 真丢包修复占比 <20%。2) 大量 TLP+DSACK+SpuriousRTO ⇒ **乱序/RTT 抖动主导**，不是真丢包主导；很多 TLP 探测的其实是没丢的数据（DSACK 回执多）。3) 查路径乱序源（per-packet 负载均衡、bonding、无线段）与 RTT 抖动（`ss -ti` rttvar、tcptrace RTT 图），而不是通知运营商"丢包"。

## 16. 本章总结

2026 年的 loss recovery = RACK（时间判丢）+ TLP（尾丢抢跑）+ PRR（平滑降窗）+ DSACK/F-RTO（假事件撤销），RTO 只是最后防线。下一章把同样的"现代化校准"应用到拥塞控制算法本身：CUBIC、BBR、ECN/AccECN 与 L4S。
