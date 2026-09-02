# 本协议已完成章节的知识骨架

出题只能基于下面这些内容。每条都标了 `pdf_id` 与页码,
填 `grounding` 时直接用这些页码,并回到对应章节的原文复制英文句子。

## OSPF 邻居邻接关系 (OSPF Neighbor Adjacency)

- `pdf_id`: `ospf-neighbor-adjacency-69619352`
- 源文件: `IGP/OSPF/OSPF Neighbor Adjacency.pdf`
- 原文页数: ?
- 本章边界: 本章覆盖 hello 报文与邻居发现、邻居状态迁移、DR/BDR 选举规则、邻居验证命令四部分;不涉及原文之外的其他内容。

**概要**:本章讲 OSPF 路由器之间怎么从互不相识变成邻居、再变成完全邻接。先讲 hello 报文如何在链路上发现邻居,以及必须匹配哪四项参数才算邻居;再讲邻居状态如何从 Down 依次推进到 Init、2-Way,最后到 Full;然后讲广播网络上 DR 与 BDR 的选举规则,以及选出来之后其余路由器只与这两台建立完全邻接;最后用 show ip ospf neighbor 命令验证邻居状态和接口。

**小节与知识点**

- **hello 报文与邻居发现** (Introduction to OSPF Neighbor Adjacency) — p.1
  - (p.1) OSPF 路由器靠 hello 报文在链路上发现邻居。
    - 原文: OSPF routers use hello packets to discover neighbors on a link.
  - (p.1) 在广播网段上,hello 报文发往组播地址 224.0.0.5,每 10 秒发一次。
    - 原文: The hello packet is sent to multicast address 224.0.0.5 every 10 seconds on a broadcast network segment.
  - (p.1) 只有当 hello interval、dead interval、area ID 和子网掩码全部一致时,两台路由器才会成为邻居。
    - 原文: Two routers become neighbors only when the hello interval, the dead interval, the area ID and the subnet mask all match.
  - (p.1) dead interval 默认是 40 秒,正好是 hello interval 的四倍。
    - 原文: The dead interval is 40 seconds by default, which is four times the hello interval.
- **邻居状态的推进** (Neighbor States) — p.2
  - (p.2) 在邻接关系建立完成之前,OSPF 邻居会经历若干个状态。
    - 原文: An OSPF neighbor moves through several states before the adjacency is complete.
  - (p.2) 最初的状态是 Down,表示还没有收到过任何 hello 报文。
    - 原文: The first state is Down, where no hello packet has been received yet.
  - (p.2) 路由器一旦收到 hello 报文,就把该邻居置为 Init 状态。
    - 原文: When a router receives a hello packet it moves the neighbor to the Init state.
  - (p.2) 当路由器在收到的 hello 报文里看到自己的 router ID 时,邻居进入 2-Way 状态。
    - 原文: Once the router sees its own router ID in the received hello packet, the neighbor moves to the 2-Way state.
  - (p.2) 数据库交换完成之后,邻居到达 Full 状态。
    - 原文: After the database exchange finishes, the neighbor reaches the Full state.
- **DR 与 BDR 的选举** (Designated Router Election) — p.3
  - (p.3) 在广播网络上,OSPF 会选出一台 DR 和一台 BDR。
    - 原文: On a broadcast network OSPF elects a designated router and a backup designated router.
  - (p.3) OSPF priority 最高的路由器成为 DR。
    - 原文: The router with the highest OSPF priority becomes the designated router.
  - (p.3) priority 相同时,router ID 最大的路由器赢得选举。
    - 原文: When the priority is equal, the router with the highest router ID wins the election.
  - (p.3) priority 为 0 的路由器永远不会成为 DR。
    - 原文: A priority of 0 means the router will never become the designated router.
  - (p.3) 其余路由器只与 DR 和 BDR 建立完全邻接关系。
    - 原文: All other routers form a full adjacency only with the DR and the BDR.
- **验证邻居关系** (Verification) — p.4
  - (p.4) 用 show ip ospf neighbor 命令来验证邻接关系。
    - 原文: Use the show ip ospf neighbor command to verify the adjacency.
  - (p.4) 命令输出会显示邻居状态和对应的接口。
    - 原文: The output below shows the neighbor state and the interface.
  - (p.4) [配置] R1#show ip ospf neighbor

**本章标注的必须掌握**

- (p.1) 成为邻居必须同时匹配四项:hello interval、dead interval、area ID、子网掩码。
- (p.2) 邻居状态的顺序是 Down、Init、2-Way、Full,且每一步都有明确的触发条件。
- (p.2) 进入 2-Way 的条件是在收到的 hello 报文里看到自己的 router ID,而不是又收到一个 hello。
- (p.3) DR 选举先比 OSPF priority 且最高者胜,priority 相同再比 router ID 且最大者胜;priority 为 0 的永远不会成为 DR。
- (p.3) 选出 DR 和 BDR 之后,其余路由器只与 DR 和 BDR 建立完全邻接,不会两两建立。

**本章标注的难点**

- (p.2) 2-Way 的触发条件容易记成再收到一个 hello —— Init 和 2-Way 都与收到 hello 报文有关,字面上非常接近,所以很容易把两个状态的触发条件混成同一个。而原文对这两步的表述其实差别很大:一个是收到 hello,另一个是在收到的 hello 里看到自己的 router ID。
- (p.1) 四项必须匹配的参数容易只记住一两项 —— 四项参数分属两类性质,时间参数与身份参数,数量又刚好超出短期记忆最舒服的范围,所以常见的情况是只记住 hello interval,或者只记住 area ID,导致排查邻居问题时漏查另外几项。
- (p.3) DR 选举的判定顺序与方向容易记反 —— 选举涉及两个判定条件 priority 与 router ID、一个前提 priority 相同才比 router ID,以及一个特例 priority 为 0,四条信息交织在三句话里。既容易把顺序说反,也容易把最高记成最小,还容易漏掉特例。

**本章术语**:OSPF(开放最短路径优先)、Hello Packet(Hello 报文)、Adjacency(邻接关系)、Multicast(组播)、Subnet Mask(子网掩码)、Router ID(路由器 ID)、Designated Router(指定路由器)、Backup Designated Router(备份指定路由器)、Interface(接口)
