#!/usr/bin/env bash
# Ubuntu 26.04 LTS 落地 VPS 一键安装。
# 目标：61.195.99.30
# SSH 22022，仅密钥登录；sing-box Shadowsocks 2022 监听 TCP+UDP 24443。
# 用法：sudo bash install.sh
if [ -z "${BASH_VERSION:-}" ]; then
  echo "请用 bash 执行：sudo bash $0"
  exit 1
fi
set -euo pipefail

SSH_PORT=22022
SS_PORT=24443
SS_METHOD="2022-blake3-aes-256-gcm"
SS_PASSWORD='tPWMZB2C6gOCGG2tAtCesH3mgN8b2j93YTVhlqEjiIo='
SERVER_IP="61.195.99.30"
SS_URI='ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206dFBXTVpCMkM2Z09DR0cydEF0Q2VzSDNtZ044YjJqOTNZVFZobHFFamlJbz0@61.195.99.30:24443#Landing-SS2022'
SSH_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPz8NeEIJCpMCUvHs85Mj+qTLMDyE9Ix07aUQdlZh7zO po0-deploy'
SSH_PUBKEY_FINGERPRINT='SHA256:obVPlFDzR5+j4okkVp3sjfRsE+iZeBkL7YDDwjBaSEs'

export DEBIAN_FRONTEND=noninteractive
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

KEY_USERS=()

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
  local filter="sport = :${port}"
  if [[ "${proto}" == "tcp" ]]; then
    if ss -lnt "${filter}" | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }'; then
      return 0
    fi
    ss -lnt | grep -E "[:.]${port}([^0-9]|$)" >/dev/null
  else
    if ss -lnu "${filter}" | awk 'NR>1 { found=1 } END { exit found ? 0 : 1 }'; then
      return 0
    fi
    ss -lnu | grep -E "[:.]${port}([^0-9]|$)" >/dev/null
  fi
}

ufw_is_active() {
  local status
  status="$(ufw status)"
  grep -q '^Status: active' <<<"${status}"
}

remove_ufw_22() {
  local line num
  local i
  for i in $(seq 1 30); do
    line="$(ufw status numbered | grep -E '\[[[:space:]]*[0-9]+\]' | grep -E '(^|[^0-9])22/tcp|OpenSSH' | head -n 1 || true)"
    [[ -z "${line}" ]] && return 0
    num="$(sed -n 's/.*\[ *\([0-9][0-9]*\)\].*/\1/p' <<<"${line}")"
    [[ -z "${num}" ]] && return 0
    ufw --force delete "${num}"
  done
}

verify_uri() {
  local decoded_len generated
  decoded_len="$(printf '%s' "${SS_PASSWORD}" | base64 -d | wc -c | tr -d '[:space:]')"
  [[ "${decoded_len}" == "32" ]] || die "SS2022 密码解码后不是 32 字节，不能用于 ${SS_METHOD}"
  generated="ss://$(printf '%s' "${SS_METHOD}:${SS_PASSWORD}" | base64 -w 0 | tr -d '=')@${SERVER_IP}:${SS_PORT}#Landing-SS2022"
  [[ "${generated}" == "${SS_URI}" ]] || die "内置分享链接和密码不一致：${generated}"
}

validate_pubkey() {
  local tmp got
  tmp="$(mktemp)"
  printf '%s\n' "${SSH_PUBKEY}" > "${tmp}"
  chmod 600 "${tmp}"
  got="$(ssh-keygen -l -f "${tmp}")"
  rm -f "${tmp}"
  grep -q "${SSH_PUBKEY_FINGERPRINT}" <<<"${got}" || die "公钥指纹不符：${got}"
}

user_already_keyed() {
  local existing
  for existing in "${KEY_USERS[@]}"; do
    [[ "${existing}" == "$1" ]] && return 0
  done
  return 1
}

install_authorized_key() {
  local user="$1"
  local passwd home shell group ak blob mode
  if user_already_keyed "${user}"; then
    return 0
  fi
  passwd="$(getent passwd "${user}" || true)"
  [[ -n "${passwd}" ]] || return 0
  home="$(cut -d: -f6 <<<"${passwd}")"
  shell="$(cut -d: -f7 <<<"${passwd}")"
  [[ -n "${home}" && "${home}" != "/" ]] || return 0

  if [[ "${user}" != "root" ]]; then
    case "${shell}" in
      */bash|*/sh|*/zsh|*/fish|*/dash) ;;
      *) return 0 ;;
    esac
  else
    case "${shell}" in
      */bash|*/sh|*/zsh|*/fish|*/dash) ;;
      *)
        echo "root 的登录 shell 是 ${shell}，改为 /bin/bash，否则密钥无法登录 root。"
        if ! usermod -s /bin/bash root; then
          echo "警告：没法修改 root 的 shell。root 可能仍不能登录，会继续给其他账号装公钥。"
          return 0
        fi
        ;;
    esac
  fi

  group="$(id -gn "${user}")"
  install -d -m 700 -o "${user}" -g "${group}" "${home}/.ssh"
  ak="${home}/.ssh/authorized_keys"
  if [[ ! -e "${ak}" ]]; then
    install -m 600 -o "${user}" -g "${group}" /dev/null "${ak}"
  fi
  blob="$(awk '{print $2}' <<<"${SSH_PUBKEY}")"
  if ! awk '{print $2}' "${ak}" | grep -qxF "${blob}"; then
    printf '%s\n' "${SSH_PUBKEY}" >> "${ak}"
  fi
  chown "${user}:${group}" "${ak}" "${home}/.ssh"
  chmod 700 "${home}/.ssh"
  chmod 600 "${ak}"
  chmod go-w "${home}" || true

  mode="$(stat -c '%a' "${home}")"
  if (( (8#${mode} & 0022) != 0 )); then
    die "${home} 对组或其他用户可写，sshd 会拒绝密钥。请先收紧家目录权限。"
  fi
  mode="$(stat -c '%a' "${home}/.ssh")"
  if [[ "${mode}" != "700" ]]; then
    die "${home}/.ssh 权限是 ${mode}，必须是 700"
  fi
  mode="$(stat -c '%a' "${ak}")"
  if [[ "${mode}" != "600" ]]; then
    die "${ak} 权限是 ${mode}，必须是 600"
  fi
  KEY_USERS+=("${user}")
}

install_keys() {
  local user
  KEY_USERS=()
  install_authorized_key root
  if [[ -n "${SUDO_USER:-}" ]]; then
    install_authorized_key "${SUDO_USER}"
  fi
  if [[ -r /etc/group ]]; then
    while IFS= read -r user; do
      [[ -n "${user}" ]] || continue
      install_authorized_key "${user}"
    done < <(awk -F: '$1=="sudo" || $1=="admin" || $1=="wheel" { n=split($4, a, ","); for (i=1; i<=n; i++) if (a[i] != "") print a[i] }' /etc/group | sort -u)
  fi
  while IFS=: read -r user _ uid _ _ _ shell; do
    [[ "${uid}" =~ ^[0-9]+$ ]] || continue
    if (( uid >= 1000 && uid < 60000 )); then
      case "${shell}" in
        */bash|*/sh|*/zsh|*/fish|*/dash) install_authorized_key "${user}" ;;
      esac
    fi
  done < /etc/passwd
  if ((${#KEY_USERS[@]} == 0)); then
    die "没有写入任何公钥。SSH 尚未改动。"
  fi
  echo "公钥已写入这些账号：${KEY_USERS[*]}"
  echo "指纹：${SSH_PUBKEY_FINGERPRINT}"
}

backup_sshd() {
  if [[ -f /root/sshd-backup/sshd_config ]]; then
    return 0
  fi
  install -d -m 700 /root/sshd-backup
  cp -a /etc/ssh/sshd_config /root/sshd-backup/sshd_config
  if [[ -d /etc/ssh/sshd_config.d ]]; then
    rm -rf /root/sshd-backup/sshd_config.d
    cp -a /etc/ssh/sshd_config.d /root/sshd-backup/sshd_config.d
  else
    install -d -m 755 /root/sshd-backup/sshd_config.d
  fi
  getent passwd root | cut -d: -f7 > /root/sshd-backup/root-shell
  chmod 600 /root/sshd-backup/root-shell
}

restore_sshd_files() {
  if [[ -f /root/sshd-backup/sshd_config ]]; then
    cp -a /root/sshd-backup/sshd_config /etc/ssh/sshd_config
  fi
  if [[ -d /root/sshd-backup/sshd_config.d ]]; then
    rm -rf /etc/ssh/sshd_config.d
    cp -a /root/sshd-backup/sshd_config.d /etc/ssh/sshd_config.d
  fi
  rm -f /etc/systemd/system/ssh.socket.d/override.conf
  rm -f /etc/systemd/system/sshd.socket.d/override.conf
  rmdir /etc/systemd/system/ssh.socket.d 2>/dev/null || true
  rmdir /etc/systemd/system/sshd.socket.d 2>/dev/null || true
}

write_revert_script() {
  cat > /root/revert-ssh-to-22.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 root 执行：sudo bash /root/revert-ssh-to-22.sh"
  exit 1
fi
if [[ -f /root/sshd-backup/sshd_config ]]; then
  cp -a /root/sshd-backup/sshd_config /etc/ssh/sshd_config
fi
if [[ -d /root/sshd-backup/sshd_config.d ]]; then
  rm -rf /etc/ssh/sshd_config.d
  cp -a /root/sshd-backup/sshd_config.d /etc/ssh/sshd_config.d
fi
rm -f /etc/systemd/system/ssh.socket.d/override.conf
rm -f /etc/systemd/system/sshd.socket.d/override.conf
rmdir /etc/systemd/system/ssh.socket.d 2>/dev/null || true
rmdir /etc/systemd/system/sshd.socket.d 2>/dev/null || true
install -d -m 755 /etc/ssh/sshd_config.d
if ! grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf[[:space:]]*$' /etc/ssh/sshd_config; then
  tmp="$(mktemp)"
  printf '%s\n' 'Include /etc/ssh/sshd_config.d/*.conf' | cat - /etc/ssh/sshd_config > "${tmp}"
  mv "${tmp}" /etc/ssh/sshd_config
fi
cat > /etc/ssh/sshd_config.d/00-restore-password.conf << 'EOT'
PasswordAuthentication yes
KbdInteractiveAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
EOT
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
echo "已把 SSH 放回 22，并重新允许密码登录。"
echo "请立刻另开窗口：ssh -p 22 用户名@61.195.99.30"
echo "登录成功后删除 /etc/ssh/sshd_config.d/00-restore-password.conf，再决定是否重新执行安装脚本。"
echo "root 原来的 shell 记录在 /root/sshd-backup/root-shell，紧急恢复时不会把它改回 nologin。"
EOF
  chmod 700 /root/revert-ssh-to-22.sh
}

comment_auth_directives() {
  local file="$1"
  local base
  [[ -f "${file}" ]] || return 0
  base="$(basename "${file}")"
  case "${base}" in
    00-landing-auth.conf|99-port.conf|00-restore-password.conf) return 0 ;;
  esac
  sed -i -E \
    -e 's/^([[:space:]]*)(PasswordAuthentication[[:space:]].*)$/# landing-disabled: \1\2/' \
    -e 's/^([[:space:]]*)(KbdInteractiveAuthentication[[:space:]].*)$/# landing-disabled: \1\2/' \
    -e 's/^([[:space:]]*)(ChallengeResponseAuthentication[[:space:]].*)$/# landing-disabled: \1\2/' \
    -e 's/^([[:space:]]*)(PermitRootLogin[[:space:]].*)$/# landing-disabled: \1\2/' \
    -e 's/^([[:space:]]*)(PubkeyAuthentication[[:space:]].*)$/# landing-disabled: \1\2/' \
    -e 's/^([[:space:]]*)(AuthenticationMethods[[:space:]].*)$/# landing-disabled: \1\2/' \
    "${file}"
}

neutralize_conflicting_auth() {
  local extra
  comment_auth_directives /etc/ssh/sshd_config
  shopt -s nullglob
  for extra in /etc/ssh/sshd_config.d/*.conf; do
    comment_auth_directives "${extra}"
  done
  shopt -u nullglob
}

ensure_sshd_include() {
  if ! grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf[[:space:]]*$' /etc/ssh/sshd_config; then
    local tmp
    tmp="$(mktemp)"
    printf '%s\n' 'Include /etc/ssh/sshd_config.d/*.conf' | cat - /etc/ssh/sshd_config > "${tmp}"
    mv "${tmp}" /etc/ssh/sshd_config
  fi
}

effective_auth_ok() {
  local user="$1"
  local out methods
  out="$(sshd -T -C "user=${user},host=localhost,addr=127.0.0.1" 2>/dev/null)" || return 1
  grep -q '^passwordauthentication no$' <<<"${out}" || return 1
  grep -q '^kbdinteractiveauthentication no$' <<<"${out}" || return 1
  grep -q '^pubkeyauthentication yes$' <<<"${out}" || return 1
  grep -q "^port ${SSH_PORT}$" <<<"${out}" || return 1
  if [[ "${user}" == "root" ]]; then
    grep -Eq '^permitrootlogin (prohibit-password|without-password)$' <<<"${out}" || return 1
  fi
  # 默认值常是 any。PasswordAuthentication 已关闭时，any 不会重新打开密码。
  methods="$(grep '^authenticationmethods ' <<<"${out}" || true)"
  if [[ -n "${methods}" ]] && ! grep -Eq 'any|publickey' <<<"${methods}"; then
    return 1
  fi
  return 0
}

ssh_socket_unit() {
  if systemctl cat ssh.socket >/dev/null 2>&1; then
    if systemctl is-enabled ssh.socket >/dev/null 2>&1 || systemctl is-active ssh.socket >/dev/null 2>&1; then
      printf '%s\n' "ssh.socket"
      return 0
    fi
  fi
  if systemctl cat sshd.socket >/dev/null 2>&1; then
    if systemctl is-enabled sshd.socket >/dev/null 2>&1 || systemctl is-active sshd.socket >/dev/null 2>&1; then
      printf '%s\n' "sshd.socket"
      return 0
    fi
  fi
  return 0
}

remove_socket_overrides() {
  rm -f /etc/systemd/system/ssh.socket.d/override.conf
  rm -f /etc/systemd/system/sshd.socket.d/override.conf
  rm -f /etc/ssh/sshd_config.d/00-restore-password.conf
  rmdir /etc/systemd/system/ssh.socket.d 2>/dev/null || true
  rmdir /etc/systemd/system/sshd.socket.d 2>/dev/null || true
}

comment_port_directives() {
  local extra
  sed -i -E 's/^[[:space:]]*Port[[:space:]]+/# Port moved to sshd_config.d\/99-port.conf: /I' /etc/ssh/sshd_config
  install -d -m 755 /etc/ssh/sshd_config.d
  shopt -s nullglob
  for extra in /etc/ssh/sshd_config.d/*.conf; do
    [[ "$(basename "${extra}")" == "99-port.conf" ]] && continue
    sed -i -E 's/^[[:space:]]*Port[[:space:]]+/# Port moved to 99-port.conf: /I' "${extra}"
  done
  shopt -u nullglob
}

write_port_conf() {
  local keep_22="$1"
  if [[ "${keep_22}" == "yes" ]]; then
    cat > /etc/ssh/sshd_config.d/99-port.conf << EOF
Port 22
Port ${SSH_PORT}
EOF
  else
    cat > /etc/ssh/sshd_config.d/99-port.conf << EOF
Port ${SSH_PORT}
EOF
  fi
}

write_auth_conf() {
  cat > /etc/ssh/sshd_config.d/00-landing-auth.conf << 'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 60
ClientAliveInterval 30
ClientAliveCountMax 4
X11Forwarding no
EOF
}

dump_ssh_failure() {
  {
    echo "===== $(date '+%F %T') ssh failure ====="
    sshd -t || true
    echo "===== sshd -T ====="
    sshd -T 2>&1 | grep -Ei 'port |passwordauthentication|kbdinteractive|pubkeyauthentication|permitrootlogin|authenticationmethods' || true
    echo "===== listeners ====="
    ss -lntup || true
    echo "===== units ====="
    systemctl status ssh.socket ssh.service --no-pager -l || true
    systemctl cat ssh.socket || true
    echo "===== journal ====="
    journalctl -u ssh.socket -u ssh.service -u ssh -n 40 --no-pager || true
  } | tee /root/landing-ssh-error.txt >&2 || true
}

reload_ssh_listener() {
  local socket_unit
  trap '' HUP
  systemctl daemon-reload || return 1
  socket_unit="$(ssh_socket_unit)"
  if [[ -n "${socket_unit}" ]]; then
    systemctl restart "${socket_unit}" || return 1
    return 0
  fi
  if systemctl cat ssh.service >/dev/null 2>&1; then
    systemctl enable ssh.service || return 1
    systemctl restart ssh.service || return 1
    return 0
  fi
  systemctl enable sshd.service || return 1
  systemctl restart sshd.service || return 1
}

disable_socket_activation() {
  trap '' HUP
  echo "套接字方式没有打开 ${SSH_PORT}，改为由 ssh 服务直接监听。"
  systemctl disable --now ssh.socket >/dev/null 2>&1 || true
  systemctl disable --now sshd.socket >/dev/null 2>&1 || true
  systemctl daemon-reload || return 1
  if systemctl cat ssh.service >/dev/null 2>&1; then
    systemctl enable ssh.service || return 1
    systemctl restart ssh.service || return 1
    return 0
  fi
  systemctl enable sshd.service || return 1
  systemctl restart sshd.service || return 1
}

rollback_ssh_or_die() {
  local message="$1"
  dump_ssh_failure
  echo "sing-box 已经在 ${SS_PORT} 提供 TCP 和 UDP。这次失败的只是 SSH。"
  bash /root/revert-ssh-to-22.sh || restore_sshd_files || true
  die "${message} 详情在 /root/landing-ssh-error.txt。当前请继续用 22 端口登录。"
}

auth_ok_for_installed_users() {
  local user
  for user in "${KEY_USERS[@]}"; do
    if ! effective_auth_ok "${user}"; then
      echo "账号 ${user} 的生效 SSH 配置还不是仅密钥。"
      sshd -T -C "user=${user},host=localhost,addr=127.0.0.1" 2>&1 | grep -Ei 'passwordauthentication|kbdinteractive|pubkeyauthentication|permitrootlogin|port |authenticationmethods' || true
      return 1
    fi
  done
  return 0
}

configure_ssh() {
  trap '' HUP
  remove_socket_overrides
  ensure_sshd_include
  ssh-keygen -A || true
  install -d -m 755 /run/sshd
  comment_port_directives

  echo "先同时监听 22 和 ${SSH_PORT}，密码登录暂时保持可用。"
  write_port_conf yes
  rm -f /etc/ssh/sshd_config.d/00-landing-auth.conf
  if ! sshd -t; then
    echo "sshd 配置校验失败，正在还原。SSH 还没有重启。"
    restore_sshd_files
    die "sshd -t 失败，SSH 仍是原来的端口和登录方式"
  fi

  if ! reload_ssh_listener; then
    echo "按原来的方式重启 SSH 失败。"
    disable_socket_activation || rollback_ssh_or_die "SSH 重启失败"
  fi
  sleep 1
  if ! port_listening tcp "${SSH_PORT}"; then
    disable_socket_activation || rollback_ssh_or_die "${SSH_PORT} 没有监听"
    sleep 1
  fi
  if ! port_listening tcp "${SSH_PORT}"; then
    rollback_ssh_or_die "${SSH_PORT} 没有监听成功"
  fi
  echo "${SSH_PORT} 已经在监听。下面关闭密码登录，并去掉 22。"

  write_port_conf no
  write_auth_conf
  if ! sshd -t; then
    write_port_conf yes
    rm -f /etc/ssh/sshd_config.d/00-landing-auth.conf
    reload_ssh_listener || true
    rollback_ssh_or_die "关闭密码前，sshd -t 失败"
  fi
  if ! auth_ok_for_installed_users; then
    echo "云镜像里的配置盖过了密钥登录，正在注释冲突项后重新检查。"
    neutralize_conflicting_auth
    if ! sshd -t || ! auth_ok_for_installed_users; then
      write_port_conf yes
      rm -f /etc/ssh/sshd_config.d/00-landing-auth.conf
      reload_ssh_listener || true
      rollback_ssh_or_die "无法确认已安装公钥的账号只会接受密钥"
    fi
  fi

  if ! reload_ssh_listener; then
    write_port_conf yes
    rm -f /etc/ssh/sshd_config.d/00-landing-auth.conf
    disable_socket_activation || true
    rollback_ssh_or_die "切换到仅密钥登录时重启失败"
  fi
  sleep 1
  if ! port_listening tcp "${SSH_PORT}"; then
    rollback_ssh_or_die "切换后 ${SSH_PORT} 不再监听"
  fi

  if port_listening tcp 22; then
    echo "警告：TCP 22 仍在监听。${SSH_PORT} 已经可用，为避免锁死，防火墙暂时保留 22。"
    echo "请另开窗口用密钥登录成功后，再执行 ufw status numbered，并删除 22 规则。"
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
  if id sing-box >/dev/null 2>&1; then
    install -d -o sing-box -g sing-box -m 750 /var/lib/sing-box
  else
    install -d -m 750 /var/lib/sing-box
  fi

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
      "tcp_fast_open": true,
      "tcp_keep_alive": "2m",
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
  if id sing-box >/dev/null 2>&1; then
    chown root:sing-box /etc/sing-box/config.json
  fi
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
  sing-box -D /var/lib/sing-box -C /etc/sing-box check || die "sing-box 配置检查失败"
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

add_sysctl() {
  local key="$1"
  local value="$2"
  local required="${3:-0}"
  if sysctl -w "${key}=${value}" >/dev/null 2>&1; then
    printf '%s = %s\n' "${key}" "${value}"
    return 0
  fi
  if [[ "${required}" == "1" ]]; then
    sysctl net.ipv4.tcp_available_congestion_control || true
    die "无法设置 ${key}=${value}"
  fi
  echo "内核不支持 ${key}，已跳过" >&2
  return 0
}

configure_bbr() {
  install -d -m 755 /etc/modules-load.d
  printf '%s\n' 'tcp_bbr' > /etc/modules-load.d/99-bbr.conf
  modprobe tcp_bbr 2>/dev/null || true

  local conf="/etc/sysctl.d/99-landing.conf"
  {
    add_sysctl net.core.default_qdisc fq 1
    add_sysctl net.ipv4.tcp_congestion_control bbr 1
    add_sysctl net.ipv4.tcp_fastopen 3
    add_sysctl net.ipv4.tcp_mtu_probing 1
    add_sysctl net.ipv4.tcp_slow_start_after_idle 0
    add_sysctl net.ipv4.tcp_no_metrics_save 1
    add_sysctl net.core.rmem_max 16777216
    add_sysctl net.core.wmem_max 16777216
    add_sysctl net.core.rmem_default 1048576
    add_sysctl net.core.wmem_default 1048576
    add_sysctl net.core.optmem_max 65536
    add_sysctl net.ipv4.tcp_rmem "4096 1048576 16777216"
    add_sysctl net.ipv4.tcp_wmem "4096 1048576 16777216"
    add_sysctl net.core.somaxconn 8192
    add_sysctl net.core.netdev_max_backlog 16384
    add_sysctl net.ipv4.tcp_max_syn_backlog 8192
    add_sysctl net.ipv4.tcp_tw_reuse 1
    add_sysctl net.ipv4.tcp_fin_timeout 15
    add_sysctl net.ipv4.ip_local_port_range "1024 65535"
    add_sysctl net.ipv4.tcp_notsent_lowat 16384
    add_sysctl net.ipv4.tcp_keepalive_time 600
    add_sysctl net.ipv4.tcp_keepalive_intvl 30
    add_sysctl net.ipv4.tcp_keepalive_probes 3
    add_sysctl net.ipv4.tcp_syncookies 1
    add_sysctl net.ipv4.tcp_rfc1337 1
    add_sysctl fs.file-max 1048576
  } > "${conf}"

  sysctl -p "${conf}" >/dev/null
  local cc qdisc
  cc="$(sysctl -n net.ipv4.tcp_congestion_control)"
  qdisc="$(sysctl -n net.core.default_qdisc)"
  if [[ "${cc}" != "bbr" || "${qdisc}" != "fq" ]]; then
    sysctl net.ipv4.tcp_available_congestion_control || true
    die "BBR 没有打开。当前拥塞控制=${cc}，队列=${qdisc}"
  fi
}

configure_limits() {
  cat > /etc/security/limits.d/99-landing.conf << 'EOF'
root soft nofile 1048576
root hard nofile 1048576
* soft nofile 1048576
* hard nofile 1048576
EOF
  install -d -m 755 /etc/systemd/system.conf.d
  cat > /etc/systemd/system.conf.d/99-landing.conf << 'EOF'
[Manager]
DefaultLimitNOFILE=1048576
EOF
}

confirm_public_ip() {
  local detected=""
  detected="$(curl -4 -fsS --max-time 8 https://api.ipify.org || true)"
  detected="${detected//$'\r'/}"
  detected="${detected//$'\n'/}"
  if [[ -z "${detected}" ]]; then
    echo "没有探测到公网 IPv4，链接仍使用 ${SERVER_IP}。"
    return 0
  fi
  if [[ "${detected}" == "${SERVER_IP}" ]]; then
    echo "公网 IPv4 核对通过：${detected}"
    return 0
  fi
  cat << EOF
警告：这台机器探测到的 IPv4 是 ${detected}，脚本里的落地地址是 ${SERVER_IP}。
如果这不是要安装的那台 VPS，现在按 Ctrl+C。
15 秒后仍会继续。继续之后，分享链接里的地址依然是 ${SERVER_IP}。
EOF
  local i
  for i in 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1; do
    printf '\r  %2d 秒后继续' "${i}"
    sleep 1
  done
  printf '\n'
}

confirm_ssh_change() {
  cat << EOF

即将分两步改 SSH：
  1. 先让 22 和 ${SSH_PORT} 同时监听，密码登录先保持可用
  2. 确认 ${SSH_PORT} 已经打开后，再关闭密码登录，并去掉 22
只接受下面这把公钥
指纹：${SSH_PUBKEY_FINGERPRINT}
账号：${KEY_USERS[*]}

改之前请确认两件事：
  - 云厂商安全组已经放行 TCP ${SSH_PORT}、TCP ${SS_PORT}、UDP ${SS_PORT}
  - 你手里的私钥指纹和上面一致。本机可执行：ssh-keygen -lf 私钥.pub

服务商网页控制台的密码不会改，也不会锁定。当前这个 SSH 窗口不应被主动断开。
不要关闭它，直到新窗口用密钥登录成功：
  ssh -i 私钥 -p ${SSH_PORT} -o IdentitiesOnly=yes 用户名@${SERVER_IP}
如果新窗口连不上，在当前窗口执行：
  bash /root/revert-ssh-to-22.sh
如果当前窗口也断了，用服务商的网页控制台执行同一条命令。

15 秒后继续。要取消请按 Ctrl+C。
EOF
  local i
  for i in 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1; do
    printf '\r  %2d 秒后修改 SSH' "${i}"
    sleep 1
  done
  printf '\n'
}

write_credentials() {
  cat > /root/ss2022-landing.txt << EOF
服务器 IP: ${SERVER_IP}
SSH 端口: ${SSH_PORT}
SSH 登录: 仅密钥，密码登录已关闭
公钥指纹: ${SSH_PUBKEY_FINGERPRINT}
可用账号: ${KEY_USERS[*]}
登录命令: ssh -i 私钥 -p ${SSH_PORT} -o IdentitiesOnly=yes 用户名@${SERVER_IP}
BBR: 已开启
协议: Shadowsocks 2022
方法: ${SS_METHOD}
端口: ${SS_PORT}
传输: TCP + UDP
密码: ${SS_PASSWORD}

SS 链接:
${SS_URI}

Clash Verge 节点:
- name: "落地-SS2022"
  type: ss
  server: ${SERVER_IP}
  port: ${SS_PORT}
  cipher: ${SS_METHOD}
  password: "${SS_PASSWORD}"
  udp: true
  tfo: true
EOF
  chmod 600 /root/ss2022-landing.txt
}

main() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "请用 root 执行：sudo bash $0"
    exit 1
  fi

  verify_uri
  log "安装基础软件"
  apt-get update
  apt-get install -y ca-certificates curl iproute2 ufw fail2ban openssh-server openssh-client

  log "核对公网地址"
  confirm_public_ip

  log "检查公钥"
  validate_pubkey

  log "开启 BBR 和网络参数"
  configure_bbr
  configure_limits

  log "配置防火墙。先放行 22 和 ${SSH_PORT}，再启用 UFW"
  configure_firewall

  log "安装 sing-box 并写入 SS2022 配置"
  install_singbox
  sing-box version || true

  log "写入 SSH 公钥"
  install_keys

  log "备份当前 SSH 配置并写入回滚脚本"
  backup_sshd
  write_revert_script

  confirm_ssh_change

  log "把 SSH 改为 ${SSH_PORT}，并关闭密码登录"
  configure_ssh

  log "按新 SSH 端口配置 fail2ban"
  if ! configure_fail2ban; then
    echo "fail2ban 启动失败，不影响 sing-box。可稍后执行：journalctl -u fail2ban -n 50 --no-pager"
  fi

  write_credentials

  log "安装完成"
  cat << EOF

================ 安装完成，下面两段直接复制 ================

BBR: 已开启 ($(sysctl -n net.ipv4.tcp_congestion_control) + $(sysctl -n net.core.default_qdisc))
SSH: ssh -i 私钥 -p ${SSH_PORT} -o IdentitiesOnly=yes 用户名@${SERVER_IP}
可用账号: ${KEY_USERS[*]}
公钥指纹: ${SSH_PUBKEY_FINGERPRINT}
网页控制台密码没有改动。SSH 密码登录已经关闭。

---------- SS 链接（整行复制）----------
${SS_URI}

---------- Clash Verge 节点（整段复制）----------
- name: "落地-SS2022"
  type: ss
  server: ${SERVER_IP}
  port: ${SS_PORT}
  cipher: ${SS_METHOD}
  password: "${SS_PASSWORD}"
  udp: true
  tfo: true

上面的内容也保存在 /root/ss2022-landing.txt
现在不要关闭这个窗口。另开一个终端，用密钥登录成功后再关闭。
EOF
  ss -lntup | grep -E ":${SSH_PORT}|:${SS_PORT}" || true
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
