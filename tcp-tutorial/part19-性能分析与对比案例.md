# 第 19 章 TCP 性能分析：三种"下载慢"与 rwnd-limited vs cwnd-limited

## 1. 本章定位

用户只会说一句话："下载慢。"本章用三组【教学模拟案例·可复现】对照实验证明：**表现完全相同的"慢"，根因可以完全不同，而抓包+ss 能把它们干净地分开**。这是第 22–23 章综合案例的方法论热身。

## 2. 吞吐上限的三个公式（先算再查）

```
① 窗口极限:  Throughput ≤ min(rwnd, cwnd稳态) / RTT
② 丢包极限(Mathis, loss-based CC):  Throughput ≤ (MSS/RTT) × 1.22/√p
③ 链路极限:  Throughput ≤ 瓶颈带宽
实际吞吐 ≈ 三者取最小
```

拿到"慢"工单：先测 RTT、估 p、查窗口，把三个上限都算出来——**哪个公式算出的值最接近实测吞吐，哪个就是主嫌疑**。

---

## 3. 对比组一：三种慢速场景（同样 10 Mbps 实测吞吐，三种根因）

实验环境（附录 A）：瓶颈 100 Mbps。三个 Case 各自只改一个变量：

| | Case 1 高 RTT | Case 2 丢包 | Case 3 小窗口 |
|---|---|---|---|
| netem/配置 | delay 200ms | delay 20ms **loss 1%** | delay 20ms + Server `tcp_rmem max=524288` |
| RTT | 400ms | 40ms | 40ms |
| 丢包率 | 0 | 1% | 0 |
| rwnd | 8 MB | 8 MB | **512 KB→受autotune限更小** |

### 3.1 三个 Case 的抓包指纹对照

| 观测面 | Case 1 高 RTT | Case 2 丢包 | Case 3 小 rwnd |
|---|---|---|---|
| Expert Info | 干净 | 大量 DupACK/SACK/FastRetx，偶发RTO | 大量 **Window Full**，偶发 ZeroWindow |
| tcptrace 图 | 阶梯又宽又高、间隔400ms、三线平行 | 阶梯锯齿、悬空SACK块、小V坑 | 阶梯**顶着窗口线**走、每级高度=rwnd |
| RTT 图 | 400ms 平线 | 40ms+丢包时轻微抬升 | 40ms 平线 |
| Window Scaling 图 | 绿线高蓝点低但持续爬 | 绿线高蓝点锯齿 | **蓝点贴绿线** |
| BiF | 持续增长(SS要爬很多轮) | 涨→腰斩循环，均值≈Mathis窗口 | 恒≈rwnd |
| `ss -ti` 关键证据 | cwnd 持续涨、rtt:400、busy 高但无 limited | retrans 持续涨、cwnd 锯齿 | **rwnd_limited:XXXXms(9x%)** |

### 3.2 三个 Case 的"为什么"

- **Case 1**：吞吐 = 窗口/RTT，RTT×10 ⇒ 同样窗口吞吐 ÷10；且 Slow Start 每轮 400ms，爬满要十几秒——**没有任何东西坏了，物理距离在收费**。修复方向：加大窗口上限（若 rwnd 不足）、就近部署/CDN、多流并发。
- **Case 2**：Mathis：(1448×8/0.04)×1.22/√0.01 ≈ **3.5 Mbps/流**（CUBIC 稍好）。1% 的丢包让 100 Mbps 链路对单流只值几 Mbps。修复方向：找到并消除丢包（第 20 章定位），或换 BBR 类算法缓解（治标）。
- **Case 3**：512KB 缓冲折算通告 ~256-384KB；384KB/40ms ≈ 77 Mbps 看似够，但 autotune 被 max 压住实际更小；蓝点贴绿线+`rwnd_limited` 占比 90%+ 是终审证据。修复方向：调 `tcp_rmem` max / 应用 SO_RCVBUF（并警惕关掉 autotune 的副作用，第 4 章）。

**同样的"慢"，三张处方完全不同——没有指纹对照就开方，是生产网络最贵的错误之一。**

---

## 4. 对比组二：rwnd-limited vs cwnd-limited（提示词指定实验）

### Case A：Receiver Limited（rwnd 小、cwnd 充足）

配置：路径完美（20ms、无丢包），Server 接收缓冲压到 64KB。

```
抓包重点: Window Size 始终 ≈64KB 且频繁 [Window Full]，偶发 [ZeroWindow]/[Window Update]
tcptrace: 数据阶梯每 RTT 一级、每级恰好 ≈64KB、级顶撞窗口线
吞吐: 64KB/40ms ≈ 13 Mbps，纹丝不动
ss(发送侧): cwnd:800(很大) unacked:44(≈rwnd/mss) rwnd_limited:9800ms(98%)
```

### Case B：Congestion Limited（rwnd 大、cwnd 小）

配置：接收缓冲 8MB；路径 20ms + **loss 2%**（把 cwnd 打小）。

```
抓包重点: Window 字段一路显示几MB——看起来毫无问题！
         但 BiF 始终只有 ~30-60KB，且 DupACK/SACK/FastRetx 满屏
tcptrace: 窗口线高高在上，数据阶梯贴着 ACK 线小步走，两者间距(=BiF)极小
吞吐: ≈ Mathis 极限 2-4 Mbps，锯齿
ss(发送侧): cwnd:25 ssthresh:18 retrans:3/2214 unacked:24 rwnd_limited:0ms
```

### 关键教学点

> **只看 Wireshark 的 Window Size，并不能判断 TCP 一定可以发送这么多数据。**

Case B 里 Window 字段显示 8MB，但发送方每 RTT 只敢发 30KB——限制它的 cwnd 在报文里**没有任何直接痕迹**。反向也成立：Case A 里 cwnd=800 段的"雄心"在抓包里同样看不见。**rwnd 看 Wireshark，cwnd 看 ss，谁在限制看 BiF 贴谁**——这三句话是本章可以带走的全部。

### 判定速查表

| 证据 | rwnd-limited | cwnd-limited |
|---|---|---|
| BiF 贴谁 | 贴 Calculated Window | 远小于窗口、锯齿 |
| Expert Info | Window Full / ZeroWindow | DupACK / Retrans（若因丢包）|
| ss 发送侧 | rwnd_limited 时长占比高 | retrans 涨 / cwnd 小 |
| 修复方向 | 收端缓冲/应用读取 | 丢包定位 / 算法 / RTT |

---

## 5. application-limited：第三种常被漏诊的"慢"

指纹：BiF 既不贴 rwnd 也不贴 cwnd，数据呈请求-响应式稀疏簇；`ss -ti` 出现 `app_limited`，`notsent:0`，`busy` 时长远小于挂钟时间。典型场景：上游 API 慢、磁盘读慢、单线程加密瓶颈。**网络与 TCP 全部无罪**——这类工单占"下载慢"相当比例，最先排除它最省钱。

## 6. 生产排障流程图（本章总纲）

```
"慢" ──▶ ss -ti (双端若可能)
  ├─ app_limited/notsent=0 ──▶ 应用侧（结束网络排查）
  ├─ rwnd_limited 高 ──▶ 第4章流程（收端缓冲/应用读取）
  ├─ sndbuf_limited 高 ──▶ tcp_wmem/SO_SNDBUF
  ├─ retrans 增长 ──▶ Mathis 核算 ──▶ 对得上 ⇒ 丢包定位（第20章）
  └─ 全都不沾 ──▶ 算 BDP vs 窗口（Case 1 型），查 RTT 膨胀（bufferbloat: rtt−minrtt）
```

## 7. 练习

四条流的证据如下，各判定根因并给修复方向：

| 流 | RTT | 实测吞吐 | Expert Info | ss 关键字段 |
|---|---|---|---|---|
| A | 180ms | 2.9 Mbps | 干净 | cwnd:800 unacked:45 rwnd_limited:88% |
| B | 35ms | 3.1 Mbps | FastRetx×214, DupACK 满屏 | cwnd:22 retrans:2/3801 |
| C | 35ms | 3.0 Mbps | 干净、数据簇稀疏 | app_limited notsent:0 busy:900ms(挂钟60s) |
| D | 240ms | 3.2 Mbps | 干净 | cwnd:第10s才爬到400 rwnd_limited:0 sndbuf_limited:0 |

**答案**：A：rwnd-limited——45×1448/0.18≈2.9Mbps 自洽，unacked 贴的是 rwnd 折算段数而非 cwnd；修收端窗口。B：丢包压制 cwnd（Mathis 型）——22×1448/0.035≈7.3Mbps 上限、实测叠加恢复期更低；先定位丢包。C：application-limited——busy 只占挂钟 1.5%，应用 60 秒里只有 0.9 秒真有数据要发；查上游/磁盘。D：纯高 RTT + 长爬坡（Case 1 型）——两个 limited 都是 0、cwnd 还在爬，240ms 的 RTT 决定了爬升以十秒计；若业务允许加大初始窗口/复用连接/就近接入。

## 8. 本章总结

三个公式先算、三类指纹后对、ss 的 limited 三件套终审。单点证据已经够判"是谁的责任"；但"丢包到底发生在路径哪一段"，必须走出主机——下一章：多点抓包。
