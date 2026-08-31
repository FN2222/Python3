"""AI 自动撰写 —— 让流水线自己调 LLM 把 note.json / interview.json 写出来。

目的:把"唯一需要 AI 的那一步"也自动化,不再需要人(或 Cursor 会话)逐章介入。
循环逻辑与人工完全一致:

    读任务包 -> 调模型产出 JSON -> 落盘 -> 跑 verify -> 把 errors 回灌 -> 重写
    直到通过,或达到 writer_max_rounds

兼容任何 **OpenAI Chat Completions 协议**的服务,只需改配置里的 base_url / model:
DeepSeek、通义千问(兼容模式)、智谱 GLM、Kimi、OpenRouter、本地 vLLM / Ollama 等。

成本可控:
  * `--dry-run` 只统计 token 与预估费用,不发请求;
  * 每章的实际用量与费用写入 build/write-log.jsonl,可随时汇总;
  * 提示词按需裁剪(schema 只发一次说明、原文按需截断)。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from nlnotes.config import REPO_ROOT, Config
from nlnotes.util import log, read_json, write_json

SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "00-system-中文笔记作者.md"
GROUP_SYSTEM_PROMPT_PATH = REPO_ROOT / "prompts" / "50-面试复习.md"

JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


# ------------------------------------------------------------------ 工具

def estimate_tokens(text: str) -> int:
    """粗略估算:英文约 4 字符/token,中文约 1.5 字符/token。用于成本预估,不求精确。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


def estimate_cost(cfg: Config, tok_in: int, tok_out: int) -> float:
    return (tok_in / 1e6 * float(cfg["writer_price_in_per_mtok"])
            + tok_out / 1e6 * float(cfg["writer_price_out_per_mtok"]))


def extract_json(text: str) -> dict[str, Any]:
    """从模型回复里取出 JSON:优先代码块,其次第一个平衡的花括号块。"""
    candidates: list[str] = []
    for m in JSON_FENCE.finditer(text):
        candidates.append(m.group(1))
    candidates.append(text)

    for cand in candidates:
        cand = cand.strip()
        start = cand.find("{")
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(cand)):
            ch = cand[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cand[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("模型回复里没有可解析的 JSON")


def _read(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8-sig")
    if limit and len(text) > limit:
        return text[:limit] + f"\n\n...(内容过长已截断,完整文件见 {path.name})"
    return text


# ------------------------------------------------------------------ LLM 调用

def call_llm(cfg: Config, system: str, user: str) -> tuple[str, dict[str, int]]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests 依赖: pip install requests") from exc

    env_name = str(cfg["writer_api_key_env"])
    key = os.environ.get(env_name, "").strip().strip('"').strip("'")
    base = str(cfg["writer_base_url"]).rstrip("/") or "https://api.openai.com/v1"
    if not key and "localhost" not in base and "127.0.0.1" not in base:
        raise RuntimeError(
            f"未设置环境变量 {env_name}。\n"
            f"Windows: $env:{env_name} = \"你的key\"\n"
            f"Linux/macOS: export {env_name}=你的key")
    # HTTP 头只能是 ASCII。如果 Key 里有中文(比如误填了占位说明文字),
    # requests 会抛出难以理解的 'latin-1' codec 错误,所以这里提前拦下并说清楚。
    if key:
        try:
            key.encode("ascii")
        except UnicodeEncodeError:
            raise RuntimeError(
                f"环境变量 {env_name} 里的 API Key 含非 ASCII 字符(比如中文)。\n"
                f"HTTP 请求头只能是 ASCII,所以这个 Key 发不出去。\n"
                f"请填真实的 Key;只是想测试网络能不能连通的话,"
                f"用纯英文占位符,例如:\n"
                f'  $env:{env_name} = "test-key-1234"') from None

    body = {
        "model": cfg["writer_model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": float(cfg["writer_temperature"]),
        "max_tokens": int(cfg["writer_max_tokens"]),
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    last_err: Exception | None = None
    for attempt in range(int(cfg["writer_retry_on_error"]) + 1):
        try:
            resp = requests.post(f"{base}/chat/completions", headers=headers, json=body,
                                 timeout=int(cfg["writer_timeout"]))
            if resp.status_code == 400 and "response_format" in resp.text:
                body.pop("response_format", None)      # 部分服务不支持 JSON mode
                resp = requests.post(f"{base}/chat/completions", headers=headers, json=body,
                                     timeout=int(cfg["writer_timeout"]))
            if resp.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"服务暂时不可用 HTTP {resp.status_code}: {resp.text[:200]}")
            # 4xx(401 Key 无效、403 无权限、404 模型名写错)重试也不会好,直接抛出
            if 400 <= resp.status_code < 500:
                raise RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}") from None
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return content, {
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
            }
        except Exception as exc:
            last_err = exc
            text = str(exc)
            fatal = (text.startswith("HTTP 4")
                     or "latin-1" in text
                     or "非 ASCII" in text)
            if fatal:
                break                      # Key/模型名/编码问题,重试无意义
            wait = 4 * (2 ** attempt)
            if attempt < int(cfg["writer_retry_on_error"]):
                log(f"调用失败({exc}),{wait}s 后重试", "warn")
                time.sleep(wait)
    raise RuntimeError(f"调用模型失败: {last_err}")


def probe(cfg: Config) -> int:
    """最小成本地探测"能不能连上模型服务" —— 只发一个几乎不花钱的极短请求。

    公司网络常拦命令行 HTTPS,直接跑 write 会在跑到一半才发现连不上,
    所以先用这个确认一次。
    """
    base = str(cfg["writer_base_url"]).rstrip("/")
    print(f"服务地址: {base}")
    print(f"模型    : {cfg['writer_model']}")
    print(f"Key 环境变量: {cfg['writer_api_key_env']}"
          f"{'(已设置)' if os.environ.get(str(cfg['writer_api_key_env'])) else '(未设置)'}")
    print()
    try:
        content, usage = call_llm(cfg, "You are a test.", "Reply with the single word: ok")
    except RuntimeError as exc:
        text = str(exc)
        print(f"❌ 连不通:{text}")
        print()
        low = text.lower()
        if any(k in low for k in ("certificate", "ssl", "tls", "untrusted", "证书")):
            print("看起来是**公司网络的 TLS 拦截**(和 git / 浏览器下载遇到的是同一类问题)。")
            print("这条路走不通,请改用 Cursor 会话批量写:")
            print("  见 prompts/60-批量流水作业.md")
        elif "401" in low or "invalid" in low or "unauthorized" in low:
            print("网络是通的,但 Key 无效 —— 换成真实的 API Key 即可。")
        elif "latin-1" in low or "ascii" in low:
            print("Key 里有非 ASCII 字符(比如中文占位文字),换成纯英文的真实 Key。")
        else:
            print("如果是超时/连接被拒,通常也是公司网络拦截;可以试试配置代理:")
            print('  $env:HTTPS_PROXY = "http://代理地址:端口"')
        return 1
    print(f"✅ 连通正常。模型回复:{str(content)[:60]}")
    print(f"   本次用量:输入 {usage['prompt_tokens']} + 输出 {usage['completion_tokens']} token")
    print()
    print("可以用 nlnotes write 全自动撰写了。建议先 --dry-run 估一下成本。")
    return 0


# ------------------------------------------------------------------ 章节笔记

def build_chapter_prompt(cfg: Config, pdf_id: str,
                         feedback: str = "") -> tuple[str, str]:
    task_dir = cfg.task_dir(pdf_id)
    if not (task_dir / "TASK.md").exists():
        raise FileNotFoundError(f"任务包不存在: {task_dir}(先跑 nlnotes tasks)")

    system = _read(SYSTEM_PROMPT_PATH)
    parts = [
        "请严格按下面的任务要求,产出**一个 JSON 对象**(不要任何解释文字、不要 Markdown 包装)。",
        "",
        "===== TASK.md(任务要求,以此为准) =====", _read(task_dir / "TASK.md"),
        "", "===== note.schema.json(输出结构) =====", _read(task_dir / "note.schema.json"),
        "", "===== note.template.json(骨架,照着填) =====", _read(task_dir / "note.template.json"),
        "", "===== outline.md(原文标题层级) =====", _read(task_dir / "outline.md"),
        "", "===== glossary.md(统一译名) =====", _read(task_dir / "glossary.md"),
        "", "===== figures.md(可用图与图内文字) =====", _read(task_dir / "figures.md"),
        "", "===== codeblocks.md(配置/命令,逐字引用) =====", _read(task_dir / "codeblocks.md"),
        "", "===== source-text.md(原文全文,页码为 [[p.N]]) =====", _read(task_dir / "source-text.md"),
    ]
    if feedback:
        parts += ["", "===== 上一轮校验未通过,请逐条修正后重新输出完整 JSON =====", feedback]
    parts += ["", "现在输出完整的 note.json(仅 JSON):"]
    return system, "\n".join(parts)


def format_feedback(report: dict[str, Any], max_items: int = 30) -> str:
    lines = ["以下是门禁报告中的错误,必须全部修掉:", ""]
    for e in report.get("errors", [])[:max_items]:
        lines.append(f"- [{e['code']}] {e['where']}: {e['message']}")
        if e.get("fix"):
            lines.append(f"  修复建议: {e['fix']}")
    extra = len(report.get("errors", [])) - max_items
    if extra > 0:
        lines.append(f"...(还有 {extra} 条同类错误,请一并修正)")
    lines += ["", "注意:不要删减内容来规避错误(会触发覆盖度不足);",
              "不要改动门禁配置;重新输出**完整**的 note.json。",
              "引用必须同页连续,不要跨页或拼接不相邻的命令行;",
              "不要自行发明缩写或换算掩码;points[].kind 不要填 process。"]
    return "\n".join(lines)


def write_chapter(cfg: Config, item: dict[str, Any], dry_run: bool = False,
                  force: bool = False) -> dict[str, Any]:
    from nlnotes.taskgen import note_path
    from nlnotes.verify import verify_note

    pdf_id = item["id"]
    out_path = note_path(cfg, pdf_id)
    stat: dict[str, Any] = {"id": pdf_id, "rel_path": item["rel_path"],
                            "rounds": 0, "prompt_tokens": 0, "completion_tokens": 0,
                            "cost_usd": 0.0, "passed": False, "kind": "chapter"}

    if out_path.exists() and not force:
        rep = verify_note(cfg, pdf_id)
        if rep.passed:
            log(f"跳过(已通过校验): {item['rel_path']}")
            stat["passed"] = True
            stat["skipped"] = True
            return stat

    system, user = build_chapter_prompt(cfg, pdf_id)
    if dry_run:
        tin = estimate_tokens(system) + estimate_tokens(user)
        tout = 9000                     # note.json 的经验输出量
        stat.update({"prompt_tokens": tin, "completion_tokens": tout,
                     "cost_usd": round(estimate_cost(cfg, tin, tout), 4), "dry_run": True})
        log(f"[预估] {item['rel_path']} — 输入约 {tin} tok / 输出约 {tout} tok / "
            f"约 ${stat['cost_usd']:.4f}(单轮)")
        return stat

    feedback = ""
    for rnd in range(1, int(cfg["writer_max_rounds"]) + 1):
        stat["rounds"] = rnd
        if feedback:
            system, user = build_chapter_prompt(cfg, pdf_id, feedback)
        log(f"撰写 {item['rel_path']} — 第 {rnd} 轮")
        content, usage = call_llm(cfg, system, user)
        stat["prompt_tokens"] += usage["prompt_tokens"]
        stat["completion_tokens"] += usage["completion_tokens"]

        try:
            note = extract_json(content)
        except ValueError as exc:
            feedback = f"上一轮的回复无法解析成 JSON({exc})。请只输出一个合法的 JSON 对象。"
            continue

        note["pdf_id"] = pdf_id                     # 防止模型写错 id
        note.setdefault("source_rel_path", item["rel_path"])
        write_json(out_path, note)

        rep = verify_note(cfg, pdf_id)
        if rep.passed:
            stat["passed"] = True
            break
        feedback = format_feedback(rep.to_dict())

    stat["cost_usd"] = round(estimate_cost(cfg, stat["prompt_tokens"],
                                           stat["completion_tokens"]), 4)
    log(f"{'✅ 通过' if stat['passed'] else '❌ 未通过'} {item['rel_path']} — "
        f"{stat['rounds']} 轮 / {stat['prompt_tokens']}+{stat['completion_tokens']} tok / "
        f"约 ${stat['cost_usd']:.4f}", "ok" if stat["passed"] else "warn")
    return stat


# ------------------------------------------------------------------ 面试复习笔记

def build_group_prompt(cfg: Config, group: dict[str, Any], feedback: str = "") -> tuple[str, str]:
    from nlnotes.groups import group_dir

    gdir = group_dir(cfg, group["id"])
    if not (gdir / "TASK.md").exists():
        raise FileNotFoundError(f"分组任务包不存在: {gdir}(先跑 nlnotes groups)")

    system = _read(GROUP_SYSTEM_PROMPT_PATH) or _read(SYSTEM_PROMPT_PATH)
    parts = [
        "请严格按下面的任务要求,产出**一个 JSON 对象**(不要任何解释文字、不要 Markdown 包装)。",
        "", "===== TASK.md(任务要求,以此为准) =====", _read(gdir / "TASK.md"),
        "", "===== interview.schema.json(输出结构) =====", _read(gdir / "interview.schema.json"),
        "", "===== chapters.md(出题素材,含 pdf_id 与页码) =====", _read(gdir / "chapters.md"),
    ]
    # 附上各章原文,便于逐字复制 grounding 引用
    ctx = read_json(gdir / "context.json")
    budget = int(cfg["group_source_chars_budget"])
    per = max(4000, budget // max(1, len(ctx.get("chapters", []))))
    for c in ctx.get("chapters", []):
        text = _read(cfg.extract_dir(c["pdf_id"]) / "text.md", per)
        parts += ["", f"===== 原文 {c['pdf_id']} — {c['title_zh']} =====", text]
    if feedback:
        parts += ["", "===== 上一轮校验未通过,请逐条修正后重新输出完整 JSON =====", feedback]
    parts += ["", "现在输出完整的 interview.json(仅 JSON):"]
    return system, "\n".join(parts)


def write_group(cfg: Config, group: dict[str, Any], dry_run: bool = False,
                force: bool = False) -> dict[str, Any]:
    from nlnotes.groups import interview_path, verify_interview

    out_path = interview_path(cfg, group["id"])
    stat: dict[str, Any] = {"id": group["id"], "rel_path": group["key"],
                            "rounds": 0, "prompt_tokens": 0, "completion_tokens": 0,
                            "cost_usd": 0.0, "passed": False, "kind": "group"}

    if out_path.exists() and not force:
        rep = verify_interview(cfg, group)
        if rep.passed:
            log(f"跳过(已通过校验): {group['key']}")
            stat["passed"] = True
            stat["skipped"] = True
            return stat

    system, user = build_group_prompt(cfg, group)
    if dry_run:
        tin = estimate_tokens(system) + estimate_tokens(user)
        tout = 16000
        stat.update({"prompt_tokens": tin, "completion_tokens": tout,
                     "cost_usd": round(estimate_cost(cfg, tin, tout), 4), "dry_run": True})
        log(f"[预估] 面试复习 {group['key']} — 输入约 {tin} tok / 输出约 {tout} tok / "
            f"约 ${stat['cost_usd']:.4f}(单轮)")
        return stat

    feedback = ""
    for rnd in range(1, int(cfg["writer_max_rounds"]) + 1):
        stat["rounds"] = rnd
        if feedback:
            system, user = build_group_prompt(cfg, group, feedback)
        log(f"撰写面试复习 {group['key']} — 第 {rnd} 轮")
        content, usage = call_llm(cfg, system, user)
        stat["prompt_tokens"] += usage["prompt_tokens"]
        stat["completion_tokens"] += usage["completion_tokens"]
        try:
            interview = extract_json(content)
        except ValueError as exc:
            feedback = f"上一轮的回复无法解析成 JSON({exc})。请只输出一个合法的 JSON 对象。"
            continue
        interview["group_key"] = group["key"]
        write_json(out_path, interview)
        rep = verify_interview(cfg, group)
        if rep.passed:
            stat["passed"] = True
            break
        feedback = format_feedback(rep.to_dict())

    stat["cost_usd"] = round(estimate_cost(cfg, stat["prompt_tokens"],
                                           stat["completion_tokens"]), 4)
    log(f"{'✅ 通过' if stat['passed'] else '❌ 未通过'} 面试复习 {group['key']} — "
        f"{stat['rounds']} 轮 / 约 ${stat['cost_usd']:.4f}", "ok" if stat["passed"] else "warn")
    return stat


# ------------------------------------------------------------------ 批量与账本

def append_log(cfg: Config, stat: dict[str, Any]) -> None:
    p = cfg.build_dir / "write-log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    stat = dict(stat)
    stat["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    stat["model"] = cfg["writer_model"]
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(stat, ensure_ascii=False) + "\n")


def summarize(stats: list[dict[str, Any]], dry_run: bool = False) -> str:
    skipped = sum(1 for s in stats if s.get("skipped"))
    estimated = [s for s in stats if s.get("dry_run")]
    tin = sum(s["prompt_tokens"] for s in stats)
    tout = sum(s["completion_tokens"] for s in stats)
    cost = sum(s["cost_usd"] for s in stats)

    lines = ["", "=" * 56]
    if dry_run:
        lines += [f"成本预估:{len(stats)} 个任务(其中 {len(estimated)} 个需要调用模型,"
                  f"{skipped} 个已完成会跳过)",
                  f"token:输入约 {tin:,} + 输出约 {tout:,}",
                  f"费用:约 ${cost:.2f}(按单轮估算;实际平均 1~2 轮,"
                  f"请按 2 倍留出余量)",
                  "",
                  "注:这是按当前配置的 writer_price_* 计算的,改模型/改服务商记得同步改价格。"]
    else:
        ok = sum(1 for s in stats if s.get("passed"))
        lines += [f"实际合计:{len(stats)} 个任务 — 通过 {ok} / 其中跳过 {skipped} / "
                  f"失败 {len(stats) - ok}",
                  f"token:输入 {tin:,} + 输出 {tout:,}",
                  f"费用:约 ${cost:.2f}"]
        rounds = [s["rounds"] for s in stats if not s.get("skipped")]
        if rounds:
            lines.append(f"平均轮数:{sum(rounds) / len(rounds):.1f}")
        failed = [s["rel_path"] for s in stats if not s.get("passed")]
        if failed:
            lines += ["", "未通过(需人工查看 build/reports/):"] + [f"  - {f}" for f in failed[:20]]
    lines.append("=" * 56)
    return "\n".join(lines)
