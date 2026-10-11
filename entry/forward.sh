#!/usr/bin/env bash
# 腾讯 / 百度入口一键转发。只做 TCP+UDP DNAT，不解密，不安装 sing-box。
# 在 10.100.132.202（腾讯）或 192.168.16.2（百度）上执行。
# 24443 -> 161.248.136.186:24443  IX 传输 A
# 24444 -> 138.252.162.176:24443  IX 传输 B
# 不修改 table ip po0relay，也不修改 table ip ix_forward。
# 用法：sudo bash forward.sh
#       sudo bash forward.sh --remove
#       bash forward.sh --render-nft eth0
set -euo pipefail

HK_IP="83.229.121.209"
TENCENT_IP="150.158.185.159"
BAIDU_IP="106.12.30.105"
TENCENT_PRIV="10.100.132.202"
BAIDU_PRIV="192.168.16.2"
IX_A_IP="161.248.136.186"
IX_B_IP="138.252.162.176"
IX_PORT=24443
ENTRY_PORT_A=24443
ENTRY_PORT_B=24444

ROLE=""
PUBLIC=""
PRIV=""
IFACE=""

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  echo "错误：$*" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "请用 root 执行：sudo bash $0"
  fi
}

has_ip() {
  ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -qx -- "$1"
}

validate_iface() {
  [[ "$1" =~ ^[A-Za-z0-9_.:-]{1,15}$ ]] || die "网卡名不合法：$1"
}

render_nft() {
  local iface="$1"
  local with_mss="${2:-full}"
  validate_iface "${iface}"
  cat << EOF
# ix-entry role=${ROLE:-example} public=${PUBLIC:-0.0.0.0} iface=${iface}
# ${ENTRY_PORT_A}/tcp+udp -> ${IX_A_IP}:${IX_PORT}
# ${ENTRY_PORT_B}/tcp+udp -> ${IX_B_IP}:${IX_PORT}
# po0relay and ix_forward stay untouched
table ip ix_entry {
  chain prerouting {
    type nat hook prerouting priority dstnat; policy accept;
    iifname "${iface}" tcp dport ${ENTRY_PORT_A} counter dnat to ${IX_A_IP}:${IX_PORT}
    iifname "${iface}" udp dport ${ENTRY_PORT_A} counter dnat to ${IX_A_IP}:${IX_PORT}
    iifname "${iface}" tcp dport ${ENTRY_PORT_B} counter dnat to ${IX_B_IP}:${IX_PORT}
    iifname "${iface}" udp dport ${ENTRY_PORT_B} counter dnat to ${IX_B_IP}:${IX_PORT}
  }

  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "${iface}" ip daddr ${IX_A_IP} counter masquerade
    oifname "${iface}" ip daddr ${IX_B_IP} counter masquerade
  }

  chain forward {
    type filter hook forward priority filter; policy accept;
    ct state established,related accept
    iifname "${iface}" oifname "${iface}" ip daddr ${IX_A_IP} tcp dport ${IX_PORT} accept
    iifname "${iface}" oifname "${iface}" ip daddr ${IX_A_IP} udp dport ${IX_PORT} accept
    iifname "${iface}" oifname "${iface}" ip daddr ${IX_B_IP} tcp dport ${IX_PORT} accept
    iifname "${iface}" oifname "${iface}" ip daddr ${IX_B_IP} udp dport ${IX_PORT} accept
  }
EOF
  if [[ "${with_mss}" == "full" ]]; then
    cat << EOF

  chain mss {
    type filter hook forward priority mangle; policy accept;
    tcp flags syn tcp option maxseg size set rt mtu
  }
EOF
  fi
  printf '}\n'
}

detect_role() {
  if has_ip "${TENCENT_PRIV}"; then
    ROLE="tencent"
    PUBLIC="${TENCENT_IP}"
    PRIV="${TENCENT_PRIV}"
  elif has_ip "${BAIDU_PRIV}"; then
    ROLE="baidu"
    PUBLIC="${BAIDU_IP}"
    PRIV="${BAIDU_PRIV}"
  else
    echo "本机 IPv4：" >&2
    ip -4 -o addr show >&2 || true
    die "没有找到腾讯内网 ${TENCENT_PRIV} 或百度内网 ${BAIDU_PRIV}"
  fi
  IFACE="$(ip -4 route show default | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}')"
  [[ -n "${IFACE}" ]] || die "没有默认路由，无法确定出口网卡"
  validate_iface "${IFACE}"
  ip -4 -o addr show dev "${IFACE}" | awk '{print $4}' | cut -d/ -f1 | grep -qx -- "${PRIV}" \
    || die "默认路由网卡 ${IFACE} 上没有 ${PRIV}"
}

apply_sysctl() {
  local line tmp="/etc/sysctl.d/99-ix-entry.conf.tmp"
  local lines=(
    "net.ipv4.ip_forward=1"
    "net.ipv4.conf.all.rp_filter=2"
    "net.ipv4.conf.default.rp_filter=2"
    "net.ipv4.conf.all.send_redirects=0"
    "net.ipv4.conf.default.send_redirects=0"
    "net.ipv4.conf.all.accept_redirects=0"
    "net.ipv4.conf.${IFACE}.rp_filter=2"
    "net.ipv4.conf.${IFACE}.send_redirects=0"
    "net.netfilter.nf_conntrack_udp_timeout=60"
    "net.netfilter.nf_conntrack_udp_timeout_stream=300"
  )
  modprobe nf_conntrack 2>/dev/null || true
  : > "${tmp}"
  for line in "${lines[@]}"; do
    if sysctl -w "${line}" >/dev/null 2>&1; then
      printf '%s\n' "${line}" >> "${tmp}"
    else
      echo "跳过内核不支持的参数: ${line}"
    fi
  done
  install -m 644 "${tmp}" /etc/sysctl.d/99-ix-entry.conf
  rm -f "${tmp}"
  [[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]] || die "ip_forward 没有打开"
}

ensure_nft() {
  if command -v nft >/dev/null 2>&1; then
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y nftables
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y nftables
  elif command -v yum >/dev/null 2>&1; then
    yum install -y nftables
  else
    die "没有 nft，也没有 apt/dnf/yum"
  fi
  command -v nft >/dev/null 2>&1 || die "nftables 安装后仍然没有 nft"
}

configure_ufw_if_active() {
  if ! command -v ufw >/dev/null 2>&1; then
    return 0
  fi
  if ! LANG=C ufw status 2>/dev/null | grep -q '^Status: active'; then
    return 0
  fi
  log "UFW 正在运行，放行 ${ENTRY_PORT_A} 和 ${ENTRY_PORT_B}，并允许转发"
  if [[ -f /etc/default/ufw ]]; then
    sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw
  fi
  if [[ -f /etc/ufw/sysctl.conf ]]; then
    if grep -q 'net/ipv4/ip_forward' /etc/ufw/sysctl.conf; then
      sed -i -E 's/^#?net\/ipv4\/ip_forward=.*/net\/ipv4\/ip_forward=1/' /etc/ufw/sysctl.conf
    else
      echo 'net/ipv4/ip_forward=1' >> /etc/ufw/sysctl.conf
    fi
  fi
  ufw allow "${ENTRY_PORT_A}/tcp" comment 'ix entry A'
  ufw allow "${ENTRY_PORT_A}/udp" comment 'ix entry A'
  ufw allow "${ENTRY_PORT_B}/tcp" comment 'ix entry B'
  ufw allow "${ENTRY_PORT_B}/udp" comment 'ix entry B'
  ufw route allow in on "${IFACE}" out on "${IFACE}" proto tcp to "${IX_A_IP}" port "${IX_PORT}"
  ufw route allow in on "${IFACE}" out on "${IFACE}" proto udp to "${IX_A_IP}" port "${IX_PORT}"
  ufw route allow in on "${IFACE}" out on "${IFACE}" proto tcp to "${IX_B_IP}" port "${IX_PORT}"
  ufw route allow in on "${IFACE}" out on "${IFACE}" proto udp to "${IX_B_IP}" port "${IX_PORT}"
  ufw reload
  sysctl -w net.ipv4.ip_forward=1 >/dev/null
}

warn_nftables_service() {
  if [[ -f /etc/nftables.conf ]] && grep -q 'flush ruleset' /etc/nftables.conf; then
    echo "警告：/etc/nftables.conf 里有 flush ruleset。如果 nftables 服务开机自启，重启后可能清掉全部转发，包括原来的规则。"
    echo "本次没有修改 /etc/nftables.conf。"
  fi
}

write_apply_script() {
  cat > /usr/local/sbin/ix-entry-apply.sh << EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
sysctl -w net.ipv4.ip_forward=1 >/dev/null
if [[ -f /etc/sysctl.d/99-ix-entry.conf ]]; then
  sysctl -p /etc/sysctl.d/99-ix-entry.conf >/dev/null 2>&1 || true
fi
nft delete table ip ix_entry 2>/dev/null || true
nft -f /etc/ix-entry.nft
if command -v iptables >/dev/null 2>&1; then
  policy="\$(iptables -S FORWARD 2>/dev/null | awk '\$1=="-P" && \$2=="FORWARD" {print \$3; exit}')"
  if [[ -n "\${policy}" && "\${policy}" != "ACCEPT" ]]; then
    iptables -C FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || iptables -I FORWARD 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    for ip in ${IX_A_IP} ${IX_B_IP}; do
      iptables -C FORWARD -d "\${ip}" -j ACCEPT 2>/dev/null || iptables -I FORWARD -d "\${ip}" -j ACCEPT
      iptables -C FORWARD -s "\${ip}" -j ACCEPT 2>/dev/null || iptables -I FORWARD -s "\${ip}" -j ACCEPT
    done
  fi
fi
EOF
  chmod 755 /usr/local/sbin/ix-entry-apply.sh
}

write_systemd_unit() {
  local nft_bin
  nft_bin="$(command -v nft)"
  cat > /etc/systemd/system/ix-entry.service << EOF
[Unit]
Description=Forward entry ports to IX
After=network-online.target nftables.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/local/sbin/ix-entry-apply.sh
ExecStop=-${nft_bin} delete table ip ix_entry

[Install]
WantedBy=multi-user.target
EOF
}

nft_syntax_ok() {
  local file="$1" rc=0
  ip netns delete ix-entry-check >/dev/null 2>&1 || true
  if ip netns add ix-entry-check >/dev/null 2>&1; then
    ip netns exec ix-entry-check nft -c -f "${file}" || rc=$?
    ip netns delete ix-entry-check >/dev/null 2>&1 || true
    return "${rc}"
  fi
  nft -c -f "${file}"
}

install_nft_rules() {
  ensure_nft
  warn_nftables_service
  render_nft "${IFACE}" full > /etc/ix-entry.nft
  if ! nft_syntax_ok /etc/ix-entry.nft; then
    echo "当前 nft 不支持 MSS 钳制，改为只做端口转发。"
    render_nft "${IFACE}" nomss > /etc/ix-entry.nft
    nft_syntax_ok /etc/ix-entry.nft || die "nft 规则语法检查失败"
  fi
  chmod 644 /etc/ix-entry.nft
  install -d -m 755 /usr/local/sbin
  write_apply_script
  if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    write_systemd_unit
    systemctl daemon-reload
    systemctl enable --now ix-entry.service
  else
    echo "警告：没有 systemd。规则现在生效，重启后需要再执行一次本脚本。"
    /usr/local/sbin/ix-entry-apply.sh
  fi
  nft list table ip ix_entry >/dev/null
}

install_firewalld_rules() {
  log "检测到 firewalld，使用 firewalld 转发。不另建 nft 表，避免转发两次。"
  firewall-cmd --permanent --add-port="${ENTRY_PORT_A}/tcp"
  firewall-cmd --permanent --add-port="${ENTRY_PORT_A}/udp"
  firewall-cmd --permanent --add-port="${ENTRY_PORT_B}/tcp"
  firewall-cmd --permanent --add-port="${ENTRY_PORT_B}/udp"
  firewall-cmd --permanent --add-forward-port="port=${ENTRY_PORT_A}:proto=tcp:toaddr=${IX_A_IP}:toport=${IX_PORT}"
  firewall-cmd --permanent --add-forward-port="port=${ENTRY_PORT_A}:proto=udp:toaddr=${IX_A_IP}:toport=${IX_PORT}"
  firewall-cmd --permanent --add-forward-port="port=${ENTRY_PORT_B}:proto=tcp:toaddr=${IX_B_IP}:toport=${IX_PORT}"
  firewall-cmd --permanent --add-forward-port="port=${ENTRY_PORT_B}:proto=udp:toaddr=${IX_B_IP}:toport=${IX_PORT}"
  firewall-cmd --permanent --add-masquerade
  firewall-cmd --permanent --add-forward || true
  firewall-cmd --reload
}

probe_ix() {
  local ip="$1" label="$2"
  if command -v ping >/dev/null 2>&1; then
    if ping -c 2 -W 2 "${ip}" >/dev/null 2>&1; then
      echo "ping ${label} ${ip} 通"
    else
      echo "警告：ping ${label} ${ip} 不通。规则已经写好，但这条 IX 现在可能不可达。"
    fi
  fi
  if command -v timeout >/dev/null 2>&1; then
    if timeout 3 bash -c "echo >/dev/tcp/${ip}/${IX_PORT}" >/dev/null 2>&1; then
      echo "TCP ${label} ${ip}:${IX_PORT} 可以连接"
    else
      echo "警告：TCP ${label} ${ip}:${IX_PORT} 连接失败。"
    fi
  fi
}

warn_local_listeners() {
  if ! command -v ss >/dev/null 2>&1; then
    return 0
  fi
  if ss -lntu | grep -E ":${ENTRY_PORT_A}\\b|:${ENTRY_PORT_B}\\b" >/dev/null 2>&1; then
    echo "提示：本机有进程监听 ${ENTRY_PORT_A} 或 ${ENTRY_PORT_B}。公网进来的包会在到达该进程之前被转走。"
    ss -lntu | grep -E ":${ENTRY_PORT_A}\\b|:${ENTRY_PORT_B}\\b" || true
  fi
}

print_summary() {
  cat << EOF

================ 入口转发已生效 ================

机器: ${ROLE}
内网: ${PRIV}  网卡: ${IFACE}
客户端填写的公网地址: ${PUBLIC}
香港落地: ${HK_IP}:${IX_PORT}（日常节点不要填这个地址）

转发（TCP 和 UDP 都转）：
  ${PUBLIC}:${ENTRY_PORT_A} -> ${IX_A_IP}:${IX_PORT}    IX 传输 A
  ${PUBLIC}:${ENTRY_PORT_B} -> ${IX_B_IP}:${IX_PORT}    IX 传输 B

原来的 po0relay、ix_forward 没有修改。
腾讯上的 20001、30001，百度上的 32001，都还在。
这个脚本没有安装 sing-box，也没有保存 SS 密码。

请在云控制台安全组或轻量防火墙放行：
  TCP ${ENTRY_PORT_A}
  UDP ${ENTRY_PORT_A}
  TCP ${ENTRY_PORT_B}
  UDP ${ENTRY_PORT_B}
来源用 0.0.0.0/0，或你家的公网 IP。

查看计数：nft list table ip ix_entry
取消这次转发：bash $0 --remove
EOF
}

install_entry() {
  command -v ip >/dev/null 2>&1 || die "没有 ip 命令，请先安装 iproute2"
  detect_role
  log "识别为 ${ROLE}，公网 ${PUBLIC}，内网 ${PRIV}，网卡 ${IFACE}"
  apply_sysctl
  configure_ufw_if_active
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    install_firewalld_rules
  else
    install_nft_rules
  fi
  warn_local_listeners
  probe_ix "${IX_A_IP}" "IX-A"
  probe_ix "${IX_B_IP}" "IX-B"
  print_summary
}

remove_rules() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now ix-entry.service >/dev/null 2>&1 || true
  fi
  rm -f /etc/systemd/system/ix-entry.service
  rm -f /usr/local/sbin/ix-entry-apply.sh
  rm -f /etc/ix-entry.nft
  if command -v nft >/dev/null 2>&1; then
    nft delete table ip ix_entry 2>/dev/null || true
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
  fi
  echo "已删除 ix_entry。原来的 po0relay / ix_forward 没有动。ip_forward 保持打开，旧转发还要用。"
}

main() {
  case "${1:-}" in
    --render-nft)
      [[ $# -eq 2 ]] || die "用法：bash forward.sh --render-nft <网卡名>"
      render_nft "$2" full
      ;;
    --remove)
      require_root
      remove_rules
      ;;
    "")
      require_root
      install_entry
      ;;
    *)
      die "未知参数：${1}"
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
