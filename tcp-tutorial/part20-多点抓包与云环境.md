# 第 20 章 多点抓包与云环境抓包限制

## 1. 为什么需要多点抓包

单点抓包能回答"有没有丢包、谁在重传"，**永远回答不了"丢在哪一段"**——发送侧 pcap 里被丢的包好好躺着（它是出主机之后丢的），接收侧 pcap 里它压根不存在（到达之前就丢了）。要定位丢包位置，必须在路径的多个点同时抓，然后**用 Sequence Number 追踪同一个 Segment 在每个点的存亡**。

## 2. 方法论：Seq 追踪法

拓扑与抓包点：

```
Sender ──[A: Sender主机/Tap]── Firewall(inside) ──[B: FW外侧镜像]── WAN ──[C: Receiver侧]── Receiver
```

步骤：

1. **对齐流**：四元组 + 原始 Seq（`tcp.seq_raw`，相对序号在不同 pcap 中可能不同！）。若 NAT 改了地址端口，用 raw Seq + IP ID + Timestamps(TSval) 三重对齐。
2. **对齐时钟**：各点 NTP/PTP 同步；否则用同一报文在两点的出现做相对校准（只比先后与存亡，不比绝对时刻）。
3. **逐段核对存亡**：

| Segment (raw seq) | A 点 | B 点 | C 点 | 结论 |
|---|---|---|---|---|
| 1000-2459 | ✅ | ✅ | ✅ | 全程存活 |
| 2460-3919 | ✅ | ✅ | ❌ | **丢在 B→C（WAN 段或 C 侧接入）** |
| 3920-5379 | ✅ | ❌ | ❌ | **丢在 A→B（防火墙或内侧链路）** |

4. **双向都要查**：数据段全程存活但发送方仍重传 ⇒ 查 ACK 方向。`Receiver 发出的 Ack=3920 在 C 有、B 有、A 没有 ⇒ ACK 丢在 B→A`——数据路径无辜，**重传的根因在回程**。这类"ACK Path Loss"只有多点抓包能实锤。
5. **量化**：对每段路径统计"进入N个/存活M个"，得出分段丢包率，与设备计数器（接口 drops、防火墙 deny 日志）交叉验证。

tshark 自动化骨架：

```bash
for p in A B C; do
  tshark -r $p.pcap -T fields -e tcp.seq_raw -e tcp.len \
    'tcp.stream==0 && tcp.len>0' | sort -n | uniq > $p.segs
done
comm -23 A.segs B.segs   # 在A不在B ⇒ 丢于A→B
comm -23 B.segs C.segs   # 在B不在C ⇒ 丢于B→C
```

（注意先按第 18 章处理 offload：A 点巨段要按 Seq **区间**展开比较，不能按行 diff。）

## 3. 实验（EXP-12：双点抓包定位人为丢包）

附录 A 三 netns 拓扑（client—wan—server），在 wan 中 netem loss，同时在 client 侧与 server 侧 veth 抓包，跑一遍上述 comm 流程，验证"消失点"恰在 wan。这是综合案例 7 的预演。

## 4. 云环境的抓包现实（2026）

### 4.1 哪里能抓、哪里不能

| 位置 | 能否抓包 | 工具/说明 |
|---|---|---|
| 云主机(EC2/GCE/Azure VM)内部 | ✅ | tcpdump 照常（但有 offload 假象，第 18 章）|
| 容器/Pod 内 | ✅ | `kubectl debug` ephemeral container + tcpdump；或宿主机对 veth 抓 |
| 宿主机(自管 K8s 节点) | ✅ | 对 cni 网桥/veth/vxlan 口抓，注意封装 |
| **云虚拟网络内部(underlay)** | ❌ 直接不可 | 用厂商流量镜像：AWS Traffic Mirroring、GCP Packet Mirroring、Azure vTAP类方案（有带宽/规格限制与费用）|
| 托管负载均衡器(ALB/NLB/云LB)内部 | ❌ | 只能两侧夹击 + LB 日志/指标 |
| Service Mesh sidecar(Envoy) | 半 | sidecar 与应用间是 localhost；Envoy 统计/access log 补位 |
| CDN 边缘 | ❌（除非你是CDN） | 用 CDN 提供的日志/Server-Timing |

### 4.2 最重要的陷阱：一条"连接"其实是多条 TCP 连接

代理型中间件（云 LB 七层模式、nginx/Envoy、Service Mesh、CDN）会**终结** TCP：

```
Client ──TCP#1── LB/Proxy ──TCP#2── Backend
```

TCP#1 与 TCP#2 是**两条独立连接**：各自独立的 Seq 空间、各自的握手/MSS/WS/SACK、各自的 rwnd/cwnd/RTT。**绝对禁止**把两侧 pcap 里的 Seq/Ack/RTT/Window 混在一起分析——"Client 的 Seq=1000 在后端找不到"不是丢包，是根本不同的连接。正确做法：

- 用**应用层关联键**跨段对齐：请求 URL+时间、`X-Request-ID`、TLS SNI+时间窗。
- 分别对 TCP#1、TCP#2 做完整的单流分析，再在应用层拼接时序（哪一段贡献了延迟）。
- 注意背压传导：Backend 慢 ⇒ Proxy 缓冲填满 ⇒ Proxy 对 Client 收缩 rwnd/Zero Window——**表面是"LB 不给力"，根因在后端**（综合案例 5 的常见变体）。

而**四层透传型** LB（DSR、部分 NLB 模式、L4 ECMP）不终结连接，Seq 全程一致，可以做端到端 Seq 追踪——**先弄清 LB 的工作模式，再决定分析方法**。

### 4.3 NAT/隧道的对齐要点

SNAT 改五元组但不改 Seq ⇒ raw Seq 仍可对齐；VXLAN/Geneve/IPIP 封装 ⇒ 抓外层后用 Wireshark 解封装（Decode As），内层四元组+Seq 照常对齐；conntrack 表满是云上经典"随机丢新建连接"来源（`nstat` / `conntrack -S` 查 insert_failed）。

## 5. 生产排障思路（值班版）

跨段丢包定位的资源排序：① 先用两端主机 pcap 夹击（成本最低）确定丢包方向与量级；② 需要更细分段再申请云流量镜像/交换机镜像（有费用与配额）；③ 中间设备只有计数器时（防火墙/LB），用两侧 pcap 的分段丢包率与设备计数器做一致性核对；④ 七层代理场景先画"连接分段图"，逐段独立分析，再按应用层键拼接。

## 6. 练习

K8s 集群：Client(公网) → 云 L7 LB → Ingress(nginx) → Pod。用户报"上传大文件卡住"。你在 Pod 内抓包看到：Pod 与 Ingress 之间的连接一切正常，但 Ingress 定期向 Pod 通告 Window 很小甚至 0。1) 能否结论"Pod 有问题"？2) LB 与 Client 之间的 TCP 状态你能从这个 pcap 看到吗？3) 给出完整的定位路径。

**答案**：1) 恰恰相反：**Ingress 作为"接收方"向 Pod 收缩窗口**，说明 Ingress 的上行缓冲堆积——但注意方向：上传场景数据流向是 Client→LB→Ingress→Pod，若是 Ingress→Pod 段 Ingress 收缩窗口，收数据的是 Pod……本题里 Ingress 通告小窗给 Pod，仅当 Pod→Ingress 方向有数据（如响应/回执）才有意义，需先确认哪个方向的数据流被卡（Conversations 看字节方向）。2) 看不到——Client↔LB 是另一条 TCP 连接，Pod 内 pcap 完全无它的信息。3) 分段夹击：(a) Pod 侧 pcap 判定 Ingress↔Pod 段的窗口/重传健康度；(b) Ingress 上同时抓上下游两条连接，看是"下游收不动导致上游缓冲堆积"还是 Ingress 自身瓶颈（CPU/磁盘缓冲）；(c) LB 前（Client 侧或 LB 日志）判定公网段 RTT/丢包；(d) 用 X-Request-ID/时间窗把三段串起来，找到最先出现背压的段——背压总是从最慢的一段向上游传导。

## 7. 本章总结

多点抓包用 raw Seq 追踪段的存亡，把"有丢包"升级为"丢在哪段"；云环境先画连接分段图、认清哪些位置根本不是同一条 TCP。至此方法论全部就绪——最后三章进入真实生产案例与大型综合案例。
