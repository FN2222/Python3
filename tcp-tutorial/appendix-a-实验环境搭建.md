# 附录 A 可复现实验环境搭建（netns + tc netem + iperf3）

> 全书所有【教学模拟案例·可复现】基于本附录环境。单台 Linux（物理机/VM/云主机均可，需 root）即可完成，不需要真实广域网。

## A.1 环境要求

- Linux 内核 ≥ 5.10（建议 6.x；观察 AccECN 需 ≥6.15/7.0）
- 软件包：`iproute2 tcpdump iperf3 wireshark(或tshark) iptables ethtool`；可选 `bcc-tools bpftrace gnuplot`
- 权限：root（netns/tc/iptables）

## A.2 基础拓扑（三 netns：client — wan — server）

```
ns-client(10.0.0.1) ── veth-c ↔ veth-w1 ── ns-wan(路由/损伤注入点) ── veth-w2 ↔ veth-s ── ns-server(10.0.0.2)
```

一键脚本：

```bash
#!/bin/bash
set -e
for ns in ns-client ns-wan ns-server; do ip netns add $ns; done
ip link add veth-c type veth peer name veth-w1
ip link add veth-s type veth peer name veth-w2
ip link set veth-c netns ns-client;  ip link set veth-w1 netns ns-wan
ip link set veth-s netns ns-server;  ip link set veth-w2 netns ns-wan
ip netns exec ns-client ip addr add 10.0.0.1/24 dev veth-c
ip netns exec ns-server ip addr add 10.0.0.2/24 dev veth-s
ip netns exec ns-wan ip link add br0 type bridge
ip netns exec ns-wan bash -c 'ip link set veth-w1 master br0; ip link set veth-w2 master br0
  for i in br0 veth-w1 veth-w2 lo; do ip link set $i up; done'
ip netns exec ns-client bash -c 'ip link set veth-c up; ip link set lo up'
ip netns exec ns-server bash -c 'ip link set veth-s up; ip link set lo up'
ip netns exec ns-client ping -c2 10.0.0.2   # 连通性验证
```

清理：`for ns in ns-client ns-wan ns-server; do ip netns del $ns; done`

## A.3 损伤注入（在 ns-wan 的两个口上做 netem）

```bash
W() { ip netns exec ns-wan tc qdisc "$@"; }
# RTT 40ms（两口各 20ms）
W add dev veth-w1 root netem delay 20ms
W add dev veth-w2 root netem delay 20ms
# 变更用 change；查看统计: ip netns exec ns-wan tc -s qdisc
W change dev veth-w1 root netem delay 20ms loss 0.5%            # 丢包
W change dev veth-w1 root netem delay 20ms reorder 5% gap 3     # 乱序
W change dev veth-w1 root netem delay 20ms rate 100mbit limit 100  # 瓶颈+浅队列
W change dev veth-w1 root netem delay 100ms 20ms                # 高RTT+抖动
```

注意：netem 挂在**发出**方向的口；`veth-w1` 影响 server→client 方向（下载数据向），`veth-w2` 影响回程 ACK。丢"数据"与丢"ACK"是两个不同实验——想清楚再挂。

## A.4 流量与观测三件套

```bash
ip netns exec ns-server iperf3 -s -D                       # 服务端
ip netns exec ns-client tcpdump -i veth-c -s 128 -w /tmp/exp.pcap 'tcp port 5201' &
ip netns exec ns-client bash -c 'while :; do echo "$(date +%s.%N) $(ss -ti dst 10.0.0.2 | tail -1)"; sleep 0.1; done' > /tmp/ss.log &
ip netns exec ns-client iperf3 -c 10.0.0.2 -t 15
# 真实下载流量替代 iperf3：
ip netns exec ns-server python3 -m http.server 8080 --directory /tmp &
ip netns exec ns-client curl -o /dev/null http://10.0.0.2:8080/bigfile
```

cwnd 曲线绘制：`grep -o 'cwnd:[0-9]*' /tmp/ss.log` 配合时间列，gnuplot/Python 画图；与 Wireshark I/O Graph、tcptrace 图对照。

## A.5 实验索引（与正文对应）

| 实验 | 配置要点 | 应该看到 | 没出现时检查 |
|---|---|---|---|
| EXP-01 基线 SS→CA | delay 20ms×2 | 首簇10段、逐RTT翻倍、I/O梳齿 | iperf3 是否满发；pacing（fq）平滑属正常 |
| EXP-02 高 RTT | delay 100ms | BDP 变大、爬坡以秒计 | ping 验证 RTT 生效 |
| EXP-03 小 rwnd | server `tcp_rmem="4096 16384 16384"` | WindowFull/rwnd_limited | 应用是否 SO_RCVBUF 覆盖 |
| EXP-04 Zero Window | server 收而不读（第4章脚本） | Win=0→ZWP退避→Update | 发送量是否足以填满缓冲 |
| EXP-05 单包丢失 | iptables statistic 精准丢 | DupACK×3→FastRetx→Ack大跳 | 计数器命中的是否数据包 |
| EXP-06 尾丢 | 丢最后一段（第12章） | TLP(2×SRTT) 或 RTO(关TLP后) | tcp_early_retrans 状态 |
| EXP-07 持续丢包 | loss 1~2% | 恢复锯齿、Mathis 量级 | 算法是否 cubic |
| EXP-08 乱序 | reorder 5% gap 3 | DupACK无重传/D-SACK | reorder 需与 delay 併用才生效 |
| EXP-09 cwnd 观测 | ss 0.1s 采样 | cwnd 与 BiF 曲线重合 | capture loss 体检 |
| EXP-10 算法对比 | cubic vs bbr 同剖面 | 丢包下吞吐差数量级 | modprobe tcp_bbr |
| EXP-11 offload | ethtool -K 开关 | 巨段消失/出现 | veth 默认全开 |
| EXP-12 双点+大联动 | 下方脚本 | 第15/23章全套图 | 时钟对齐、两点同时启停 |

## A.6 EXP-12：大联动/综合案例 8 复现脚本（两次丢包事件）

```bash
# 前置：A.2 拓扑 + delay 20ms×2 + rate 100mbit；两点抓包：
ip netns exec ns-client tcpdump -i veth-c -s128 -w /tmp/A.pcap 'tcp port 8080' &
ip netns exec ns-server tcpdump -i veth-s -s128 -w /tmp/D.pcap 'tcp port 8080' &
ip netns exec ns-server bash -c 'head -c 200M /dev/urandom > /tmp/bigfile'
ip netns exec ns-server python3 -m http.server 8080 --directory /tmp &
# ss 采样（server=发送方）:
ip netns exec ns-server bash -c 'while :; do echo "$(date +%s.%N) $(ss -ti sport = :8080 | tail -1)"; sleep 0.05; done' > /tmp/ss.log &
ip netns exec ns-client curl -o /dev/null --limit-rate 0 http://10.0.0.2:8080/bigfile &
CURL=$!
sleep 2   # 事件一：0.3 秒 0.8% 丢包（大概率打出单段丢失+快速恢复）
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms rate 100mbit loss 0.8%
sleep 0.3
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms rate 100mbit
sleep 1.7 # 事件二：0.25 秒 100% 丢包（必然打出 RTO；含 TLP 一并丢）
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms rate 100mbit loss 100%
sleep 0.25
ip netns exec ns-wan tc qdisc change dev veth-w1 root netem delay 20ms rate 100mbit
wait $CURL
```

复现后导出：I/O Graph（吞吐）、tcptrace/Stevens 图、Window Scaling 图、`ss.log` 的 cwnd/ssthresh 曲线、两点 pcap 的 Seq 存亡表（第 20 章脚本）——与第 15/23 章十图逐一比对。100% 丢包窗口内 TLP 探测必然同殁，RTO 指纹稳定复现；`nstat` 里可核对 `TCPLossProbes`、`TCPTimeouts` 各 +1。

## A.7 通用排错

- netem 不生效：确认挂在数据流出方向的口；`tc -s qdisc` 看计数。
- 看不到丢包效果：veth+bridge 下 offload 巨段会让 loss 百分比"按帧"生效而观感异常 ⇒ 先关 offload（EXP-11）再做丢包类实验。
- ss 采样全空：过滤表达式与方向（sport/dst）核对；连接是否已结束。
- pcap 巨段/校验错：正常（第 18 章），分析 Seq/Ack 不受影响。
