# 附录 B 陌生 pcap 独立分析 Checklist（教程最终能力验收）

> 拿到任何一个陌生 TCP pcap，按以下顺序走完。每一步给出：动作、工具/Filter、判定要点、对应章节。目标：**独立得出"问题在 Client / Server / Application / LAN / WAN / Firewall / LB / Cloud Network 哪一层"的证据链结论。**

## 第 0 步：抓包质量体检（不做这步，后面全部作废）

- [ ] `capinfos file.pcap`：时长、速率、截断（snaplen）
- [ ] filter `tcp.analysis.ack_lost_segment`：非零 ⇒ capture loss，所有丢包结论降级（第 16、18 章）
- [ ] 抓包点在哪台设备哪个方向？offload 巨段/假校验错预期（第 18 章）
- [ ] 有没有抓到握手？没有 ⇒ WS 未知，窗口分析需手工设定因子（第 2 章）

## 第 1 步：确定 TCP Stream 与 Client/Server

- [ ] Statistics → Conversations，按字节排序锁定目标流；`tcp.stream eq N`
- [ ] 谁发 SYN 谁是 Client；数据主方向是哪边（第 1 章）

## 第 2 步：三次握手三要素

- [ ] MSS（双向各多少？被 clamp 过？）
- [ ] Window Scale（双向因子？缺失⇒64KB 封顶）
- [ ] SACK Permitted（缺失⇒恢复能力受限，且怀疑中间盒剥离）
- [ ] iRTT（握手 RTT = 无队列基线）（第 2 章）

## 第 3 步：Seq/Ack 与 Next Seq 连续性

- [ ] 抽查 `Next Seq = Seq + Len` 链是否连续；Ack 是否单调（第 1 章）

## 第 4 步：Bytes in Flight 与窗口关系

- [ ] Window Scaling Graph：蓝点（BiF）与绿线（Calculated Window）的关系
- [ ] BiF 贴绿线 ⇒ rwnd-limited；BiF 锯齿远低于绿线 ⇒ cwnd/丢包；BiF 稀疏 ⇒ application-limited（第 3、5、19 章）

## 第 5 步：判断 rwnd

- [ ] `tcp.analysis.zero_window || tcp.analysis.window_full` 计数与时长
- [ ] 谁通告的小窗口（方向！）⇒ 该侧接收应用/缓冲嫌疑（第 4 章）

## 第 6 步：判断是否可能受 cwnd 限制

- [ ] 抓包**看不到** cwnd——若可登录发送端：`ss -ti`（cwnd/ssthresh/unacked/rwnd_limited/sndbuf_limited）
- [ ] 不能登录：用 BiF 包络 + 丢包事件反推（第 6、17 章）

## 第 7 步：RTT 与 Throughput

- [ ] tcptrace RTT 图：基线、缓爬（队列/bufferbloat）、突刺（抖动）
- [ ] I/O Graph 吞吐波形：平直（窗口钉死）/锯齿（丢包）/深坑（RTO）/规律小凹（BBR PROBE_RTT）（第 14、19 章）
- [ ] 三公式核算：窗口/RTT、Mathis、链路额定——哪个最接近实测（第 19 章）

## 第 8 步：Dup ACK 与 SACK Block

- [ ] `tcp.analysis.duplicate_ack`：数量、集中时段、方向
- [ ] SACK 左右沿：缺口几个？在扩张还是自愈？
- [ ] SACK Block < Ack ⇒ D-SACK ⇒ 假重传/乱序线索（第 9 章）

## 第 9 步：Packet Loss vs Reordering

- [ ] 缺口自愈无重传 ⇒ 乱序；重传+Ack大跳 ⇒ 真丢；重传+D-SACK ⇒ 假重传（第 9 章）

## 第 10 步：重传分型

- [ ] Fast Retransmission：≥3 DupACK/SACK 证据 + 与触发 ACK 零间隔（第 10 章）
- [ ] Fast Recovery：重传后新数据不断流、节奏减半（PRR）、BiF 滑降 ~0.7×（第 11 章）
- [ ] TLP：尾部静默 ~2×SRTT 后单包探测（第 13 章）
- [ ] RTO：静默 ≥200ms（≈ss 的 rto 值）+ 无 DupACK + 同 Seq 再现 + 退避翻倍（第 12 章）

## 第 11 步：Zero Window / Window Full 专查

- [ ] ZW→ZWP（指数退避）→Update 链完整性；停顿总时长；哪侧通告（第 4 章）

## 第 12 步：结合 ss / nstat（可登录时）

- [ ] `ss -ti`：算法、cwnd/ssthresh、rtt/rto、limited 三件套、notsent、retrans
- [ ] `nstat`：TLP/DSACK/SpuriousRTO/ListenDrops 分诊（第 13、17 章）

## 第 13 步：多点抓包定段（需要定位"丢在哪"时）

- [ ] raw Seq 存亡表（A/B/C 点）；ACK 方向反查；offload 巨段按区间展开（第 20 章）
- [ ] 云环境先画连接分段图：七层 LB/代理 = 多条独立 TCP，禁止跨段比 Seq/RTT（第 20 章）

## 第 14 步：输出证据链结论

按第 23 章九环格式书写：现象 → 逐环证据（每环注明 Frame/字段/工具输出）→ 分层定位（Client/Server/App/LAN/WAN/FW/LB/Cloud）→ 修复建议 → 验证计划。**禁止出现"可以明显看到""显然"；每个结论必须挂证据。**

---

## 速查：五大症状 → 首查动作

| 症状 | 首查 |
|---|---|
| 慢而平直 | 窗口/RTT 核算 + Window Scaling 图（rwnd? WS 缺失?）|
| 慢而锯齿 | 重传分型 + Mathis 核算（丢包在哪段）|
| 周期性卡死几百 ms | RTO 指纹（200ms 空洞、退避）+ 尾丢/小窗成因 |
| 彻底停顿后恢复 | Zero Window 链 vs RTO 空洞（平台末尾是新 Seq 还是旧 Seq）|
| "重传很多"报警 | 先体检 capture loss/offload/D-SACK，再谈丢包 |
