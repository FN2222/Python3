# 两台 H3C 直连：IPv6 ping 丢包排查手册

结论先行：**直连两台 H3C 互 ping IPv6 丢包，多数不是光纤/网线坏了。**  
先看丢包形态，再决定要不要动物理层。

| 丢包形态 | 优先判断 | 是不是故障 |
| --- | --- | --- |
| 只丢第 1 个包，马上再 ping 全通 | ND 邻居解析首包被丢 | 否，IPv6 正常机制 |
| 扫很多个陌生 IPv6，每个地址大约丢 1 个 | 每个新邻居都要做一次 ND | 否 |
| 连续 ping 对端本机 IPv6，随机/规律丢几个；过交换机的业务不丢 | 控制平面 ICMP 低优先级 + CPU 防护限速 | 多数情况下否 |
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
   `ping ipv6 fe80::<对端> GigabitEthernet1/0/24`  
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
display ipv6 neighbors GigabitEthernet 1/0/24 verbose
```

| 状态 | 含义 |
| --- | --- |
| REACH | 正常可达 |
| STALE | 老化未确认，下一包会探测，一般仍能转发 |
| DELAY / PROBE | 正在做 NUD |
| INCMP | 解析没完成。持续 INCMP 才是故障 |

处理：

- 业务不受影响，可以不管。
- 测链路时先 ping 3 个包预热，再看后续统计。
- 互联口很少几个邻居时，可写静态 ND（生产慎用，MAC 变了会黑掉）：

```text
system-view
ipv6 neighbor 2001:db8:12::2 001e-xxxx-xxxx GigabitEthernet 1/0/24
```

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
ping ipv6 fe80::xxxx GigabitEthernet 1/0/24
```

链路本地不通：先查二层、STP、是否 shutdown、是否配了丢 NS/NA 的 ACL。  
链路本地通、全球单播不通：查地址是否同网段、是否配成了 /128 却当直连用、本机策略。

### 4.4 ND 表

```text
display ipv6 neighbors all
display ipv6 neighbors entry-limit
display ipv6 neighbors count
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
ping ipv6 -c 20 fe80::<对端> <出接口>
```

再补三句话：

- IPv4 同链路丢不丢
- 穿过这对口的主机 IPv6 丢不丢
- 丢包是「仅首包 / 随机 / 固定地址」哪一种

---

## 相关文件

- [commands.md](commands.md) — 复制即用的命令清单（按场景分组）
