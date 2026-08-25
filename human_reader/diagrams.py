from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from .models import Diagram
from .textutil import normalize_visible_text

_TOPOLOGY_RE = re.compile(
    r"topology|topo|flowchart|diagram|architecture|mermaid|vis-network|"
    r"cytoscape|graph|schema|拓扑|架构|流程图|网络图|拓扑图",
    re.IGNORECASE,
)
_SKIP_SRC_RE = re.compile(
    r"favicon|sprite|emoji|avatar|pixel\.gif|1x1|tracking|ads?[-_/]",
    re.IGNORECASE,
)


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.diagrams: list[Diagram] = []
        self._svg_depth = 0
        self._svg_parts: list[str] = []
        self._svg_attrs: dict[str, str] = {}
        self._in_caption = False
        self._caption: list[str] = []
        self._pending_alt = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "img":
            src = ad.get("src") or ad.get("data-src") or ad.get("data-original") or ""
            alt = ad.get("alt") or ad.get("title") or ""
            cls = " ".join([ad.get("class", ""), ad.get("id", ""), alt, src])
            if src and not _SKIP_SRC_RE.search(src):
                self.diagrams.append(
                    Diagram(
                        index=len(self.diagrams),
                        kind="img",
                        alt=alt or "课程配图",
                        src=src,
                        caption=alt,
                        is_topology=bool(_TOPOLOGY_RE.search(cls)),
                    )
                )
            self._pending_alt = alt
        elif tag == "svg":
            self._svg_depth += 1
            if self._svg_depth == 1:
                self._svg_parts = ["<svg"]
                for key, val in attrs:
                    if val is None:
                        self._svg_parts.append(f" {key}")
                    else:
                        self._svg_parts.append(f' {key}="{val}"')
                self._svg_parts.append(">")
                self._svg_attrs = ad
        elif self._svg_depth:
            self._svg_parts.append(f"<{tag}")
            for key, val in attrs:
                if val is None:
                    self._svg_parts.append(f" {key}")
                else:
                    self._svg_parts.append(f' {key}="{val}"')
            self._svg_parts.append(">")
        elif tag in {"figcaption", "caption"}:
            self._in_caption = True
        elif tag == "pre" and _TOPOLOGY_RE.search(ad.get("class", "") + ad.get("id", "")):
            self._pending_alt = "mermaid"

    def handle_data(self, data: str) -> None:
        if self._svg_depth:
            self._svg_parts.append(data)
        elif self._in_caption:
            self._caption.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "svg" and self._svg_depth:
            self._svg_parts.append("</svg>")
            self._svg_depth -= 1
            if self._svg_depth == 0:
                markup = "".join(self._svg_parts)
                blob = " ".join(
                    [
                        self._svg_attrs.get("class", ""),
                        self._svg_attrs.get("id", ""),
                        self._svg_attrs.get("aria-label", ""),
                        markup[:500],
                    ]
                )
                self.diagrams.append(
                    Diagram(
                        index=len(self.diagrams),
                        kind="svg",
                        alt=self._svg_attrs.get("aria-label") or "拓扑图",
                        src="inline-svg",
                        caption=normalize_visible_text("".join(self._caption)),
                        inline_svg=markup,
                        is_topology=True if _TOPOLOGY_RE.search(blob) else True,
                    )
                )
                self._svg_parts = []
                self._caption = []
            return
        if self._svg_depth:
            self._svg_parts.append(f"</{tag}>")
            return
        if tag in {"figcaption", "caption"}:
            self._in_caption = False
            if self.diagrams and not self.diagrams[-1].caption:
                self.diagrams[-1].caption = normalize_visible_text("".join(self._caption))
            self._caption = []


def extract_diagrams(html: str, base_url: str, limit: int) -> list[Diagram]:
    parser = _AssetParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    out: list[Diagram] = []
    for item in parser.diagrams:
        if len(out) >= limit:
            break
        if item.src and item.src != "inline-svg":
            item.src = urljoin(base_url, item.src)
        item.index = len(out)
        out.append(item)
    return out
