#!/usr/bin/env bash
# 香港落地一键安装：sing-box + Shadowsocks 2022。
# 只在 83.229.121.209 上执行。腾讯和百度入口请执行 entry/forward.sh。
# 用法：sudo bash install.sh
#       sudo bash install.sh --force-ip
set -euo pipefail

SS_PORT=24443
SS_METHOD="2022-blake3-aes-256-gcm"
SS_PASSWORD='qBhTDj3OZFq7pYUKdrNECJpc4AqA16fWQRb53SXwn7I='
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
SS_TOKEN=""
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

build_token() {
  local token
  token="$(printf '%s' "${SS_METHOD}:${SS_PASSWORD}" | base64 -w 0 | tr -d '=')"
  if [[ "${token}" == *+* || "${token}" == */* ]]; then
    token="$(printf '%s' "${SS_METHOD}:${SS_PASSWORD}" | base64 -w 0 | tr '+/' '-_' | tr -d '=')"
  fi
  SS_TOKEN="${token}"
}

ss_uri() {
  local host="$1" port="$2" name="$3"
  [[ -n "${SS_TOKEN}" ]] || die "分享链接还没有生成"
  printf 'ss://%s@%s:%s#%s\n' "${SS_TOKEN}" "${host}" "${port}" "${name}"
}

print_uris() {
  ss_uri "${TENCENT_IP}" "${ENTRY_PORT_A}" "Tencent-IX-A"
  ss_uri "${TENCENT_IP}" "${ENTRY_PORT_B}" "Tencent-IX-B"
  ss_uri "${BAIDU_IP}" "${ENTRY_PORT_A}" "Baidu-IX-A"
  ss_uri "${BAIDU_IP}" "${ENTRY_PORT_B}" "Baidu-IX-B"
  ss_uri "${HK_IP}" "${SS_PORT}" "HK-Direct-Test"
}

check_password() {
  local key_bytes
  printf '%s' "${SS_PASSWORD}" | base64 -d >/dev/null 2>&1 || die "密码不是合法 Base64"
  key_bytes="$(printf '%s' "${SS_PASSWORD}" | base64 -d | wc -c | tr -d '[:space:]')"
  [[ "${key_bytes}" == "32" ]] || die "密码解码后是 ${key_bytes} 字节，${SS_METHOD} 必须是 32 字节"
  [[ "${#SS_TOKEN}" -gt 20 ]] || die "分享链接生成失败"
}

port_listening() {
  local proto="$1" port="$2"
  if [[ "${proto}" == "tcp" ]]; then
    ss -lnt "sport = :${port}" 2>/dev/null | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }' && return 0
    ss -lnt | grep -E "(^|[[:space:]])${port}\\b|:${port}\\b" >/dev/null
  else
    ss -lnu "sport = :${port}" 2>/dev/null | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }' && return 0
    ss -lnu | grep -E "(^|[[:space:]])${port}\\b|:${port}\\b" >/dev/null
  fi
}

apply_sysctl_lines() {
  local dest="$1"
  shift
  local line tmp
  tmp="$(mktemp)"
  for line in "$@"; do
    if sysctl -w "${line}" >/dev/null 2>&1; then
      printf '%s\n' "${line}" >> "${tmp}"
    else
      echo "跳过内核不支持的参数: ${line}"
    fi
  done
  if [[ -s "${tmp}" ]]; then
    install -m 644 "${tmp}" "${dest}"
  fi
  rm -f "${tmp}"
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

refuse_entry_machines() {
  if has_ip "${TENCENT_PRIV}"; then
    die "这是腾讯入口 ${TENCENT_PRIV}，不能安装落地。请执行 entry/forward.sh"
  fi
  if has_ip "${BAIDU_PRIV}"; then
    die "这是百度入口 ${BAIDU_PRIV}，不能安装落地。请执行 entry/forward.sh"
  fi
}

confirm_public_ip() {
  local detected=""
  if detected="$(detect_public_ip)"; then
    if [[ "${detected}" != "${HK_IP}" && "${FORCE_IP}" -ne 1 ]]; then
      die "这台机器的公网 IP 是 ${detected}，不是香港落地 ${HK_IP}。确认就是这台机器后执行：bash $0 --force-ip"
    fi
    if [[ "${detected}" == "${HK_IP}" ]]; then
      log "公网 IP 核对通过：${detected}"
    else
      log "已按 --force-ip 继续。检测到的公网 IP 是 ${detected}"
    fi
  else
    log "出网 IP 探测失败"
    if [[ "${FORCE_IP}" -ne 1 ]]; then
      die "无法确认这是 ${HK_IP}。确认后执行：bash $0 --force-ip"
    fi
  fi
}

configure_bbr() {
  modprobe tcp_bbr 2>/dev/null || true
  apply_sysctl_lines /etc/sysctl.d/99-landing.conf \
    "net.core.default_qdisc=fq" \
    "net.ipv4.tcp_congestion_control=bbr" \
    "net.ipv4.tcp_fastopen=3" \
    "net.ipv4.tcp_mtu_probing=1" \
    "net.ipv4.tcp_slow_start_after_idle=0" \
    "net.core.rmem_max=16777216" \
    "net.core.wmem_max=16777216" \
    "net.ipv4.tcp_rmem=4096 87380 16777216" \
    "net.ipv4.tcp_wmem=4096 65536 16777216"
  if [[ "$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || true)" == "bbr" ]]; then
    log "BBR 已开启"
  else
    echo "警告：BBR 没有打开，sing-box 仍会继续安装。"
    sysctl net.ipv4.tcp_available_congestion_control || true
  fi
}

open_local_firewall() {
  if command -v ufw >/dev/null 2>&1 && LANG=C ufw status 2>/dev/null | grep -q '^Status: active'; then
    log "UFW 已启用，放行 ${SS_PORT}/tcp 和 ${SS_PORT}/udp"
    ufw allow "${SS_PORT}/tcp" comment 'sing-box ss2022'
    ufw allow "${SS_PORT}/udp" comment 'sing-box ss2022'
  else
    log "UFW 未启用，不改 UFW"
  fi

  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    log "firewalld 已启用，放行 ${SS_PORT}"
    firewall-cmd --permanent --add-port="${SS_PORT}/tcp"
    firewall-cmd --permanent --add-port="${SS_PORT}/udp"
    firewall-cmd --reload
  fi

  if command -v iptables >/dev/null 2>&1; then
    local policy
    policy="$(iptables -S INPUT 2>/dev/null | awk '$1=="-P" && $2=="INPUT" {print $3; exit}' || true)"
    if [[ "${policy}" == "DROP" || "${policy}" == "REJECT" ]]; then
      log "iptables INPUT 是 ${policy}，放行 ${SS_PORT}"
      iptables -C INPUT -p tcp --dport "${SS_PORT}" -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport "${SS_PORT}" -j ACCEPT
      iptables -C INPUT -p udp --dport "${SS_PORT}" -j ACCEPT 2>/dev/null || iptables -I INPUT -p udp --dport "${SS_PORT}" -j ACCEPT
      install -d -m 755 /usr/local/sbin
      cat > /usr/local/sbin/ss2022-input.sh << EOF
#!/usr/bin/env bash
set -euo pipefail
iptables -C INPUT -p tcp --dport ${SS_PORT} -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport ${SS_PORT} -j ACCEPT
iptables -C INPUT -p udp --dport ${SS_PORT} -j ACCEPT 2>/dev/null || iptables -I INPUT -p udp --dport ${SS_PORT} -j ACCEPT
EOF
      chmod 755 /usr/local/sbin/ss2022-input.sh
      cat > /etc/systemd/system/ss2022-input.service << EOF
[Unit]
Description=Allow SS2022 port ${SS_PORT}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/ss2022-input.sh

[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload
      systemctl enable ss2022-input.service
    fi
  fi
}

write_singbox_config() {
  local listen_addr="${1:-}"
  local svc_user
  if [[ -z "${listen_addr}" ]]; then
    listen_addr="0.0.0.0"
    if ipv6_enabled; then
      listen_addr="::"
    fi
  fi

  install -d -m 755 /etc/sing-box
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

  svc_user="$(systemctl show -p User --value sing-box 2>/dev/null || true)"
  if [[ -z "${svc_user}" ]]; then
    svc_user="root"
  fi
  if id "${svc_user}" >/dev/null 2>&1 && chown "root:${svc_user}" /etc/sing-box/config.json 2>/dev/null; then
    chmod 640 /etc/sing-box/config.json
    install -d -o "${svc_user}" -g "${svc_user}" -m 750 /var/lib/sing-box
  else
    chmod 644 /etc/sing-box/config.json
    install -d -m 755 /var/lib/sing-box
  fi
}

singbox_arch() {
  case "$(uname -m)" in
    x86_64) printf 'amd64' ;;
    aarch64 | arm64) printf 'arm64' ;;
    armv7l) printf 'armv7' ;;
    i386 | i686) printf '386' ;;
    *) die "不支持的架构：$(uname -m)" ;;
  esac
}

singbox_version() {
  local url version
  url="$(curl -fsSL -o /dev/null -w '%{url_effective}' https://github.com/SagerNet/sing-box/releases/latest)" || die "无法访问 sing-box 发布页"
  version="${url##*/}"
  version="${version#v}"
  [[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?$ ]] || die "无法确定 sing-box 版本：${url}"
  printf '%s' "${version}"
}

install_singbox() {
  local version arch deb
  version="$(singbox_version)"
  arch="$(singbox_arch)"
  deb="/tmp/sing-box_${version}_linux_${arch}.deb"
  log "下载 sing-box ${version} (${arch})"
  curl -fL --retry 3 --retry-delay 2 -o "${deb}" \
    "https://github.com/SagerNet/sing-box/releases/download/v${version}/sing-box_${version}_linux_${arch}.deb" \
    || die "sing-box 安装包下载失败"
  if ! dpkg --force-confold --force-confdef -i "${deb}"; then
    apt-get install -f -y || true
  fi
  rm -f "${deb}"
  command -v sing-box >/dev/null 2>&1 || die "sing-box 安装失败"
  if ! id sing-box >/dev/null 2>&1; then
    if command -v systemd-sysusers >/dev/null 2>&1; then
      systemd-sysusers sing-box.conf >/dev/null 2>&1 || true
    fi
  fi
  if ! id sing-box >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/sing-box --shell /usr/sbin/nologin sing-box
  fi
  systemctl stop sing-box >/dev/null 2>&1 || true
  write_singbox_config
  grep -F -q "${SS_PASSWORD}" /etc/sing-box/config.json || die "落地配置没有写入"
  if grep -F -q 'Gn1JUS14bLUHgv1cWDDp4A==' /etc/sing-box/config.json; then
    die "仍在使用 sing-box 安装包自带的示例配置"
  fi
  sing-box -D /var/lib/sing-box -C /etc/sing-box check || die "sing-box 配置检查失败"
  systemctl enable sing-box
  systemctl restart sing-box
  if ! wait_for_ports && grep -q '"listen": "::"' /etc/sing-box/config.json; then
    echo "IPv6 监听没有起来，改为 0.0.0.0 再试一次。"
    write_singbox_config "0.0.0.0"
    sing-box -D /var/lib/sing-box -C /etc/sing-box check || die "sing-box 配置检查失败"
    systemctl restart sing-box
  fi
  if ! wait_for_ports; then
    journalctl -u sing-box -n 80 --no-pager || true
    die "sing-box 没有同时监听 TCP 和 UDP ${SS_PORT}"
  fi
  sing-box version || true
}

wait_for_ports() {
  local _try
  for _try in 1 2 3 4 5; do
    if port_listening tcp "${SS_PORT}" && port_listening udp "${SS_PORT}"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

write_clash() {
  # clash-template-start
  cat > /root/ss2022-clash.yaml << EOF
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
ipv6: false
find-process-mode: strict
unified-delay: true
tcp-concurrent: true

dns:
  enable: true
  ipv6: false
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  default-nameserver:
    - 223.5.5.5
    - 119.29.29.29
  nameserver:
    - https://dns.alidns.com/dns-query
    - https://doh.pub/dns-query
  fallback:
    - https://1.1.1.1/dns-query#入口选择
    - https://dns.google/dns-query#入口选择
  fallback-filter:
    geoip: true
    geoip-code: CN
  proxy-server-nameserver:
    - 223.5.5.5
    - 119.29.29.29

proxies:
  - name: "腾讯-IX-A"
    type: ss
    server: ${TENCENT_IP}
    port: ${ENTRY_PORT_A}
    cipher: ${SS_METHOD}
    password: "${SS_PASSWORD}"
    udp: true
  - name: "腾讯-IX-B"
    type: ss
    server: ${TENCENT_IP}
    port: ${ENTRY_PORT_B}
    cipher: ${SS_METHOD}
    password: "${SS_PASSWORD}"
    udp: true
  - name: "百度-IX-A"
    type: ss
    server: ${BAIDU_IP}
    port: ${ENTRY_PORT_A}
    cipher: ${SS_METHOD}
    password: "${SS_PASSWORD}"
    udp: true
  - name: "百度-IX-B"
    type: ss
    server: ${BAIDU_IP}
    port: ${ENTRY_PORT_B}
    cipher: ${SS_METHOD}
    password: "${SS_PASSWORD}"
    udp: true
  - name: "香港直连-仅测试"
    type: ss
    server: ${HK_IP}
    port: ${SS_PORT}
    cipher: ${SS_METHOD}
    password: "${SS_PASSWORD}"
    udp: true

proxy-groups:
  - name: "入口选择"
    type: select
    proxies:
      - "自动选择"
      - "腾讯-IX-A"
      - "腾讯-IX-B"
      - "百度-IX-A"
      - "百度-IX-B"
      - "香港直连-仅测试"
  - name: "自动选择"
    type: url-test
    url: http://www.gstatic.com/generate_204
    interval: 300
    tolerance: 50
    lazy: true
    proxies:
      - "腾讯-IX-A"
      - "腾讯-IX-B"
      - "百度-IX-A"
      - "百度-IX-B"

rules:
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,169.254.0.0/16,DIRECT,no-resolve
  - IP-CIDR,224.0.0.0/4,DIRECT,no-resolve
  - MATCH,入口选择
EOF
  # clash-template-end
  chmod 600 /root/ss2022-clash.yaml
}

write_credentials() {
  local old_umask
  old_umask="$(umask)"
  umask 077
  {
    echo "香港落地: ${HK_IP}:${SS_PORT}"
    echo "加密: ${SS_METHOD}"
    echo "密码: ${SS_PASSWORD}"
    echo "IX 传输 A: ${IX_A_IP}:${IX_PORT}"
    echo "IX 传输 B: ${IX_B_IP}:${IX_PORT}"
    echo "腾讯入口: ${TENCENT_IP}:${ENTRY_PORT_A} -> IX-A, ${TENCENT_IP}:${ENTRY_PORT_B} -> IX-B"
    echo "百度入口: ${BAIDU_IP}:${ENTRY_PORT_A} -> IX-A, ${BAIDU_IP}:${ENTRY_PORT_B} -> IX-B"
    echo
    echo "SS 链接:"
    print_uris
  } > /root/ss2022-landing.txt
  write_clash
  umask "${old_umask}"
}

print_summary() {
  cat << EOF

================ 香港落地已装好 ================

SSH 没有改动。
监听: ${SS_PORT}/tcp 和 ${SS_PORT}/udp
加密: ${SS_METHOD}
密码: ${SS_PASSWORD}
出站: 本机直接上网

IX 面板保持原样：
  161.248.136.186:24443 -> ${HK_IP}:${SS_PORT}
  138.252.162.176:24443 -> ${HK_IP}:${SS_PORT}

客户端平时填腾讯或百度的公网地址，不要填香港地址。
最后一条 HK-Direct-Test 只用于在香港本机或境外网络测试落地，不经过 IX。

---------- SS 链接（每行单独复制）----------
$(print_uris)

---------- Clash Verge ----------
完整配置已写入 /root/ss2022-clash.yaml
在你自己的电脑上执行：
  scp root@${HK_IP}:/root/ss2022-clash.yaml .
然后在 Clash Verge Rev 里导入这个文件。

连接信息也在 /root/ss2022-landing.txt
云安全组必须放行 TCP ${SS_PORT} 和 UDP ${SS_PORT}，来源用 0.0.0.0/0。
IX 回源的地址不是百度或腾讯的公网 IP。
EOF
  ss -lntup | grep -E ":${SS_PORT}\\b" || true
}

main() {
  if [[ "${1:-}" == "--force-ip" ]]; then
    FORCE_IP=1
  elif [[ -n "${1:-}" ]]; then
    die "未知参数：${1}。只支持 --force-ip"
  fi
  if [[ "${EUID}" -ne 0 ]]; then
    die "请用 root 执行：sudo bash $0"
  fi
  command -v apt-get >/dev/null 2>&1 || die "这个脚本只支持 Debian/Ubuntu"
  command -v ip >/dev/null 2>&1 || die "没有 ip 命令，请先安装 iproute2"

  export DEBIAN_FRONTEND=noninteractive
  refuse_entry_machines

  log "安装 curl 和基础工具"
  apt-get update
  apt-get install -y ca-certificates curl iproute2

  confirm_public_ip
  build_token
  check_password

  if [[ -r /etc/os-release ]]; then
    log "系统：$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-unknown}")"
  fi

  log "调整 TCP（BBR）"
  configure_bbr

  log "检查本机防火墙"
  open_local_firewall

  log "安装 sing-box"
  install_singbox

  write_credentials
  log "安装完成"
  print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
