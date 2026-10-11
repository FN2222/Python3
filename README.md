# Ubuntu 26.04 LTS 落地节点

登录 `150.66.49.113` 之后，整行复制这一条命令。它会装好 sing-box、打开 BBR、把 SSH 改到 22022，并在最后打印 SS 链接和 Clash Verge 节点。

```bash
curl -fsSL https://raw.githubusercontent.com/FN2222/Python3/main/server/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

这台机器的参数已经全部写好，不需要再改端口、密码或 IP。系统按 Ubuntu 26.04 LTS（也就是 26.0 LTS）处理；同一脚本在 Ubuntu 22.04 / 24.04 上也能用。

这份目录里的分享链接和密码是这台服务器的真实密钥。不要把仓库公开。

## 已经固定的参数

| 项目 | 值 |
| --- | --- |
| 服务器 IP | `150.66.49.113` |
| SSH | `22022/tcp` |
| 业务端口 | `24443/tcp` 和 `24443/udp` |
| 程序 | sing-box |
| 协议 | Shadowsocks 2022 |
| 加密 | `2022-blake3-aes-256-gcm` |
| 密码 | `WaLb8NWiW90b6m5MtmJ0GiaVODUkPcsz0JAf2YphvV0=` |
| 出站 | 本机直接上网（落地，不再转发到下一台） |

密码是 32 字节密钥的 Base64，对应 `2022-blake3-aes-256-gcm`。TCP 和 UDP 都由 sing-box 在 `24443` 上直接监听，Clash 里打开 `udp: true` 即可走原生 UDP，不需要额外插件。

## 分享链接

给 v2rayN、Shadowrocket、sing-box 图形客户端，或任何支持 SIP002 的软件。复制下面这一整行：

```text
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206V2FMYjhOV2lXOTBiNm01TXRtSjBHaWFWT0RVa1Bjc3owSkFmMllwaHZWMD0@150.66.49.113:24443#Landing-SS2022
```

同一行也保存在 `client/ss-uri.txt`。

## Clash Verge 节点

Clash Verge / Clash Verge Rev 使用 Mihomo 内核，可以直接导入 `client/clash-verge.yaml`。节点内容是：

```yaml
- name: "落地-SS2022"
  type: ss
  server: 150.66.49.113
  port: 24443
  cipher: 2022-blake3-aes-256-gcm
  password: "WaLb8NWiW90b6m5MtmJ0GiaVODUkPcsz0JAf2YphvV0="
  udp: true
```

导入步骤：

1. 打开 Clash Verge Rev。
2. 进入「订阅」。
3. 选择「新建」里的本地配置，导入 `client/clash-verge.yaml`。也可以把这个文件拖进订阅页。
4. 选中这份配置并启用。
5. 打开「系统代理」，或者打开「虚拟网卡 / Tun」。两个都开时，以 Tun 为准。
6. 进入「代理」，选择 `落地-SS2022`。
7. 浏览器打开 `https://ip.sb`。页面上的 IP 应是 `150.66.49.113`。

这份配置的本地混合端口是 `7890`。局域网设备不能连这台电脑的代理（`allow-lan: false`）。内网地址直连，其余流量走落地节点。旧版 Clash Premium 不支持 SS2022，不要用它导入。

如果已经有自己的 Clash 配置，只把上面的节点贴进 `proxies`，并在你的策略组里加上 `落地-SS2022`。

## 服务器上只做这两步

### 1. 云厂商安全组

在运行脚本之前，到 VPS 面板的安全组或防火墙里放行下面三条。来源可以用 `0.0.0.0/0`；如果只想自己用，来源改成你家的公网 IP。

- TCP `22022`
- TCP `24443`
- UDP `24443`

面板里没有安全组、或者默认已经全部放行时，跳过这一步。

先放行 `22022` 再运行脚本。脚本会把 SSH 从 `22` 改走 `22022`，云面板如果仍只放行 `22`，当前连接还在，但新连接会进不来。

### 2. 上传并执行

在你自己的电脑上，进入本仓库目录后执行。现在 SSH 还是 `22`，所以第一次上传不要加新端口：

```bash
scp -P 22 server/install.sh 用户名@150.66.49.113:/tmp/install.sh
ssh -p 22 用户名@150.66.49.113
sudo bash /tmp/install.sh
```

`用户名` 用你现在登录这台 VPS 的用户，脚本不会改它，也不会改密码登录。

脚本开始改 SSH 前会倒计时 15 秒，可以按 Ctrl+C 取消。倒计时出现时，安全组里的 `22022` 应该已经放行。

脚本跑完后不要关闭这个窗口。另开一个终端测试：

```bash
ssh -p 22022 用户名@150.66.49.113
```

新窗口登录成功后，再关闭旧窗口。

## 脚本实际会做的事

`server/install.sh` 是完整安装程序，服务器上只需要这一个文件。它会：

1. 安装 `curl`、`ufw`、`fail2ban`、`openssh-server`。
2. 打开 BBR。写入 `/etc/sysctl.d/99-landing.conf`：

```text
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
```

3. 启用 UFW：默认拒绝入站、放行出站，并放行 `22/tcp`、`22022/tcp`、`24443/tcp`、`24443/udp`。确认 SSH 已经改到 `22022` 之后，再删掉 `22` 的放行规则。
4. 从 `https://deb.sagernet.org/` 安装 sing-box，写入 `/etc/sing-box/config.json`，检查配置，然后开机自启。
5. 把 SSH 改到 `22022`。Ubuntu 26.04 的 SSH 由 `ssh.socket` 接管监听，所以脚本同时写：
   - `/etc/ssh/sshd_config.d/99-port.conf`：`Port 22022`
   - `/etc/systemd/system/ssh.socket.d/override.conf`：清空原来的 `22`，只听 `22022`
6. 让 fail2ban 只看守 `22022`。5 次失败后封禁 1 小时，封禁方式走 UFW。
7. 把连接信息写到 `/root/ss2022-landing.txt`，权限 `600`。

IPv6 可用时，sing-box 监听 `::`，这个套接字同时接收 IPv4 和 IPv6。IPv6 被系统关掉时，脚本改听 `0.0.0.0`，密码和端口不变。

不需要打开 `net.ipv4.ip_forward`。这是用户态代理：客户端连到 `24443`，sing-box 再替客户端访问网站。它不是网卡上的 NAT 转发。

sing-box 服务用户是 `sing-box`，配置文件权限是 `640`，属主 `root:sing-box`。`/etc/sing-box` 目录里不要再放别的 `.json`，服务启动参数是 `-C /etc/sing-box`，该目录下每个 JSON 都会被加载。

服务器上的配置如下。IPv6 关闭时，`listen` 会由脚本写成 `0.0.0.0`：

```json
{
  "log": {
    "level": "info",
    "timestamp": true
  },
  "inbounds": [
    {
      "type": "shadowsocks",
      "tag": "ss-in",
      "listen": "::",
      "listen_port": 24443,
      "method": "2022-blake3-aes-256-gcm",
      "password": "WaLb8NWiW90b6m5MtmJ0GiaVODUkPcsz0JAf2YphvV0="
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}
```

同一份文件在 `server/config.json`。配置已在 sing-box 1.14.3 上检查通过：省略 `network` 时，TCP 和 UDP 会一起监听。

## 装完后在服务器上核对

```bash
systemctl status sing-box --no-pager
ss -lntup | grep -E '22022|24443'
sysctl net.ipv4.tcp_congestion_control
```

正常时能看到：

- `22022` 是 TCP，进程属于 SSH。
- `24443` 同时有一条 TCP `LISTEN` 和一条 UDP `UNCONN`，进程都是 `sing-box`。
- 拥塞控制是 `bbr`。

查看代理日志：

```bash
journalctl -u sing-box -n 50 --no-pager
```

升级 sing-box 时如果 apt 询问配置文件，选择保留本地版本，不要用软件包里的示例配置覆盖 `/etc/sing-box/config.json`。

## SSH 连不上时

当前还开着的那个旧窗口里执行：

```bash
sudo bash /root/revert-ssh-to-22.sh
```

它会去掉 `22022` 的覆盖配置，把 SSH 放回 `22`，并重新放行 UFW 的 `22/tcp`。然后另开窗口：

```bash
ssh -p 22 用户名@150.66.49.113
```

脚本在倒计时之前失败的话，SSH 仍然是 `22`，还没有改端口。

## 可选的 sing-box 客户端

不用 Clash 时，可以用 `client/sing-box-client.json`。它在本机 `127.0.0.1:2080` 提供 HTTP/SOCKS 混合端口，私网地址直连，其余走这台落地机：

```bash
sing-box run -c client/sing-box-client.json
```

系统代理填 `127.0.0.1:2080`。不要和 Clash Verge 的 `7890` 同时设成系统代理。
