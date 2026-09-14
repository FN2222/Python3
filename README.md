# Python3

本仓库提供 **SSH 密钥登录**（公钥认证）的完整配置说明：原理、Linux / Unix 服务端，以及 Windows 11、Linux 两套客户端逐步方案。

## 文档

- **[SSH 密钥登录完整配置指南](docs/ssh-key-login.md)**
  - 主机密钥 vs 用户密钥、签名挑战原理
  - Linux / Unix 服务端（systemd、FreeBSD、Solaris、AIX）
  - Windows 11：系统 OpenSSH、PuTTY/Pageant、WSL2
  - Linux 客户端：`ssh-keygen`、`ssh-copy-id`、`ssh-agent`、`~/.ssh/config`
  - 关闭密码登录的顺序、排错与加固

正确用词是「密钥」。口语里的「秘钥登录」即本文所述方式。
