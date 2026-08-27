# Python3

本仓库按主题归档网络与运维笔记。

## H3C 直连 IPv6 ping 丢包

两台 H3C 交换机直连、互 ping IPv6 丢包时，先按丢包形态分流：ND 首包、控制平面 ICMP 限速、物理层、ACL/本机策略。不要用 ping 交换机自身去判断链路质量。

手册：[h3c-ipv6-ping-loss/README.md](h3c-ipv6-ping-loss/README.md)  
命令清单：[h3c-ipv6-ping-loss/commands.md](h3c-ipv6-ping-loss/commands.md)
