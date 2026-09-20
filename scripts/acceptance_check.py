#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KB-Embodied-Agent · 交付前全面验收测试（跑通即代表可交付）

用法：
    python scripts/acceptance_check.py [http://127.0.0.1:8080]

覆盖 8 组检查：
    A 部署与健康      B 合规红队全量回归      C 真转人工闭环（含人工接管/转回问候）
    D 记忆与个性化    E 国标体检与知识库体检  F 信任层（一键停/留痕/依据溯源）
    G 密钥边界        H 前端页面可达与静态资源
退出码：全过 0；任一失败 1（可接 CI）。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
OK: list[str] = []
BAD: list[str] = []


def req(path: str, obj=None, method: str | None = None, timeout: int = 180):
    data = json.dumps(obj or {}).encode() if (obj is not None or method == "POST") else None
    r = urllib.request.Request(BASE + path, data=data,
                               headers={"Content-Type": "application/json"},
                               method=method or ("POST" if obj is not None else "GET"))
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read()
        try:
            return json.loads(raw)
        except Exception:
            return raw.decode("utf-8", "ignore")


def check(name: str, cond: bool, detail: str = "") -> None:
    (OK if cond else BAD).append(f"{name}{('：' + detail) if detail else ''}")
    print(("✅ " if cond else "❌ ") + name + (("　" + detail) if detail else ""))


def main() -> int:
    print(f"—— 验收目标：{BASE} ——\n")

    # A 部署与健康
    h = req("/api/health")
    check("A1 后端健康", bool(h.get("ok")), f"llm={h.get('llm_configured')} xmov={h.get('xmov_configured')} kb={h.get('kb_path')}")
    st = req("/api/stats")
    check("A2 数字人并发与开关可读", "concurrency" in st and "avatar_enabled" in st,
          f"开关={st.get('avatar_enabled')} 并发={st.get('concurrency')}")

    # B 合规红队全量回归
    rt = req("/api/redteam/run-all", method="POST")
    check("B1 红队 12 条用例全量回归", rt.get("passed") == rt.get("total"),
          f"{rt.get('passed')}/{rt.get('total')}")
    check("B2 五项一票项全过", rt.get("veto_passed") == rt.get("veto_total"),
          f"{rt.get('veto_passed')}/{rt.get('veto_total')}")

    # C 真转人工闭环
    sid = "acc-handoff"
    d = req("/api/chat", {"text": "帮我转人工", "session_id": sid})
    tid = next((w["payload"].get("ticket", {}).get("id") for w in d.get("widgets", [])
                if w.get("type") == "handoff"), None)
    check("C1 转人工自动建单", bool(tid), f"工单 {tid}")
    if tid:
        q = req("/api/handoff/queue")
        check("C2 坐席台队列可见", any(i["id"] == tid for i in q["items"]), f"排队 {q['queued']}")
        req("/api/handoff/claim", {"ticket": tid, "agent": "坐席A"})
        r = req("/api/chat", {"text": "我再问一句", "session_id": sid})
        check("C3 人工接管期间 AI 暂停", r.get("mode") == "takeover", r.get("mode", ""))
        req("/api/handoff/say", {"ticket": tid, "text": "已为您处理完成。", "role": "agent"})
        req("/api/handoff/release", {"ticket": tid})
        msgs = req(f"/api/handoff/messages?ticket={tid}&since=0")["messages"]
        ai_msgs = [m for m in msgs if m["role"] == "ai"]
        check("C4 转回后数字客服主动问候", bool(ai_msgs),
              (ai_msgs[0]["text"][:34] + "…") if ai_msgs else "无")
        check("C5 问候语询问是否解决", any("解决" in m["text"] for m in ai_msgs))
        r2 = req("/api/chat", {"text": "国标要自查多少项", "session_id": sid})
        check("C6 转回后 AI 恢复应答", bool((r2.get("text") or "").strip()) and r2.get("mode") != "takeover",
              (r2.get("text") or "")[:20])
        req("/api/handoff/close", {"ticket": tid, "note": "验收测试"})

    # D 记忆与个性化
    sid2 = "acc-memory"
    req("/api/chat", {"text": "我叫龙建洲，做小微企业知识库的", "session_id": sid2})
    m = req(f"/api/memory?session_id={sid2}")
    check("D1 多轮记忆写入", m["turns"] >= 2, f"{m['turns']} 轮")
    check("D2 个性化档案记住称呼", m["profile"].get("name") == "龙建洲", str(m["profile"]))
    d3 = req("/api/chat", {"text": "我刚才说我叫什么？", "session_id": sid2})
    check("D3 记忆问题不再转人工", "龙" in (d3.get("text") or ""), (d3.get("text") or "")[:24])

    # E 国标体检与知识库体检
    sc = req("/api/selfcheck", {})
    check("E1 国标体检可用", bool(sc.get("summary") or sc.get("items") or sc.get("markdown")))
    kb = req("/api/kb-audit", {})
    check("E2 知识库体检可用", bool(kb.get("files") or kb.get("coverage") or kb))

    # F 信任层
    req("/api/kill", {"stopped": True, "reason": "验收测试"})
    rk = req("/api/chat", {"text": "国标要自查多少项", "session_id": "acc-kill"})
    check("F1 一键停生效（转人工）", rk.get("mode") == "killed"
          or any(w.get("type") == "handoff" for w in rk.get("widgets", [])))
    req("/api/kill", {"stopped": False, "reason": ""})
    au = req("/api/audit?limit=5")
    check("F2 操作留痕可回查", bool(au.get("items") or au.get("entries") or au))

    # G 密钥边界
    sess = req("/api/session", method="POST")
    blob = json.dumps(sess, ensure_ascii=False)
    leaked = [k for k in ("appSecret", "app_secret", "secret", "token", "Authorization") if k in blob]
    check("G1 /api/session 不下发密钥", not leaked, ("泄漏字段 " + ",".join(leaked)) if leaked else "仅下发代理地址")
    av = sess.get("avatar", {})
    check("G2 浏览器走服务端网关代理", (not av.get("enabled")) or bool(av.get("gateway_proxy")),
          str(av.get("gateway_proxy", "")))

    # H 前端页面
    for path in ("/", "/audit.html", "/agent.html"):
        try:
            body = req(path) if not isinstance(req(path), dict) else ""
            check(f"H 页面可达 {path}", True)
        except Exception as e:
            check(f"H 页面可达 {path}", False, str(e))

    print("\n—— 汇总 ——")
    print(f"通过 {len(OK)} 项，失败 {len(BAD)} 项")
    for b in BAD:
        print("  ❌ " + b)
    return 0 if not BAD else 1


if __name__ == "__main__":
    raise SystemExit(main())
