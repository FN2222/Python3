# SSH 密钥登录完整配置指南

本文说明如何用 **SSH 公钥认证**（常被口语称为「密钥登录 / 秘钥登录」）代替密码登录。覆盖：

- 认证原理（密钥对、握手、签名校验、与密码登录的差异）
- **Linux / Unix 服务端** 逐步配置
- **Windows 11 客户端** 逐步配置（系统自带 OpenSSH、PuTTY、WSL 三套方案）
- **Linux 客户端** 逐步配置
- 验证、排错、加固

正确写法是 **密钥**。下文统一用「密钥」。

---

## 0. 先建立正确模型

SSH 密钥登录里有 **两套完全不同的密钥**，不要混为一谈：

| 种类 | 谁持有 | 作用 | 典型文件 |
|------|--------|------|----------|
| **主机密钥（Host Key）** | 服务器 | 证明「你连上的就是这台机器」，防止中间人冒充 | 服务器 `/etc/ssh/ssh_host_*`；客户端 `~/.ssh/known_hosts` |
| **用户密钥（User Key）** | 客户端持有私钥，服务器保存对应公钥 | 证明「你就是这个用户」 | 客户端私钥 `id_ed25519`；服务器 `~/.ssh/authorized_keys` |

本文配置的是 **用户密钥登录**。主机密钥会在第一次连接时自动出现（`Are you sure you want to continue connecting?`），那是另一层信任。

**私钥永远留在客户端，绝不上传到服务器，也绝不通过聊天工具发送。** 传到服务器的只有公钥。

---

## 1. 原理讲解

### 1.1 非对称密码：一对钥匙

密钥登录建立在 **非对称密码** 上。一次生成会得到：

- **私钥（Private Key）**：保密。能对数据做 **数字签名**。相当于印章。
- **公钥（Public Key）**：可以公开。只能用来 **验证** 对应私钥的签名。相当于验印模板。

常用算法：

| 算法 | 建议 | 说明 |
|------|------|------|
| **Ed25519** | **首选** | 密钥短、速度快、实现简单、抗实现失误能力好。现代 OpenSSH / Windows 11 均支持。 |
| RSA 4096 | 兼容老设备时使用 | 老旧网络设备、某些嵌入式 Unix 可能只认 RSA。 |
| ECDSA | 可用，但不如 Ed25519 | 曲线参数选择更敏感。 |
| DSA / ssh-dss | **禁止** | 已过时，默认禁用。 |

密码登录是「把口令送到服务器比对」；密钥登录是「服务器出一道题，客户端用私钥签名，服务器用公钥验签」。私钥不会离开本机。

### 1.2 一次密钥登录实际发生了什么

简化后的流程（对应 SSH 协议中的 `publickey` 认证方法）：

```
客户端                                           服务器 sshd
  |                                                |
  |  1. TCP 连接（默认 22）                          |
  |----------------------------------------------->|
  |  2. 版本交换、算法协商、密钥交换                  |
  |     （ECDH 等，生成本次会话的对称密钥）           |
  |     同时校验服务器主机密钥 vs known_hosts        |
  |<---------------------------------------------->|
  |  3. 认证：我要用公钥证明身份                      |
  |     USERAUTH_REQUEST (user, publickey, 公钥)    |
  |----------------------------------------------->|
  |                                                | 在 authorized_keys 里找这把公钥
  |  4. PK_OK：这把钥匙登记过，请签名证明你持有私钥   |
  |<-----------------------------------------------|
  |  5. 用私钥对「会话标识」做数字签名                 |
  |----------------------------------------------->|
  |                                                | 用公钥验签
  |  6. SUCCESS：开会话（shell / sftp / 远程命令）    |
  |<-----------------------------------------------|
```

要点：

1. **第 2 步** 解决「信道保密」和「这是不是那台服务器」。
2. **第 3–5 步** 解决「你是不是这个账号」。服务器只保存公钥，无法从公钥推出私钥。
3. 即便有人截获全部网络流量，也拿不到私钥，也不能伪造签名（在算法安全的前提下）。
4. 若私钥文件上还加了 **口令短语（passphrase）**，硬盘被复制后，没有口令短语也解不开私钥。那是第二道锁，锁在客户端本地。

### 1.3 服务器凭什么相信这把公钥

用户家目录中的：

```text
~/.ssh/authorized_keys
```

每一行一把公钥。sshd 在认证时：

1. 确认配置允许公钥认证（`PubkeyAuthentication yes`）。
2. 按 `AuthorizedKeysFile` 找到该文件。
3. 核对权限（`StrictModes`）：家目录、`.ssh`、`authorized_keys` 不能被别人写。
4. 比对客户端出示的公钥是否在列表中。
5. 验签成功才放行。

因此：**权限过宽会直接导致密钥登录失败**。这是最常见的「配置了却连不上」原因。

### 1.4 和密码登录对比

| | 密码登录 | 密钥登录 |
|--|----------|----------|
| 网络上传输什么 | 口令（在加密信道里） | 签名，不是私钥、也不是 Unix 密码 |
| 防爆破 | 弱。口令可被反复试 | 强。没有私钥就无法构造合法签名 |
| 运维体验 | 每次输入；脚本难写 | 可配合 ssh-agent 一次解锁多次用 |
| 主要风险 | 弱口令、撞库、键盘记录 | 私钥泄露、权限配错、agent 转发滥用 |

正确姿势是：**先配好密钥并确认能登录，再关闭密码登录。** 顺序反了会把自己锁在门外。

### 1.5 关键文件一览

**客户端（Windows / Linux 相同逻辑）：**

```text
~/.ssh/
├── id_ed25519          # 私钥，权限必须仅本人可读
├── id_ed25519.pub      # 公钥，可复制到服务器
├── config              # 可选，主机别名与参数
├── known_hosts         # 已信任的服务器主机密钥
└── authorized_keys     # 仅当本机也当服务器时才需要
```

**Linux / Unix 服务器：**

```text
/etc/ssh/sshd_config                 # sshd 主配置（或 Include 进来的 drop-in）
/etc/ssh/ssh_host_ed25519_key        # 主机私钥（系统所有，勿改、勿拷走）
/etc/ssh/ssh_host_ed25519_key.pub    # 主机公钥
~目标用户/.ssh/authorized_keys       # 允许登录该用户的客户端公钥列表
```

Windows 11 上 `~` 对应 `C:\Users\<用户名>`。Linux / Unix 上对应 `$HOME`。

---

## 2. 开始前的约定

下文示例统一使用：

| 项 | 示例值 | 请换成你的 |
|----|--------|------------|
| 服务器 IP 或域名 | `203.0.113.10` | 真实地址 |
| SSH 端口 | `22` | 若改过端口则同步改 |
| 服务器登录用户 | `deploy` | 普通用户，不要一上来就用 root |
| 客户端密钥注释 | `win11-workstation` / `linux-laptop` | 方便以后辨认是哪台机器 |

**全程保持一个已能登录的会话不要关**（密码登录或控制台均可）。新开第二个窗口测试密钥登录。等确认成功，再改「禁止密码」。

---

## 3. Linux / Unix 服务端配置

客户端生成密钥之前，服务器必须已经能接受 SSH 连接。本节只改服务器。

### 3.1 确认 OpenSSH 服务在运行

多数 Linux 发行版和现代 Unix 都用 OpenSSH。

**Debian / Ubuntu：**

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
sudo systemctl status ssh
```

较新 Ubuntu 的服务名是 `ssh`；若失败可试 `sshd`。

**RHEL / Rocky / Alma / Fedora：**

```bash
sudo dnf install -y openssh-server
sudo systemctl enable --now sshd
sudo systemctl status sshd
```

**Arch / Manjaro：**

```bash
sudo pacman -S openssh
sudo systemctl enable --now sshd
```

**FreeBSD：**

```sh
# /etc/rc.conf
sysrc sshd_enable=YES
service sshd start
sockstat -4 -l | grep sshd
```

**OpenBSD：** sshd 通常默认启用。配置文件仍是 `/etc/ssh/sshd_config`，改完后：

```sh
rcctl restart sshd
```

**Solaris 11 / illumos：**

```sh
svcs -a | grep ssh
svcadm enable network/ssh
svcadm restart network/ssh
```

**AIX（常见企业 Unix）：**

```sh
lslpp -l | grep -i openssh
startsrc -s sshd
# 配置多在 /etc/ssh/sshd_config
```

确认本机在听端口：

```bash
# Linux
ss -tlnp | grep ssh
# 或
sudo ss -tlnp | grep ':22'

# BSD
sockstat -4 -l | grep ssh
```

### 3.2 放行防火墙与安全组

密钥再正确，端口没开也连不上。

**firewalld（RHEL 系）：**

```bash
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload
```

若 SSH 不在 22 端口：

```bash
sudo firewall-cmd --permanent --add-port=2222/tcp
sudo firewall-cmd --reload
```

**ufw（Ubuntu）：**

```bash
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

**nftables / iptables：** 自行放行对应 TCP 端口，这里不展开。

**FreeBSD pf 示例：** 在 `pf.conf` 中允许 `proto tcp to port 22` 后 `pfctl -f /etc/pf.conf`。

云主机还要在 **安全组 / 网络 ACL** 放行来源 IP 到 SSH 端口。这与操作系统防火墙是两层。

### 3.3 创建专用登录用户（推荐）

不要把日常密钥绑在 root 上。

```bash
sudo adduser deploy          # Debian 系
# 或
sudo useradd -m -s /bin/bash deploy
sudo passwd deploy           # 先设一个临时密码，仅用于第一次拷公钥
```

需要管理权限时再给 sudo：

```bash
sudo usermod -aG sudo deploy     # Debian / Ubuntu
sudo usermod -aG wheel deploy    # RHEL 系；FreeBSD 则用 pw groupmod wheel -m deploy
```

后续客户端都登录 `deploy`，需要 root 时用 `sudo`。

### 3.4 准备 `~/.ssh` 与权限（核心）

**在服务器上以目标用户执行**（或 `sudo -u deploy -H bash`）：

```bash
install -d -m 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
# 家目录不应对 others 可写
chmod go-w ~
```

权限目标：

| 路径 | 权限 | 属主 |
|------|------|------|
| `~` | `755` 或 `750`，**不能** `777` | 该用户 |
| `~/.ssh` | `700`（`drwx------`） | 该用户 |
| `~/.ssh/authorized_keys` | `600`（`-rw-------`） | 该用户 |

`sshd` 默认 `StrictModes yes`。家目录或 `.ssh` 对组/其他人可写时，公钥会被 **静默忽略**，表现就是 `Permission denied (publickey)`。

**SELinux（RHEL / Rocky 等）：** 若家目录不在默认路径，或文件是从别处拷来的，需要恢复上下文：

```bash
sudo restorecon -Rv ~/.ssh
```

**FreeBSD：** 注意家目录常在 `/usr/home/<user>`，`/home` 只是符号链接。以真实路径设权限即可。

### 3.5 打开公钥认证（先不要关密码）

主配置一般是 `/etc/ssh/sshd_config`。新发行版常把片段放在 `/etc/ssh/sshd_config.d/*.conf`，**Include 行生效时，drop-in 可能覆盖主文件**。改之前先看：

```bash
sudo sshd -T | grep -Ei 'pubkeyauthentication|authorizedkeysfile|passwordauthentication|permitrootlogin|port|challengeresponse|kbdinteractive'
```

`sshd -T` 打印的是 **最终生效值**，比只看配置文件更可靠。

建议在 `/etc/ssh/sshd_config.d/99-pubkey.conf`（若该目录存在）或主配置中明确：

```text
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AuthenticationMethods publickey,password
# 暂时保留密码，等密钥验证成功后再改
PasswordAuthentication yes
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin prohibit-password
StrictModes yes
```

说明：

- `PermitRootLogin prohibit-password`：root 只能密钥登录，不能密码。更严则改为 `no`，禁止 root 直接 SSH。
- `AuthenticationMethods publickey,password` 表示可以密钥或密码（逗号在部分版本表示「或」需核对；更稳妥是先不写这一行，等确认后再改成只允许 `publickey`）。
- OpenSSH 8+ 用 `KbdInteractiveAuthentication` 替代已废弃的 `ChallengeResponseAuthentication`。

检查语法并重载，**不要断开当前会话**：

```bash
sudo sshd -t && echo OK
# Debian / Ubuntu
sudo systemctl reload ssh
# RHEL / 多数 Linux
sudo systemctl reload sshd
# FreeBSD
sudo service sshd reload
```

若 `reload` 不够（极少配置项需要），再 `restart`。restart 前确保另有控制台或云厂商 VNC。

### 3.6 把客户端公钥写入 authorized_keys

公钥还没生成时，先看到第 4、5 章。生成后，服务器上 `authorized_keys` **一行一把钥匙**，例如：

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx win11-workstation
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy linux-laptop
```

注意：

- 必须是 **一行**，不要手动折行。
- 不要把私钥内容贴进来。私钥文件第一行是 `-----BEGIN OPENSSH PRIVATE KEY-----`。
- 可用选项收紧某一把钥匙，例如只允许某个办公网：

```text
from="203.0.113.0/24",no-agent-forwarding,no-port-forwarding ssh-ed25519 AAAAC3... win11-workstation
```

写入后再次确认权限：

```bash
ls -la ~/.ssh
stat -c '%a %n' ~/.ssh ~/.ssh/authorized_keys
```

### 3.7 Unix 与 Linux 的差异摘要

| 项目 | Linux | FreeBSD / OpenBSD | Solaris / AIX |
|------|-------|-------------------|---------------|
| 配置 | `/etc/ssh/sshd_config`，常有 `sshd_config.d` | 同样路径，少用 drop-in | 同样路径为主 |
| 服务管理 | systemd：`ssh` 或 `sshd` | `service sshd` / `rcctl` | `svcadm` / `src` |
| 权限模型 | 同 POSIX；另有 SELinux/AppArmor | POSIX + 可能有 MAC | POSIX |
| shell | 多为 bash | 默认可能是 `sh`/`tcsh`/`ksh` | `ksh` 常见 |
| 拷公钥工具 | 服务器不必装；客户端 `ssh-copy-id` 即可 | 同左（客户端是 Linux 时） | 同左 |

**原则相同：OpenSSH + 700/600 权限 + authorized_keys。** 只是服务命令不同。

---

## 4. Windows 11 客户端方案

Windows 11 自带 OpenSSH Client，与 Linux 的 `ssh` / `ssh-keygen` 命令兼容。这是 **首选**。PuTTY 适合老脚本和 `.ppk` 生态。WSL 则是「在 Windows 上使用完整 Linux 客户端」。

先打开 **Windows Terminal** 或 **PowerShell**（建议以普通用户，不要「以管理员身份」生成个人密钥，否则密钥会落到 Administrator 的主目录）。

### 4.1 方案 A（推荐）：系统自带 OpenSSH

#### 步骤 A1：确认客户端已安装

PowerShell：

```powershell
Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Client*'
ssh -V
where.exe ssh
```

正常应看到 `OpenSSH_for_Windows` 以及路径：

```text
C:\Windows\System32\OpenSSH\ssh.exe
```

若 State 不是 `Installed`：

```powershell
# 需要管理员 PowerShell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

也可：设置 → 应用 → 可选功能 → 添加功能 → **OpenSSH 客户端**。

> 不要和「OpenSSH 服务器」搞混。本机当客户端时 **不必** 安装 OpenSSH 服务器。

#### 步骤 A2：生成 Ed25519 密钥对

```powershell
# 建立 .ssh 目录（若不存在）
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null

ssh-keygen -t ed25519 -a 100 -C "win11-workstation"
```

提示含义：

1. `Enter file in which to save the key`：直接回车，使用默认  
   `C:\Users\<你>\.ssh\id_ed25519`
2. `Enter passphrase`：**建议设置** 口令短语。这不是服务器上 `deploy` 的 Unix 密码，而是加密本地私钥的口令。
3. 再输入一次确认。

`-a 100` 增加私钥加密的 KDF 轮数，暴力破解加密私钥更慢，生成会稍慢几秒。

若必须对接只认 RSA 的老 Unix：

```powershell
ssh-keygen -t rsa -b 4096 -a 100 -C "win11-workstation-rsa"
```

完成后应有：

```text
C:\Users\<你>\.ssh\id_ed25519        # 私钥，绝不外传
C:\Users\<你>\.ssh\id_ed25519.pub    # 公钥，要拷到服务器
```

查看公钥（稍后要贴到服务器或通过管道传过去）：

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

#### 步骤 A3：收紧私钥 ACL（Windows 特有，必做）

Linux 用 `chmod 600`。Windows OpenSSH 用 NTFS ACL：私钥若对「Users / Authenticated Users」可读，会拒绝使用并报：

```text
WARNING: UNPROTECTED PRIVATE KEY FILE!
Permissions for '...\id_ed25519' are too open.
```

在 **PowerShell** 中执行：

```powershell
$key = "$env:USERPROFILE\.ssh\id_ed25519"
icacls $key /inheritance:r
icacls $key /grant:r "$($env:USERNAME):(R)"
icacls $key
```

理想输出里只有你的用户 `(R)`，没有 `Everyone`、`Users`。

`.ssh` 目录也可限制：

```powershell
icacls "$env:USERPROFILE\.ssh" /inheritance:r
icacls "$env:USERPROFILE\.ssh" /grant:r "$($env:USERNAME):(OI)(CI)(F)"
```

#### 步骤 A4：把公钥安装到 Linux / Unix 服务器

Windows **通常没有** `ssh-copy-id`。用下面任一方法。此时服务器还需允许 **密码登录一次**。

**方法 1：一条管道（推荐）**

```powershell
$type = Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" -Raw
ssh deploy@203.0.113.10 "umask 077; mkdir -p ~/.ssh; chmod 700 ~/.ssh; touch ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; grep -qxF '$($type.Trim())' ~/.ssh/authorized_keys || echo '$($type.Trim())' >> ~/.ssh/authorized_keys"
```

按提示输入 **服务器用户 deploy 的密码**（仅此一次）。命令会：

- 创建 `~/.ssh`
- 追加公钥（已存在则不重复）
- 设置 700/600

若服务器 SSH 端口不是 22：

```powershell
ssh -p 2222 deploy@203.0.113.10 "..."
```

**方法 2：先 scp 再手动追加（适合不习惯复杂引号时）**

```powershell
scp $env:USERPROFILE\.ssh\id_ed25519.pub deploy@203.0.113.10:~/id_ed25519.pub
ssh deploy@203.0.113.10
```

登录服务器后：

```bash
umask 077
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
cat ~/id_ed25519.pub >> ~/.ssh/authorized_keys
rm ~/id_ed25519.pub
# 确认没有折行、没有把私钥贴进去
cat ~/.ssh/authorized_keys
```

**方法 3：云控制台 / 虚拟机串口**

若还不能密码 SSH（例如已关密码但没配钥匙），用厂商 VNC、物理控制台或 `virt-manager` 登录，把 `.pub` 内容手工追加到 `authorized_keys`。

#### 步骤 A5：第一次用密钥登录

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 deploy@203.0.113.10
```

第一次会问主机指纹：

```text
The authenticity of host '203.0.113.10 (203.0.113.10)' can't be established.
ED25519 key fingerprint is SHA256:xxxxxxxx.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

应事先从 **另一可信渠道**（云控制台、机房同事、`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`）核对指纹，再输入 `yes`。指纹写入 `C:\Users\<你>\.ssh\known_hosts`。

若私钥有 passphrase，会再问一次。成功则直接进入 Linux / Unix shell，**不再要 Unix 密码**。

指定端口、详细日志（排错）：

```powershell
ssh -p 2222 -i $env:USERPROFILE\.ssh\id_ed25519 deploy@203.0.113.10
ssh -vvv -i $env:USERPROFILE\.ssh\id_ed25519 deploy@203.0.113.10
```

`-vvv` 里若出现 `Offering public key` 随后 `Authentication succeeded (publickey)`，说明密钥路径已走通。

#### 步骤 A6：写入 SSH config，免每次敲参数

编辑（没有就新建）：

```text
C:\Users\<你>\.ssh\config
```

可用记事本，**必须是 UTF-8，不要用 Word**。内容示例：

```ssh-config
Host myserver
    HostName 203.0.113.10
    User deploy
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

之后只需：

```powershell
ssh myserver
```

`IdentitiesOnly yes` 避免 ssh-agent 里钥匙太多，服务器还没试到正确那把就断开（部分 sshd 有 `MaxAuthTries` 限制）。

多台服务器就写多个 `Host` 段。可用通配：

```ssh-config
Host *.example.com
    User deploy
    IdentityFile ~/.ssh/id_ed25519
```

#### 步骤 A7：启动 ssh-agent，避免反复输入 passphrase

Windows 的 `ssh-agent` 是 **系统服务**，默认常为 Disabled。

**管理员 PowerShell：**

```powershell
Get-Service ssh-agent
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service ssh-agent
```

**普通用户 PowerShell：**

```powershell
ssh-add $env:USERPROFILE\.ssh\id_ed25519
ssh-add -l
```

输入一次 passphrase 后，本机后续 `ssh myserver`、`scp`、`git` 都可复用这把已解锁的钥匙。锁屏后是否仍保留因版本而异；重启后通常要再 `ssh-add` 一次（Windows OpenSSH 较新版本可把钥匙持久化到 agent，视版本而定）。

查看已加载：

```powershell
ssh-add -l
```

删除已加载（不删除磁盘文件）：

```powershell
ssh-add -d $env:USERPROFILE\.ssh\id_ed25519
# 或清空全部
ssh-add -D
```

---

### 4.2 方案 B：PuTTY + PuTTYgen（.ppk 生态）

适合：原有自动化依赖 Pageant、WinSCP 使用 `.ppk`、或公司只发 PuTTY。

#### 步骤 B1：安装

从 [PuTTY 官网](https://www.chiark.greenend.org.uk/~sgtatham/putty/) 安装，包含 `putty.exe`、`puttygen.exe`、`pageant.exe`、`pscp.exe`、`plink.exe`。

#### 步骤 B2：生成或转换密钥

**新生成：**

1. 打开 PuTTYgen。
2. Parameters：Type of key 选 **Ed25519**（老版本若无则选 RSA 4096）。
3. 点 Generate，移动鼠标采集熵。
4. Key comment 填 `win11-putty`。
5. Key passphrase 建议填写。
6. **Save private key** 存为例如 `C:\Users\<你>\.ssh\id_ed25519.ppk`。
7. 上方 **Public key for pasting into OpenSSH authorized_keys file** 整行复制，这才是服务器要的格式。不要把 `.ppk` 传到服务器。

**已有 OpenSSH 私钥时转换：**

1. PuTTYgen → Conversions → Import key → 选 `id_ed25519`。
2. 输入 passphrase。
3. Save private key 得到 `.ppk`。

反向（`.ppk` 转 OpenSSH，给 Windows 自带 ssh.exe 用）：

- Conversions → Export OpenSSH key

#### 步骤 B3：把 OpenSSH 格式公钥写入服务器

与方案 A 相同：把 PuTTYgen 文本框里那一行追加进服务器 `authorized_keys`。可用 PuTTY 先密码登录再粘贴，或用 `pscp`。

#### 步骤 B4：PuTTY 会话配置

1. Session：Host Name 填 `deploy@203.0.113.10` 或 Host 填 IP、Connection → Data 填用户名。
2. Connection → SSH → Auth → Credentials：Private key file 选 `.ppk`。
3. Connection → SSH 可勾选启用压缩等，非必须。
4. 回到 Session，Saved Sessions 起名 `myserver`，Save。
5. Open。首次同样核对主机指纹。

#### 步骤 B5：Pageant（PuTTY 的 agent）

1. 运行 Pageant。
2. Add Key，选 `.ppk`，输入 passphrase。
3. PuTTY 会话里可不再指定 key 文件，会自动向 Pageant 要签名。
4. 把 Pageant 放进开机启动，可减少重复输入。注意：已解锁的钥匙等同于「当前登录会话里的身份」，离开座位应锁屏。

WinSCP、部分 GUI 也可勾选 “Attempt authentication using Pageant”。

---

### 4.3 方案 C：WSL2（在 Windows 上用 Linux 客户端）

若你更熟悉 Linux 命令，或要使用真正的 `ssh-copy-id`：

```powershell
wsl --install
```

重启后进入 Ubuntu（或其他发行版），然后 **完全按第 5 章 Linux 客户端** 操作。注意：

- WSL 里的 `~/.ssh` 是 Linux 文件系统里的，**不是** `C:\Users\...\ .ssh`。两套钥匙互不相通，除非你主动复制。
- 可以从 WSL 读取 Windows 文件：`/mnt/c/Users/<你>/.ssh/`，但权限和 systemd 的 ssh-agent 行为与原生 Linux 略有差异。更干净的做法是 **在 WSL 内单独生成一把钥匙**。

---

### 4.4 Windows 11 常用连接命令对照

| 目的 | OpenSSH（PowerShell / Terminal） | PuTTY 系 |
|------|----------------------------------|----------|
| 登录 | `ssh myserver` | `putty -load myserver` |
| 拷文件到服务器 | `scp .\app.tar.gz myserver:/tmp/` | `pscp .\app.tar.gz deploy@host:/tmp/` |
| 从服务器拷回 | `scp myserver:/var/log/syslog .` | `pscp deploy@host:/var/log/syslog .` |
| SFTP | `sftp myserver` | WinSCP / `psftp` |
| 远程执行一条命令 | `ssh myserver 'uname -a'` | `plink -load myserver uname -a` |

密钥登录配好后，这些命令都不再要 Unix 密码；最多问本地 passphrase / agent。

---

## 5. Linux 客户端方案

适用于 Ubuntu、Debian、Fedora、Arch、openSUSE 等作为 **你自己的电脑**。树莓派、另一台跳板机同样适用。

### 5.1 安装客户端

多数桌面发行版已带 `openssh-client`。没有则：

```bash
# Debian / Ubuntu
sudo apt install -y openssh-client

# RHEL / Fedora
sudo dnf install -y openssh-clients

# Arch
sudo pacman -S openssh
```

```bash
ssh -V
```

### 5.2 生成密钥

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -a 100 -C "linux-laptop"
```

默认路径：`~/.ssh/id_ed25519` 与 `~/.ssh/id_ed25519.pub`。

务必设 passphrase。确认权限：

```bash
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
ls -l ~/.ssh/id_ed25519*
```

私钥必须是 `-rw-------`。若曾用 root 生成或从 U 盘拷来，属主不对也会失败。

只认 RSA 的老 Unix：

```bash
ssh-keygen -t rsa -b 4096 -a 100 -C "linux-laptop-rsa"
```

### 5.3 安装公钥到服务器（ssh-copy-id）

这是 Linux 客户端相对 Windows 最省事的一步：

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub deploy@203.0.113.10
```

非 22 端口：

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub -p 2222 deploy@203.0.113.10
```

它会密码登录一次，在远端创建 `.ssh`、追加公钥并设权限。重复执行一般不会插入重复行（仍建议事后 `cat` 看一眼）。

没有 `ssh-copy-id` 时的等价手工命令：

```bash
ssh deploy@203.0.113.10 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys' < ~/.ssh/id_ed25519.pub
```

### 5.4 登录验证

```bash
ssh -i ~/.ssh/id_ed25519 deploy@203.0.113.10
# 或默认就会找 id_ed25519 / id_rsa
ssh deploy@203.0.113.10
```

详细日志：

```bash
ssh -vvv deploy@203.0.113.10
```

### 5.5 客户端 config

```bash
nano ~/.ssh/config
chmod 600 ~/.ssh/config
```

```ssh-config
Host myserver
    HostName 203.0.113.10
    User deploy
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 60
    ServerAliveCountMax 3

# 通过跳板机访问内网（可选）
Host inner
    HostName 10.0.0.8
    User deploy
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump myserver
```

之后：`ssh myserver`、`scp ./file myserver:~/`、`rsync -avz ./dir/ myserver:~/dir/`。

### 5.6 ssh-agent 与桌面钥匙环

**当前终端会话：**

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
ssh-add -l
```

**systemd 用户服务（无图形的机器上更干净）：**

```bash
systemctl --user enable --now ssh-agent
```

需在 `~/.bashrc` 或 `~/.profile` 中：

```bash
export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-agent.socket"
```

具体 socket 路径以发行版 unit 为准：`systemctl --user cat ssh-agent`。

**GNOME / KDE：** 首次使用密钥时钥匙环会弹出，可勾选「登录时自动解锁」。登录桌面后 agent 中已有钥匙，终端里 `ssh-add -l` 能看到。

**macOS 作为 Unix 客户端时（补充）：**

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519
```

并在 `~/.ssh/config` 加：

```ssh-config
Host *
    AddKeysToAgent yes
    UseKeychain yes
    IdentityFile ~/.ssh/id_ed25519
```

### 5.7 一台 Linux 客户端管理多把钥匙

```ssh-config
Host gitlab.com
    IdentityFile ~/.ssh/id_ed25519_gitlab
    IdentitiesOnly yes

Host myserver
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

工作钥匙、个人 Git、生产跳板 **分开**，某一把泄露时便于单独作废（从对应 `authorized_keys` 删那一行）。

---

## 6. 服务端：确认密钥可用后再关闭密码

**另开一个终端**，确保 `ssh myserver` 不输入 Unix 密码也能进。当前旧会话先别关。

然后在服务器上把生效配置改为只允许公钥：

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
PermitRootLogin no
```

若仍 Include 了发行版默认文件，其中可能写着 `PasswordAuthentication yes`，要用 **更晚加载的 drop-in** 覆盖，或直接改那个文件。以 `sudo sshd -T | grep passwordauthentication` 为准。

```bash
sudo sshd -t && sudo systemctl reload sshd   # 或 reload ssh
```

**立刻用第三个窗口再登录一次。** 失败就回到旧会话改回去。

可用普通用户测试「密码已被拒绝」：

```bash
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no deploy@203.0.113.10
```

应得到 `Permission denied`。这表示密码通道已关。

---

## 7. 端到端核对清单

按顺序打勾：

1. 服务器 `sshd` 在跑，防火墙 / 安全组放行端口。
2. 目标用户存在，家目录属主正确，`~/.ssh` 为 `700`，`authorized_keys` 为 `600`。
3. `sshd -T` 显示 `pubkeyauthentication yes`。
4. 客户端生成 Ed25519（或 RSA 4096），私钥权限 / Windows ACL 已收紧。
5. 公钥 **一行** 出现在服务器 `authorized_keys`，不是私钥。
6. 客户端 `ssh -vvv` 出现 `Authentication succeeded (publickey)`。
7. 新开会话验证成功后，再关 `PasswordAuthentication`。
8. 关闭密码后再验证一次密钥登录，并确认密码登录失败。

---

## 8. 排错

### 8.1 Permission denied (publickey)

服务器上看原因（权限允许时）：

```bash
# Debian / Ubuntu
sudo journalctl -u ssh -e
# RHEL
sudo journalctl -u sshd -e
# 通用
sudo grep sshd /var/log/auth.log     # Debian
sudo grep sshd /var/log/secure       # RHEL
sudo grep sshd /var/log/authlog      # 部分 BSD
```

常见原因：

| 现象 / 日志 | 处理 |
|-------------|------|
| `Authentication refused: bad ownership or modes` | 修 `~`、`~/.ssh`、`authorized_keys` 权限与属主 |
| 客户端根本没有 `Offering public key` | `-i` 路径错；Windows 用了别人的主目录；config 未生效 |
| 提供了钥匙但服务器忽略 | 公钥算法被 `PubkeyAcceptedAlgorithms` 关掉；或文件折行 |
| SELinux `avc: denied` | `restorecon -Rv ~/.ssh` |
| `Too many authentication failures` | agent 里钥匙太多，加 `IdentitiesOnly yes` |
| 登录用户错了 | `authorized_keys` 在 `deploy` 家目录，你却 `ssh root@...` |

客户端对照：

```bash
ssh -vvv -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 deploy@203.0.113.10
```

Windows 把路径换成 `$env:USERPROFILE\.ssh\id_ed25519`。

### 8.2 UNPROTECTED PRIVATE KEY FILE（Windows / Linux 都可能）

- Linux：`chmod 600 ~/.ssh/id_ed25519`
- Windows：按 4.1 步骤 A3 用 `icacls` 去掉继承，只留给自己读

### 8.3 Host key verification failed

服务器重装过系统后主机密钥会变。确认确实是你重装的，而不是被劫持，再：

```bash
ssh-keygen -R 203.0.113.10
```

Windows 同样可在 PowerShell 里运行这条（自带 OpenSSH 提供 `ssh-keygen`）。然后重新核对指纹并连接。

### 8.4 Connection refused / timed out

- 服务没起：`systemctl status sshd`
- 端口改过：客户端要 `-p`
- 防火墙 / 安全组 / 公司出口拦截 22：换端口或走 VPN，而不是关防火墙了事
- 服务器只听 `ListenAddress 127.0.0.1`：改回需要的网卡地址

### 8.5 能密钥登录，交互很慢

多半是服务器 DNS 反向解析超时：

```text
UseDNS no
GSSAPIAuthentication no
```

`sshd -t` 后 reload。客户端也可：

```ssh-config
Host myserver
    GSSAPIAuthentication no
```

---

## 9. 加固与运维习惯

在密钥登录已经稳定的前提下，再考虑下面这些。**不要一次改十个选项再测试**，否则难以回滚。

1. **算法**：新系统优先 Ed25519；老 Unix 并存一把 RSA 4096。
2. **私钥 passphrase + agent**：磁盘加密不能替代 passphrase；agent 不能替代锁屏。
3. **关闭密码与 root 直登**：见第 6 节。
4. **限制来源**：`sshd_config` 的 `AllowUsers deploy`、`AllowGroups sshusers`，或 `authorized_keys` 的 `from=`。
5. **改端口不是保密**，只能减少扫默认 22 的噪音。改了必须同步防火墙与客户端 `Port`。
6. **不要** 把私钥放进 Git、网盘、聊天记录、邮件。作废一把钥匙 = 从所有 `authorized_keys` 删除对应那一行，并视情况轮换。
7. **agent 转发（`ssh -A`）有风险**：跳板被攻破等于你的钥匙被借去签名。能用 `ProxyJump` 就不要用长期 `-A`。
8. **硬件密钥（FIDO2 / YubiKey）**：`ssh-keygen -t ed25519-sk`，私钥操作必须触碰硬件。Windows 11 较新 OpenSSH 与现代 Linux 均支持，适合高敏感环境。
9. **审计**：定期 `cat ~/.ssh/authorized_keys`，删掉离职人员、报废笔记本对应的行。
10. **备份**：加密备份私钥（密码管理器附件、加密盘）。没有私钥且关了密码，只能走控制台。

示例：仅允许 `deploy`、仅公钥、限制算法（确认客户端都支持后再加）：

```text
AllowUsers deploy
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
# 按 OpenSSH 版本调整名称
PubkeyAcceptedAlgorithms ssh-ed25519,rsa-sha2-256,rsa-sha2-512
```

---

## 10. 原理与配置对照（为什么「按步骤做」就能通）

| 你做的操作 | 对应原理 |
|------------|----------|
| `ssh-keygen` | 在客户端生成用户密钥对 |
| 拷 `.pub` 到 `authorized_keys` | 服务器登记「以后认这把印章」 |
| `chmod 700/600` 或 Windows ACL | 满足 StrictModes，防止别人偷偷加钥匙 |
| `PubkeyAuthentication yes` | sshd 启用 publickey 方法 |
| `ssh -i 私钥` | 客户端用对应私钥完成挑战签名 |
| `ssh-agent` / Pageant | 把已解锁私钥留在内存，避免每次解密文件 |
| `known_hosts` 里的指纹 | 绑定服务器主机密钥，防中间人 |
| 关闭 `PasswordAuthentication` | 去掉弱口令通道，只留签名通道 |

到此，Linux/Unix 服务器 + Windows 11 / Linux 两套客户端的密钥登录闭环已经完整。先通密钥，再关密码，始终留一条已登录会话或控制台作为退路。
