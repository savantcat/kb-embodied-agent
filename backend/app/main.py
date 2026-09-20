"""星云·企业知识库具身客服 —— Agent 编排服务（骨架）

设计要点见 ../ARCHITECTURE.md：
- D1 关闭 SDK 内置 LLM 直连（`auto_send_asr_to_llm=false`），由本服务接管"听→想→做→说"
- D2 密钥不进仓库、不进前端源码：星云 `appSecret` 是**浏览器侧签名凭证**（厂商设计如此），
     仅在会话建立时由 `/api/session` 下发；仓库只留 `.env.example`，`.env` 被 .gitignore 忽略
- D4 强制检索企业语料，命中不足即"不知道 + 转人工"
- D5 工具结果以 Widget 指令返回，由前端渲染卡片
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

APP_ID = os.getenv("XMOV_APP_ID", "")
APP_SECRET = os.getenv("XMOV_APP_SECRET", "")
GATEWAY = os.getenv("XMOV_GATEWAY", "https://nebula-agent.xingyun3d.com/user/v1/ttsa_v2/session")
# 端到端版 SDK（XingyunAvatarAgent）：感知 + 大脑 + 表达；我方关闭其内置大脑，仅用其表达层
SDK_URL = os.getenv("XMOV_SDK_URL", "https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar_e2e@latest.js")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
KB_PATH = Path(os.getenv("KB_PATH", "./kb"))
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


# ---------------------------------------------------------------- 会话

@app.post("/api/session")
def create_session() -> dict:
    """签发会话配置。

    星云 SDK 的 appSecret 属**浏览器侧签名凭证**（厂商文档明示，前端必须持有才能建立
    实时会话）——本服务的职责是：密钥只从服务端 .env 读取、绝不出现在仓库与构建产物里，
    并按需下发给已授权的会话。更高安全等级的做法是向星云后端换取一次性 token（见
    docs/风险与边界.md「密钥边界」）。
    """
    if DEMO_MODE == "offline":
        return {
            "mode": "offline",
            "session_id": f"demo-{uuid.uuid4().hex[:8]}",
            "ttl": SESSION_TTL,
            "note": "离线演示模式：不连接星云实时驱动，不消耗积分",
        }
    if not APP_ID or not APP_SECRET:
        raise HTTPException(503, "未配置 XMOV_APP_ID / XMOV_APP_SECRET（请复制 .env.example）")
    return {
        "mode": "online",
        "session_id": f"s-{uuid.uuid4().hex[:12]}",
        "app_id": APP_ID,
        "app_secret": APP_SECRET,          # 浏览器侧签名凭证，由 SDK 用于建立实时会话
        "gateway": GATEWAY,
        "sdk_url": SDK_URL,                # 端到端版 SDK（XingyunAvatarAgent）
        # 我方接管"听→想→做→说"：关闭 SDK 的 ASR→LLM 自动链路与内置大脑，仅用其表达层
        "agent_brain": "external",
        "auto_send_asr_to_llm": False,
        "ttl": SESSION_TTL,
        "issued_at": int(time.time()),
    }


# ---------------------------------------------------------------- 检索（RAG）

def retrieve(query: str, top_k: int = 3) -> list[tuple[str, str, str]]:
    """最小可用检索：别名命中 + 字符重叠打分（生产替换为向量 + 关键词混合检索，见 ARCHITECTURE D4）。

    返回 [(主题, 答案, 来源标签)]，按得分降序。别名表让"未拆封能退吗""几点开门"这类口语问法也能命中。
    """
    scored: list[tuple[int, str, str, str]] = []
    for topic, item in DEMO_KB.items():
        aliases = item.get("aliases", [])
        alias_hits = [a for a in aliases if a in query]
        # 命中判定：必须有别名或主题命中（字符重叠只用于排序，不作为命中依据，否则噪声来源满天飞）
        if not alias_hits and topic not in query:
            continue
        score = 2 * len(alias_hits) + (3 if topic in query else 0)
        score += sum(1 for ch in set(query) if ch in item["answer"] and ch not in "的了是在有和与吗呢")
        scored.append((score, topic, item["answer"], item["source"]))
    scored.sort(key=lambda x: -x[0])

    hits: list[tuple[str, str, str]] = [(t, a, s) for _, t, a, s in scored]
    if KB_PATH.is_dir():
        for path in sorted(KB_PATH.glob("*.md")):
            body = path.read_text(encoding="utf-8", errors="ignore")
            for line in body.splitlines():
                if line.strip() and line.strip()[:12] and line.strip()[:12] in query:
                    hits.append((path.stem, line.strip(), path.name))
    return hits[:top_k]


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
            title="补贴申报自查清单",
            payload={"items": ["营业执照", "上年度报表", "设备清单与发票", "改造前照片"], "note": "示例数据"},
        )
    if name == "quote.calc":
        sku = args.get("sku", "知识库部署（小微版）")
        qty = int(args.get("qty", 1) or 1)
        unit = int(args.get("unit_price", 5000) or 5000)
        return Widget(
            type="quote",
            title="报价卡",
            payload={"sku": sku, "qty": qty, "unit": "¥%d" % unit,
                     "total": "¥%s" % format(unit * qty, ","), "note": "示例数据，实际以正式报价为准"},
        )
    if name == "handoff.human":
        return Widget(
            type="handoff",
            title="已为你转接人工",
            payload={"reason": args.get("reason", "客户主动要求"),
                     "queue": args.get("queue", "门店客服"),
                     "note": "示例数据：真实部署时这里会带上通话记录与知识库命中的上下文"},
        )
    return None


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

    docs = retrieve(text)
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
        w = call_tool("handoff.human", {"reason": "客户主动要求", "queue": "门店客服"})
        if w:
            widgets.append(w)

    answer = await _ask_llm(text, docs)
    if not docs and not widgets:
        answer = "这个问题我这边暂时没有依据，我先帮您转人工，稍后会有同事跟进，可以吗？"
        w = call_tool("handoff.human", {"reason": "知识库未命中，主动转人工", "queue": "门店客服"})
        if w:
            widgets.append(w)

    return {
        "text": answer,
        "sources": [t for t, _a, _s in docs],
        "widgets": [w.model_dump() for w in widgets],
        "state": ["Listen", "Think", "Speak"],
    }


async def _ask_llm(question: str, docs: list[tuple[str, str, str]]) -> str:
    if not LLM_API_KEY:
        return "（未配置 LLM_API_KEY，当前为本地骨架输出）" + (docs[0][1] if docs else "")
    ctx = "\n".join(f"[{t}·{s}] {a}" for t, a, s in docs) or "（无检索结果，不得编造）"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是企业门店的数字人员工。只依据提供的资料回答，资料不足就说不知道并建议转人工。回答口语化、简短，适合语音播报。"},
            {"role": "user", "content": f"资料：\n{ctx}\n\n顾客问：{question}"},
        ],
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
        (("你好", "您好"), "您好，我是这家店里的智能导购，有什么可以帮您？", None),
        (("几点", "营业", "时间"), "本店每天早九点到晚九点营业，节假日照常。", None),
        (("退货", "退换", "换货"), "未拆封的商品七天内可以退换，麻烦带上购买凭证。", None),
        (("补贴", "政策", "申报"), "我帮您列了一份补贴申报自查清单，需要的材料都在上面。",
         ("policy.selfcheck", {})),
        (("报价", "多少钱", "价格", "费用"), "按您说的情况，我拉了一张报价卡，明细在下面。",
         ("quote.calc", {"sku": "企业知识库部署（小微版）", "qty": 1, "unit_price": 5000})),
        (("人工", "转人", "客服电话"), "好的，正在为您转接人工客服，同时把刚才的对话一并交接过去。",
         ("handoff.human", {"reason": "客户主动要求", "queue": "门店客服"})),
        (("国标", "标准", "合规"), "AI 客服要过的是 GB/T 47746—2026：自查共 61 项（48 应 + 4 宜 + 9 可，含 5 项一票项），"
                                  "其中 5 类场景必须自动转人工。", ("policy.selfcheck", {})),
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
