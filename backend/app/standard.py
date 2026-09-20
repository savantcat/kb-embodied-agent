# -*- coding: utf-8 -*-
"""国标体检内核：加载 GB/T 47746—2026 逐项清单，做判定与整改清单生成。

数据源：kb/standards/gbt47746-checklist.json（真源：cn-ai-cs-checklist/data/checklist-v2.0.json，
2026-09-19 逐项实数复核：61 项 = 48「应」+ 4「宜」+ 9「可」，含 5 项一票项 B21a–e）。
判定口径（建议口径，标准本身未规定分级）：
  ✅ 达标      48 项「应」全部满足
  ⚠️ 基本达标  「应」不满足 ≤ 3 项，且不涉及任何一票项
  ❌ 不达标    「应」不满足 ≥ 4 项，或任一票项不满足
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).resolve().parents[2] / "kb" / "standards" / "gbt47746-checklist.json"

STATUS_OK = "满足"
STATUS_PARTIAL = "部分"
STATUS_BAD = "不满足"

SECTIONS = {
    "A": "总体要求（第 4 章）",
    "B": "呼入任务（第 5 章）",
    "C": "呼出任务（第 6 章）",
    "D": "服务结束与后续处理（第 7 章）",
    "E": "信息安全（第 8 章）",
    "F": "协同服务改进（第 9 章）",
}


def load_checklist(path: Path | None = None) -> dict:
    p = path or _DATA
    return json.loads(p.read_text(encoding="utf-8"))


def ids(cl: dict | None = None) -> list[str]:
    """全部条目编号（按标准顺序）。"""
    return [i["id"] for i in load_checklist(cl)["items"]]


def summary(cl: dict | None = None) -> dict:
    """返回清单元信息与计数，供体检报告头部使用。"""
    cl = cl or load_checklist()
    items = cl["items"]
    by_level: dict[str, int] = {}
    for it in items:
        by_level[it["level"]] = by_level.get(it["level"], 0) + 1
    sections: dict[str, dict] = {}
    for it in items:
        sec = it["id"][0]
        s = sections.setdefault(sec, {"key": sec, "name": SECTIONS.get(sec, sec), "total": 0, "应": 0, "宜": 0, "可": 0})
        s["total"] += 1
        s[it["level"]] += 1
    return {
        "standard": cl["meta"].get("standard", "GB/T 47746—2026"),
        "published": cl["meta"].get("standard_published", ""),
        "effective": cl["meta"].get("standard_effective", ""),
        "nature": cl["meta"].get("nature", "推荐性国家标准"),
        "total": len(items),
        "by_level": by_level,
        "veto_ids": [it["id"] for it in items if it.get("is_veto")],
        "sections": list(sections.values()),
    }


def evaluate(answers: dict[str, str], cl: dict | None = None) -> dict:
    """按逐项自查结果出报告。

    answers: {"A1": "满足"|"部分"|"不满足", ...}；未提供的项按"不满足"计（保守口径）。
    """
    cl = cl or load_checklist()
    items = cl["items"]
    rows = []
    miss_mandatory, miss_veto, pending = [], [], []
    for it in items:
        st = answers.get(it["id"], STATUS_BAD)
        if st not in (STATUS_OK, STATUS_PARTIAL, STATUS_BAD):
            st = STATUS_BAD
        ok = st == STATUS_OK
        if not ok and it["level"] == "应":
            miss_mandatory.append(it["id"])
        if not ok and it.get("is_veto"):
            miss_veto.append(it["id"])
        if st == STATUS_BAD:
            pending.append(it["id"])
        rows.append({
            "id": it["id"], "clause": it["clause"], "level": it["level"],
            "is_veto": bool(it.get("is_veto")), "requirement": it["requirement"],
            "status": st, "how_to_fix": it["how_to_fix"],
        })

    if miss_veto or len(miss_mandatory) >= 4:
        verdict = "❌ 不达标"
        verdict_reason = ("存在一票项未满足：" + "、".join(miss_veto)) if miss_veto else f"「应」项不满足 {len(miss_mandatory)} 项（≥4）"
    elif miss_mandatory:
        verdict = "⚠️ 基本达标"
        verdict_reason = f"「应」项不满足 {len(miss_mandatory)} 项（≤3），且未涉及一票项"
    else:
        verdict = "✅ 达标"
        verdict_reason = "48 项「应」全部满足"

    return {
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "summary": {
            "total": len(items),
            "ok": sum(1 for r in rows if r["status"] == STATUS_OK),
            "partial": sum(1 for r in rows if r["status"] == STATUS_PARTIAL),
            "bad": sum(1 for r in rows if r["status"] == STATUS_BAD),
            "miss_mandatory": len(miss_mandatory),
            "miss_veto": miss_veto,
        },
        "rows": rows,
        "todo": [r for r in rows if r["status"] != STATUS_OK],
    }


def to_markdown(report: dict) -> str:
    """把体检报告导出为 Markdown 整改清单（可直接交给客户/内部整改）。"""
    s, sm = report, report["summary"]
    lines = [
        "# AI 客服国标自查体检报告",
        "",
        f"- 依据标准：GB/T 47746—2026《顾客联络服务 人工与智能客户服务协同要求》"
        f"（发布 2026-05-25，实施 2026-09-01，推荐性国家标准）",
        f"- 结论：**{s['verdict']}** —— {s['verdict_reason']}",
        f"- 自查覆盖：{sm['total']} 项 ｜ 满足 {sm['ok']} ｜ 部分 {sm['partial']} ｜ 不满足 {sm['bad']}",
        f"- 其中「应」项未满足 {sm['miss_mandatory']} 项；一票项未满足：{('、'.join(sm['miss_veto']) or '无')}",
        "",
        "## 待整改清单（按一票项优先）",
        "",
        "| 编号 | 条款 | 强制 | 一票项 | 要求 | 现状 | 整改动作 |",
        "|:--|:--|:--|:--|:--|:--|:--|",
    ]
    ordered = sorted(s["todo"], key=lambda r: (not r["is_veto"], r["id"]))
    for r in ordered:
        lines.append(f"| {r['id']} | {r['clause']} | {r['level']} | {'★' if r['is_veto'] else ''} | "
                     f"{r['requirement']} | {r['status']} | {r['how_to_fix']} |")
    if not ordered:
        lines.append("| — | — | — | — | 全部达标，无需整改 | — | — |")
    lines += [
        "",
        "> 说明：本报告为自查工具输出，不构成认证结论。标准「应」为必须做到、「宜」为推荐、「可」为可选。",
        "> 题目口径：61 项 = 48「应」+ 4「宜」+ 9「可」，含 5 项一票项（B21a–e 五类强制自动转接）。",
        "",
    ]
    return "\n".join(lines)
