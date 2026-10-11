#!/usr/bin/env bash
# Ubuntu 26.04 LTS 落地 VPS 一键安装。
# 参数已写死：SSH 22022，sing-box Shadowsocks 2022 监听 TCP+UDP 24443。
# 用法：sudo bash install.sh
set -euo pipefail

SSH_PORT=22022
SS_PORT=24443
SS_METHOD="2022-blake3-aes-256-gcm"
SS_PASSWORD='WaLb8NWiW90b6m5MtmJ0GiaVODUkPcsz0JAf2YphvV0='
SERVER_IP="150.66.49.113"
SS_URI='ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206V2FMYjhOV2lXOTBiNm01TXRtSjBHaWFWT0RVa1Bjc3owSkFmMllwaHZWMD0@150.66.49.113:24443#Landing-SS2022'

if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 root 执行：sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  echo "错误：$*" >&2
  exit 1
}

ipv6_enabled() {
  [[ -r /proc/sys/net/ipv6/conf/all/disable_ipv6 ]] || return 1
  [[ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6)" == "0" ]]
}

port_listening() {
  local proto="$1"
  local port="$2"
  if [[ "${proto}" == "tcp" ]]; then
    ss -lnt "sport = :${port}" | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }'
  else
    ss -lnu "sport = :${port}" | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }'
  fi
}

ufw_is_active() {
  local status
  status="$(ufw status)"
  grep -q '^Status: active' <<<"${status}"
}

remove_ufw_22() {
  local i line num
  for i in $(seq 1 30); do
    line="$(ufw status numbered | grep -E '\[[[:space:]]*[0-9]+\]' | grep -E '(^|[^0-9])22/tcp|OpenSSH' | head -n 1 || true)"
    [[ -z "${line}" ]] && return 0
    num="$(sed -n 's/.*\[ *\([0-9][0-9]*\)\].*/\1/p' <<<"${line}")"
    [[ -z "${num}" ]] && return 0
    ufw --force delete "${num}"
  done
}

write_revert_script() {
  cat > /root/revert-ssh-to-22.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 root 执行：sudo bash /root/revert-ssh-to-22.sh"
  exit 1
fi
rm -f /etc/systemd/system/ssh.socket.d/override.conf
rm -f /etc/ssh/sshd_config.d/99-port.conf
rmdir /etc/systemd/system/ssh.socket.d 2>/dev/null || true
systemctl daemon-reload
if systemctl cat ssh.socket >/dev/null 2>&1 && { systemctl is-enabled ssh.socket >/dev/null 2>&1 || systemctl is-active ssh.socket >/dev/null 2>&1; }; then
  systemctl restart ssh.socket
elif systemctl cat sshd.socket >/dev/null 2>&1 && { systemctl is-enabled sshd.socket >/dev/null 2>&1 || systemctl is-active sshd.socket >/dev/null 2>&1; }; then
  systemctl restart sshd.socket
elif systemctl cat ssh.service >/dev/null 2>&1; then
  systemctl restart ssh.service
else
  systemctl restart sshd.service
fi
ufw allow 22/tcp comment 'SSH restore' || true
echo "已尝试把 SSH 恢复到 22。请立刻另开窗口执行：ssh -p 22 用户名@150.66.49.113"
EOF
  chmod 700 /root/revert-ssh-to-22.sh
}

configure_ssh_port() {
  local socket_unit=""
  local use_socket=0

  if systemctl cat ssh.socket >/dev/null 2>&1; then
    socket_unit="ssh.socket"
  elif systemctl cat sshd.socket >/dev/null 2>&1; then
    socket_unit="sshd.socket"
  fi

  if [[ -n "${socket_unit}" ]]; then
    if systemctl is-enabled "${socket_unit}" >/dev/null 2>&1 || systemctl is-active "${socket_unit}" >/dev/null 2>&1; then
      use_socket=1
    fi
  fi

  sed -i -E 's/^[[:space:]]*Port[[:space:]]+/# Port moved to sshd_config.d\/99-port.conf: /' /etc/ssh/sshd_config
  mkdir -p /etc/ssh/sshd_config.d
  local extra
  shopt -s nullglob
  for extra in /etc/ssh/sshd_config.d/*.conf; do
    [[ "$(basename "${extra}")" == "99-port.conf" ]] && continue
    sed -i -E 's/^[[:space:]]*Port[[:space:]]+/# Port moved to 99-port.conf: /' "${extra}"
  done
  shopt -u nullglob

  cat > /etc/ssh/sshd_config.d/99-port.conf << EOF
Port ${SSH_PORT}
EOF

  if [[ "${use_socket}" -eq 1 ]]; then
    mkdir -p "/etc/systemd/system/${socket_unit}.d"
    if ipv6_enabled; then
      cat > "/etc/systemd/system/${socket_unit}.d/override.conf" << EOF
[Socket]
ListenStream=
BindIPv6Only=ipv6-only
ListenStream=0.0.0.0:${SSH_PORT}
ListenStream=[::]:${SSH_PORT}
EOF
    else
      cat > "/etc/systemd/system/${socket_unit}.d/override.conf" << EOF
[Socket]
ListenStream=
ListenStream=0.0.0.0:${SSH_PORT}
EOF
    fi
  fi

  if ! sshd -t; then
    bash /root/revert-ssh-to-22.sh || true
    die "sshd 配置校验失败，已尝试恢复到 22 端口"
  fi

  systemctl daemon-reload
  if [[ "${use_socket}" -eq 1 ]]; then
    if ! systemctl restart "${socket_unit}"; then
      bash /root/revert-ssh-to-22.sh || true
      die "重启 ${socket_unit} 失败，已尝试恢复到 22 端口"
    fi
  elif systemctl cat ssh.service >/dev/null 2>&1; then
    systemctl enable ssh.service
    if ! systemctl restart ssh.service; then
      bash /root/revert-ssh-to-22.sh || true
      die "重启 ssh.service 失败，已尝试恢复到 22 端口"
    fi
  else
    systemctl enable sshd.service
    if ! systemctl restart sshd.service; then
      bash /root/revert-ssh-to-22.sh || true
      die "重启 sshd.service 失败，已尝试恢复到 22 端口"
    fi
  fi

  sleep 1
  if ! port_listening tcp "${SSH_PORT}"; then
    echo "22022 没有监听成功，正在恢复 SSH。"
    bash /root/revert-ssh-to-22.sh || true
    die "SSH 端口修改失败，已尝试恢复。请查看：journalctl -u ${socket_unit:-ssh} -n 50 --no-pager"
  fi

  if port_listening tcp 22; then
    echo "警告：TCP 22 仍在监听。22022 已经可用，为避免锁死，防火墙暂时保留 22。"
    echo "请另开窗口用 ssh -p ${SSH_PORT} 登录成功后，再执行：ufw status numbered，并删除 22 规则。"
    return 0
  fi

  remove_ufw_22
}

write_singbox_config() {
  local listen_addr="0.0.0.0"
  if ipv6_enabled; then
    listen_addr="::"
  fi

  install -d -m 755 /etc/sing-box
  install -d -o sing-box -g sing-box -m 750 /var/lib/sing-box

  shopt -s nullglob
  local stray
  for stray in /etc/sing-box/*.json; do
    if [[ "$(basename "${stray}")" != "config.json" ]]; then
      mv "${stray}" "/root/$(basename "${stray}").disabled.$(date +%s)"
    fi
  done
  shopt -u nullglob

  cat > /etc/sing-box/config.json << EOF
{
  "log": {
    "level": "info",
    "timestamp": true
  },
  "inbounds": [
    {
      "type": "shadowsocks",
      "tag": "ss-in",
      "listen": "${listen_addr}",
      "listen_port": ${SS_PORT},
      "method": "${SS_METHOD}",
      "password": "${SS_PASSWORD}"
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}
EOF
  chown root:sing-box /etc/sing-box/config.json
  chmod 640 /etc/sing-box/config.json
}

install_singbox() {
  install -d -m 755 /etc/apt/keyrings
  curl -fsSL https://sing-box.app/gpg.key -o /etc/apt/keyrings/sagernet.asc
  chmod a+r /etc/apt/keyrings/sagernet.asc
  cat > /etc/apt/sources.list.d/sagernet.sources << 'EOF'
Types: deb
URIs: https://deb.sagernet.org/
Suites: *
Components: *
Enabled: yes
Signed-By: /etc/apt/keyrings/sagernet.asc
EOF
  apt-get update
  apt-get install -y sing-box
  systemctl stop sing-box >/dev/null 2>&1 || true
  write_singbox_config
  sing-box -D /var/lib/sing-box -C /etc/sing-box check
  systemctl enable sing-box
  systemctl restart sing-box
  sleep 1
  systemctl is-active --quiet sing-box || die "sing-box 没有运行。查看日志：journalctl -u sing-box -n 80 --no-pager"
  port_listening tcp "${SS_PORT}" || die "TCP ${SS_PORT} 没有监听"
  port_listening udp "${SS_PORT}" || die "UDP ${SS_PORT} 没有监听"
}

configure_firewall() {
  ufw allow 22/tcp comment 'SSH temporary'
  ufw allow "${SSH_PORT}/tcp" comment 'SSH'
  ufw allow "${SS_PORT}/tcp" comment 'sing-box ss2022'
  ufw allow "${SS_PORT}/udp" comment 'sing-box ss2022'
  ufw default deny incoming
  ufw default allow outgoing
  ufw --force enable
  ufw_is_active || die "UFW 没有处于 active，已停止，避免改 SSH 后无法登录"
}

configure_fail2ban() {
  install -d -m 755 /etc/fail2ban/jail.d
  cat > /etc/fail2ban/jail.d/99-landing.local << EOF
[sshd]
enabled = true
port = ${SSH_PORT}
backend = systemd
maxretry = 5
findtime = 600
bantime = 3600
banaction = ufw
EOF
  systemctl enable fail2ban
  systemctl restart fail2ban
}

configure_bbr() {
  cat > /etc/sysctl.d/99-landing.conf << 'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
EOF
  modprobe tcp_bbr 2>/dev/null || true
  sysctl --system >/dev/null
}

write_credentials() {
  cat > /root/ss2022-landing.txt << EOF
服务器 IP: ${SERVER_IP}
SSH: ssh -p ${SSH_PORT} 用户名@${SERVER_IP}
协议: Shadowsocks 2022
方法: ${SS_METHOD}
端口: ${SS_PORT}
传输: TCP + UDP
密码: ${SS_PASSWORD}
分享链接: ${SS_URI}
EOF
  chmod 600 /root/ss2022-landing.txt
}

confirm_ssh_change() {
  cat << EOF

即将把 SSH 从 22 改到 ${SSH_PORT}。
改端口前请确认云厂商安全组已经放行：
  TCP ${SSH_PORT}
  TCP ${SS_PORT}
  UDP ${SS_PORT}
当前这个 SSH 窗口不会被主动断开。请勿关闭它，直到新窗口用下面的命令登录成功：
  ssh -p ${SSH_PORT} 用户名@${SERVER_IP}
如果改完后新窗口连不上，在当前窗口执行：
  bash /root/revert-ssh-to-22.sh

15 秒后继续。要取消请按 Ctrl+C。
EOF
  local i
  for i in 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1; do
    printf '\r  %2d 秒后修改 SSH 端口' "${i}"
    sleep 1
  done
  printf '\n'
}

verify_uri() {
  local generated
  generated="ss://$(printf '%s' "${SS_METHOD}:${SS_PASSWORD}" | base64 -w 0 | tr -d '=')@${SERVER_IP}:${SS_PORT}#Landing-SS2022"
  [[ "${generated}" == "${SS_URI}" ]] || die "内置分享链接和密码不一致：${generated}"
}

main() {
  verify_uri
  log "安装基础软件"
  apt-get update
  apt-get install -y ca-certificates curl iproute2 ufw fail2ban openssh-server

  log "开启 BBR"
  configure_bbr

  log "配置防火墙。先放行 22 和 ${SSH_PORT}，再启用 UFW"
  configure_firewall

  log "安装 sing-box 并写入 SS2022 配置"
  install_singbox

  log "写入 SSH 回滚脚本"
  write_revert_script

  confirm_ssh_change

  log "把 SSH 改为 ${SSH_PORT}"
  configure_ssh_port

  log "按新 SSH 端口配置 fail2ban"
  if ! configure_fail2ban; then
    echo "fail2ban 启动失败，不影响 sing-box。可稍后执行：journalctl -u fail2ban -n 50 --no-pager"
  fi

  write_credentials

  log "安装完成"
  cat << EOF

落地节点已经启动。
  IP           ${SERVER_IP}
  SSH          ${SSH_PORT}/tcp
  业务端口     ${SS_PORT}/tcp 和 ${SS_PORT}/udp
  加密         ${SS_METHOD}
  密码         ${SS_PASSWORD}
  分享链接     ${SS_URI}

凭据已写入 /root/ss2022-landing.txt
请马上另开一个终端测试：
  ssh -p ${SSH_PORT} 用户名@${SERVER_IP}
不要关闭当前窗口，直到新连接成功。
EOF
  ss -lntup | grep -E ":${SSH_PORT}|:${SS_PORT}" || true
  sysctl net.ipv4.tcp_congestion_control
}

main "$@"
