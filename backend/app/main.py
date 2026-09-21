"""星云·企业知识库具身客服 —— Agent 编排服务（骨架）

设计要点见 ../ARCHITECTURE.md：
- D1 关闭 SDK 内置 LLM 直连（`auto_send_asr_to_llm=false`），由本服务接管"听→想→做→说"
- D2 密钥不进仓库、不进前端源码：星云 `appSecret` 是**浏览器侧签名凭证**（厂商设计如此），
     仅在会话建立时由 `/api/session` 下发；仓库只留 `.env.example`，`.env` 被 .gitignore 忽略
- D4 强制检索企业语料，命中不足即"不知道 + 转人工"
- D5 工具结果以 Widget 指令返回，由前端渲染卡片
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import app.standard as sm

load_dotenv()

APP_ID = os.getenv("XMOV_APP_ID", "")
APP_SECRET = os.getenv("XMOV_APP_SECRET", "")
GATEWAY = os.getenv("XMOV_GATEWAY", "https://nebula-agent.xingyun3d.com/user/v1/ttsa_v2/session")
# 端到端版 SDK（XingyunAvatarAgent）：感知 + 大脑 + 表达；我方关闭其内置大脑，仅用其表达层
SDK_URL = os.getenv("XMOV_SDK_URL", "https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar_e2e@latest.js")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
# 语料目录：默认按本文件位置解析到仓库根的 kb/（这样不管从哪个目录启动都能读到 kb/），
# 可用 KB_PATH 覆盖（docker 里由 compose 指定）
_DEFAULT_KB = Path(__file__).resolve().parents[2] / "kb"
KB_PATH = Path(os.getenv("KB_PATH") or _DEFAULT_KB)
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "")
DEMO_MODE = os.getenv("DEMO_MODE", "online")
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "900"))

# 演示用虚构语料（真实企业语料只存在本地 kb/，绝不入库）
# 结构：主题 → {aliases 命中词, answer 答案, source 来源标签}
DEMO_KB = {
    "营业时间": {
        "aliases": ["几点", "营业", "开门", "关门", "上班", "休息", "节假日", "营业时间", "开张"],
        "answer": "本店每天 9:00-21:00 营业，节假日照常。",
        "source": "门店信息",
    },
    "退换货": {
        "aliases": ["退", "换货", "退货", "退款", "售后", "不满意", "不要了", "换一个", "七天"],
        "answer": "未拆封商品 7 天内可退换，需提供购买凭证；已拆封的请到店说明情况，我们按厂家售后政策处理。",
        "source": "售后政策",
    },
    "数字化改造补贴": {
        "aliases": ["补贴", "政策", "申报", "扶持", "奖励", "专项资金", "改造", "数字化"],
        "answer": "小微企业数字化改造补贴按设备与软件投入的一定比例补贴，需先备案后采购。",
        "source": "政策汇编",
    },
    "发票": {
        "aliases": ["发票", "开票", "税号", "抬头", "报销", "收据"],
        "answer": "支持开电子发票，把抬头和税号给我们即可；当月订单请在次月 10 日前申请。",
        "source": "财务口径",
    },
    "配送与安装": {
        "aliases": ["送货", "配送", "安装", "上门", "快递", "几天到", "运费", "包邮"],
        "answer": "市区内满 500 元免费送货，安装服务需提前一天预约，上门费按区域收取。",
        "source": "服务政策",
    },
    "保修": {
        "aliases": ["保修", "质保", "坏了", "维修", "保养", "三包"],
        "answer": "整机保修一年、主要部件保修两年，保留好购买凭证与保修卡即可。",
        "source": "售后政策",
    },
    "价格与优惠": {
        "aliases": ["多少钱", "价格", "报价", "优惠", "折扣", "便宜", "活动", "促销"],
        "answer": "价格随型号与配置不同，可以告诉我您看中的型号，我给您拉一张报价卡。",
        "source": "价格口径",
    },
    "预约与到店": {
        "aliases": ["预约", "到店", "上门", "预约时间", "排队", "现场"],
        "answer": "可以提前预约，预约后到店直接办理、不用排队；临时到店我们会按现场顺序安排。",
        "source": "门店信息",
    },
    "联系方式": {
        "aliases": ["电话", "联系", "地址", "在哪", "怎么找", "导航", "客服电话"],
        "answer": "门店地址与客服电话可以在页面底部看到；紧急事项也可以直接让我为您转人工。",
        "source": "门店信息",
    },
    "支付方式": {
        "aliases": ["支付", "付款", "微信", "支付宝", "刷卡", "现金", "分期"],
        "answer": "支持微信、支付宝、刷卡与现金；大额订单可申请分期，需要现场审核。",
        "source": "财务口径",
    },
}

app = FastAPI(title="KB Embodied Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatIn(BaseModel):
    session_id: str
    text: str


class Widget(BaseModel):
    type: str
    title: str
    payload: dict


# ---------------------------------------------------------------- 数字人开放控制（B 方案：半开放）
# 设计要点：数字人实时驱动默认【关闭】；访客始终能用"文字 + 卡片"版（零密钥、零积分、可并发）。
# 运营侧在后台打开开关后，才下发有时效的 e2eServer/authToken（**密钥永不出服务器**）。
# 因账号驱动并发 = 1（实测 error_code 7），采用"一次一人 + 单场 TTL + 自动释放"的串行策略。
POINTS_PER_MIN = float(os.getenv("POINTS_PER_MIN", "0.5"))   # 实测：1 分钟交互 ≈ 0.5 积分
AVATAR_TTL = int(os.getenv("AVATAR_TTL", "180"))
AVATAR_IDLE = int(os.getenv("AVATAR_IDLE", "45"))            # 无心跳多久算掉线（秒）
AVATAR_DAILY_SESSIONS = int(os.getenv("AVATAR_DAILY_SESSIONS", "30"))
AVATAR_DAILY_POINTS = float(os.getenv("AVATAR_DAILY_POINTS", "60"))
IP_DAILY_SESSIONS = int(os.getenv("IP_DAILY_SESSIONS", "2"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

AVATAR = {"enabled": os.getenv("AVATAR_DEFAULT", "off").strip().lower() in ("on", "1", "true", "yes"),
          "since": None, "reason": "默认状态由 AVATAR_DEFAULT 决定"}
AVATAR_CONCURRENCY = int(os.getenv("AVATAR_CONCURRENCY", "3"))   # 并发路数（魔珐线路放开后调此值即可）
SLOTS: dict[str, dict] = {}          # sid -> {"until": 时长, "start": 起始, "xsid": 平台会话号}
DAY = {"day": "", "sessions": 0, "seconds": 0.0}
IP_USE: dict[str, int] = {}


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _roll_day() -> None:
    if DAY["day"] != _today():
        DAY.update(day=_today(), sessions=0, seconds=0.0)
        IP_USE.clear()


def _points_used() -> float:
    return round(DAY["seconds"] / 60.0 * POINTS_PER_MIN, 2)


def _sweep_slots() -> None:
    """主动释放：TTL 到期、或客户端心跳中断（掉线/关页面/断网）即回收名额。"""
    now = time.time()
    for sid, s in list(SLOTS.items()):
        if now >= s["until"]:
            _release_slot(sid, "ttl_expired")
        elif now - float(s.get("last_seen") or s["start"]) > AVATAR_IDLE:
            _release_slot(sid, "idle_timeout")


def _busy_count() -> int:
    _sweep_slots()
    return len(SLOTS)


def _slot_busy() -> bool:
    """是否已无空闲名额（默认 3 路并发，可用 AVATAR_CONCURRENCY 调整）。"""
    return _busy_count() >= AVATAR_CONCURRENCY


def _slot_of(sid: str) -> dict | None:
    _sweep_slots()
    return SLOTS.get(sid)


def _release_slot(sid: str, reason: str) -> None:
    s = SLOTS.pop(sid, None)
    if not s:
        return
    if s.get("xsid"):               # 顺手结束平台会话，立刻把名额还回去
        record_audit({"kind": "avatar-stop", "session_id": sid,
                      "gateway": _stop_xmov_session(s["xsid"], reason)})
    secs = max(0.0, min(time.time() - s["start"], float(AVATAR_TTL)))
    DAY["seconds"] += secs
    record_audit({"kind": "avatar-release", "session_id": sid, "seconds": round(secs, 1),
                  "reason": reason, "day_seconds": round(DAY["seconds"], 1),
                  "est_points": _points_used()})


def _sign_xmov(path: str, body: dict) -> dict:
    """按星云 SDK 同款算法生成签名头（appSecret 只在服务器参与计算，绝不下发浏览器）。

    算法取自官方 SDK 实现：
        X-TOKEN = md5(path.toLowerCase() + method.toLowerCase()
                      + 紧凑JSON(键排序、非 ASCII 转义、去空格) + appSecret + 秒级时间戳)
    """
    compact = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    ts = int(time.time())
    raw = path.lower() + "post" + compact + APP_SECRET + str(ts)
    return {
        "data": compact,
        "headers": {"Content-Type": "application/json", "X-APP-ID": APP_ID,
                    "X-TOKEN": hashlib.md5(raw.encode()).hexdigest(), "X-TIMESTAMP": str(ts)},
    }




def _stop_xmov_session(xsid: str, reason: str = "admin_release") -> str:
    """主动结束平台会话（DELETE），把并发=1 的房间立刻还回去。"""
    if not (xsid and APP_ID and APP_SECRET):
        return "无会话可释放"
    path = "/" + GATEWAY.split("//", 1)[-1].split("/", 1)[-1] if "//" in GATEWAY else GATEWAY
    compact = json.dumps({"session_id": xsid, "stop_reason": reason},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    ts = int(time.time())
    raw = path.lower() + "delete" + compact + APP_SECRET + str(ts)
    headers = {"Content-Type": "application/json", "X-APP-ID": APP_ID,
               "X-TOKEN": hashlib.md5(raw.encode()).hexdigest(), "X-TIMESTAMP": str(ts)}
    try:
        with httpx.Client(timeout=12) as c:
            r = c.request("DELETE", GATEWAY, content=compact.encode(), headers=headers)
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return f"error_code={d.get('error_code')}"
    except Exception as e:
        return f"释放失败（{type(e).__name__}）"




class AvatarToggle(BaseModel):
    enabled: bool
    token: str = ""


# ---------------------------------------------------------------- 会话

@app.post("/api/session")
def create_session(request: Request) -> dict:
    """签发会话配置（B 方案：半开放）。

    - 文字 + 卡片版**永远可用**（零密钥、零积分，可并发）；
    - 数字人实时驱动仅在后台开关打开、且名额可用时下发，且**只下发有时效的
      e2eServer/authToken**——appId/appSecret 永不出服务器（签名在服务端完成）。
    """
    _roll_day()
    if DEMO_MODE == "offline":
        return {
            "mode": "offline",
            "session_id": f"demo-{uuid.uuid4().hex[:8]}",
            "ttl": SESSION_TTL,
            "avatar": {"enabled": False, "reason": "离线演示模式：不连接星云实时驱动，不消耗积分"},
            "sdk_url": SDK_URL,
            "note": "离线演示模式：不连接星云实时驱动，不消耗积分",
        }
    sid = f"s-{uuid.uuid4().hex[:12]}"
    base = {"session_id": sid, "sdk_url": SDK_URL, "points_per_min": POINTS_PER_MIN,
            "avatar_ttl": AVATAR_TTL}
    ip = (request.client.host if request.client else "-") or "-"

    if not (APP_ID and APP_SECRET):
        return {**base, "mode": "text", "ttl": SESSION_TTL,
                "avatar": {"enabled": False, "reason": "服务端未配置星云凭证，数字人不可用（文字版照常）"}}

    reason = ""
    if not AVATAR["enabled"]:
        reason = AVATAR["reason"] or "数字人演示当前未开放（后台开关控制）"
    elif _slot_busy():
        _sweep_slots()
        wait = int(max(1, min((s["until"] for s in SLOTS.values()), default=time.time() + 5) - time.time()))
        reason = (f"数字人演示名额已满（同时服务 {AVATAR_CONCURRENCY} 人），"
                  f"请约 {wait} 秒后再试")
    elif DAY["sessions"] >= AVATAR_DAILY_SESSIONS:
        reason = f"今日数字人演示场次已用完（{AVATAR_DAILY_SESSIONS} 场/天）"
    elif _points_used() >= AVATAR_DAILY_POINTS:
        reason = f"今日演示积分额度已到上限（约 {AVATAR_DAILY_POINTS} 积分/天）"
    elif IP_USE.get(ip, 0) >= IP_DAILY_SESSIONS:
        reason = f"同一访客今日体验次数已用完（{IP_DAILY_SESSIONS} 场/天）"

    if reason:
        record_audit({"kind": "avatar-denied", "reason": reason, "ip": ip})
        return {**base, "mode": "text", "ttl": SESSION_TTL,
                "avatar": {"enabled": False, "reason": reason}}

    # 关键：不再下发任何密钥、也不在后端预建会话 —— 下发"我们自己的网关代理地址"，
    # SDK 拿它当 gatewayServer，由服务端完成签名后转发给星云网关（密钥永不出服务器）。
    # 平台会话号由代理端在 SDK 发起请求时回填到槽位，用于管理侧强制释放。
    now = time.time()
    SLOTS[sid] = {"until": now + AVATAR_TTL, "start": now, "last_seen": now,
                  "xsid": None, "ws": ""}
    DAY["sessions"] += 1
    IP_USE[ip] = IP_USE.get(ip, 0) + 1
    record_audit({"kind": "avatar-open", "session_id": sid, "ip": ip, "ttl": AVATAR_TTL,
                  "day_sessions": DAY["sessions"], "est_points": _points_used()})
    return {**base, "mode": "online", "ttl": AVATAR_TTL,
            "avatar": {"enabled": True, "gateway_proxy": "/api/xmov/gateway",
                       "ttl": AVATAR_TTL, "expires_at": int(now) + AVATAR_TTL,
                       "note": "会话经服务端代理建立并签名；浏览器不持有任何密钥"}}


class KeepIn(BaseModel):
    session_id: str = ""


@app.post("/api/avatar/keepalive")
def avatar_keepalive(body: KeepIn) -> dict:
    """心跳：证明访客还在用。停跳即视为掉线，由清扫器主动释放名额。"""
    s = _slot_of(body.session_id)
    if not s:
        return {"ok": False, "reason": "会话不存在或已释放", "busy": _busy_count()}
    s["last_seen"] = time.time()
    return {"ok": True, "remain": int(max(0, s["until"] - time.time())), "busy": _busy_count(),
            "concurrency": AVATAR_CONCURRENCY}


class ReleaseIn(BaseModel):
    session_id: str = ""


@app.post("/api/avatar/release")
def release_avatar(body: ReleaseIn) -> dict:
    """访客离开页面时主动释放名额（并发=1，早释放就是省钱）。"""
    if body.session_id and body.session_id in SLOTS:
        _release_slot(body.session_id, "client_release")
    elif not body.session_id:
        for sid in list(SLOTS):
            _release_slot(sid, "client_release")
    return {"ok": True, "busy": _slot_busy(), "day_sessions": DAY["sessions"],
            "day_points": _points_used()}


@app.get("/api/stats")
def public_stats() -> dict:
    """给前端展示的公开口径（不含任何密钥）。"""
    return {"avatar_enabled": AVATAR["enabled"], "avatar_reason": AVATAR["reason"],
            "slot_busy": _slot_busy(), "concurrency": AVATAR_CONCURRENCY,
            "busy_now": _busy_count(), "day_sessions": DAY["sessions"],
            "day_session_cap": AVATAR_DAILY_SESSIONS, "day_points": _points_used(),
            "day_points_cap": AVATAR_DAILY_POINTS, "avatar_ttl": AVATAR_TTL,
            "points_per_min": POINTS_PER_MIN}


def _admin_ok(request: Request, token: str) -> bool:
    """管理鉴权：优先口令；未设口令时只允许本机（含经 nginx 反代的本机请求）。

    注意：走 nginx 反代时 request.client.host 是容器地址，真实来源在
    X-Real-IP / X-Forwarded-For 里，必须一并识别，否则本机管理会被 403。
    """
    if ADMIN_TOKEN and token == ADMIN_TOKEN:
        return True
    peer = (request.client.host if request.client else "") or ""
    # 只有当直连来源本身是内网（如 nginx 容器）时才信任反代头，
    # 否则外部可伪造 X-Real-IP: 127.0.0.1 绕过管理鉴权
    private = peer.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.3", "192.168.", "127.", "::1"))
    host = peer
    if private:
        host = (request.headers.get("x-real-ip")
                or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
                or peer)
    return not ADMIN_TOKEN and host in ("127.0.0.1", "::1", "localhost")


@app.get("/api/admin/stats")
def admin_stats(request: Request, token: str = "") -> dict:
    if not _admin_ok(request, token):
        raise HTTPException(403, "需要管理口令（ADMIN_TOKEN）")
    return {**public_stats(), "slots": {k: dict(v) for k, v in SLOTS.items()},
            "audit_tail": AUDIT[-8:], "ip_use": IP_USE}


@app.post("/api/admin/release")
def admin_release(request: Request, session_id: str = "", token: str = "") -> dict:
    """管理侧强制释放：立刻结束占用中的会话（并发=1，占死了就靠这个救）。"""
    if not _admin_ok(request, token):
        raise HTTPException(403, "需要管理口令（ADMIN_TOKEN）")
    out = []
    if session_id:
        s = SLOTS.get(session_id)
        if s and s.get("xsid"):
            out.append(_stop_xmov_session(s["xsid"], "admin_force_release"))
        if s:
            _release_slot(session_id, "admin_force_release")
    else:
        for sid in list(SLOTS):
            s = SLOTS.get(sid) or {}
            if s.get("xsid"):
                out.append(_stop_xmov_session(s["xsid"], "admin_force_release"))
            _release_slot(sid, "admin_force_release")
    return {"ok": True, "gateway": out or "无会话可释放", "busy": _slot_busy(),
            "concurrency": AVATAR_CONCURRENCY}


@app.post("/api/admin/avatar")
def admin_avatar(body: AvatarToggle, request: Request) -> dict:
    """后台开关：一键开放/关闭数字人演示（关闭后访客自动用文字+卡片版）。"""
    if not _admin_ok(request, body.token):
        raise HTTPException(403, "需要管理口令（ADMIN_TOKEN）")
    AVATAR["enabled"] = bool(body.enabled)
    AVATAR["since"] = time.strftime("%Y-%m-%d %H:%M:%S") if body.enabled else None
    AVATAR["reason"] = "数字人演示开放中（后台开关）" if body.enabled else "默认关闭（后台开关控制）"
    if not body.enabled:
        for sid in list(SLOTS):
            _release_slot(sid, "admin_close")
    record_audit({"kind": "avatar-switch", "enabled": AVATAR["enabled"], "at": AVATAR["since"]})
    return {"ok": True, **public_stats()}


# ---------------------------------------------------------------- 红队测试台（双数字人）
import app.redteam as rt          # noqa: E402  （合规测试用例 + 判定引擎）


@app.get("/api/memory")
def memory_view(session_id: str) -> dict:
    """查看某会话的记忆：历史轮次 + 个性化档案（长短期记忆的可验证证据）。"""
    return {"session_id": session_id,
            "turns": len(SESS_HISTORY.get(session_id, [])),
            "history": SESS_HISTORY.get(session_id, [])[-6:],
            "profile": SESS_PROFILE.get(session_id, {})}


@app.get("/api/redteam/cases")
def redteam_cases() -> dict:
    """全部合规测试用例（对齐 GB/T 47746 条款，含反向用例）。"""
    return {"cases": rt.get_cases(), "total": len(rt.CASES)}


class JudgeIn(BaseModel):
    case_id: str
    turns: list[dict]


@app.post("/api/redteam/judge")
def redteam_judge(body: JudgeIn) -> dict:
    """对一条用例的逐轮记录做客观判定（是否转人工/带上下文/有依据/有留痕）。"""
    # 「留痕」不采信前端自述：直接读服务端审计文件，核对客户问题是否真的写进去了
    # 注意：① 审计文件是 JSONL 且中文可能被转义，必须逐行解析后比对，不能用原始串搜索；
    #      ② 必须复用 record_audit 的同一个 LOG_PATH —— 容器内路径解析与宿主机不同
    #         （早期用相对路径 logs/audit.jsonl 在容器里读不到，导致 R11 误判不达标）。
    logged_texts: list[str] = []
    try:
        ap = Path(os.getenv("AUDIT_PATH") or LOG_PATH)
        if ap.exists():
            for line in ap.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    rec = json.loads(line)
                    logged_texts.append(str(rec.get("text") or ""))
                except Exception:
                    continue
    except Exception:
        pass
    for i, tn in enumerate(body.turns):
        if tn.get("role") != "agent":
            continue
        q = ""
        for j in range(i - 1, -1, -1):
            if body.turns[j].get("role") == "customer":
                q = str(body.turns[j].get("text") or "")
                break
        tn["logged"] = bool(q and any(q[:12] in x for x in logged_texts))
    out = rt.judge(body.case_id, body.turns)
    record_audit({"kind": "redteam-case", "case_id": body.case_id, "pass": out.get("pass"),
                  "checks": [c["name"] for c in out.get("checks", []) if not c["ok"]]})
    return out


class KillTestIn(BaseModel):
    case_id: str = "R12"
    text: str = "国标要自查多少项"


@app.post("/api/redteam/kill-test")
async def redteam_kill_test(body: KillTestIn) -> dict:
    """一键停回归：临时停用 AI → 走真实问答链路 → 恢复。用于验证「停用后一律转人工」。"""
    prev = dict(KILL)
    KILL["stopped"], KILL["reason"], KILL["at"] = True, "红队测试台：验证一键停回归", time.time()
    try:
        r = await chat(ChatIn(text=body.text, session_id=f"redteam-kill-{int(time.time())}"))
    finally:
        KILL.update(prev)
    turns = [{"role": "customer", "text": body.text},
             {"role": "agent", "text": r.get("text", ""), "widgets": r.get("widgets", []),
              "sources": r.get("sources", []), "logged": r.get("logged", True)}]
    return {"turns": turns, "mode": r.get("mode")}


@app.post("/api/redteam/run-all")
async def redteam_run_all(save: bool = True) -> dict:
    """无人值守全量回归：服务端把 12 条用例全部跑完并出报告（不依赖浏览器）。

    用途：CI / 评委复现 —— `curl -X POST http://localhost:8080/api/redteam/run-all`。
    前端双数字人页面只是"可视化跑法"，判定逻辑与这里完全同源。
    """
    results: list[dict] = []
    for c in rt.CASES:
        sid = f"rt-{c['id']}-{int(time.time() * 1000)}"
        turns: list[dict] = []
        if (c.get("expect") or {}).get("kill_switch"):
            d = await redteam_kill_test(KillTestIn(case_id=c["id"], text=c["customer"][0]))
            turns = d["turns"]
        else:
            for line in c["customer"]:
                r = await chat(ChatIn(text=line, session_id=sid))
                turns.append({"role": "customer", "text": line})
                turns.append({"role": "agent", "text": r.get("text", ""),
                              "widgets": r.get("widgets", []), "sources": r.get("sources", [])})
        j = redteam_judge(JudgeIn(case_id=c["id"], turns=turns))
        results.append(j)
    md = rt.report(results)
    if save:
        try:
            outp = Path("docs/合规红队测试报告.md")
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(md, encoding="utf-8")
        except Exception:
            pass
    passed = sum(1 for r in results if r.get("pass"))
    veto = [r for r in results if "一票项" in (r.get("caliber") or "")]
    record_audit({"kind": "redteam-run-all", "total": len(results), "passed": passed})
    return {"total": len(results), "passed": passed,
            "veto_passed": sum(1 for r in veto if r.get("pass")), "veto_total": len(veto),
            "results": results, "markdown": md}


# ---------------------------------------------------------------- 真转人工（人工坐席协同）
# 转人工不是"出一张卡就完了"：这里落真实工单，坐席工作台可接入、可对话，客户页双向可见。
TICKETS: dict = {}          # tid -> {..., status: queued|active|released|closed, messages: [...]}
TAKEOVER: dict = {}         # session_id -> tid：人工接管期间，AI 暂停应答（真·人工接管）


def create_ticket(session_id: str, reason: str, question: str,
                  sources: list | None = None, history: list | None = None,
                  summary: str = "") -> dict:
    tid = "T" + time.strftime("%m%d%H%M%S") + str(len(TICKETS) % 100).zfill(2)
    tk = {
        "id": tid, "session_id": session_id, "reason": reason, "question": question,
        "sources": sources or [], "history": history or [], "summary": summary,
        "status": "queued", "agent": "", "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "claimed_at": None, "closed_at": None,
        "messages": [{"role": "customer", "text": question,
                      "ts": time.strftime("%H:%M:%S")}],
    }
    TICKETS[tid] = tk
    record_audit({"kind": "handoff-ticket", "ticket": tid, "reason": reason,
                  "session_id": session_id, "status": "queued"})
    return tk


def _public_ticket(tk: dict) -> dict:
    d = dict(tk)
    d["waiting_seconds"] = int(time.time() - time.mktime(time.strptime(tk["created_at"], "%Y-%m-%d %H:%M:%S")))
    return d


class TicketIn(BaseModel):
    session_id: str = ""
    reason: str = "客户主动要求"
    question: str = ""
    sources: list = []
    history: list = []
    summary: str = ""


@app.post("/api/handoff/ticket")
def handoff_ticket(body: TicketIn) -> dict:
    """登记转人工工单（前端提交转人工请求时调用；服务端也会在命中转人工规则时自动建单）。"""
    return _public_ticket(create_ticket(body.session_id, body.reason, body.question,
                                        body.sources, body.history, body.summary))


@app.post("/api/admin/clear-tickets")
def clear_tickets(request: Request) -> dict:
    """清空演示工单（管理接口，需 ADMIN_TOKEN；录演示前清场用）。"""
    if not _admin_ok(request, request.headers.get("x-admin-token", "")):
        raise HTTPException(403, "需要管理口令（ADMIN_TOKEN）")
    n = len(TICKETS)
    TICKETS.clear(); TAKEOVER.clear()
    record_audit({"kind": "clear-tickets", "count": n})
    return {"ok": True, "cleared": n}


@app.get("/api/handoff/queue")
def handoff_queue() -> dict:
    """坐席工作台：待接入 + 进行中的工单列表。"""
    items = [ _public_ticket(v) for v in TICKETS.values() if v["status"] != "closed" ]
    items.sort(key=lambda x: (x["status"] != "queued", x["created_at"]))
    return {"queued": sum(1 for i in items if i["status"] == "queued"),
            "active": sum(1 for i in items if i["status"] == "active"),
            "items": items}


class ClaimIn(BaseModel):
    ticket: str
    agent: str = "坐席A"


@app.post("/api/handoff/claim")
def handoff_claim(body: ClaimIn) -> dict:
    """坐席接入会话：客户侧会立刻看到「人工坐席已接入」。"""
    tk = TICKETS.get(body.ticket)
    if not tk:
        raise HTTPException(404, "工单不存在")
    tk["status"] = "active"
    tk["agent"] = body.agent
    tk["claimed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tk["messages"].append({"role": "system", "text": f"{body.agent} 已接入会话，已由人工接管（数字人对话已暂停）",
                           "ts": time.strftime("%H:%M:%S")})
    TAKEOVER[tk["session_id"]] = tk["id"]      # 接管登记：期间 AI 不再应答
    record_audit({"kind": "handoff-claim", "ticket": tk["id"], "agent": body.agent})
    return _public_ticket(tk)


class SayIn(BaseModel):
    ticket: str
    text: str
    role: str = "agent"        # agent（坐席）/ customer（客户）


@app.post("/api/handoff/say")
def handoff_say(body: SayIn) -> dict:
    """工单内发言（坐席或客户），双方通过 /api/handoff/messages 轮询获取。"""
    tk = TICKETS.get(body.ticket)
    if not tk:
        raise HTTPException(404, "工单不存在")
    txt = (body.text or "").strip()
    if not txt:
        raise HTTPException(400, "text 不能为空")
    tk["messages"].append({"role": body.role, "text": txt, "ts": time.strftime("%H:%M:%S")})
    if body.role == "agent" and tk["status"] == "queued":
        tk["status"], tk["agent"] = "active", tk.get("agent") or "坐席A"
    record_audit({"kind": "handoff-msg", "ticket": tk["id"], "role": body.role, "text": txt[:40]})
    return _public_ticket(tk)


@app.get("/api/handoff/messages")
def handoff_messages(ticket: str, since: int = 0) -> dict:
    """轮询工单消息（客户页每 2 秒、坐席台每 3 秒）。since 为已取到的消息条数。"""
    tk = TICKETS.get(ticket)
    if not tk:
        raise HTTPException(404, "工单不存在")
    return {"id": tk["id"], "status": tk["status"], "agent": tk["agent"],
            "total": len(tk["messages"]), "messages": tk["messages"][since:]}


class CloseIn(BaseModel):
    ticket: str
    note: str = ""


class ReleaseIn(BaseModel):
    ticket: str
    note: str = ""


async def _back_to_ai_greeting(tk: dict) -> str:
    """数字客服接手后的主动问候：结合刚才的问题，问候并确认是否已解决。"""
    tmpl = ("我是数字客服，已经接手啦。刚才您提到的问题，"
            "请问现在解决了吗？还有什么需要我帮您处理的？")
    if not LLM_API_KEY:
        return tmpl
    hist = [{"role": "user", "content": m["text"]} for m in tk["messages"] if m["role"] == "customer"]
    try:
        return await _ask_llm(
            "（这是人工坐席把会话交回给你之后的接手开场。请用一句话主动问候，"
            "说明你已经接手了，并询问对方刚才的问题是否已经解决、还有什么需要帮忙；"
            "口语化、不超过 60 字，不要重复客户的原文。）",
            [], hist[-4:], {}, memory_ok=True)
    except Exception:
        return tmpl


@app.post("/api/handoff/release")
async def handoff_release(body: ReleaseIn) -> dict:
    """坐席把会话交回数字客服：解除接管，AI 恢复应答，并由数字客服主动开口确认。"""
    tk = TICKETS.get(body.ticket)
    if not tk:
        raise HTTPException(404, "工单不存在")
    tk["status"] = "released"
    tk["messages"].append({"role": "system", "text": "已转回数字客服，AI 恢复应答",
                           "ts": time.strftime("%H:%M:%S")})
    TAKEOVER.pop(tk["session_id"], None)
    # 数字客服主动打招呼（带上下文；失败也有模板兜底，绝不让客户面对空白）
    try:
        greet = await _back_to_ai_greeting(tk)
    except Exception:
        greet = "我是数字客服，已经接手啦。请问刚才的问题解决了吗？还有什么需要我帮您处理的？"
    if not greet or "NO_INFO" in greet:
        greet = "我是数字客服，已经接手啦。请问刚才的问题解决了吗？还有什么需要我帮您处理的？"
    tk["messages"].append({"role": "ai", "text": greet, "ts": time.strftime("%H:%M:%S")})
    _remember(tk["session_id"], "assistant", greet)
    record_audit({"kind": "handoff-release", "ticket": tk["id"], "note": body.note,
                  "greeting": greet[:40]})
    return _public_ticket(tk)


@app.post("/api/handoff/close")
def handoff_close(body: CloseIn) -> dict:
    tk = TICKETS.get(body.ticket)
    if not tk:
        raise HTTPException(404, "工单不存在")
    tk["status"] = "closed"
    tk["closed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    TAKEOVER.pop(tk["session_id"], None)
    tk["messages"].append({"role": "system", "text": "会话已结束" + (f"（{body.note}）" if body.note else ""),
                           "ts": time.strftime("%H:%M:%S")})
    record_audit({"kind": "handoff-close", "ticket": tk["id"], "note": body.note})
    return _public_ticket(tk)


@app.get("/api/handoff/ticket/{tid}")
def handoff_detail(tid: str) -> dict:
    tk = TICKETS.get(tid)
    if not tk:
        raise HTTPException(404, "工单不存在")
    return _public_ticket(tk)


class ReportIn(BaseModel):
    results: list[dict]


@app.post("/api/redteam/report")
def redteam_report(body: ReportIn) -> dict:
    """把判定结果汇总成可导出的 Markdown 测试报告。"""
    md = rt.report(body.results)
    passed = sum(1 for r in body.results if r.get("pass"))
    record_audit({"kind": "redteam-report", "total": len(body.results), "passed": passed})
    return {"markdown": md, "total": len(body.results), "passed": passed}


# ------------------------------------------------- 星云网关代理（密钥不出服务器，实验路径）
@app.api_route("/api/xmov/{path:path}", methods=["POST", "DELETE", "GET"])
async def xmov_gateway_proxy(path: str, request: Request) -> dict:
    """把 SDK 发来的"统一会话接口"请求转发给真网关，并由服务端完成签名。

    目的：让浏览器无需持有 appId/appSecret，只连我们自己的域名。
    """
    raw = await request.body()
    body = {}
    if raw:
        try:
            import json as _json
            body = _json.loads(raw.decode() or "{}")
        except Exception:
            body = {}
    record_audit({"kind": "xmov-proxy", "method": request.method, "path": path,
                  "body_keys": sorted(body.keys()) if isinstance(body, dict) else "raw",
                  "ua": (request.headers.get("user-agent") or "")[:60]})
    target_path = "/" + GATEWAY.split("//", 1)[-1].split("/", 1)[-1] if "//" in GATEWAY else GATEWAY
    method = request.method.lower()
    compact = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    ts = int(time.time())
    tok = hashlib.md5((target_path.lower() + method + compact + APP_SECRET + str(ts)).encode()).hexdigest()
    headers = {"Content-Type": "application/json", "X-APP-ID": APP_ID,
               "X-TOKEN": tok, "X-TIMESTAMP": str(ts)}
    try:
        with httpx.Client(timeout=25) as c:
            r = c.request(request.method, GATEWAY, content=compact.encode(), headers=headers)
        out = r.json()
    except Exception as e:
        record_audit({"kind": "xmov-proxy-error", "error": f"{type(e).__name__}"})
        raise HTTPException(502, f"网关转发失败：{type(e).__name__}")
    # 把平台会话号记到对应槽位，便于管理侧强制释放
    demo_sid = request.headers.get("x-demo-session") or ""
    got = (out.get("data") or {}).get("session_id") if isinstance(out, dict) else None
    if demo_sid and got and demo_sid in SLOTS:
        SLOTS[demo_sid]["xsid"] = str(got)
        record_audit({"kind": "xmov-session-bound", "demo_session": demo_sid,
                      "platform_session": str(got)[:24]})
    if isinstance(out, dict) and out.get("error_code") not in (0, None):
        record_audit({"kind": "xmov-proxy-denied", "error_code": out.get("error_code"),
                      "reason": str(out.get("error_reason"))[:40]})
    # 诊断用：只记录字段名结构（不含任何密钥值），用于判断平台是否下发 E2E 音频通道
    try:
        data = out.get("data") if isinstance(out, dict) else None
        data = data if isinstance(data, dict) else {}
        record_audit({"kind": "xmov-session-probe",
                      "req_keys": sorted(list(body.keys()))[:12] if isinstance(body, dict) else [],
                      "top_keys": sorted(list(out.keys()))[:12] if isinstance(out, dict) else [],
                      "data_keys": sorted(list(data.keys()))[:20],
                      "has_e2e_resp": bool(data.get("e2e_resp")),
                      "e2e_keys": sorted(list((data.get("e2e_resp") or {}).keys()))[:8]
                      if isinstance(data.get("e2e_resp"), dict) else []})
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- 后台清扫器
@app.on_event("startup")
async def _start_sweeper() -> None:
    """每 15 秒扫一次：TTL 到期 / 心跳中断 / 平台侧会话残留，都主动释放。"""
    async def _sweeper_loop():
        while True:
            try:
                _sweep_slots()
            except Exception:
                pass
            await asyncio.sleep(15)

    asyncio.create_task(_sweeper_loop())


# ---------------------------------------------------------------- 语料加载
# 语料以 kb/*.md 为真源（数据驱动，可整体替换为真实企业语料）：
#   ### Q: 问题
#   关键词: a, b, c        ← 口语别名，命中即召回
#   A: 答案
#   来源: 出处标签
QA_Q = re.compile(r"^###\s*Q[:：]\s*(.+)$")
QA_KW = re.compile(r"^(?:关键词|Keywords)[:：]\s*(.+)$", re.I)
QA_A = re.compile(r"^(?:A|答)[:：]\s*(.+)$")
QA_SRC = re.compile(r"^(?:来源|Source)[:：]\s*(.+)$", re.I)


def load_corpus() -> list[dict]:
    """解析 kb/*.md 为问答条目列表；kb/ 为空时回退到内置 DEMO_KB。"""
    entries: list[dict] = []
    if KB_PATH.is_dir():
        for path in sorted(KB_PATH.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            cur: dict | None = None
            for raw in text.splitlines():
                line = raw.strip()
                m = QA_Q.match(line)
                if m:
                    cur = {"q": m.group(1).strip(), "kw": [], "a": "", "src": path.stem}
                    entries.append(cur)
                    continue
                if cur is None:
                    continue
                m = QA_KW.match(line)
                if m:
                    cur["kw"] = [x for x in re.split(r"[,，、\s]+", m.group(1)) if x]
                    continue
                m = QA_A.match(line)
                if m:
                    cur["a"] = m.group(1).strip()
                    continue
                m = QA_SRC.match(line)
                if m:
                    cur["src"] = m.group(1).strip()
                    continue
            # 清理：无答案的条目丢弃
        entries = [e for e in entries if e["a"]]
    if not entries:  # 回退：内置示例（评委拿到的是含 kb/ 的仓库，正常走上面分支）
        entries = [{"q": k, "kw": v["aliases"], "a": v["answer"], "src": v["source"]}
                   for k, v in DEMO_KB.items()]
    return entries


CORPUS = load_corpus()


# ---------------------------------------------------------------- 检索（RAG）

def retrieve(query: str, top_k: int = 3) -> list[tuple[str, str, str]]:
    """关键词别名命中 + 问句重合度打分，返回 [(问题, 答案, 来源)]。

    命中判定必须有别名或问句实词重合；都不命中就交回上层走"不知道 + 转人工"。
    生产替换为向量 + 关键词混合检索并重排（见 ARCHITECTURE D4）。
    """
    scored: list[tuple[int, str, str, str]] = []
    for e in CORPUS:
        kw_hits = [k for k in e["kw"] if k and k in query]
        q_overlap = sum(1 for ch in set(query) if ch in e["q"] and ch not in "的了是在有和与吗呢？?什么怎么")
        if not kw_hits and q_overlap < 3:
            continue
        score = 3 * len(kw_hits) + q_overlap + (6 if e["q"] in query else 0)
        scored.append((score, e["q"], e["a"], e["src"]))
    scored.sort(key=lambda x: -x[0])
    return [(q, a, s) for _, q, a, s in scored[:top_k]]


# ---------------------------------------------------------------- 行动层（MCP）

TOOLS = [
    {"name": "kb.search", "desc": "检索企业知识库"},
    {"name": "policy.selfcheck", "desc": "生成合规/补贴自查清单（返回卡片）"},
    {"name": "quote.calc", "desc": "按商品与数量生成报价卡"},
    {"name": "handoff.human", "desc": "转人工并留下联系方式"},
]


def call_tool(name: str, args: dict) -> Widget | None:
    """MCP 工具调用桩：接入 MCP_SERVER_URL 后替换为真实 JSON-RPC 调用。"""
    if name == "policy.selfcheck":
        return Widget(
            type="checklist",
            title="AI 客服合规自查清单（节选）",
            payload={"items": [
                "人工坐席数量与在线时段是否明确（A1）",
                "是否有人机协同服务制度（A2）",
                "对话界面是否设「转人工服务」入口（B17）",
                "五类场景是否自动转接人工（B21a–e，一票项）",
                "切换人工时是否同步身份与历史记录（B13）",
                "客户信息是否分级备份（E1）",
            ], "note": "示例卡：完整 61 项（48 应 + 4 宜 + 9 可）可对接工具生成"},
        )
    if name == "quote.calc":
        sku = args.get("sku", "企业知识库部署（小微场景）")
        qty = int(args.get("qty", 1) or 1)
        return Widget(
            type="quote",
            title="服务报价单（示例卡）",
            payload={"sku": sku, "qty": qty, "unit": "按语料量与部署方式核算",
                     "total": "面议", "note": "演示用示例卡：不在语料与界面中展示价格"},
        )
    if name == "handoff.human":
        # 上下文同步（对应国标 B13）：转人工时把客户问题、命中依据、会话号一并交接，
        # 客户无需再重复一遍；本字段是"是否携带上下文"的客观证据。
        hist = args.get("history") or []
        return Widget(
            type="handoff",
            title="已为你转接人工",
            payload={"reason": args.get("reason", "客户主动要求"),
                     "queue": args.get("queue", "门店客服"),
                     "context": {                       # 上下文摘要（B13）
                         "session": args.get("session_id", ""),
                         "question": args.get("question", ""),
                         "sources": args.get("sources", []),
                         "history": hist[-4:],
                         "summary": args.get("summary", ""),
                     },
                     "note": "已同步客户问题与历史，坐席可直接接着聊，客户不必重复描述"},
        )
    return None


# ---------------------------------------------------------------- 信任层
# ① 一键停（Kill Switch）：停用后所有问答直接转人工，AI 不再作答
# ② 操作留痕：每次问答落盘 logs/audit.jsonl 并可回查（"出事了能说清"）
# ③ 可审计引用：回答携带来源，前端可折叠查看依据原文
KILL = {"stopped": False, "reason": "", "at": None}

# 会话轮次计数：用于 B21a/B21e「交互失败/超时阈值」
SESS_TURNS: dict = {}
# 会话级上下文记忆：多轮对话不从头开始（对应评审「记忆与个性化」）
SESS_HISTORY: dict = {}      # sid -> [{"role": "user"|"assistant", "content": ...}]
SESS_PROFILE: dict = {}      # sid -> {"name": ..., "industry": ...}
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "12"))


def _remember(sid: str, role: str, content: str) -> None:
    h = SESS_HISTORY.setdefault(sid, [])
    h.append({"role": role, "content": content})
    del h[:-HISTORY_TURNS]


def _profile_update(sid: str, text: str) -> None:
    """从对话中抽取个性化信息（称呼/行业），下次直接称呼客户、不必重问。"""
    pf = SESS_PROFILE.setdefault(sid, {})
    m = re.search(r"(?:我叫|我是|叫我|我姓)\s*([一-龥A-Za-z]{1,8})", text)
    if m and "name" not in pf:
        pf["name"] = m.group(1)
    m2 = re.search(r"(?:我是|我在|我们)\s*([一-龥]{2,10}(?:行业|企业|公司|门店))", text)
    if m2 and "industry" not in pf:
        pf["industry"] = m2.group(1)
TURN_HANDOFF = int(os.getenv("TURN_HANDOFF", "5"))   # 同一会话到第 N 轮仍未解决即转人工

# 示例企业现状（演示用基线；某项不在表中即视为"满足"）：
# 4 项不满足 + 5 项部分满足 = 9 项待整改，其中一票项 B21a / B21c 未满足 → 结论"不达标"。
# 仅用于演示判定分级与整改动作，报告里明确标注"示例企业现状"。
DEMO_BASELINE_OVERRIDE = {
    "B21a": "不满足",   # 一票项：未设交互失败阈值（几轮没识别就该转）
    "B21c": "不满足",   # 一票项：涉信息安全未强制转人工
    "E1": "不满足",     # 未建分级备份
    "F5": "不满足",     # 未做系统监测
    "A7": "部分",       # 有知识库但不更新
    "A11": "部分",      # 切换时同步数据不全
    "B14": "部分",      # 切换等待未告知时长
    "B20": "部分",      # 自动转人工/情绪感知能力弱
    "D6": "部分",       # 服务记录/工单闭环不全
}
DEMO_BASELINE = {i: DEMO_BASELINE_OVERRIDE.get(i, "满足") for i in sm.ids()}
AUDIT: list[dict] = []
LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "audit.jsonl"


def record_audit(entry: dict) -> None:
    entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    AUDIT.append(entry)
    del AUDIT[:-200]  # 只保留最近 200 条在内存
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 国标体检（A）

@app.get("/api/standard")
def standard_info() -> dict:
    return sm.summary()


class SelfCheckIn(BaseModel):
    answers: dict[str, str] = {}


@app.post("/api/selfcheck")
def selfcheck(body: SelfCheckIn) -> dict:
    """国标自查体检：返回判定结论 + 逐项结果 + Markdown 整改清单。

    演示用法：不传 answers 时按内置「示例企业现状」出报告（便于演示判定分级与整改动作），
    前端也可逐项勾选后重新体检，实时看结论变化。
    """
    answers = dict(body.answers or {})
    baseline = not answers
    if baseline:
        answers = dict(DEMO_BASELINE)
    report = sm.evaluate(answers)
    report["baseline"] = baseline
    if baseline:
        report["verdict_reason"] += "（当前为示例企业现状；换成贵司实际答复即可重算）"
    record_audit({"kind": "selfcheck", "verdict": report["verdict"],
                  "answered": len(answers), "miss_veto": report["summary"]["miss_veto"]})
    report["markdown"] = sm.to_markdown(report)
    return report


# ---------------------------------------------------------------- 知识库体检（B）

# 探针问题：覆盖"该覆盖的常见问题"，未命中即语料缺口（含 2 条故意语料外的问题作为对照）
KB_PROBES = [
    "国标要自查多少项", "什么时候必须转人工", "转人工要不要重新说一遍问题",
    "知识库为什么总是不好用", "语料要准备成什么格式", "知识库多久更新一次",
    "交付一次要多久", "支持哪些部署方式", "数据安全怎么保证", "这套东西三年后会过时吗",
    "今天天气怎么样", "你们公司老板是谁",
]


@app.post("/api/kb-audit")
def kb_audit() -> dict:
    """知识库体检：用探针问题跑检索，给出覆盖率与缺口清单。

    这是"知识库死于运营而非技术"那个痛点的工具化——把"缺什么料"变成可执行清单。
    """
    covered, gaps = [], []
    for q in KB_PROBES:
        hits = retrieve(q)
        if hits:
            covered.append({"q": q, "src": hits[0][2], "answer_head": hits[0][1][:40]})
        else:
            gaps.append({"q": q, "suggest": "建议补充该主题语料（一问一答 + 来源标签）"})
    total = len(KB_PROBES)
    report = {
        "corpus_files": len(list(KB_PATH.glob("*.md"))) if KB_PATH.is_dir() else 0,
        "corpus_entries": len(CORPUS),
        "probes": total,
        "covered": len(covered),
        "coverage": round(len(covered) / total * 100) if total else 0,
        "covered_detail": covered,
        "gaps": gaps,
        "note": "对照探针里含 2 条语料外问题（如天气、内部人事），未命中属预期行为——"
                "此时数字员工会说不知道并转人工，而不是编造。",
    }
    record_audit({"kind": "kb-audit", "coverage": report["coverage"], "gaps": len(gaps)})
    return report


# ---------------------------------------------------------------- 一键停 / 留痕

class KillIn(BaseModel):
    reason: str = "人工接管"
    stopped: bool = True


@app.post("/api/kill")
def kill_switch(body: KillIn) -> dict:
    KILL["stopped"] = bool(body.stopped)
    KILL["reason"] = body.reason
    KILL["at"] = time.strftime("%Y-%m-%d %H:%M:%S") if body.stopped else None
    record_audit({"kind": "kill-switch", "stopped": KILL["stopped"], "reason": body.reason})
    return {"stopped": KILL["stopped"], "reason": KILL["reason"], "at": KILL["at"],
            "note": "停用后 AI 不再作答，所有请求直接转人工；可随时恢复"}


@app.get("/api/kill")
def kill_state() -> dict:
    return {"stopped": KILL["stopped"], "reason": KILL["reason"], "at": KILL["at"]}


@app.get("/api/audit")
def audit_tail(limit: int = 20) -> dict:
    return {"total": len(AUDIT), "items": AUDIT[-limit:][::-1]}


# ---------------------------------------------------------------- 主链路

@app.get("/api/tools")
def list_tools() -> dict:
    return {"tools": TOOLS, "transport": MCP_SERVER_URL or "local-stub"}


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict:
    """一次问答：检索 → 决策 → 生成 → （可选）工具调用 → 返回文本 + Widget。"""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")

    if DEMO_MODE == "offline":
        return _offline_reply(text)

    # 人工接管中：AI 暂停应答，请求直接落到人工工单（客户页会看到"人工接管中"）
    tid_now = TAKEOVER.get(body.session_id)
    if tid_now and DEMO_MODE != "offline":
        tk = TICKETS.get(tid_now)
        record_audit({"kind": "chat", "text": text, "takeover": tid_now, "handoff": True})
        return {
            "text": "当前已由人工坐席接管，AI 已暂停应答。您的话已经转给坐席，请稍候。",
            "sources": [], "widgets": [], "state": ["Listen"],
            "mode": "takeover",
            "handoff": {"ticket": tid_now, "agent": (tk or {}).get("agent", "")},
            "logged": True,
        }

    # 一键停：AI 已停用 → 一律转人工，不再作答
    if KILL["stopped"]:
        w = call_tool("handoff.human", {"reason": "AI 已人工停用（" + (KILL["reason"] or "人工接管") + "）",
                                        "queue": "人工坐席", "session_id": body.session_id,
                                        "question": text, "sources": [],
                                        "history": [{"role": "customer", "text": text}],
                                        "summary": "客户在本轮提问，AI 已停用，直接转人工"})
        tk = create_ticket(body.session_id, "AI 已停用（一键停）", text, [], [], "停用期间直接转人工")
        w.payload["ticket"] = {"id": tk["id"], "status": tk["status"]}
        record_audit({"kind": "chat", "text": text, "stopped": True, "handoff": True})
        return {
            "text": "AI 已停用，正在为您转接人工坐席，请稍等。",
            "sources": [],
            "widgets": [w.model_dump()] if w else [],
            "state": ["Listen", "Think", "Speak"],
            "mode": "killed",
        }

    docs = retrieve(text)
    if not docs:
        # 关键词检索落空 → 语义兜底（让模型在知识库条目里挑编号；挑不出才走转人工）
        try:
            docs = await semantic_pick(text)
        except Exception:
            docs = []
    widgets: list[Widget] = []

    # 行动层触发（真实项目由 LLM function-calling 决策，这里用规则桩演示链路）
    if any(k in text for k in ("补贴", "自查", "合规")):
        w = call_tool("policy.selfcheck", {})
        if w:
            widgets.append(w)
    if any(k in text for k in ("报价", "多少钱", "价格", "费用")):
        w = call_tool("quote.calc", {"sku": "示例商品", "qty": 1})
        if w:
            widgets.append(w)
    if any(k in text for k in ("转人工", "人工", "客服电话", "投诉")):
        w = call_tool("handoff.human", {"reason": "客户主动要求", "queue": "门店客服",
                                        "session_id": body.session_id, "question": text,
                                        "summary": "客户明确要求人工服务"})
        if w:
            widgets.append(w)

    # —— 一票项场景规则（B21a–e）：命中即转人工，且必须同步上下文 ——
    VETO_RULES = [
        (("身份证", "银行卡", "密码", "验证码", "转账", "支付信息"),
         "B21c 对话涉及信息安全，转人工处理", "客户问题涉及敏感信息，转人工核验"),
        (("过敏", "发烧", "受伤", "急救", "出事了", "有危险", "报警"),
         "B21d 涉及人身/财产安全，立即转人工", "客户反馈人身或财产安全风险，立即转人工"),
        (("不想跟机器", "不要机器人", "别让机器人", "叫个人来", "要真人", "转真人", "真人服务"),
         "B21b 客户明确拒绝智能客服，立即转人工", "客户拒绝由 AI 应答，直接转人工"),
    ]
    for kws, reason, summary in VETO_RULES:
        if any(k in text for k in kws):
            w = call_tool("handoff.human", {"reason": reason, "queue": "人工坐席",
                                            "session_id": body.session_id, "question": text,
                                            "summary": summary,
                                            "history": [{"role": "customer", "text": text}]})
            if w:
                widgets.append(w)
            break

    # 交互失败/超时阈值（B21a / B21e）：同一会话多轮仍未解决 → 转人工
    SESS_TURNS[body.session_id] = SESS_TURNS.get(body.session_id, 0) + 1
    if SESS_TURNS[body.session_id] >= TURN_HANDOFF and not any(w.type == "handoff" for w in widgets):
        w = call_tool("handoff.human", {"reason": f"B21a/B21e 多轮（{SESS_TURNS[body.session_id]} 轮）仍未解决，转人工",
                                        "queue": "人工坐席", "session_id": body.session_id,
                                        "question": text, "summary": "连续多轮交互未达成结论，按失败阈值转人工",
                                        "history": [{"role": "customer", "text": text}]})
        if w:
            widgets.append(w)

    hist = SESS_HISTORY.get(body.session_id, [])
    _profile_update(body.session_id, text)
    if docs:
        answer = await _ask_llm(text, docs, hist, SESS_PROFILE.get(body.session_id))
    elif hist:
        # 无检索结果但有会话记忆：允许据历史回答（体现"记得住、不用客户重复"）；
        # 历史也答不上来时返回约定串 NO_INFO，走诚实转人工分支。
        answer = await _ask_llm(text, [], hist, SESS_PROFILE.get(body.session_id),
                                memory_ok=True)
        if not answer or "NO_INFO" in answer:
            answer = ""
    else:
        answer = await _ask_llm(text, [], hist, SESS_PROFILE.get(body.session_id))
    handoff = False
    if not docs and not widgets and not answer:
        answer = "这个问题我这边暂时没有依据，我先帮您转人工，稍后会有同事跟进，可以吗？"
        w = call_tool("handoff.human", {"reason": "知识库未命中，主动转人工", "queue": "服务坐席",
                                        "session_id": body.session_id, "question": text, "sources": [],
                                        "history": [{"role": "customer", "text": text}],
                                        "summary": "知识库无对应依据，未编造，转人工处理"})
        if w:
            widgets.append(w)
            handoff = True
    else:
        handoff = any(w.type == "handoff" for w in widgets)

    # 兜底：任何路径都不允许返回空回答（数字人一声不吭是最糟的体验）
    if not answer:
        docs = []
        answer = "这个问题我这边暂时没有依据，我先帮您转人工，稍后会有同事跟进，可以吗？"
        if not any(w.type == "handoff" for w in widgets):
            w = call_tool("handoff.human", {"reason": "知识库未命中，主动转人工", "queue": "服务坐席",
                                            "session_id": body.session_id, "question": text, "sources": [],
                                            "history": [{"role": "customer", "text": text}],
                                            "summary": "知识库无对应依据，未编造，转人工处理"})
            if w:
                widgets.append(w)
        handoff = True

    # 命中转人工 → 落真实工单（坐席台可接入、可对话），工单号回填到交接卡
    for w in widgets:
        if w.type == "handoff":
            tk = create_ticket(body.session_id, str(w.payload.get("reason") or "转人工"),
                               text, [x for x in (w.payload.get("context") or {}).get("sources") or []],
                               w.payload.get("context", {}).get("history") or [],
                               str(w.payload.get("summary") or ""))
            w.payload["ticket"] = {"id": tk["id"], "status": tk["status"]}

    _remember(body.session_id, "user", text)
    _remember(body.session_id, "assistant", answer)
    record_audit({
        "kind": "chat", "session_id": body.session_id, "text": text,
        "sources": [t for t, _a, _s in docs], "tools": [w.type for w in widgets],
        "handoff": handoff, "llm": bool(LLM_API_KEY),
    })

    return {
        "text": answer,
        "sources": [t for t, _a, _s in docs],
        # 可审计引用：同时给出依据原文，前端可折叠查看
        "evidences": [{"src": s, "text": a} for _q, a, s in docs],
        "widgets": [w.model_dump() for w in widgets],
        "state": ["Listen", "Think", "Speak"],
        # 记忆证据：多轮上下文轮次 + 个性化档案（前端徽标可见，接口可查证）
        "memory": {"turns": len(SESS_HISTORY.get(body.session_id, [])),
                   "profile": SESS_PROFILE.get(body.session_id, {})},
        "logged": True,
    }


async def _llm_raw(sys_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    """最小 LLM 调用（供检索判定等内部环节使用，不走 RAG 提示词）。"""
    if not LLM_API_KEY:
        return ""
    payload = {"model": LLM_MODEL, "temperature": temperature,
               "messages": [{"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt}]}
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(
            f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"}, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def semantic_pick(text: str, top_k: int = 3) -> list[tuple[str, str, str]]:
    """关键词检索落空时的语义兜底。

    只让模型在「知识库条目清单」里挑编号，不回答、不编造：挑不出就返回空，
    由调用方走「不知道 + 转人工」。既提高口语问法命中率，又不破坏「无依据不说」。
    """
    if not LLM_API_KEY or not CORPUS:
        return []
    idx = "\n".join("%d. %s" % (i + 1, e["q"]) for i, e in enumerate(CORPUS))
    out = await _llm_raw(
        "你是检索助手。只做选择，不回答、不解释、不编造。",
        "企业知识库条目清单：\n%s\n\n用户问题：%s\n\n"
        "只输出能回答该问题的条目编号（1~3 个，英文逗号分隔）；"
        "没有任何条目能回答就只输出 NO。除编号或 NO 外不要输出任何内容。" % (idx, text))
    if not out or out.upper().lstrip().startswith("NO"):
        return []
    picked: list[tuple[str, str, str]] = []
    for m in re.findall(r"\d+", out)[:top_k]:
        i = int(m) - 1
        if 0 <= i < len(CORPUS):
            e = CORPUS[i]
            picked.append((e["q"], e["a"], e["src"]))
    if picked:
        record_audit({"kind": "rag-semantic-pick", "query": text[:40],
                      "picked": [p[0][:24] for p in picked]})
    return picked


async def _ask_llm(question: str, docs: list[tuple[str, str, str]],
                   history: list[dict] | None = None, profile: dict | None = None,
                   memory_ok: bool = False) -> str:
    """接大模型：RAG 资料 + 会话历史 + 个性化档案（多轮对话不从头开始）。"""
    if not LLM_API_KEY:
        return "（未配置 LLM_API_KEY，当前为本地骨架输出）" + (docs[0][1] if docs else "")
    ctx = "\n".join(f"[{t}·{s}] {a}" for t, a, s in docs) or "（无检索结果，不得编造）"
    sys_prompt = ("你是企业门店的数字人员工。只依据提供的资料回答，资料不足就说不知道并建议转人工。"
                  "回答口语化、简短，适合语音播报。")
    pf = profile or {}
    if pf.get("name"):
        sys_prompt += f"客户称呼：{pf['name']}，自然使用该称呼，不要每次重复自我介绍。"
    if pf.get("industry"):
        sys_prompt += f"已知客户背景：{pf['industry']}，结合该背景回答，不要重复询问。"
    if history:
        sys_prompt += "下面是本次会话已有对话，请保持连贯，不要重复客户已说过的信息。"
    if memory_ok:
        sys_prompt += ("本轮知识库里没有检索到资料，但**会话历史中可能已有答案**："
                       "若历史里能找到，就直接依据历史作答（例如客户问『我刚才说我叫什么』就回答其称呼）；"
                       "若历史里确实没有，只回四个字符：NO_INFO（不要编造、不要道歉）。")
    msgs = [{"role": "system", "content": sys_prompt}]
    msgs += [{"role": h["role"], "content": h["content"]} for h in (history or [])]
    msgs.append({"role": "user", "content": f"资料：\n{ctx}\n\n顾客问：{question}"})
    payload = {
        "model": LLM_MODEL,
        "messages": msgs,
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


def _offline_reply(text: str) -> dict:
    """离线演示：预置脚本，用于评审体验与无网络/无积分场景（D3）。"""
    script = [
        (("你好", "您好"), "您好，我是这家企业的知识库数字员工，有什么可以帮您？", None),
        (("国标", "标准", "合规", "多少项"), "AI 客服要过的是 GB/T 47746—2026：自查共 61 项（48 应 + 4 宜 + 9 可，含 5 项一票项），"
                                            "我给您列一份自查清单。", ("policy.selfcheck", {})),
        (("转人工", "人工", "客服电话"), "好的，正在为您转接人工客服，同时把刚才的对话一并交接过去，您不用再重复描述一次。",
         ("handoff.human", {"reason": "客户主动要求", "queue": "服务坐席"})),
        (("知识库", "不好用", "答不准"), "大多不是技术问题，而是运营问题：知识是业务过程的产物，不是一堆文件。"
                                          "指定维护人、设更新节奏、用真实问题回归测试，效果才稳。", None),
        (("交付", "多久", "部署", "实施"), "典型分四步：需求与语料盘点、知识库搭建、联调回归、培训验收并留维护手册，全程可远程。", None),
        (("报价", "多少钱", "价格", "费用"), "按语料量与部署方式核算，我给您一张报价卡（演示用示例卡）。",
         ("quote.calc", {"sku": "企业知识库部署（小微场景）", "qty": 1})),
        (("几点", "营业", "时间"), "我们服务时间为工作日 9:00-18:00，其他时间留言次日回复。", None),
    ]
    for keys, reply, tool in script:
        if any(k in text for k in keys):
            widgets = []
            if tool:
                w = call_tool(tool[0], tool[1])
                if w:
                    widgets = [w.model_dump()]
            return {
                "text": reply,
                "sources": [],
                "widgets": widgets,
                "state": ["Listen", "Think", "Speak"],
                "mode": "offline",
            }
    return {"text": "（离线演示模式）这是一段预置回复。离线模式覆盖的示例问题见页面下方的按钮；"
                    "接入在线链路后由大模型自由作答。", "sources": [], "widgets": [], "mode": "offline"}


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "demo_mode": DEMO_MODE,
        "llm_configured": bool(LLM_API_KEY),
        "xmov_configured": bool(APP_ID and APP_SECRET),
        "kb_path": str(KB_PATH),
    }
