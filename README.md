# Ubuntu 26.04 LTS 落地节点

这台机器是 `61.195.99.30`。登录后整行复制这一条命令。它会装好 sing-box、打开 BBR、把 SSH 改到 `22022` 并关闭密码登录，最后打印 SS 链接和 Clash Verge 节点。

这条命令在本变更进入 `main` 之后使用：

```bash
curl -fsSL https://raw.githubusercontent.com/FN2222/Python3/main/server/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh
```

在那之前，把本仓库的 `server/install.sh` 上传到服务器再执行。系统按 Ubuntu 26.04 LTS 处理；同一脚本在 Ubuntu 22.04 / 24.04 上也能用。

这个 GitHub 仓库目前是公开的。下面的 SS 密码会随仓库和拉取请求一起公开。合并前请把仓库改成私有，否则任何人都能使用这个节点。

## 已经固定的参数

| 项目 | 值 |
| --- | --- |
| 服务器 IP | `61.195.99.30` |
| SSH | `22022/tcp`，只接受密钥 |
| 公钥指纹 | `SHA256:obVPlFDzR5+j4okkVp3sjfRsE+iZeBkL7YDDwjBaSEs` |
| 业务端口 | `24443/tcp` 和 `24443/udp` |
| 程序 | sing-box |
| 协议 | Shadowsocks 2022 |
| 加密 | `2022-blake3-aes-256-gcm` |
| 密码 | `tPWMZB2C6gOCGG2tAtCesH3mgN8b2j93YTVhlqEjiIo=` |
| 出站 | 本机直接上网（落地，不再转发到下一台） |

密码是 32 字节密钥的 Base64，对应 `2022-blake3-aes-256-gcm`。这是这台机器的新密钥，不沿用 `150.66.49.113`。TCP 和 UDP 都由 sing-box 在 `24443` 上直接监听。Clash 里 `udp: true` 走原生 UDP。`tfo: true` 打开 TCP Fast Open；如果握手失败，把客户端这项改成 `false`，服务器不用动。

没有新建系统用户。公钥会写入 root，以及 sudo / admin / wheel 组和 uid 1000 以上、使用正常登录 shell 的现有账号。密钥注释 `po0-deploy` 只是这把公钥的名字。服务商网页控制台的密码保持原样，只关闭 SSH 里的密码登录。

## 分享链接

给 v2rayN、Shadowrocket、sing-box 图形客户端，或任何支持 SIP002 的软件。复制下面这一整行：

```text
ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206dFBXTVpCMkM2Z09DR0cydEF0Q2VzSDNtZ044YjJqOTNZVFZobHFFamlJbz0@61.195.99.30:24443#Landing-SS2022
```

同一行也保存在 `client/ss-uri.txt`。

## Clash Verge 节点

Clash Verge / Clash Verge Rev 使用 Mihomo 内核，可以直接导入 `client/clash-verge.yaml`。节点内容是：

```yaml
- name: "落地-SS2022"
  type: ss
  server: 61.195.99.30
  port: 24443
  cipher: 2022-blake3-aes-256-gcm
  password: "tPWMZB2C6gOCGG2tAtCesH3mgN8b2j93YTVhlqEjiIo="
  udp: true
  tfo: true
```

导入步骤：

1. 打开 Clash Verge Rev。
2. 进入「订阅」。
3. 选择「新建」里的本地配置，导入 `client/clash-verge.yaml`。也可以把这个文件拖进订阅页。
4. 选中这份配置并启用。
5. 打开「系统代理」，或者打开「虚拟网卡 / Tun」。两个都开时，以 Tun 为准。
6. 进入「代理」，选择 `落地-SS2022`。
7. 浏览器打开 `https://ip.sb`。页面上的 IP 应是 `61.195.99.30`。

这份配置的本地混合端口是 `7890`。局域网设备不能连这台电脑的代理（`allow-lan: false`）。内网地址直连，其余流量走落地节点。旧版 Clash Premium 不支持 SS2022，不要用它导入。

如果已经有自己的 Clash 配置，只把上面的节点贴进 `proxies`，并在你的策略组里加上 `落地-SS2022`。

## 服务器上先做这两步

### 1. 云厂商安全组

在运行脚本之前，到 VPS 面板的安全组或防火墙里放行下面三条。来源可以用 `0.0.0.0/0`；如果只想自己用，来源改成你家的公网 IP。

- TCP `22022`
- TCP `24443`
- UDP `24443`

面板里没有安全组、或者默认已经全部放行时，跳过这一步。

先放行 `22022` 再运行脚本。脚本会把 SSH 从 `22` 改走 `22022`，云面板如果仍只放行 `22`，当前连接还在，但新连接会进不来。

### 2. 确认私钥，然后执行

在你自己的电脑上核对指纹。输出里必须有 `SHA256:obVPlFDzR5+j4okkVp3sjfRsE+iZeBkL7YDDwjBaSEs`：

```bash
ssh-keygen -lf 你的私钥.pub
```

指纹不一致就不要运行脚本。运行之后 SSH 不再接受密码，只有这把私钥能登录。

进入本仓库目录后上传。现在 SSH 还是 `22`：

```bash
scp -P 22 server/install.sh 用户名@61.195.99.30:/tmp/install.sh
ssh -p 22 用户名@61.195.99.30
sudo bash /tmp/install.sh
```

`用户名` 用你现在登录这台 VPS 的用户。脚本不会删除这个用户，也不会改网页控制台的密码。

脚本开始改 SSH 前会倒计时 15 秒，可以按 Ctrl+C 取消。倒计时出现时，安全组里的 `22022` 应该已经放行，私钥指纹也应该核对过。

脚本跑完后不要关闭这个窗口。另开一个终端测试：

```bash
ssh -i 你的私钥 -p 22022 -o IdentitiesOnly=yes 用户名@61.195.99.30
```

脚本结束时会打印实际写入公钥的账号。新窗口登录成功后，再关闭旧窗口。

## 脚本实际会做的事

`server/install.sh` 是完整安装程序，服务器上只需要这一个文件。它会：

1. 安装 `curl`、`ufw`、`fail2ban`、`openssh-server`。探测到的公网 IPv4 如果不是 `61.195.99.30`，先暂停 15 秒。
2. 打开内核自带的 BBR，不安装第三方 BBR 模块。能被当前内核接受的参数写入 `/etc/sysctl.d/99-landing.conf`，至少包括：

```text
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_no_metrics_save = 1
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_notsent_lowat = 16384
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
fs.file-max = 1048576
```

登录会话的文件描述符上限写到 `/etc/security/limits.d/99-landing.conf`。sing-box 官方服务文件已经是 `LimitNOFILE=infinity`。

3. 把公钥装进 root 和现有可登录账号的 `authorized_keys`。root 的 shell 如果是 `nologin`，会改成 `/bin/bash`。原来的 shell 记在 `/root/sshd-backup/root-shell`。
4. 启用 UFW：默认拒绝入站、放行出站，并放行 `22/tcp`、`22022/tcp`、`24443/tcp`、`24443/udp`。确认 SSH 已经改到 `22022` 并且 `22` 不再监听之后，再删掉 `22` 的放行规则。
5. 从 `https://deb.sagernet.org/` 安装 sing-box，写入 `/etc/sing-box/config.json`，检查配置，然后开机自启。配置里打开了 TCP Fast Open，TCP 保活初始间隔是 2 分钟。没有写 `network`，所以 TCP 和 UDP 一起监听。
6. 备份原来的 SSH 配置，再把 SSH 改成密钥登录和 `22022`。Ubuntu 26.04 的 SSH 由 `ssh.socket` 接管监听，所以脚本同时写：
   - `/etc/ssh/sshd_config.d/00-landing-auth.conf`：关闭密码和键盘交互登录，允许 root 使用密钥
   - `/etc/ssh/sshd_config.d/99-port.conf`：`Port 22022`
   - `/etc/systemd/system/ssh.socket.d/override.conf`：清空原来的 `22`，只听 `22022`
7. 改端口前用 `sshd -T` 核对每个已写入公钥的账号。生效结果必须是密码关闭、密钥开启、端口 `22022`。核对失败时还原配置文件，不重启 SSH。
8. 让 fail2ban 只看守 `22022`。5 次失败后封禁 1 小时，封禁方式走 UFW。
9. 把连接信息写到 `/root/ss2022-landing.txt`，权限 `600`。

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
      "tcp_fast_open": true,
      "tcp_keep_alive": "2m",
      "method": "2022-blake3-aes-256-gcm",
      "password": "tPWMZB2C6gOCGG2tAtCesH3mgN8b2j93YTVhlqEjiIo="
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

同一份文件在 `server/config.json`。省略 `network` 时，TCP 和 UDP 会一起监听。

## 装完后在服务器上核对

```bash
systemctl status sing-box --no-pager
ss -lntup | grep -E '22022|24443'
sysctl net.ipv4.tcp_congestion_control
sshd -T | grep -Ei 'port |passwordauthentication|pubkeyauthentication|permitrootlogin'
```

正常时能看到：

- `22022` 是 TCP，进程属于 SSH。
- `24443` 同时有一条 TCP `LISTEN` 和一条 UDP `UNCONN`，进程都是 `sing-box`。
- 拥塞控制是 `bbr`。
- `passwordauthentication no`，`pubkeyauthentication yes`，`permitrootlogin prohibit-password`。

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

它会还原脚本运行前的 SSH 配置，去掉 `22022` 的套接字覆盖，把 SSH 放回 `22`，重新允许密码登录，并放行 UFW 的 `22/tcp`。然后另开窗口：

```bash
ssh -p 22 用户名@61.195.99.30
```

如果旧窗口也断了，用服务商网页控制台执行同一条回滚命令。脚本在倒计时之前失败的话，SSH 仍然是原来的端口和登录方式。

## 可选的 sing-box 客户端

不用 Clash 时，可以用 `client/sing-box-client.json`。它在本机 `127.0.0.1:2080` 提供 HTTP/SOCKS 混合端口，私网地址直连，其余走这台落地机：

```bash
sing-box run -c client/sing-box-client.json
```

系统代理填 `127.0.0.1:2080`。不要和 Clash Verge 的 `7890` 同时设成系统代理。
