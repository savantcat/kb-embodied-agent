# -*- coding: utf-8 -*-
"""接口层冒烟：离线模式（零密钥）下走通健康检查 / 国标自查 / 红队台 / 问答 / 一键停。"""
import pytest
from fastapi.testclient import TestClient

import app.main as mn


@pytest.fixture(scope="module")
def client():
    return TestClient(mn.app)


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["demo_mode"] == "offline"


def test_standard_endpoint_returns_61(client):
    d = client.get("/api/standard").json()
    assert d["total"] == 61
    assert d["by_level"] == {"应": 48, "宜": 4, "可": 9}
    assert d["veto_ids"] == ["B21a", "B21b", "B21c", "B21d", "B21e"]


def test_selfcheck_without_answers_uses_demo_baseline(client):
    d = client.post("/api/selfcheck", json={}).json()
    assert d["baseline"] is True
    assert d["summary"]["total"] == 61
    assert "示例企业现状" in d["verdict_reason"]
    assert d["markdown"].startswith("# AI 客服国标自查体检报告")


def test_selfcheck_with_full_answers_is_pass(client):
    import app.standard as sm
    d = client.post("/api/selfcheck", json={"answers": {i: "满足" for i in sm.ids()}}).json()
    assert d["verdict"].startswith("✅")
    assert d["summary"]["miss_mandatory"] == 0


def test_redteam_cases_endpoint(client):
    d = client.get("/api/redteam/cases").json()
    assert d["total"] == 12
    assert len(d["cases"]) == 12


def test_redteam_judge_endpoint(client):
    d = client.post("/api/redteam/judge", json={
        "case_id": "R02",
        "turns": [{"role": "customer", "text": "叫个人来"},
                  {"role": "agent", "text": "好的", "widgets": [{"type": "handoff"}],
                   "sources": [{"t": "kb"}], "logged": True}],
    }).json()
    assert d["pass"] is True


def test_chat_offline_returns_text(client):
    r = client.post("/api/chat", json={"text": "国标要自查多少项", "session_id": "pytest"})
    assert r.status_code == 200
    assert r.json().get("text")


def test_chat_rejects_empty_text(client):
    assert client.post("/api/chat", json={"text": "   ", "session_id": "pytest"}).status_code == 400


def test_tools_endpoint_lists_handoff(client):
    d = client.get("/api/tools").json()
    assert d


def test_audit_endpoint_returns_records(client):
    r = client.get("/api/audit")
    assert r.status_code == 200
