#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解决率回归测试：用 60 条真实口语问句验证「数字人客服自己接住多少」。

用法：
    python scripts/run_regression.py                    # 打本地 8080
    BASE=https://xxx python scripts/run_regression.py   # 打远端

判据（对齐用户验收口径）：
  - 语料内/业务内问题：必须「接住」——route ∈ {kb, answer, clarify, guide}，**不得转人工**；
  - 高风险问题（投诉/法律/身份核验/明确要人工）：必须 route == handoff；
  - 空回答（text 为空）= 0 条；
  - 解决率 = 接住数 / 业务内问句数 ≥ 90%。

每条问句用**独立会话**，避免多轮阈值干扰。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MODE = "unknown"
BASE = os.getenv("BASE", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = int(os.getenv("TIMEOUT", "90"))

# (问句, 期望)  期望 handoff = 必须转人工；其余 = 必须自己接住（kb 直答 / clarify 引导 / guide 拉回 / answer 据实答）
CASES: list[tuple[str, str]] = [
    # —— 国标合规（10） ——
    ("国标要自查多少项？", "kb"),
    ("客服必须保留人工坐席吗？", "kb"),
    ("哪些情况必须自动转人工？", "kb"),
    ("转人工之后要不要让客户重新说一遍？", "kb"),
    ("AI 客服会不会把人工坐席全替代掉？", "kb"),
    ("客户信息和交互记录有什么安全要求？", "kb"),
    ("不满足国标会被罚款吗？", "kb"),
    ("最容易漏掉的自查项是哪些？", "kb"),
    ("应、宜、可分别是什么意思？", "kb"),
    ("AI 客服要满足哪个国家标准？", "kb"),
    # —— 知识库建设（9） ——
    ("企业知识库为什么总是不好用？", "kb"),
    ("知识库到底是什么结构？", "kb"),
    ("为什么要用 RAG 而不是直接把文档丢给大模型？", "kb"),
    ("检索是怎么找资料的？", "kb"),
    ("知识库能不能保证不答错？", "kb"),
    ("语料要准备成什么格式？", "kb"),
    ("知识库更新要多久一次？", "kb"),
    ("知识库建好以后谁来维护？", "kb"),
    ("我们公司不大，适合用吗？", "kb"),
    # —— 交付 / 报价 / 售后 / 部署 / 安全（12） ——
    ("你们的服务时间是什么时候？", "kb"),
    ("这套东西大概多少钱？", "kb"),
    ("报价怎么算、按什么收？", "kb"),
    ("交付一次大概要多久？", "kb"),
    ("交付之后谁来维护？", "kb"),
    ("能不能先免费试用看看效果？", "kb"),
    ("支持哪些部署方式？", "kb"),
    ("可以本地部署吗，数据不出我们公司？", "kb"),
    ("客户数据会不会被上传到外部？", "kb"),
    ("这套东西三年后会不会过时？", "kb"),
    ("数字人这层是自研的吗？", "kb"),
    ("和直接在大模型平台搭个机器人有什么区别？", "kb"),
    # —— 口语化变体（业务内，必须接住）（6） ——
    ("你们这个知识库怎么才能弄好啊？", "any"),
    ("国标那个自查，到底查些啥？", "any"),
    ("我们这种小公司弄这个，值不值？", "any"),
    ("弄一套下来，大概要花多少？", "any"),
    ("这玩意儿上线要备案吗？", "any"),
    ("客户问东问西答不上来怎么办？", "any"),
    # —— 通用概念 / 常识（4） ——
    ("什么是大模型？", "any"),
    ("RAG 是什么的缩写？", "any"),
    ("数字人是怎么动起来的？", "any"),
    ("知识库和搜索引擎有什么区别？", "any"),
    # —— 含糊 / 信息不足（引导澄清）（8） ——
    ("就是那个东西，你们懂的吧", "any"),
    ("反正就上次那个，你帮我看看", "any"),
    ("我说不清楚，你直接给我处理了吧", "any"),
    ("那个怎么弄？", "any"),
    ("我不太懂，你说说", "any"),
    ("有没有方案？", "any"),
    ("帮我看看这个", "any"),
    ("你们能做吗？", "any"),
    # —— 闲聊 / 非业务（拉回业务）（6） ——
    ("今天天气怎么样？", "any"),
    ("你叫什么名字？", "any"),
    ("你们老板是谁？", "any"),
    ("中午吃什么好？", "any"),
    ("给我讲个笑话", "any"),
    ("现在几点了？", "any"),
    # —— 高风险 / 明确要人工（必须转人工）（6） ——
    ("我要转人工", "handoff"),
    ("我要投诉你们！", "handoff"),
    ("我要报警", "handoff"),
    ("这是诈骗，我请律师起诉你们", "handoff"),
    ("我不想跟机器说话，叫个人来", "handoff"),
    ("我的身份证号能帮我改一下绑定的银行卡吗", "handoff"),
]


def ask(text: str, sid: str) -> dict:
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps({"session_id": sid, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _mode() -> str:
    """读后端当前模式：报告必须写明 online/offline —— 否则评审用离线复现会得到相反结论。"""
    try:
        import json as _json
        with urllib.request.urlopen(BASE + "/api/health", timeout=5) as r:
            return str(_json.load(r).get("demo_mode") or "unknown")
    except Exception:
        return "unknown"


def main() -> int:
    global MODE
    MODE = _mode()                     # 报告里必须写明 online/offline
    rows: list[dict] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    print("回归问句集：%d 条 → %s（模式 %s）\n" % (len(CASES), BASE, MODE))
    for i, (q, expect) in enumerate(CASES, 1):
        sid = "reg-%s-%03d" % (stamp, i)
        try:
            d = ask(q, sid)
            route = str(d.get("route") or "")
            text = str(d.get("text") or "")
            ok = (route == "handoff") if expect == "handoff" else (route != "handoff")
            rows.append({"q": q, "expect": expect, "route": route, "text": text, "ok": ok})
            print("%s %2d. [%-7s] %s → %s" % ("✓" if ok else "✗", i, route or "?", q, text[:44].replace("\n", " ")))
        except Exception as e:  # noqa: BLE001
            rows.append({"q": q, "expect": expect, "route": "ERROR", "text": str(e)[:80], "ok": False})
            print("✗ %2d. [ERROR  ] %s → %s" % (i, q, type(e).__name__))
        time.sleep(0.3)

    biz = [r for r in rows if r["expect"] != "handoff"]
    hi = [r for r in rows if r["expect"] == "handoff"]
    caught = [r for r in biz if r["route"] != "handoff"]
    wrong_handoff = [r for r in biz if r["route"] == "handoff"]
    missed_handoff = [r for r in hi if r["route"] != "handoff"]
    empty = [r for r in rows if not str(r["text"]).strip()]
    rate = 100.0 * len(caught) / max(1, len(biz))

    print("\n" + "=" * 56)
    print("业务内问句 %d 条：自己接住 %d 条，误转人工 %d 条 → 解决率 %.1f%%"
          % (len(biz), len(caught), len(wrong_handoff), rate))
    print("高风险问句 %d 条：正确转人工 %d 条，漏转 %d 条" % (len(hi), len(hi) - len(missed_handoff), len(missed_handoff)))
    print("空回答 %d 条（必须为 0）" % len(empty))
    from collections import Counter
    print("路由分布：", dict(Counter(r["route"] for r in rows)))
    if wrong_handoff:
        print("\n误转人工明细：")
        for r in wrong_handoff:
            print("  -", r["q"], "→", r["text"][:50])
    if missed_handoff:
        print("\n漏转人工明细：")
        for r in missed_handoff:
            print("  -", r["q"], "→ [%s] %s" % (r["route"], r["text"][:50]))

    out = Path("docs") / "解决率回归报告.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 数字人客服 · 解决率回归报告",
        "",
        "生成时间：%s　|　问句集：%d 条　|　端点：`%s`　|　模式：**%s**"
        % (time.strftime("%Y-%m-%d %H:%M:%S"), len(rows), BASE, MODE),
        "",
        "口径：**业务内问题必须被数字人自己接住**（知识库直答 / 反问引导 / 拉回业务 / 据实作答），",
        "不得转人工；只有高风险场景（投诉、法律、身份核验、客户明确要求人工）才转人工。",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        "| 业务内问句 | %d |" % len(biz),
        "| 自己接住 | %d |" % len(caught),
        "| 误转人工 | %d |" % len(wrong_handoff),
        "| **解决率** | **%.1f%%** |" % rate,
        "| 高风险问句 | %d（正确转人工 %d） |" % (len(hi), len(hi) - len(missed_handoff)),
        "| 空回答 | %d（要求 0） |" % len(empty),
        "",
        "## 逐条结果",
        "",
        "| # | 问句 | 期望 | 实际路由 | 是否达标 | 回答摘要 |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append("| %d | %s | %s | `%s` | %s | %s |" % (
            i, r["q"].replace("|", "\\|"), r["expect"], r["route"], "✅" if r["ok"] else "❌",
            r["text"][:60].replace("\n", " ").replace("|", "\\|")))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n报告已写入：%s" % out)
    Path("_regression_result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if (rate >= 90 and not empty and not wrong_handoff and not missed_handoff) else 1


if __name__ == "__main__":
    sys.exit(main())
