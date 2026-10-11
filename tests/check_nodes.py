#!/usr/bin/env python3
"""Check the landing installer, entry forwarder, and client files describe the same nodes."""

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGN = re.compile(
    r"""^([A-Z0-9_]+)=(?:"([^"]*)"|'([^']*)'|([0-9]+))\s*$""",
    re.M,
)
SHARED = (
    "HK_IP",
    "TENCENT_IP",
    "BAIDU_IP",
    "TENCENT_PRIV",
    "BAIDU_PRIV",
    "IX_A_IP",
    "IX_B_IP",
    "IX_PORT",
    "ENTRY_PORT_A",
    "ENTRY_PORT_B",
)
OLD_SECRETS = (
    "150.66.49.113",
    "WaLb8NWiW90b6m5MtmJ0GiaVODUkPcsz0JAf2YphvV0=",
)


def assignments(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in ASSIGN.finditer(path.read_text()):
        found[match.group(1)] = next(
            group for group in match.groups()[1:] if group is not None
        )
    return found


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def bash(script: str) -> str:
    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        fail(completed.stdout + completed.stderr)
    return completed.stdout


def main() -> None:
    install = assignments(ROOT / "server" / "install.sh")
    forward = assignments(ROOT / "entry" / "forward.sh")
    for key in SHARED:
        if install[key] != forward[key]:
            fail(f"{key} differs: install={install[key]!r} forward={forward[key]!r}")
    if install["SS_PORT"] != install["IX_PORT"] or install["SS_PORT"] != "24443":
        fail("Hong Kong listen port must be 24443, the IX origin port")
    if install["ENTRY_PORT_A"] != "24443" or install["ENTRY_PORT_B"] != "24444":
        fail("entry ports must be 24443 for IX-A and 24444 for IX-B")
    if install["IX_PORT"] != "24443":
        fail("IX listen port must stay 24443")
    password = install["SS_PASSWORD"]
    method = install["SS_METHOD"]
    if method != "2022-blake3-aes-256-gcm":
        fail(method)
    if len(base64.b64decode(password, validate=True)) != 32:
        fail("password is not 32 bytes")
    if password in (ROOT / "entry" / "forward.sh").read_text():
        fail("entry forwarder must not contain the SS password")

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path == Path(__file__):
            continue
        text = path.read_text(errors="ignore")
        for secret in OLD_SECRETS:
            if secret in text:
                fail(f"old landing secret still in {path}")

    subprocess.run(["bash", "-n", "server/install.sh"], cwd=ROOT, check=True)
    subprocess.run(["bash", "-n", "entry/forward.sh"], cwd=ROOT, check=True)

    uris = bash("source server/install.sh && build_token && print_uris")
    uri_file = (ROOT / "client" / "ss-uri.txt").read_text()
    if uris != uri_file:
        fail(f"ss-uri.txt does not match install.sh\n{uris}\n---\n{uri_file}")
    readme = (ROOT / "README.md").read_text()
    for line in uris.splitlines():
        if line not in readme:
            fail(f"README is missing {line}")

    token = base64.b64encode(f"{method}:{password}".encode()).decode().rstrip("=")
    if "+" in token or "/" in token:
        fail("share-link token contains + or /")
    for line in uris.splitlines():
        encoded, rest = line.removeprefix("ss://").split("@", 1)
        padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
        userinfo = base64.b64decode(padded).decode()
        if userinfo != f"{method}:{password}":
            fail(f"decoded URI does not match password: {line}")
        host_port, _name = rest.split("#", 1)
        host, port = host_port.rsplit(":", 1)
        if port not in {"24443", "24444"}:
            fail(port)
        if host not in {install["TENCENT_IP"], install["BAIDU_IP"], install["HK_IP"]}:
            fail(host)

    script = (ROOT / "server" / "install.sh").read_text()
    start = script.index("# clash-template-start\n")
    end = script.index("# clash-template-end\n")
    match = re.search(r"<< EOF\n(.*)\nEOF\n", script[start:end], re.S)
    if match is None:
        fail("clash template markers missing")
    rendered = match.group(1) + "\n"
    for key, value in install.items():
        rendered = rendered.replace("${" + key + "}", value)
    if "${" in rendered:
        fail("unsubstituted clash template variable")
    clash_path = ROOT / "client" / "clash-verge.yaml"
    if rendered != clash_path.read_text():
        fail("client/clash-verge.yaml does not match the installer template")
    clash = clash_path.read_text()
    auto = clash.split('- name: "自动选择"', 1)[1].split("rules:", 1)[0]
    if "香港直连-仅测试" in auto:
        fail("url-test group must not include the direct Hong Kong node")
    if "腾讯-IX-A" not in auto or "百度-IX-B" not in auto:
        fail("url-test group is missing an entry node")

    config = json.loads((ROOT / "server" / "config.json").read_text())
    inbound = config["inbounds"][0]
    if inbound["type"] != "shadowsocks" or inbound["listen_port"] != 24443:
        fail("server config port")
    if inbound["method"] != method or inbound["password"] != password:
        fail("server config credential")
    if "network" in inbound:
        fail("omit network so sing-box listens on TCP and UDP")
    if config["outbounds"][0]["type"] != "direct":
        fail("landing outbound must be direct")

    client = json.loads((ROOT / "client" / "sing-box-client.json").read_text())
    by_tag = {item["tag"]: item for item in client["outbounds"]}
    expected = {
        "tencent-ix-a": (install["TENCENT_IP"], 24443),
        "tencent-ix-b": (install["TENCENT_IP"], 24444),
        "baidu-ix-a": (install["BAIDU_IP"], 24443),
        "baidu-ix-b": (install["BAIDU_IP"], 24444),
        "hk-direct-test": (install["HK_IP"], 24443),
    }
    for tag, (host, port) in expected.items():
        item = by_tag[tag]
        if item["server"] != host or item["server_port"] != port:
            fail(tag)
        if item["method"] != method or item["password"] != password:
            fail(tag)
    if by_tag["proxy"]["default"] != "tencent-ix-a":
        fail("selector default")
    if by_tag["proxy"]["outbounds"] != list(expected):
        fail("selector members")
    if client["route"]["final"] != "proxy":
        fail("client final outbound")

    rendered_nft = bash("source entry/forward.sh && render_nft eth0 full")
    nomss = bash("source entry/forward.sh && render_nft eth0 nomss")
    for required in (
        "tcp dport 24443 counter dnat to 161.248.136.186:24443",
        "udp dport 24443 counter dnat to 161.248.136.186:24443",
        "tcp dport 24444 counter dnat to 138.252.162.176:24443",
        "udp dport 24444 counter dnat to 138.252.162.176:24443",
        "ip daddr 161.248.136.186 counter masquerade",
        "ip daddr 138.252.162.176 counter masquerade",
        'iifname "eth0"',
    ):
        if required not in rendered_nft:
            fail(f"nft rule missing: {required}")
    if "maxseg" not in rendered_nft or "maxseg" in nomss:
        fail("mss clamp fallback is wrong")
    if "flush ruleset" in rendered_nft:
        fail("rendered nft flushes the ruleset")
    forward_text = (ROOT / "entry" / "forward.sh").read_text()
    for forbidden in (
        "nft flush",
        "delete table ip po0relay",
        "delete table ip ix_forward",
        password,
    ):
        if forbidden in forward_text:
            fail(f"forward.sh contains {forbidden}")
    if "delete table ip ix_entry" not in forward_text:
        fail("forward.sh must only delete its own table")

    bad = subprocess.run(
        ["bash", "entry/forward.sh", "--render-nft", "eth0; flush ruleset"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if bad.returncode == 0:
        fail("interface name injection was accepted")

    print("node checks passed")


if __name__ == "__main__":
    main()
