# 两台 H3C 直连：IPv6 ping 丢包排查手册

结论先行：**直连两台 H3C 互 ping IPv6 丢包，多数不是光纤/网线坏了。**  
先看丢包形态，再决定要不要动物理层。

| 丢包形态 | 优先判断 | 是不是故障 |
| --- | --- | --- |
| 只丢第 1 个包，马上再 ping 全通 | ND 邻居解析首包被丢 | 否，IPv6 正常机制 |
| 能 ping 通，GUA 邻居一直 STALE，同 MAC 的 FE80 是 REACH | Echo 不刷新 NUD；STALE 仍可转发 | 否 |
| 扫很多个陌生 IPv6，每个地址大约丢 1 个 | 每个新邻居都要做一次 ND | 否 |
| 连续 ping 对端本机 IPv6，随机/规律丢几个；过交换机的业务不丢 | 控制平面 ICMP 低优先级 + CPU 防护限速 | 多数情况下否 |
| 日志 `DRVPLAT/4/SOFTCAR DROP` 且 `PktType=IPv6_ND_PASS` | ND 上 CPU 超软限速被丢，NUD 刷新失败 | 会间接造成偶发 ping 丢包 / 长期 STALE |
| 接口 CRC / error / 光功率持续异常，v4/v6 都丢 | 物理层 | 是 |
| 固定某几个地址永远丢，其它地址正常 | ND 表满、ACL、前缀长度、本机防护 | 要查配置 |
| IPv4 互 ping 不丢，只有 IPv6 丢 | ND / ICMPv6 / 本机 IPv6 策略 | 要查 IPv6 专属项 |

不要用「ping 交换机自身」去判定链路质量。  
H3C 上 **目的地址是本机 IP 的 ping 必须上 CPU**；**穿过交换机的业务走 ASIC**。两条路径完全不同。

官方社区同类案例（两台交换机互联、v6 丢包）的分流结论与上表一致：  
https://zhiliao.h3c.com/questions/dispcont/321112

---

## 0. 先花 2 分钟确认你在 ping 什么

两台设备记为 SW-A、SW-B，互联口同网段，例如：

```
SW-A  G1/0/24   2001:db8:12::1/64
SW-B  G1/0/24   2001:db8:12::2/64
```

在 SW-A 上：

```text
ping ipv6 2001:db8:12::2
```

这是 **ping 对端本机地址**，两端 CPU 都要处理 ICMP。  
它测的是「控制平面愿不愿意理你」，不是「链路转不转发」。

对照实验（按顺序做，不要跳）：

1. **同链路 IPv4**（如果有双栈）  
   `ping <对端 IPv4>`  
   v4 不丢、v6 丢 → 排除物理层，专查 IPv6。

2. **链路本地**  
   `ping ipv6 -i GigabitEthernet 1/0/24 fe80::<对端>`  
   链路本地必须带出接口。不通 = 二层/ND 有问题；通而全球单播不通 = 地址/路由/本机策略。

3. **小包**  
   `ping ipv6 -s 32 2001:db8:12::2`  
   小包通、默认包或大包丢 → MTU / jumbo，不是 ND。

4. **慢速连续 ping**  
   `ping ipv6 -c 100 -m 1000 2001:db8:12::2`  
   间隔 1 秒仍随机丢 → 更像 CPU 防护或物理错误，不像瞬时突发。

5. **穿透业务**（最关键）  
   ping **对端交换机下面某台主机的 IPv6**，或让两台主机穿过这对互联口互 ping。  
   业务不丢、本机 ping 丢 → **按设计如此，不要当链路故障去换模块。**

H3C 对 ping 本机的定位很明确：PING 用来检测连通，处理优先级低；PING 不稳不等于业务转发有问题。  
参考：http://www.h3c.com/cn/d_200711/318140_30005_0.htm

---

## 1. 形态 A：只丢首包

现象：

```text
PING 2001:db8:12::2: 56 data bytes, press CTRL_C to break
Request time out
56 bytes from 2001:db8:12::2, icmp_seq=1 ttl=64 time=1.234 ms
56 bytes from 2001:db8:12::2, icmp_seq=2 ttl=64 time=0.456 ms
```

或：对 1000 个不同 IPv6 各丢 1 个，重复 ping 同一地址不再丢。

原因：IPv6 没有 ARP。第一次去陌生地址时要先发 NS、等 NA，邻居表还没建立时，触发包常被丢掉。这是 ND 解析，不是误码。

确认：

```text
display ipv6 neighbors all
display ipv6 neighbors interface GigabitEthernet 1/0/24 verbose
```

| 状态 | 含义 |
| --- | --- |
| REACH | 正常可达 |
| STALE | 上次确认可达已经超过 ReachableTime。**MAC 仍有效，照样转发**。不是邻居挂了 |
| DELAY / PROBE | 正在做 NUD |
| INCMP | 解析没完成。持续 INCMP 才是故障 |

H3C 官方对 `Aging` 的定义：动态表项显示 **上次可达以来经过的时间（秒）**。  
所以 GUA `State: STALE` 且 `Aging: 8705` 的意思是：这条全球单播邻居 **大约 2.4 小时没被确认过 REACH**，但表项还在，MAC 还能用。

处理：

- 业务不受影响，可以不管。
- 测链路时先 ping 3 个包预热，再看后续统计。
- 互联口很少几个邻居时，可写静态 ND（生产慎用，MAC 变了会黑掉）：

```text
system-view
ipv6 neighbor 2001:db8:12::2 001e-xxxx-xxxx GigabitEthernet 1/0/24
```

### 现场案例：能 ping 通、中间丢 1 个、GUA 一直 STALE

设备 `JiangSuHaiShang_DF_HJ_SW01_HSFDC001`，`GE1/0/22` VLAN 10：

```text
ping ipv6 2404:d6c0:3:2602:1:0:1:5
# 5 包：seq 0/1/2/4 通（RTT 约 4.0～4.7 ms），seq 3 Request time out，20% loss
# 源  ...:1:0:1:1   目的  ...:1:0:1:5

display ipv6 neighbors interface g1/0/22 verbose
# 2404:d6c0:3:2602:1:0:1:5     MAC 305f-7769-3d44  STALE  Aging 8705s
# FE80::325F:77FF:FE69:3D44     MAC 305f-7769-3d44  REACH  Aging 1069s
```

这三件事可以同时成立，而且 **STALE 不是丢包原因**。

1. **STALE ≠ 不通。**  
   RFC 4861 / H3C 都规定：STALE 只是「暂时不确定还可达」，**继续用缓存 MAC 发包**。你已经 ping 通 4/5，说明二层地址是对的。真正不通的是 INCMP（解析失败）或表项消失。

2. **ICMP Echo Reply 不会把邻居打成 REACH。**  
   NUD 只认两类「可达确认」：
   - 对端回的 **solicited NA**（你先发了 NS）
   - TCP 这类上层「正向进展」提示（ACK）
   ping 的 Echo Reply **不算**。所以 GUA 表项的 `Aging` 不会因为 ping 成功而归零，会一直停在 STALE。截图里 8705 秒就是铁证：刚 ping 通了，上次 REACH 仍是两个多小时前。

3. **同一台设备的 GUA 和 FE80 是两条 ND 表项。**  
   MAC 相同不代表状态会一起刷新。FE80 常被 ND 自身、RA/RS、OSPFv3 hello 反复确认，所以是 REACH；GUA 只有你去 ping 它，而 ping 又不刷新 NUD，所以一直 STALE。这是正常现象，不是表坏了。

4. **这次丢的不是「ND 首包」。**  
   首包 seq=0 已经通了，挂的是中间的 seq=3，RTT 稳定在 4ms。这是 **ping 对端本机地址、ICMP 上 CPU** 的典型样子（见下一节），5 包里丢 1 个统计上也会显示成 20%。不要按 20% 去判断链路误码。

建议接着做（用来证明，不是为了把 STALE 改成 REACH）：

```text
# 1) 加大样本，看真实丢包率，别用 5 包
ping ipv6 -c 100 -m 200 2404:d6c0:3:2602:1:0:1:5

# 2) ping 同一台设备的链路本地，对照丢包率
ping ipv6 -c 100 -m 200 -i GigabitEthernet 1/0/22 FE80::325F:77FF:FE69:3D44

# 3) 想看到 GUA 变成 REACH：清空后再 ping，立刻 display（大约 30 秒内会回到 STALE）
reset ipv6 neighbors interface GigabitEthernet 1/0/22
ping ipv6 -c 5 2404:d6c0:3:2602:1:0:1:5
display ipv6 neighbors interface GigabitEthernet 1/0/22 verbose

# 4) 穿透业务：ping 对端下面主机的 IPv6。业务不丢就不要换模块
display interface GigabitEthernet 1/0/22
display cpu-defend statistics
display ipv6 icmp statistics
```

不要为了「表项好看」去改 `ipv6 nd reachable-time` 或关 CPU 防护。STALE 长期存在、MAC 不变、业务通，就让它 STALE。

---

## 2. 形态 B：互 ping 本机 IPv6 随机丢，业务不丢

这是 H3C 直连互 ping **最常见**的「假故障」。

机制：

1. Echo Request 目的是交换机自身 → 上送 CPU。
2. ICMP 在控制平面里优先级低于 OSPF/BFD/ARP/ND。
3. `cpu-defend` / `qos cpu-car` 对 ICMPv6 有默认 CAR。超速直接丢。
4. CPU 并不忙（比如 10%）也可能丢：高优先级协议报文插队，ICMP 在低优先级队列里被挤掉。

所以会出现：本机 ping 丢 1%～10%，时延抖动；下面主机互 ping 0 丢、时延稳定。

### 2.1 取证（先看再改）

两台都做：

```text
display cpu-usage
display interface GigabitEthernet 1/0/24
display ipv6 icmp statistics
display current-configuration | include icmp
```

CPU 防护命令 **按平台分家，不要混华为 CE 的语法**：

```text
# Comware 中高端常见
display cpu-defend statistics
display cpu-defend car software
display cpu-defend car icmpv6 software

# 部分园区交换机
display qos cpu-car
display qos-car

# 攻击防范
display attack-defense statistics
display attack-defense flood statistics ipv6
```

本机命令不存在就换下一条，以 `?` 和当前版本为准。

看什么：

- `cpu-defend` / `qos cpu-car` 里 **icmpv6 / icmp 的 Drop 计数是否在涨**。
- `display ipv6 icmp statistics` 里 echo request / echo reply 是否不对等，有无 `ratelimited`。
- 接口 **CRC、input error、output error 是否为 0**。为 0 就先别怀疑模块。

### 2.2 处理原则

1. **业务转发正常 → 不要为了 ping 漂亮去关 CPU 防护。**
2. 只是测试需要更稳的 ping，优先开硬件快回（支持的平台）：

```text
system-view
ipv6 icmpv6 fast-reply enable
display ipv6 icmpv6 fast-reply statistics
```

   开启后 Echo 由转发芯片直接回，少走 CPU。默认是关的。

3. 确认是 CAR 丢包、又确实需要提高本机 ping 稳定性时，**只上调 icmpv6，不要 undo 整个 cpu-defend**。示例（中高端，slot 按实际改）：

```text
system-view
cpu-defend car icmpv6 software pps 500 slot 1
display cpu-defend car icmpv6 software slot 1
```

   园区交换机常见是 `qos cpu-car`，语法不同，先 `display qos cpu-car` 再改。

4. IPv4 上有人会配 `ip icmp rate-limit echo 1000`。  
   IPv6 对应的 `ipv6 icmpv6 error-interval` **只管 ICMPv6 差错报文，不管 Echo**，改它解决不了 ping 丢包。

### 2.3 S5130S-28S-EI / Comware 7.1.070 R6328：不要「关闭」，只覆盖 ICMPv6 限速

这台机器没有中高端的 `cpu-defend`，CPU 防护是 **控制平面预定义 QoS 策略**。  
官方行为：预定义策略缺省生效，**没有关闭/删除命令**。`undo qos apply policy` 只能撤掉你自己加的策略，预定义会回来。

先看再改：

```text
display qos policy control-plane pre-defined
display qos policy control-plane slot 1
if-match control-plane protocol ?
```

记下两件事：协议名是 `icmp6` 还是 `icmpv6`；限速单位是 `pps` 还是 `kbps`。S5130 系列命令参考里是 `icmp6`。

只放开 ICMPv6（测试用，测完必须撤）：

```text
system-view
traffic classifier ICMP6 operator or
 if-match control-plane protocol icmp6
quit
traffic behavior ICMP6
 car cir 10240
quit
qos policy ICMP6-LOOSE
 classifier ICMP6 behavior ICMP6
quit
control-plane slot 1
 qos apply policy ICMP6-LOOSE inbound
quit
```

`car cir 10240` 的单位跟预定义表一致。若 `display` 里是 `(pps)`，这就是 10240 pps；若是 `(kbps)` 就是 10240 kbps。本机用 `car cir ?` 看允许的最大值，能开多大开多大。`if-match` 报错就改成 `icmpv6`。

独立设备一般是 `slot 1`。IRF 把 slot 换成成员号。`control-plane slot 1` 不存在就试 `control-plane`。

确认：

```text
display qos policy control-plane slot 1
ping ipv6 -c 100 -m 200 <对端>
```

回退（预定义防护恢复）：

```text
system-view
control-plane slot 1
 undo qos apply policy ICMP6-LOOSE inbound
quit
undo qos policy ICMP6-LOOSE
undo traffic behavior ICMP6
undo traffic classifier ICMP6
```

不要做：

- 不要指望「一键关闭全部 CPU 防护」。预定义策略关不掉，硬关等于把 STP/LACP/ARP 的限速一起拆掉。
- 不要用 `ipv6 icmpv6 error-interval 0` 当关闭 CPU 防护，它只管差错报文。
- 5 包丢 1 个、默认 ICMPv6 限速通常是几百～两千 pps：**这点 ping 打不满 CAR**。关掉/放宽限速，seq=3 超时多半还在。那是 ICMP 上 CPU、优先级低，不是限速桶空了。

### 2.4 日志 `SOFTCAR DROP` / `IPv6_ND_PASS` 会不会让 ping IPv6 丢包

会，但是 **丢的不是 Echo 本身**，是邻居发现。和「能 ping 通、偶发超时、GUA 一直 STALE」可以对上。

现场 `JiangSuHaiShang_DF_SP_SW03_HSFDC001` 的 `GigabitEthernet1/0/24`：

```text
%DRVPLAT/4/SOFTCAR DROP: ... PktType=IPv6_ND_PASS, SrcMAC=305f-7769-4883,
Dropped from interface=GigabitEthernet1/0/24 ... TotalCnt=9425455
%DRVPLAT/4/SOFTCAR DROP: ... PktType=ARP, SrcMAC=0046-0000-4b27, ... Stage=63
%IFNET/3/PHY_UPDOWN: Physical state on the interface GigabitEthernet1/0/24 changed to down
```

怎么读：

| 字段 | 含义 |
| --- | --- |
| `SOFTCAR DROP` | 上送 CPU 的协议报文超过软件 CAR，驱动丢掉超额部分 |
| `PktType=IPv6_ND_PASS` | 丢的是 NS/NA/RS/RA 这类 ND，**不是** Echo Request/Reply |
| `PktType=ARP` | 同一口上 IPv4 ARP 也在超速被丢 |
| `TotalCnt` 到百万级 | 累计值，要看是不是还在涨，不能单凭一个大数字定故障 |
| 口 down/up | 那几秒 v4/v6 都会断，和 SOFTCAR 是另一件事 |

对应 ping 的三条路径：

1. **MAC 还在、表项 STALE：Echo 多数能通。**  
   STALE 继续用缓存 MAC 转发，所以你会看到「能 ping 通」。ND 被丢 → NUD 确认不了 → GUA **一直 STALE**。这和前面截图一致。
2. **NUD 探测那一轮：会丢 ping。**  
   STALE 超时后设备发 NS，对端回 NA。NA/NS 若被 SOFTCAR 丢掉，这一轮解析失败，对应的 Echo 就会 `Request time out`。表现为中间丢 1 个、过一会又通。
3. **表项被删掉之后：会连续丢，直到重新学到。**  
   NUD 多次失败会清邻居，接下来的 ping 要重新组播 NS，首包必丢，严重时整段不通。

同一口上很多不同源 MAC 的 ARP 被丢，说明 `G1/0/24` 不是「只有对端一台设备」的安静直连，而是带着大量主机 ARP/ND 上 CPU（对端是交换机、VLAN 网关在本机、或 ND/ARP 检测把报文复制给 CPU）。CPU 协议队列已经挤，Echo 也可能在别的队列被丢，但这条日志 **没有**打出 ICMP/ICMPv6 类型，不要把 ND 丢包数直接当成 ping 丢包数。

建议：

```text
display logbuffer reverse | include SOFTCAR
display qos policy control-plane pre-defined
display ipv6 neighbors interface GigabitEthernet 1/0/24 verbose
display interface GigabitEthernet 1/0/24
```

- `IPv6_ND_PASS` 的 `TotalCnt` 还在涨，同时 GUA 长期 STALE、ping 偶发超时 → 就是这条因果。
- 只在口 down/up 那几秒丢 → 先查链路/光模块，不是 SOFTCAR。
- 不要为了消日志去关整机 CPU 防护。先查这个口为什么有这么多 ARP/ND 上送（网关 SVI、ND snooping、对端是否在扫网）。

---

## 3. 形态 C：物理层

同时满足下面几条，才优先查线/模块：

- IPv4 和 IPv6 都丢，或接口 error 持续涨
- 换端口、换跳线后计数停止
- DOM 光功率/温度越限

```text
display interface GigabitEthernet 1/0/24
display transceiver diagnosis interface GigabitEthernet 1/0/24
display link-aggregation verbose
display stp abnormal-port
```

关注：

- `CRC`、`input errors`、`giants`、`runts`、`aborts`
- 光模块 `RxPower` / `TxPower` / `Temperature`
- 聚合组是否半活着（一条 member down，管理口还指着旧成员）
- 两端速率/双工：`Speed`、`Duplex` 必须一致（现代口基本是 full）

处理：换跳线、换端口、换模块、对端 DOM 对照。不要先改 IPv6 配置。

---

## 4. 形态 D：几乎 ping 不通，或固定地址不通

直连同网段都 ping 不通，按这个顺序，不要一上来抓包。

### 4.1 接口模式

三层 IPv6 地址只能配在 **路由口** 或 **VLAN 接口** 上。一端 `port link-mode route`、另一端还是 access/trunk，会不通。

```text
# 路由口互联（示意）
interface GigabitEthernet 1/0/24
 port link-mode route
 ipv6 address 2001:db8:12::1 64

# VLANIF 互联则两端都是 trunk，放行同一 VLAN
# IPv6 配在 Vlan-interface 上，不要配在物理口上
```

### 4.2 全局 IPv6 开关

很多 Comware 设备 **缺省不开启 IPv6 转发**。接口配了地址也不转发。

```text
system-view
ipv6
```

确认：

```text
display ipv6 interface brief
display ipv6 interface GigabitEthernet 1/0/24
```

接口 IPv6 协议态要是 UP，前缀长度两端必须一样。

### 4.3 链路本地交叉验证

```text
display ipv6 interface GigabitEthernet 1/0/24
# 记下对端 fe80::...
ping ipv6 -i GigabitEthernet 1/0/24 fe80::xxxx
```

链路本地不通：先查二层、STP、是否 shutdown、是否配了丢 NS/NA 的 ACL。  
链路本地通、全球单播不通：查地址是否同网段、是否配成了 /128 却当直连用、本机策略。

### 4.4 ND 表

```text
display ipv6 neighbors all
display ipv6 neighbors entry-limit
display ipv6 neighbors all count
display mac-address interface GigabitEthernet 1/0/24
```

- 完全没有对端条目：NS/NA 没交互（ACL、二层、接口模式）。
- 长期 INCMP：对端没回 NA，或本端丢了 NA。
- 表项打满：`neighbor-limit`，新地址解析失败，表现为「一批地址固定丢」。

刷新后再测：

```text
reset ipv6 neighbors interface GigabitEthernet 1/0/24
ping ipv6 2001:db8:12::2
```

### 4.5 ACL / 包过滤 / 本机防护

```text
display acl ipv6 all
display current-configuration interface GigabitEthernet 1/0/24
display current-configuration | include packet-filter
display current-configuration | include local-ipv6
```

临时验证（改前先备份）：

```text
interface GigabitEthernet 1/0/24
 undo packet-filter ipv6 inbound
 undo packet-filter ipv6 outbound
```

社区里有 `ipv6 local-packet permit all` 的说法，**不是所有平台都有这条命令**（S12500 / S6520X 部分版本就没有）。命令不存在时，改查 `local-ipv6 acl`、控制平面 ACL、`ipv6 icmpv6 receive enable` / `ipv6 icmpv6 send enable`。

ND 依赖 ICMPv6 类型：

| 类型 | 编号 | 作用 |
| --- | --- | --- |
| RS / RA | 133 / 134 | 路由器发现 |
| NS / NA | 135 / 136 | 地址解析、NUD |
| Echo Request / Reply | 128 / 129 | ping |
| Packet Too Big | 2 | PMTU |

ACL 如果只放行 128/129、丢掉 135/136，表现就是「ping 不通、邻居学不会」。

### 4.6 前缀长度 > /64

部分盒式/框式交换机缺省硬件路由模式只装 **IPv6 /64**。互联口写成 `/80`、`/112`、`/127` 时，表项可能不下硬件，直连 ping 异常。

```text
display current-configuration | include hardware-resource
system-view
hardware-resource routing-mode ipv6-128
```

改硬件资源模式通常要重启才生效，先看文档和当前模式再动。直连能用 /64 就用 /64。

### 4.7 MTU

IPv6 中间设备不分片。两端 MTU 不一致时，默认 56 字节 icmp 可能仍通，大包丢。

```text
ping ipv6 -s 32 2001:db8:12::2
ping ipv6 -s 1400 2001:db8:12::2
display interface GigabitEthernet 1/0/24
```

接口下对齐：

```text
interface GigabitEthernet 1/0/24
 mtu 1500
 ipv6 mtu 1500
```

---

## 5. 推荐操作顺序（现场）

两端都做，结果记下来。

1. `display version` / `display device` — 型号版本，命令才对得上。
2. `display interface` — Link/Protocol UP，error 是否涨。
3. `display ipv6 interface brief` — 地址、协议态、是否同网段。
4. 链路本地 ping → 全球单播 ping → IPv4 ping → 小包 ping。
5. `display ipv6 neighbors` — REACH 还是 INCMP。
6. 穿透业务 ping — 区分「本机控制平面」和「硬件转发」。
7. `display cpu-usage` + CPU 防护统计 — 是否 CAR 丢 icmpv6。
8. ACL / packet-filter / 本机 IPv6 策略。
9. 光模块 DOM、聚合、STP。
10. 仍不明再镜像抓包：看有没有 NS/NA，有没有 Echo Request/Reply，丢在哪一侧。

抓包过滤：`icmpv6`（Wireshark）。  
正常首包应看到：NS → NA → Echo Request → Echo Reply。  
只有 NS 没有 NA：对端没收到或没回 ND。  
有 Request 无 Reply：对端 CPU 丢了，或 Reply 被本端丢了。

---

## 6. 不要做的事

- 看到丢包就换光模块，却没看 CRC 和穿透业务。
- 生产网关掉整个 `cpu-defend` 只为了 ping 全绿。
- 用 `ipv6 icmpv6 error-interval` 去「修复」Echo 丢包。
- ping 链路本地却不指定出接口。
- 一端路由口、一端 trunk 还配 IPv6 地址。
- 把华为 CE 的 `cpu-defend policy` / `car packet-type icmpv6 pps` 原样贴到 H3C 上。

---

## 7. 给 TAC / 同事的最小证据包

```text
display version
display device manuinfo
display current-configuration
display ipv6 interface brief
display ipv6 interface <互联口>
display ipv6 neighbors all verbose
display ipv6 routing-table
display ipv6 icmp statistics
display interface <互联口>
display transceiver diagnosis interface <互联口>
display cpu-usage
display cpu-defend statistics
display acl ipv6 all
ping ipv6 -c 100 <对端全球单播>
ping ipv6 -c 20 -i <出接口> fe80::<对端>
```

再补三句话：

- IPv4 同链路丢不丢
- 穿过这对口的主机 IPv6 丢不丢
- 丢包是「仅首包 / 随机 / 固定地址」哪一种

---

## 相关文件

- [commands.md](commands.md) — 复制即用的命令清单（按场景分组）
