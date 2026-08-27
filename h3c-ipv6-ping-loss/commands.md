# H3C 直连 IPv6 ping 丢包 — 命令清单

Comware V7 为主。框式设备把 `slot` / `chassis` 换成实际值。  
命令不存在时换下一条，不要把华为 CE 语法硬贴过来。

互联口、地址按现场替换：

```text
IFACE=GigabitEthernet1/0/24
PEER=2001:db8:12::2
PEER_LL=fe80::xxxx
```

---

## 1. 设备与接口

```text
display version
display device
display device manuinfo
display clock
display interface brief
display interface GigabitEthernet 1/0/24
display transceiver diagnosis interface GigabitEthernet 1/0/24
display link-aggregation verbose
display stp brief
display stp abnormal-port
```

---

## 2. IPv6 基础

```text
display ipv6
display ipv6 interface brief
display ipv6 interface GigabitEthernet 1/0/24
display ipv6 routing-table
display ipv6 routing-table protocol connected
display current-configuration | include hardware-resource
```

开启（两端都要，缺省经常是关的）：

```text
system-view
ipv6
interface GigabitEthernet 1/0/24
 ipv6 address 2001:db8:12::1 64
quit
```

路由口互联：

```text
interface GigabitEthernet 1/0/24
 port link-mode route
 ipv6 address 2001:db8:12::1 64
```

---

## 3. ping 对照（必须做全套）

```text
# 对端全球单播（本机控制平面）
ping ipv6 2001:db8:12::2
ping ipv6 -c 100 -m 200 2001:db8:12::2
ping ipv6 -c 100 -m 1000 2001:db8:12::2

# 指定源
ping ipv6 -a 2001:db8:12::1 2001:db8:12::2

# 小包 / 大包
ping ipv6 -s 32 2001:db8:12::2
ping ipv6 -s 1400 2001:db8:12::2

# 链路本地（必须带出接口）
ping ipv6 fe80::xxxx GigabitEthernet 1/0/24

# 同链路 IPv4（有双栈才做）
ping <peer-ipv4>
```

Windows 终端侧：

```text
ping -6 2001:db8:12::2
ping -6 -S <本机全球单播> 2001:db8:12::2
ping -6 -l 32 2001:db8:12::2
netsh interface ipv6 show neighbors
netsh interface ipv6 show route
```

Linux 终端侧：

```text
ping -6 2001:db8:12::2
ping -6 -I eth0 fe80::xxxx
ping -6 -s 32 2001:db8:12::2
ip -6 neigh
ip -6 route
```

---

## 4. ND 邻居

```text
display ipv6 neighbors all
display ipv6 neighbors all verbose
display ipv6 neighbors GigabitEthernet 1/0/24
display ipv6 neighbors 2001:db8:12::2 verbose
display ipv6 neighbors count
display ipv6 neighbors entry-limit
display ipv6 neighbors statistics all
display mac-address interface GigabitEthernet 1/0/24
```

刷新：

```text
reset ipv6 neighbors interface GigabitEthernet 1/0/24
reset ipv6 neighbors all
```

静态邻居（仅互联这种极少条目的场景，MAC 必须对）：

```text
system-view
ipv6 neighbor 2001:db8:12::2 xxxx-xxxx-xxxx GigabitEthernet 1/0/24
```

---

## 5. ICMPv6 统计

```text
display ipv6 icmp statistics
display ipv6 statistics
display current-configuration | include icmp
```

复位后再复现一次，看计数怎么涨：

```text
reset ipv6 icmp statistics
reset ipv6 statistics
ping ipv6 -c 50 2001:db8:12::2
display ipv6 icmp statistics
```

关注：echo request / echo reply 是否接近 1:1，有无 `ratelimited`。

---

## 6. CPU 与控制平面防护

```text
display cpu-usage
display cpu-usage task
```

中高端 Comware：

```text
display cpu-defend statistics
display cpu-defend car software
display cpu-defend car hardware
display cpu-defend car icmpv6 software
display cpu-defend car icmpv6 hardware
```

上调（确认 Drop 在涨、且只是测试需要；slot 按实际）：

```text
system-view
cpu-defend car icmpv6 software pps 500 slot 1
```

园区交换机常见：

```text
display qos cpu-car
display qos-car
```

攻击防范：

```text
display attack-defense statistics
display attack-defense flood statistics ipv6
display attack-defense policy
```

硬件快回 Echo（有命令再开）：

```text
system-view
ipv6 icmpv6 fast-reply enable
display ipv6 icmpv6 fast-reply statistics
```

不要用这条去「修 ping」——它只管差错报文，不管 Echo：

```text
ipv6 icmpv6 error-interval
```

---

## 7. ACL / 本机策略

```text
display acl ipv6 all
display current-configuration | include packet-filter
display current-configuration | include local-ipv6
display current-configuration | include local-packet
display current-configuration interface GigabitEthernet 1/0/24
```

临时摘掉接口过滤（先 `display current-configuration` 备份）：

```text
interface GigabitEthernet 1/0/24
 undo packet-filter ipv6 inbound
 undo packet-filter ipv6 outbound
```

部分平台本机放行（没有这条就跳过）：

```text
system-view
ipv6 local-packet permit all
```

部分平台本机 ACL：

```text
acl ipv6 basic 2000
 rule permit icmpv6
#
local-ipv6 acl 2000
```

确认收发 ICMPv6 没被关掉：

```text
system-view
ipv6 icmpv6 receive enable
ipv6 icmpv6 send enable
```

---

## 8. MTU / 硬件路由模式

```text
display interface GigabitEthernet 1/0/24 | include MTU
system-view
interface GigabitEthernet 1/0/24
 mtu 1500
 ipv6 mtu 1500
```

前缀长于 /64 才考虑（通常要重启，先查文档）：

```text
display current-configuration | include hardware-resource
system-view
hardware-resource routing-mode ipv6-128
```

互联口优先用 /64，少碰硬件模式。

---

## 9. 抓包 / 示踪（最后再用）

有 `packet-trace` 的平台：

```text
packet-trace profile v6ping match icmpv6 source 2001:db8:12::0/64 destination 2001:db8:12::0/64
packet-trace start profile v6ping duration 20
ping ipv6 -c 10 2001:db8:12::2
display packet-trace history profile v6ping
```

端口镜像（把互联口镜像到一台装 Wireshark 的电脑）：

```text
# 语法因平台而异，示意
monitor-port GigabitEthernet 1/0/48
mirroring-group 1 local
mirroring-group 1 mirroring-port GigabitEthernet 1/0/24 both
mirroring-group 1 monitor-port GigabitEthernet 1/0/48
```

Wireshark 显示过滤：

```text
icmpv6
icmpv6.type == 128 || icmpv6.type == 129
icmpv6.type == 135 || icmpv6.type == 136
```

调试（生产会刷屏，用完立刻关）：

```text
terminal monitor
terminal debugging
debugging ipv6 icmp
debugging ipv6 nd
undo debugging all
```

---

## 10. 一页采集模板

```text
display diagnostic-information
```

若不能一次导出，按 README 第 7 节逐条贴。
