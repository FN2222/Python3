"""通用工具:JSON 读写、slug、哈希、日志、文本归一化。"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------- 日志

_LEVEL_TAG = {"info": "[信息]", "warn": "[警告]", "error": "[错误]", "ok": "[完成]"}


def log(msg: str, level: str = "info") -> None:
    stream = sys.stderr if level in ("warn", "error") else sys.stdout
    print(f"{_LEVEL_TAG.get(level, '[信息]')} {msg}", file=stream, flush=True)


# ---------------------------------------------------------------- JSON

def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"文件不存在: {p}")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- 标识与哈希

_SLUG_BAD = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKC", text).strip()
    text = _SLUG_BAD.sub("-", text).strip("-").lower()
    return text[:max_len] or "untitled"


def short_hash(text: str, n: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def pdf_id_for(rel_path: str) -> str:
    """由相对路径生成稳定、可读、无冲突的 ID。"""
    rel = rel_path.replace("\\", "/")
    stem = Path(rel).stem
    return f"{slugify(stem, 48)}-{short_hash(rel)}"


# ---------------------------------------------------------------- 文本

_WS = re.compile(r"\s+")


def norm_space(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def norm_for_match(text: str) -> str:
    """用于原文比对的归一化:统一空白、破折号、引号,并转小写。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = (text.replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2013", "-").replace("\u2014", "-")
                .replace("\u2011", "-").replace("\u00a0", " "))
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    return _WS.sub(" ", text).strip().lower()


CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text or ""))


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def rel_posix(path: Path, start: Path) -> str:
    import os
    return Path(os.path.relpath(path, start)).as_posix()


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
