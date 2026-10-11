# 香港落地 + 百度/腾讯入口转发

客户端连百度或腾讯的公网端口。这两台机器只做 TCP/UDP 转发，把流量送到 IX。IX 再送到香港。香港上的 sing-box 用 Shadowsocks 2022 解密，然后直接上网。

```text
客户端（SS2022 密文）
  ├─ 腾讯 150.158.185.159:24443 ─► IX 传输 A 161.248.136.186:24443 ─┐
  ├─ 腾讯 150.158.185.159:24444 ─► IX 传输 B 138.252.162.176:24443 ─┤
  ├─ 百度 106.12.30.105:24443   ─► IX 传输 A 161.248.136.186:24443 ─┼─► 香港 83.229.121.209:24443
  └─ 百度 106.12.30.105:24444   ─► IX 传输 B 138.252.162.176:24443 ─┘   sing-box 解密后直接出网
```

IX 面板不用改。源端口保持 `83.229.121.209:24443`，协议保持 TCP+UDP。两条加速地址保持：

| 线路 | 加速地址 | 转到 |
| --- | --- | --- |
| CNIX-1 传输 A | `161.248.136.186:24443` | `83.229.121.209:24443` |
| CNIX-1 传输 B | `138.252.162.176:24443` | `83.229.121.209:24443` |

入口上的 `24444` 也是转到 IX 的 `24443`。IX 只监听 24443。

这份仓库里有这台落地的真实密码。不要把仓库公开。

这两个脚本只处理上面这三台机器。

## 先放行云防火墙

脚本改不了云控制台。三台都要在安全组里放行，再运行脚本。腾讯如果还有轻量防火墙，两处都放行。

| 机器 | 入站 | 来源 |
| --- | --- | --- |
| 香港 `83.229.121.209` | TCP `24443`、UDP `24443` | `0.0.0.0/0` |
| 腾讯 `150.158.185.159` | TCP/UDP `24443` 和 `24444` | `0.0.0.0/0`，或只填你家公网 IP |
| 百度 `106.12.30.105` | TCP/UDP `24443` 和 `24444` | 同上 |

香港这边的来源不要写成百度或腾讯的公网 IP。IX 回源时用的是 IX 自己的地址。SS2022 会校验密码，所以落地端口可以对公网开放。

SSH 保持你现在的端口。两个脚本都不改 SSH。

已经在用的转发不会被删：

| 机器 | 保留 |
| --- | --- |
| 腾讯 `10.100.132.202` | `20001` → `177.0.130.85:20001`，`30001` → `103.169.216.124:30001` |
| 百度 `192.168.16.2` | `32001` → `124.14.19.231:31001` |

新规则写在单独的 `table ip ix_entry` 里。不要在这三台机器上执行 `nft flush ruleset`。

## 1. 香港安装落地

系统按 Debian/Ubuntu 处理。上传 `server/install.sh` 后执行：

```bash
scp server/install.sh root@83.229.121.209:/tmp/install.sh
ssh root@83.229.121.209
bash /tmp/install.sh
```

脚本会核对公网 IP 是不是 `83.229.121.209`。出网 IP 探测失败、但你确认就是这台机器时：

```bash
bash /tmp/install.sh --force-ip
```

脚本会：

1. 拒绝在腾讯 `10.100.132.202` 或百度 `192.168.16.2` 上运行。
2. 从 GitHub 下载当前 sing-box 正式版 deb 并安装，写入 `/etc/sing-box/config.json`，监听 `24443/tcp` 和 `24443/udp`。
3. 尝试打开 BBR。打不开时继续安装，代理不受影响。
4. 不开启 `ip_forward`。这是用户态代理，不是网卡转发。
5. 本机 UFW 或 firewalld 如果已经开着，会放行 `24443`。没开则不主动打开防火墙。
6. 把节点写到 `/root/ss2022-landing.txt` 和 `/root/ss2022-clash.yaml`，权限 `600`。

IPv6 可用时监听 `::`，同时接收 IPv4。IPv6 关闭时监听 `0.0.0.0`。密码和端口不变。省略 `network` 时，sing-box 同时监听 TCP 和 UDP。

加密是 `2022-blake3-aes-256-gcm`。不要在客户端里选普通的 `aes-256-gcm`。

装完核对：

```bash
systemctl status sing-box --no-pager
ss -lntup | grep 24443
```

应同时看到 TCP `LISTEN` 和 UDP `UNCONN`，进程都是 sing-box。

## 2. 腾讯和百度只做转发

同一个 `entry/forward.sh` 上传到两台入口。脚本看到 `10.100.132.202` 就按腾讯处理，看到 `192.168.16.2` 就按百度处理。

```bash
scp entry/forward.sh root@150.158.185.159:/tmp/forward.sh
scp entry/forward.sh root@106.12.30.105:/tmp/forward.sh

ssh root@150.158.185.159 'bash /tmp/forward.sh'
ssh root@106.12.30.105 'bash /tmp/forward.sh'
```

每台入口上的转发是：

| 入口公网端口 | 转到 |
| --- | --- |
| `24443/tcp` 和 `24443/udp` | `161.248.136.186:24443`（传输 A） |
| `24444/tcp` 和 `24444/udp` | `138.252.162.176:24443`（传输 B） |

脚本会打开 `ip_forward`，做 DNAT 和回程 masquerade，并在重启后由 `ix-entry.service` 重新加载。入口不安装 sing-box，也不保存密码。

取消这次新增的转发：

```bash
bash /tmp/forward.sh --remove
```

这只删除 `ix_entry`。`po0relay` 和 `ix_forward` 不动，`ip_forward` 也保持打开。

## 节点参数

| 项目 | 值 |
| --- | --- |
| 加密 | `2022-blake3-aes-256-gcm` |
| 密码 | `qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I=` |
| 传输 | TCP + UDP，无插件，无 multiplex |

四条入口线路密码相同。最后一条直连香港，不经过百度、腾讯和 IX，只用来确认落地本身。

## SS 链接

整行复制。给 v2rayN、Shadowrocket、sing-box，或 Clash Verge 的「从剪贴板导入」。

```text
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206cUJoVERqM09aRnE3cFlVS2RyTkVDSnBjNEFxQTE2ZldRUmI1M1NYd243ST0@150.158.185.159:24443#Tencent-IX-A
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206cUJoVERqM09aRnE3cFlVS2RyTkVDSnBjNEFxQTE2ZldRUmI1M1NYd243ST0@150.158.185.159:24444#Tencent-IX-B
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206cUJoVERqM09aRnE3cFlVS2RyTkVDSnBjNEFxQTE2ZldRUmI1M1NYd243ST0@106.12.30.105:24443#Baidu-IX-A
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206cUJoVERqM09aRnE3cFlVS2RyTkVDSnBjNEFxQTE2ZldRUmI1M1NYd243ST0@106.12.30.105:24444#Baidu-IX-B
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206cUJoVERqM09aRnE3cFlVS2RyTkVDSnBjNEFxQTE2ZldRUmI1M1NYd243ST0@83.229.121.209:24443#HK-Direct-Test
```

同一份内容在 `client/ss-uri.txt`。

## Clash Verge

Clash Verge Rev 使用 Mihomo，可以导入 `client/clash-verge.yaml`。旧版 Clash Premium 不支持 SS2022。

导入：

1. 打开 Clash Verge Rev，进入「订阅」。
2. 新建本地配置，导入 `client/clash-verge.yaml`。也可以把文件拖进订阅页。
3. 选中这份配置。
4. 打开「系统代理」或「虚拟网卡 / Tun」。两个都开时，以 Tun 为准。
5. 在「代理」里选择「入口选择」。默认会走「自动选择」，在四条入口线路里挑延迟更低的一条。
6. 浏览器打开 `https://ip.sb`。出口应是香港 `83.229.121.209`。

本地混合端口是 `7890`。`allow-lan: false`，局域网设备不能连这台电脑的代理。内网地址直连，其余走当前节点。

已经有自己的配置时，只把下面几段加进 `proxies`，并在策略组里加上对应名字：

```yaml
- name: "腾讯-IX-A"
  type: ss
  server: 150.158.185.159
  port: 24443
  cipher: 2022-blake3-aes-256-gcm
  password: "qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I="
  udp: true
- name: "腾讯-IX-B"
  type: ss
  server: 150.158.185.159
  port: 24444
  cipher: 2022-blake3-aes-256-gcm
  password: "qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I="
  udp: true
- name: "百度-IX-A"
  type: ss
  server: 106.12.30.105
  port: 24443
  cipher: 2022-blake3-aes-256-gcm
  password: "qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I="
  udp: true
- name: "百度-IX-B"
  type: ss
  server: 106.12.30.105
  port: 24444
  cipher: 2022-blake3-aes-256-gcm
  password: "qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I="
  udp: true
- name: "香港直连-仅测试"
  type: ss
  server: 83.229.121.209
  port: 24443
  cipher: 2022-blake3-aes-256-gcm
  password: "qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I="
  udp: true
```

「自动选择」里不要放「香港直连-仅测试」。

如果某一条线路 TCP 能通、UDP 超时，把那一条的 `udp` 改成 `false`。TCP 代理仍然可用。

## 可选的 sing-box 客户端

不用 Clash 时，用 `client/sing-box-client.json`。本机 `127.0.0.1:2080` 是 HTTP/SOCKS 混合端口，默认走腾讯传输 A，可以在 selector 里改线路：

```bash
sing-box run -c client/sing-box-client.json
```

系统代理填 `127.0.0.1:2080`。不要和 Clash Verge 的 `7890` 同时设成系统代理。

## 怎么确认整条链路

先只开香港，在香港上执行：

```bash
ss -lntup | grep 24443
```

再在腾讯和百度上执行转发脚本。入口上应能看到计数：

```bash
nft list table ip ix_entry
```

然后从自己的电脑连「腾讯-IX-A」。同时：

```bash
# 腾讯或百度
tcpdump -n -i eth0 'port 24443 or port 24444'

# 香港
tcpdump -n -i any port 24443
journalctl -u sing-box -f
```

入口上的源地址应是你的客户端。香港上的源地址应是 IX，不是你家的地址，也不是百度或腾讯的公网地址。sing-box 日志里出现连接后，`https://ip.sb` 显示 `83.229.121.209`。

连不上时按这个顺序看：

1. 云安全组是否放行了对应的 TCP 和 UDP。
2. 入口上 `sysctl net.ipv4.ip_forward` 是否为 `1`，`nft list table ip ix_entry` 的 counter 是否在增加。counter 一直是 0，说明包还没进这台机器。
3. 入口上 `ping 161.248.136.186` 和 `ping 138.252.162.176` 是否通。
4. IX 面板里源端口是否仍是 `83.229.121.209:24443`，状态是否为 active。
5. 香港 `ss` 是否在监听 24443。认证失败时，检查加密是不是 `2022-blake3-aes-256-gcm`，密码有没有少掉末尾的 `=`。
