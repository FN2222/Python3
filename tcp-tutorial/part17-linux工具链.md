# 第 17 章 Linux 工具链：ss / tcpdump / tshark / nstat / eBPF

## 1. 本章定位

抓包看不到的④层数据（cwnd、ssthresh、RTO、缓冲、pacing、内核丢包点），这里逐一给出获取工具、输出解读与"什么时候必须换这个工具"。

## 2. ss：TCP Stack 的仪表盘

### 2.1 常用形态

```bash
ss -tn                      # 连接 + Recv-Q/Send-Q
ss -tnm                     # + 内存 skmem
ss -ti                      # + TCP 内部信息（本教程主力）
ss -ti dst 10.0.0.2         # 过滤对端
ss -ti sport = :443         # 过滤本端端口
watch -n 0.2 'ss -ti dst 10.0.0.2'   # 粗粒度追踪
```

### 2.2 `ss -ti` 全字段对照（Linux iproute2）

```
cubic wscale:7,7 rto:248 rtt:44.1/0.9 ato:40 mss:1448 pmtu:1500 rcvmss:1448
advmss:1448 cwnd:300 ssthresh:256 bytes_sent:52428800 bytes_retrans:8688
bytes_acked:51989201 bytes_received:376 segs_out:36240 segs_in:18113
data_segs_out:36211 send 79.7Mbps lastsnd:2 lastrcv:1224 lastack:2
pacing_rate 95.6Mbps delivery_rate 78.9Mbps delivered:35907 busy:2244ms
rwnd_limited:12ms(0.5%) sndbuf_limited:0ms unacked:299 retrans:1/6 lost:1
sacked:118 dsack_dups:2 rcv_rtt:40 rcv_space:65535 rcv_ssthresh:512000
notsent:2896000 minrtt:40.0
```

| 字段 | 含义 | 排障用法 |
|---|---|---|
| `cubic` | 拥塞算法 | 一切分析的前提 |
| `wscale:7,7` | snd,rcv 缩放因子 | 对照抓包 Calculated |
| `rto:248` / `backoff:` | 当前RTO/退避次数 | 空洞时长核对（第12章） |
| `rtt:44.1/0.9` | SRTT/RTTVAR | 与 tcptrace RTT 图互证 |
| `minrtt:40.0` | 最小RTT | rtt−minrtt = 排队时延（bufferbloat 测量）|
| `cwnd:300 ssthresh:256` | ④层核心 | SS/CA/恢复阶段判定 |
| `unacked:299` | 在途段数 | ≈BiF；贴cwnd=cwnd受限 |
| `retrans:1/6` | 在途/累计重传 | 增速=丢包率线索 |
| `lost/sacked/dsack_dups` | 记分板状态 | 恢复期解剖（第11、13章）|
| `rwnd_limited:12ms(0.5%)` | **被对端窗口卡住的累计时长** | rwnd受限的直接内核判决 |
| `sndbuf_limited:` | 被本端发送缓冲卡住时长 | 调 tcp_wmem 的依据 |
| `busy:` | 有数据要发的总时长 | 上两项的分母 |
| `pacing_rate / delivery_rate` | 计划/实测速率 | BBR 分析主粮 |
| `notsent:` | 应用已写未发 | >0 排除应用瓶颈 |
| `app_limited` | 应用受限标记 | 出现⇒吞吐低先怪应用 |

**`rwnd_limited` / `sndbuf_limited` / `busy` 三件套值得单独强调**：内核直接告诉你这条流的时间花在哪种等待上——第 19 章三种慢速场景的终审证据。

### 2.3 什么时候必须用 ss 而不是 Wireshark

cwnd/ssthresh 判定（④层）；恢复阶段解剖；rwnd/sndbuf 受限时长；pacing/delivery_rate；RTO 与退避——以上抓包全都给不出或只能间接猜。

## 3. tcpdump：生产服务器的标准抓包器

```bash
tcpdump -i eth0 -w cap.pcap -s 128 'tcp port 443 and host 10.1.2.3'
#                              ^^^ snaplen 只留头部：高速链路防 drop 的关键
tcpdump -i any -c 100000 -w cap.pcap 'tcp[tcpflags] & (tcp-syn|tcp-rst) != 0'
# 结束时必看:
# "N packets dropped by kernel"  → 非零 ⇒ 本pcap的重传/缺口结论全部降级
```

要点：① 过滤器尽量收窄（BPF 在内核态执行，代价低）；② `-s 96~128` 抓头即可做 Seq/Ack 分析（TLS 载荷反正加密）；③ 轮转 `-C 100 -W 10` 防磁盘写满；④ `-i any` 会丢失 VLAN/方向细节，定位物理口问题时指定接口。

## 4. tshark：批量统计与脚本化

```bash
# 每秒重传数
tshark -r cap.pcap -q -z io,stat,1,'COUNT(tcp.analysis.retransmission)tcp.analysis.retransmission'
# 导出字段做离线分析（本教程画 BiF/RTT 曲线的方法）
tshark -r cap.pcap -T fields -e frame.time_epoch -e tcp.seq -e tcp.ack \
  -e tcp.analysis.bytes_in_flight -e tcp.analysis.ack_rtt 'tcp.stream==0' > flow.tsv
# 会话摘要 / 专家信息汇总
tshark -r cap.pcap -q -z conv,tcp        tshark -r cap.pcap -q -z expert
```

## 5. nstat / netstat -s：主机级 TCP 事件计数器

```bash
nstat -az | grep -Ei 'retrans|TCPLossProbe|DSACK|SpuriousRTO|TCPFastRetrans|ListenDrops|PruneCalled|RcvCollapsed'
```

第 13 章的分诊法基于它：TLP/DSACK/SpuriousRTO 的比例几分钟内区分"真丢包 vs 乱序抖动"。`TCPRcvCollapsed` 正是 Cloudflare 延迟尖峰案例的关键计数器（第 21 章 R2）；`ListenDrops`/`ListenOverflows` 则指向 accept 队列溢出（常被误报为"网络丢包"）。

## 6. eBPF / BCC / bpftrace：内核内的显微镜

**为什么 Wireshark 不够**：抓包发生在协议栈边缘的 tap 点。丢在**内核里**（qdisc 满、conntrack 表满、内存压力、防火墙规则）的包，tcpdump 可能根本看不见或看见了但不知道为何被丢；重传**决策瞬间**的内核状态（cwnd、状态机）抓包只能事后推断。

```bash
# BCC 工具箱（多数发行版 bcc-tools 包）
tcpretrans -l          # 每次重传/TLP：时刻、四元组、tcp状态 —— 重传的"为什么"现场
tcpdrop                # 每次内核丢包：调用栈+四元组 —— 丢在内核哪一行
tcprtt / tcpconnlat    # RTT 直方图 / 建连延迟
tcplife               # 每连接生命周期摘要（时长、字节、重传）

# bpftrace 一行式：谁在触发RTO？
bpftrace -e 'kprobe:tcp_retransmit_timer { printf("%s %d\n", comm, pid); }'
# tracepoint 版本（内核≥4.16 更稳定）：
bpftrace -e 'tracepoint:tcp:tcp_retransmit_skb { @[args->saddr, args->daddr] = count(); }'
```

适用判据：**"包去哪了"在主机内 ⇒ eBPF；在主机外 ⇒ 多点抓包（第 20 章）**。长期低开销监控（全量抓包不可行的 40G+ 链路）也属 eBPF 场景。

## 7. 工具选择决策树

```
问题症状
 ├─ 要看报文字段/顺序/时序 ────────── tcpdump 抓、Wireshark 看、tshark 批量
 ├─ 要看 cwnd/ssthresh/rto/受限时长 ── ss -ti
 ├─ 要看缓冲/队列占用 ──────────────── ss -tnm / Recv-Q Send-Q
 ├─ 要看主机级事件比例(分诊) ───────── nstat
 ├─ 要知道内核为什么丢/何时重传 ────── BCC tcpdrop / tcpretrans / bpftrace
 └─ 要定位路径上哪一跳丢包 ─────────── 双点抓包 + Seq 追踪（第20章）
```

## 8. 练习

服务 A 调用服务 B 偶发 1s 超时。已有证据：A 侧 pcap 显示偶发 SYN 重传（1s 间隔）；B 侧 pcap 在对应时刻**看不到那些 SYN**；B 主机 `nstat` 显示 `TcpExtListenDrops` 持续增长。1) SYN 重传为什么恰好 1s？2) B 侧 pcap 看不到 SYN 是否说明网络丢包？3) ListenDrops 指向什么根因？4) 用哪个 eBPF 工具最后钉死？

**答案**：1) SYN 的初始 RTO 为 1s（RFC 6298），首次重传固定 ~1s——SYN 阶段无 RTT 样本。2) 不一定，此处恰恰相反：tcpdump 在 B 上通常抓于驱动之后、协议栈之前，**accept 队列满时内核丢弃发生在栈内，SYN 仍应被抓到**；若 B 侧确实没抓到，需先排除抓包过滤/镜像问题，而 ListenDrops 增长说明至少有一部分 SYN 到达后被栈丢弃。3) accept 队列（somaxconn/backlog）溢出：应用 accept() 不及时或突发连接洪峰——是**应用/配置问题不是网络丢包**。4) `bpftrace tracepoint:tcp:tcp_listendrop`（或 BCC `tcpdrop` 看丢弃调用栈），可逐事件打印被丢 SYN 的四元组，与 A 侧超时时刻一一对上，证据链闭合。

## 9. 本章总结

ss 管状态、tcpdump/tshark 管报文、nstat 管比例、eBPF 管内核现场。但所有主机侧抓包都有一个共同的失真源——网卡 offload。下一章专门拆它。
