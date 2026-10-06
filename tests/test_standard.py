# -*- coding: utf-8 -*-
"""国标体检内核单测：清单完整性 + 判定分级边界 + 整改清单导出。

判定口径（app/standard.py 模块注释）：✅ 48 项「应」全满足；
⚠️ 「应」不满足 ≤3 且不涉及一票项；❌ 「应」不满足 ≥4 或任一票项不满足。
"""
import app.standard as sm


def _all_ok():
    return {i: "满足" for i in sm.ids()}


# ---------------------------------------------------------------- 清单完整性

def test_checklist_has_61_items():
    """61 项是唯一正确口径（禁写 59/53/48）。"""
    assert len(sm.load_checklist()["items"]) == 61
    assert len(sm.ids()) == 61


def test_level_counts_are_48_4_9():
    lv = {}
    for it in sm.load_checklist()["items"]:
        lv[it["level"]] = lv.get(it["level"], 0) + 1
    assert lv == {"应": 48, "宜": 4, "可": 9}
    assert sum(lv.values()) == 61


def test_ids_unique_and_start_with_section_letters():
    ids = sm.ids()
    assert len(set(ids)) == 61, "编号必须唯一"
    assert ids[0] == "A1"
    assert all(i[0] in "ABCDEF" for i in ids)


def test_veto_items_are_b21a_to_e():
    """一票项恰好 5 项，且是 B21a–e（五类强制自动转接）。"""
    assert sm.summary()["veto_ids"] == ["B21a", "B21b", "B21c", "B21d", "B21e"]


def test_sections_cover_six_chapters_and_sum_to_61():
    secs = sm.summary()["sections"]
    assert [s["key"] for s in secs] == ["A", "B", "C", "D", "E", "F"]
    assert sum(s["total"] for s in secs) == 61
    for s in secs:
        assert s["应"] + s["宜"] + s["可"] == s["total"], f"{s['key']} 分区级别数不守恒"


def test_summary_meta_matches_standard():
    s = sm.summary()
    assert "GB/T 47746" in s["standard"]
    assert s["published"] == "2026-05-25"
    assert s["effective"] == "2026-09-01"
    assert s["total"] == 61


def test_every_item_has_required_fields():
    for it in sm.load_checklist()["items"]:
        for k in ("id", "clause", "level", "requirement", "how_to_fix"):
            assert it.get(k), f"{it.get('id')} 缺字段 {k}"


# ---------------------------------------------------------------- 判定分级边界

def test_all_ok_is_full_pass():
    r = sm.evaluate(_all_ok())
    assert r["verdict"].startswith("✅")
    assert r["summary"]["miss_mandatory"] == 0
    assert r["todo"] == []


def test_three_mandatory_missing_is_basic_pass():
    """「应」不满足 ≤3 且不碰一票项 → ⚠️ 基本达标（边界值 3）。"""
    cl = sm.load_checklist()
    mand = [i["id"] for i in cl["items"] if i["level"] == "应" and not i.get("is_veto")]
    a = _all_ok()
    for x in mand[:3]:
        a[x] = "不满足"
    r = sm.evaluate(a)
    assert r["verdict"].startswith("⚠️")
    assert r["summary"]["miss_mandatory"] == 3


def test_four_mandatory_missing_fails():
    """边界值 4 → ❌ 不达标。"""
    cl = sm.load_checklist()
    mand = [i["id"] for i in cl["items"] if i["level"] == "应" and not i.get("is_veto")]
    a = _all_ok()
    for x in mand[:4]:
        a[x] = "不满足"
    r = sm.evaluate(a)
    assert r["verdict"].startswith("❌")
    assert "≥4" in r["verdict_reason"]


def test_single_veto_miss_fails_even_if_everything_else_ok():
    """一票项一票否决：哪怕只有它一项不满足。"""
    a = _all_ok()
    a["B21a"] = "不满足"
    r = sm.evaluate(a)
    assert r["verdict"].startswith("❌")
    assert r["summary"]["miss_veto"] == ["B21a"]


def test_partial_counts_as_not_satisfied():
    """「部分」按未满足计（保守口径）。"""
    a = _all_ok()
    a["A1"] = "部分"
    r = sm.evaluate(a)
    assert r["summary"]["partial"] == 1
    assert r["summary"]["miss_mandatory"] == 1
    assert r["verdict"].startswith("⚠️")


def test_missing_answers_default_to_not_satisfied():
    r = sm.evaluate({})
    assert r["summary"]["bad"] == 61
    assert r["verdict"].startswith("❌")


def test_unknown_status_value_falls_back_to_not_satisfied():
    r = sm.evaluate({"A1": "说不清"})
    assert r["rows"][0]["status"] == "不满足"


def test_optional_items_missing_do_not_block_pass():
    """「宜」「可」不满足不影响达标结论（只有「应」与一票项影响）。"""
    cl = sm.load_checklist()
    optional = [i["id"] for i in cl["items"] if i["level"] != "应"]
    a = _all_ok()
    for x in optional:
        a[x] = "不满足"
    r = sm.evaluate(a)
    assert r["verdict"].startswith("✅")
    assert r["summary"]["miss_mandatory"] == 0


# ---------------------------------------------------------------- 整改清单导出

def test_markdown_export_has_table_and_verdict():
    a = _all_ok()
    a["A1"] = "不满足"
    md = sm.to_markdown(sm.evaluate(a))
    assert "# AI 客服国标自查体检报告" in md
    assert "| 编号 | 条款 | 强制 | 一票项 | 要求 | 现状 | 整改动作 |" in md
    assert "| A1 " in md
    assert "不构成认证结论" in md


def test_markdown_orders_veto_items_first():
    """整改清单按「一票项优先」排序，且一票项行带 ★ 标记。"""
    a = _all_ok()
    a["A1"] = "不满足"
    a["B21c"] = "不满足"
    md = sm.to_markdown(sm.evaluate(a))
    rows = [l for l in md.splitlines()
            if l.startswith("| ") and not l.startswith("| 编号") and not l.startswith("|:")]
    ids_order = [l.split(" | ")[0][2:].strip() for l in rows]
    assert "B21c" in ids_order and "A1" in ids_order
    assert ids_order.index("B21c") < ids_order.index("A1"), "一票项必须排在普通项之前"
    veto_row = next(l for l in rows if l.startswith("| B21c "))
    plain_row = next(l for l in rows if l.startswith("| A1 "))
    assert "★" in veto_row
    assert "★" not in plain_row


def test_markdown_when_all_ok_says_nothing_to_fix():
    md = sm.to_markdown(sm.evaluate(_all_ok()))
    assert "全部达标，无需整改" in md
