# -*- coding: utf-8 -*-
"""本地开发服务器（仅开发用，不是生产部署方式）。

作用：把 web/ 静态页跑起来，并把 /api/* 反向代理到本地后端，
      这样不装 Docker 也能验证前端 ↔ 后端整条链路。

用法：
  1) 先起后端：cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8011
     （或：uvicorn app.main:app --port 8011）
  2) 再起本脚本：python scripts/dev_server.py --port 8080 --backend http://127.0.0.1:8011
  3) 浏览器打开 http://127.0.0.1:8080
"""
import argparse, http.server, os, socketserver, urllib.error, urllib.request

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
BACKEND = "http://127.0.0.1:8011"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    def _proxy(self, method):
        url = BACKEND + self.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(url, data=body, method=method,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload, status, ctype = r.read(), r.status, r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            payload, status, ctype = e.read(), e.code, "application/json"
        except Exception as e:
            payload, status, ctype = ('{"detail":"%s"}' % e).encode(), 502, "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy("POST")
        self.send_error(405)

    def log_message(self, fmt, *args):
        print("[dev] %s" % (fmt % args))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--backend", default=BACKEND)
    a = ap.parse_args()
    BACKEND = a.backend.rstrip("/")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", a.port), Handler) as srv:
        print("web: %s\n后端: %s\n打开: http://127.0.0.1:%d" % (WEB_DIR, BACKEND, a.port))
        srv.serve_forever()
