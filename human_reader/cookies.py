from __future__ import annotations

import json
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from pathlib import Path


def load_cookie_jar(cookies_path: str | None = None, storage_state_path: str | None = None) -> CookieJar:
    """Load a session the user already created in a real browser.

    The reader never logs in by itself and never bypasses login checks.
    """
    jar: CookieJar
    if cookies_path and Path(cookies_path).is_file() and _looks_like_netscape(Path(cookies_path)):
        jar = MozillaCookieJar(cookies_path)
        jar.load(ignore_discard=True, ignore_expires=True)
    else:
        jar = CookieJar()

    if cookies_path and Path(cookies_path).is_file() and not _looks_like_netscape(Path(cookies_path)):
        _add_json_cookies(jar, Path(cookies_path))
    if storage_state_path:
        _add_json_cookies(jar, Path(storage_state_path), key="cookies")
    return jar


def _looks_like_netscape(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return False
    return "# Netscape HTTP Cookie File" in head or head.startswith("# HttpOnly_")


def _add_json_cookies(jar: CookieJar, path: Path, key: str | None = None) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get(key, raw) if isinstance(raw, dict) else raw
    if isinstance(items, dict) and "cookies" in items:
        items = items["cookies"]
    if not isinstance(items, list):
        raise ValueError(f"unsupported cookie file: {path}")
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name:
            continue
        domain = item.get("domain") or item.get("Domain") or ""
        path_v = item.get("path") or item.get("Path") or "/"
        secure = bool(item.get("secure") or item.get("Secure"))
        rest = {}
        if domain.startswith("."):
            domain_specified = True
        else:
            domain_specified = bool(domain)
        cookie = Cookie(
            version=0,
            name=str(name),
            value=str(value if value is not None else ""),
            port=None,
            port_specified=False,
            domain=str(domain),
            domain_specified=domain_specified,
            domain_initial_dot=str(domain).startswith("."),
            path=str(path_v),
            path_specified=True,
            secure=secure,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest=rest,
            rfc2109=False,
        )
        jar.set_cookie(cookie)
