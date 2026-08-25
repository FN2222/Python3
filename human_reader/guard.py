from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import AccessStopped, StopReason

# HTTP statuses that mean "a human must take over". Never retried, never bypassed.
STOP_HTTP_STATUSES = frozenset({401, 403, 407, 423, 429, 451, 503})

_CAPTCHA_PATTERNS = (
    r"recaptcha",
    r"h-?captcha",
    r"geetest",
    r"cf-challenge",
    r"captcha",
    r"验证码",
    r"滑动验证",
    r"安全验证",
    r"waf.?captcha",
)
_LOGIN_PATTERNS = (
    r"请先登录",
    r"请登录后",
    r"登录后查看",
    r"登录后才能",
    r"登录后阅读",
    r"sign in to continue",
    r"please log ?in",
    r"please sign in",
    r"需要登录",
    r"未登录",
)
_PERMISSION_PATTERNS = (
    r"没有权限",
    r"无权访问",
    r"无权限查看",
    r"access denied",
    r"permission denied",
    r"not authorized",
    r"forbidden",
)
_RATE_PATTERNS = (
    r"too many requests",
    r"访问过于频繁",
    r"请求过于频繁",
    r"操作过于频繁",
    r"rate limit",
    r"稍后重试",
)

_CAPTCHA_RE = re.compile("|".join(_CAPTCHA_PATTERNS), re.IGNORECASE)
_LOGIN_RE = re.compile("|".join(_LOGIN_PATTERNS), re.IGNORECASE)
_PERM_RE = re.compile("|".join(_PERMISSION_PATTERNS), re.IGNORECASE)
_RATE_RE = re.compile("|".join(_RATE_PATTERNS), re.IGNORECASE)
_PASSWORD_RE = re.compile(r'type\s*=\s*["\']password["\']', re.IGNORECASE)
_LOGIN_URL_RE = re.compile(
    r"/(login|signin|sign-in|passport|sso|auth|account/login)(/|$|\?)",
    re.IGNORECASE,
)


def inspect_http_status(status_code: int, url: str = "") -> None:
    if status_code in STOP_HTTP_STATUSES:
        reason = StopReason.RATE_LIMIT if status_code == 429 else StopReason.HTTP_STATUS
        if status_code in {401, 403}:
            reason = StopReason.PERMISSION
        raise AccessStopped(
            reason,
            (
                f"站点返回 HTTP {status_code}，已停止继续请求。"
                "请人工处理登录 / 验证码 / 访问限制后再继续，工具不会尝试绕过。"
            ),
            status_code=status_code,
            url=url,
        )


def inspect_page(html: str, url: str, visible_text: str = "") -> None:
    """Stop when the page itself says a human must take over.

    This is a hard stop: no retry, no captcha solving, no login-form filling.
    """
    sample = f"{url}\n{html[:80_000]}"
    text_sample = visible_text or html

    if _CAPTCHA_RE.search(sample):
        # A tiny footer mention of "captcha" in third-party scripts is possible;
        # require a widget-ish hint or explicit 验证码 challenge copy.
        if _looks_like_challenge(html, visible_text):
            raise AccessStopped(
                StopReason.CAPTCHA,
                "页面出现验证码或人机验证，已停止。请在浏览器中完成验证后，再导出 Cookie / storage 继续。",
                url=url,
            )

    if _RATE_RE.search(text_sample):
        raise AccessStopped(
            StopReason.RATE_LIMIT,
            "页面提示访问过于频繁，已停止继续请求。请等待限制解除后再由人工继续。",
            url=url,
        )

    parsed = urlparse(url)
    path_q = parsed.path + ("?" + parsed.query if parsed.query else "")
    login_url = bool(_LOGIN_URL_RE.search(path_q))
    has_password = bool(_PASSWORD_RE.search(html))
    login_copy = bool(_LOGIN_RE.search(text_sample))

    if login_url and (has_password or login_copy or len(visible_text.strip()) < 400):
        raise AccessStopped(
            StopReason.LOGIN_REQUIRED,
            "当前被转到登录页，没有继续读取课程。请先在浏览器登录（不要让工具代填或绕过），再携带会话继续。",
            url=url,
        )

    if login_copy and has_password and len(visible_text.strip()) < 800:
        raise AccessStopped(
            StopReason.LOGIN_REQUIRED,
            "页面要求登录后才能查看内容，已停止。请人工登录后再继续。",
            url=url,
        )

    if _PERM_RE.search(text_sample) and len(visible_text.strip()) < 500:
        raise AccessStopped(
            StopReason.PERMISSION,
            "页面提示没有权限，已停止。请确认账号已登录且有课程权限后再继续。",
            url=url,
        )


def _looks_like_challenge(html: str, visible_text: str) -> bool:
    html_l = html.lower()
    widget_hints = (
        "g-recaptcha",
        "h-captcha",
        "hcaptcha",
        "geetest",
        "cf-challenge",
        "captcha-container",
        'id="captcha"',
        "id='captcha'",
    )
    if any(hint in html_l for hint in widget_hints):
        return True
    challenge_copy = any(
        phrase in html for phrase in ("请完成验证码", "滑动验证", "安全验证", "人机验证", "请输入验证码")
    )
    if challenge_copy and len((visible_text or "").strip()) < 1500:
        return True
    if re.search(r"\bcaptcha\b", visible_text or "", re.IGNORECASE) and len((visible_text or "").strip()) < 400:
        return True
    return False


def stop_message(exc: AccessStopped, saved_dir: str | None = None) -> str:
    lines = [
        "访问已停止，未尝试绕过检测或访问控制。",
        f"原因：{exc.reason.value}" + (f" / HTTP {exc.status_code}" if exc.status_code else ""),
        f"说明：{exc.message}",
    ]
    if exc.url:
        lines.append(f"停在：{exc.url}")
    if saved_dir:
        lines.append(f"此前已读完并保存的内容仍在：{saved_dir}")
        lines.append("处理完登录/验证码后，可用 --resume 从下一页继续，不要重启并发任务。")
    return "\n".join(lines)
