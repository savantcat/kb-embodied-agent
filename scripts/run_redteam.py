#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合规红队测试台 · 无人值守回归（宿主机侧运行，结果落仓）

用法：
    python scripts/run_redteam.py                     # 默认后端 http://127.0.0.1:8080
    python scripts/run_redteam.py http://host:8080    # 指定后端

做的事：
    1) 调 POST /api/redteam/run-all —— 服务端把 12 条用例跑完并逐条客观判定；
    2) 把 Markdown 报告写到 docs/合规红队测试报告.md（便于随仓库一起交付/审阅）；
    3) 若存在不达标用例，退出码为 1（可直接接进 CI）。

说明：判定在服务端完成（是否转人工 / 是否携带上下文 / 是否有依据来源 / 是否留痕），
本脚本只负责触发与落盘，因此与前端双数字人页面跑出的结论完全同源。
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "合规红队测试报告.md"


def main() -> int:
    req = urllib.request.Request(f"{BASE}/api/redteam/run-all", data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())

    rows = d.get("results", [])
    print(f"达标 {d.get('passed')}/{d.get('total')} | 一票项 {d.get('veto_passed')}/{d.get('veto_total')}")
    for x in rows:
        bad = [c["name"] for c in x.get("checks", []) if not c["ok"]]
        print(("✅" if x.get("pass") else "❌"), x.get("case_id"), x.get("caliber"),
              ("| 未过：" + "、".join(bad)) if bad else "")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(d.get("markdown", ""), encoding="utf-8")
    print(f"报告已写入：{OUT}")
    return 0 if d.get("passed") == d.get("total") else 1


if __name__ == "__main__":
    raise SystemExit(main())
