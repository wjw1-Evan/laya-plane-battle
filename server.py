# -*- coding: utf-8 -*-
"""飞机大战 · Laya 控制版 —— 本地决策服务器 + 静态页面。

GET  /       -> index.html
POST /decide -> {"text": "<战场状态文字>"} -> Laya Router -> 五项判断 JSON
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from laya import Router

Q_DODGE = {
    "dodge": {
        "type": "choice",
        "instructions": "Is a bullet about to hit the player?",
        "criteria": {
            "yes": "a bullet is about to hit the player",
            "no":  "no bullet is about to hit the player",
        },
    },
    "bullet_side": {
        "type": "choice",
        "instructions": "Which side of the player is the bullet about to hit on?",
        "criteria": {
            "left":  "the bullet is on the left side of the player",
            "right": "the bullet is on the right side of the player",
        },
    },
    "dodge_dir": {
        "type": "choice",
        "instructions": "If escaping sideways, which corridor is safer?",
        "criteria": {
            "left":  "the left corridor crosses fewer bullet lanes",
            "right": "the right corridor crosses fewer bullet lanes",
        },
    },
    "dodge_dir": {
        "type": "choice",
        "instructions": "If escaping sideways, which corridor is safer?",
        "criteria": {
            "left":  "the left corridor crosses fewer bullet lanes",
            "right": "the right corridor crosses fewer bullet lanes",
        },
    },
}

Q_CHASE = {
    "fire": {
        "type": "choice",
        "instructions": "Should the player fire right now?",
        "criteria": {
            "yes": "an enemy ship is almost directly above the player (aligned with the guns), so firing will hit it",
            "no":  "no enemy ship is aligned with the player, firing would miss",
        },
    },
    "enemy_side": {
        "type": "choice",
        "instructions": "Where is the most urgent (deepest) enemy ship?",
        "criteria": {
            "left":  "to the left of the player",
            "right": "to the right of the player",
            "here":  "almost directly above the player",
        },
    },
}

QUESTIONS = {"dodge": Q_DODGE, "chase": Q_CHASE}   # 按需出题:躲弹态 3 问,拦截态 2 问

router = Router()
router.load("multilingual")   # 游戏只用 multilingual;避免 preload 全量(含未下载的 typed-decisions)
_predict_lock = threading.Lock()   # torch/MPS 不支持并发推理,必须串行
print("[laya-game] models loaded, serving on http://127.0.0.1:8787")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # keep-alive:浏览器复用连接,省掉每请求 TCP+线程开销(~40ms)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            p = Path(__file__).parent / "index.html"
            self._send(200, p.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"{}", "application/json")

    def do_POST(self):
        if self.path != "/decide":
            return self._send(404, b"{}", "application/json")
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        with _predict_lock:
            r = router.predict(req["text"], QUESTIONS[req.get("mode", "chase")], model="multilingual")
        out = {"answers": r["answers"]}
        self._send(200, json.dumps(out, ensure_ascii=False).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
