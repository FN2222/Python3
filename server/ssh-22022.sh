#!/usr/bin/env bash
# 只改香港落地的 SSH：监听 22022，并关闭本机的 22。
# 不安装、不重启 sing-box。
# 用法：sudo bash ssh-22022.sh
#       sudo bash ssh-22022.sh --force-ip
set -euo pipefail

SSH_PORT=22022
HK_IP="83.229.121.209"
TENCENT_PRIV="10.100.132.202"
BAIDU_PRIV="192.168.16.2"
FORCE_IP=0

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  echo "错误：$*" >&2
  exit 1
}

has_ip() {
  ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -qx -- "$1"
}

ipv6_enabled() {
  [[ -r /proc/sys/net/ipv6/conf/all/disable_ipv6 ]] || return 1
  [[ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6)" == "0" ]]
}

port_listening() {
  local port="$1"
  ss -lnt "sport = :${port}" 2>/dev/null | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }' && return 0
  ss -lnt | grep -E ":${port}\\b" >/dev/null
}

ufw_active() {
  command -v ufw >/dev/null 2>&1 || return 1
  LANG=C ufw status 2>/dev/null | grep -q '^Status: active'
}

detect_public_ip() {
  local url ip
  for url in https://api.ipify.org https://ifconfig.me/ip https://ipv4.icanhazip.com; do
    ip="$(curl -4 -fsSL --max-time 8 "${url}" 2>/dev/null || true)"
    ip="${ip//[[:space:]]/}"
    if [[ "${ip}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
      printf '%s' "${ip}"
      return 0
    fi
  done
  return 1
}

refuse_wrong_machine() {
  if has_ip "${TENCENT_PRIV}"; then
    die "这是腾讯入口，不能在这里改 SSH"
  fi
  if has_ip "${BAIDU_PRIV}"; then
    die "这是百度入口，不能在这里改 SSH"
  fi
  local detected=""
  if detected="$(detect_public_ip)"; then
    if [[ "${detected}" != "${HK_IP}" && "${FORCE_IP}" -ne 1 ]]; then
      die "公网 IP 是 ${detected}，不是香港 ${HK_IP}。确认后执行：bash $0 --force-ip"
    fi
    return 0
  fi
  if ss -lntup | grep -q 'sing-box'; then
    log "出网 IP 探测失败。本机正在跑 sing-box，按香港落地继续"
    return 0
  fi
  if [[ "${FORCE_IP}" -ne 1 ]]; then
    die "无法确认这是 ${HK_IP}。确认后执行：bash $0 --force-ip"
  fi
}

write_revert_script() {
  cat > /root/revert-ssh-to-22.sh << EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${EUID}" -ne 0 ]]; then
  echo "请用 root 执行：bash /root/revert-ssh-to-22.sh"
  exit 1
fi
rm -f /etc/systemd/system/ssh.socket.d/override.conf
rm -f /etc/systemd/system/sshd.socket.d/override.conf
rm -f /etc/ssh/sshd_config.d/99-port.conf
rmdir /etc/systemd/system/ssh.socket.d 2>/dev/null || true
rmdir /etc/systemd/system/sshd.socket.d 2>/dev/null || true
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
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp comment 'SSH restore' || true
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=ssh || true
  firewall-cmd --reload || true
fi
echo "已尝试把 SSH 恢复到 22。请立刻另开窗口执行：ssh -p 22 root@${HK_IP}"
EOF
  chmod 700 /root/revert-ssh-to-22.sh
}

allow_new_port() {
  if ufw_active; then
    ufw allow "${SSH_PORT}/tcp" comment 'SSH'
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-port="${SSH_PORT}/tcp"
    firewall-cmd --reload
  fi
  if command -v iptables >/dev/null 2>&1; then
    local policy
    policy="$(iptables -S INPUT 2>/dev/null | awk '$1=="-P" && $2=="INPUT" {print $3; exit}' || true)"
    if [[ "${policy}" == "DROP" || "${policy}" == "REJECT" ]]; then
      iptables -C INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT
    fi
  fi
}

close_old_port() {
  if ufw_active; then
    local line num
    for _ in $(seq 1 30); do
      line="$(LANG=C ufw status numbered | grep -E '\[[[:space:]]*[0-9]+\]' | grep -E '(^|[^0-9])22/tcp|OpenSSH' | head -n 1 || true)"
      [[ -z "${line}" ]] && break
      num="$(sed -n 's/.*\[ *\([0-9][0-9]*\)\].*/\1/p' <<<"${line}")"
      [[ -z "${num}" ]] && break
      ufw --force delete "${num}"
    done
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --remove-service=ssh || true
    firewall-cmd --permanent --remove-port=22/tcp || true
    firewall-cmd --reload || true
  fi
  if command -v iptables >/dev/null 2>&1; then
    while iptables -C INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null; do
      iptables -D INPUT -p tcp --dport 22 -j ACCEPT
    done
  fi
  if [[ -d /etc/fail2ban/jail.d ]]; then
    cat > /etc/fail2ban/jail.d/99-ssh-port.local << EOF
[sshd]
port = ${SSH_PORT}
EOF
    systemctl restart fail2ban >/dev/null 2>&1 || true
  fi
}

configure_ssh_port() {
  local socket_unit="" use_socket=0
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

  if [[ -f /etc/ssh/sshd_config ]] && ! grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config; then
    printf '\nInclude /etc/ssh/sshd_config.d/*.conf\n' >> /etc/ssh/sshd_config
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
    die "sshd 配置校验失败，已尝试恢复到 22"
  fi

  systemctl daemon-reload
  if [[ "${use_socket}" -eq 1 ]]; then
    systemctl restart "${socket_unit}" || { bash /root/revert-ssh-to-22.sh || true; die "重启 ${socket_unit} 失败，已尝试恢复到 22"; }
  elif systemctl cat ssh.service >/dev/null 2>&1; then
    systemctl enable ssh.service
    systemctl restart ssh.service || { bash /root/revert-ssh-to-22.sh || true; die "重启 ssh 失败，已尝试恢复到 22"; }
  else
    systemctl enable sshd.service
    systemctl restart sshd.service || { bash /root/revert-ssh-to-22.sh || true; die "重启 sshd 失败，已尝试恢复到 22"; }
  fi

  sleep 1
  if ! port_listening "${SSH_PORT}"; then
    bash /root/revert-ssh-to-22.sh || true
    die "22022 没有监听成功，已尝试恢复到 22"
  fi

  if port_listening 22; then
    echo "警告：TCP 22 仍在监听。22022 已经可用。为避免把当前连接锁死，本机防火墙暂时仍放行 22。"
    echo "请另开窗口执行：ssh -p ${SSH_PORT} root@${HK_IP}"
    echo "登录成功后把结果发出来，再继续关闭 22。"
    ss -lntup | grep -E ':22|:22022' || true
    return 0
  fi

  close_old_port
}

confirm() {
  cat << EOF

即将把 SSH 改到 ${SSH_PORT}，并关闭本机的 22。
sing-box 的 24443 不会动。当前这个窗口不会主动断开。

改之前，香港面板的防火墙里必须已经放行 TCP ${SSH_PORT}。
面板里的 22 先留着。等新窗口用下面的命令登录成功后，再从面板删掉 22：
  ssh -p ${SSH_PORT} root@${HK_IP}

如果新窗口连不上，不要关闭当前窗口，执行：
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

main() {
  if [[ "${1:-}" == "--force-ip" ]]; then
    FORCE_IP=1
  elif [[ -n "${1:-}" ]]; then
    die "未知参数：${1}。只支持 --force-ip"
  fi
  [[ "${EUID}" -eq 0 ]] || die "请用 root 执行：bash $0"
  command -v systemctl >/dev/null 2>&1 || die "没有 systemd，不能自动改 SSH 端口"
  command -v sshd >/dev/null 2>&1 || die "没有 sshd"
  refuse_wrong_machine
  log "先放行 ${SSH_PORT}，再切换端口"
  allow_new_port
  write_revert_script
  confirm
  log "切换 SSH 到 ${SSH_PORT}"
  configure_ssh_port
  log "完成"
  cat << EOF

本机 SSH 现在监听 ${SSH_PORT}。
请立刻另开一个窗口测试，不要关闭当前窗口：
  ssh -p ${SSH_PORT} root@${HK_IP}
新窗口登录成功后，再到香港面板里删除 TCP 22。
连不上时，在当前窗口执行：
  bash /root/revert-ssh-to-22.sh
EOF
  ss -lntup | grep -E ':22|:22022' || true
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
