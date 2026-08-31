"""一个假的 OpenAI 兼容服务,用来在**不花任何 API 费用**的情况下验证 nlnotes write 的自修闭环。

行为:
  第 1 次请求 -> 故意返回一份"有臆想"的 note.json(编造定时器数值 + 引用被改写)
  第 2 次请求 -> 返回正确的 note.json
这样就能验证:写 -> 校验拦下 -> 错误回灌 -> 重写 -> 通过 的整个循环真的跑得通。

用法:
    python tests/mock_llm_server.py <port> <fixture.json> [broken|ok]
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATE = {"calls": 0}


def _make_broken(note: dict) -> dict:
    """制造两处必被门禁拦下的问题。"""
    bad = json.loads(json.dumps(note))
    # 1) 编造定时器数值(T001)
    bad["sections"][0]["points"][3]["text_zh"] = "dead interval 默认是 120 秒,是 hello interval 的四倍。"
    # 2) 把原文引用改写成自己的话(Q001)
    bad["sections"][0]["points"][0]["text_en_quote"] = \
        "OSPF routers exchange gossip messages so that they can find their friends."
    return bad


class Handler(BaseHTTPRequestHandler):
    fixture: dict = {}
    mode: str = "broken"

    def log_message(self, *args):        # 静默
        pass

    def do_POST(self):                   # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except Exception:
            req = {}

        STATE["calls"] += 1
        first = STATE["calls"] == 1
        note = (_make_broken(self.fixture)
                if (self.mode == "broken" and first) else self.fixture)

        # 第 2 次请求应当带上门禁反馈,顺手断言一下
        user = ""
        for m in req.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        if not first and "上一轮校验未通过" not in user:
            note = {"error": "反馈没有回灌给模型"}

        content = json.dumps(note, ensure_ascii=False)
        payload = {
            "id": "mock-1", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": len(user) // 4,
                      "completion_tokens": len(content) // 4,
                      "total_tokens": (len(user) + len(content)) // 4},
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int, fixture_path: Path, mode: str = "broken") -> None:
    Handler.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    Handler.mode = mode
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]), Path(sys.argv[2]),
          sys.argv[3] if len(sys.argv) > 3 else "broken")
