/* ============================================================================
   KB-Embodied-Agent · v2 数据层（主题 + 起始画面 + 真实数据面板）
   ----------------------------------------------------------------------------
   铁律：面板上的每个数字都必须来自真实接口，取不到就显式写"取不到"。
        做出来的仪表盘是假的，比页面单调更糟。
   接口：/api/stats /api/standard /api/tools /api/audit /api/health /api/memory
   零侵入：不改原 CSS、不改原内联脚本；只往 DOM 里加节点。
   ============================================================================ */
(function () {
  "use strict";

  var TKEY = "kb_v2_theme";
  var POLL_MS = 3000;

  function $(s) { return document.querySelector(s); }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function mk(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function num(v, d) {
    var n = Number(v);
    return isFinite(n) ? n : (d == null ? 0 : d);
  }

  /* ---------------------------------------------------------------- 主题 */
  var THEMES = [
    { id: "light", label: "亮色·商务", icon: "☀" },
    { id: "dark", label: "深色·科技", icon: "🌙" }
  ];
  function applyTheme(id) {
    document.body.setAttribute("data-v2t", id);
    try { localStorage.setItem(TKEY, id); } catch (e) {}
    var b = $("#v2theme");
    if (b) {
      var t = THEMES.filter(function (x) { return x.id === id; })[0] || THEMES[0];
      var nx = THEMES.filter(function (x) { return x.id !== id; })[0];
      b.innerHTML = '<span aria-hidden="true">' + t.icon + "</span>切换为" + nx.label;
      b.title = "当前：" + t.label + "；点击切到" + nx.label;
    }
  }
  var saved = "light";
  try { saved = localStorage.getItem(TKEY) || "light"; } catch (e) {}
  if (saved !== "dark") saved = "light";
  applyTheme(saved);

  /* ------------------------------------------------------- 审计语义分组 */
  var KIND_CN = {
    "chat": "对话", "triage": "意图分流", "rag-semantic-pick": "知识检索",
    "selfcheck": "国标体检", "kb-audit": "知识库体检",
    "handoff-ticket": "转人工", "handoff-claim": "坐席接单", "handoff-msg": "坐席消息",
    "handoff-release": "坐席释放", "handoff-close": "工单关闭", "clear-tickets": "清理工单",
    "kill-switch": "一键停",
    "avatar-open": "数字人开启", "avatar-release": "数字人释放", "avatar-denied": "数字人被拒",
    "avatar-stop": "数字人停止", "avatar-switch": "数字人开关",
    "redteam-case": "红队用例", "redteam-run-all": "红队全量", "redteam-report": "红队报告",
    "xmov-proxy": "星云通道", "xmov-proxy-error": "星云通道异常", "xmov-proxy-denied": "星云通道拒绝",
    "xmov-session-bound": "星云会话绑定", "xmov-session-probe": "星云会话探测"
  };
  var KIND_GROUP = {
    "chat": "对话", "triage": "对话", "rag-semantic-pick": "对话",
    "handoff-ticket": "转人工", "handoff-claim": "转人工", "handoff-msg": "转人工",
    "handoff-release": "转人工", "handoff-close": "转人工", "clear-tickets": "转人工",
    "kill-switch": "停用",
    "avatar-open": "数字人", "avatar-release": "数字人", "avatar-stop": "数字人",
    "avatar-switch": "数字人", "xmov-proxy": "数字人", "xmov-session-bound": "数字人",
    "xmov-session-probe": "数字人",
    "avatar-denied": "合规拦截", "redteam-case": "合规拦截", "redteam-run-all": "合规拦截",
    "redteam-report": "合规拦截", "xmov-proxy-denied": "合规拦截", "xmov-proxy-error": "合规拦截",
    "selfcheck": "工具", "kb-audit": "工具"
  };
  function kindCN(k) { return KIND_CN[k] || (k || "事件"); }
  function kindGroup(k) { return KIND_GROUP[k] || "对话"; }

  /* ------------------------------------------------------------ 顶部状态条 */
  function buildBar() {
    var h = $("header");
    if (!h || $("#v2bar")) return;
    var bar = mk("div", "", "");
    bar.id = "v2bar";
    bar.appendChild(mk("span", "v2pill", '<span class="v2dot" id="v2dotAv"></span>数字人 <b id="v2pAv">—</b>'));
    bar.appendChild(mk("span", "v2pill", '<span class="v2dot ok"></span>并发 <b id="v2pCc">—</b>'));
    bar.appendChild(mk("span", "v2pill", "记忆 <b id=\"v2pMem\">—</b>"));
    bar.appendChild(mk("span", "v2pill", '运行模式 <b id="v2pMode">—</b>'));

    var board = mk("button", "v2pill", "📋 能力看板");
    board.id = "v2board";
    board.type = "button";
    board.style.cursor = "pointer";
    board.onclick = openModal;
    bar.appendChild(board);

    var th = mk("button", "", "");
    th.id = "v2theme";
    th.type = "button";
    th.onclick = function () {
      applyTheme(document.body.getAttribute("data-v2t") === "light" ? "dark" : "light");
    };
    bar.appendChild(th);

    h.appendChild(bar);
    // 必须等按钮进了 DOM 再刷新文案，否则取不到节点
    applyTheme(document.body.getAttribute("data-v2t"));
  }

  /* -------------------------------------------------------------- 左栏骨架 */
  function buildLeft() {
    var m = $("main");
    if (!m || $("#v2left")) return;
    var a = mk("aside", "v2rail", "");
    a.id = "v2left";

    a.appendChild(mk("section", "v2card",
      '<h3>实时运行<span class="vhint" id="v2kpiAt">—</span></h3>' +
      '<div class="v2kpis">' +
      '  <div class="v2kpi"><div class="k">今日会话</div><div class="v" id="v2kSess">—</div><div class="d" id="v2kSessD">—</div></div>' +
      '  <div class="v2kpi"><div class="k">今日积分</div><div class="v" id="v2kPts">—</div><div class="d" id="v2kPtsD">—</div></div>' +
      '  <div class="v2kpi"><div class="k">并发占用</div><div class="v" id="v2kCc">—</div><div class="d" id="v2kCcD">—</div></div>' +
      '  <div class="v2kpi"><div class="k">会话单场时长</div><div class="v" id="v2kTtl">—</div><div class="d" id="v2kTtlD">—</div></div>' +
      "</div>"));

    a.appendChild(mk("section", "v2card",
      '<h3>配额占用<span class="vhint">达 80% 转黄 · 95% 转红</span></h3>' +
      '<div class="v2bars" id="v2Bars"><div class="v2empty">读取中…</div></div>'));

    a.appendChild(mk("section", "v2card",
      '<h3>国标能力总览<span class="vhint" id="v2StdHint">GB/T 47746</span></h3>' +
      '<div class="v2ring">' +
      '  <svg width="104" height="104" viewBox="0 0 100 100" aria-hidden="true">' +
      '    <circle cx="50" cy="50" r="40" fill="none" stroke="var(--v2-track-bg)" stroke-width="11"></circle>' +
      '    <circle id="v2RingA" cx="50" cy="50" r="40" fill="none" stroke="#1a4eda" stroke-width="11" stroke-linecap="butt" transform="rotate(-90 50 50)"></circle>' +
      '    <circle id="v2RingB" cx="50" cy="50" r="40" fill="none" stroke="#b7791f" stroke-width="11" stroke-linecap="butt" transform="rotate(-90 50 50)"></circle>' +
      '    <circle id="v2RingC" cx="50" cy="50" r="40" fill="none" stroke="#9aa5b4" stroke-width="11" stroke-linecap="butt" transform="rotate(-90 50 50)"></circle>' +
      '    <text id="v2RingN" x="50" y="47" text-anchor="middle" font-size="21" font-weight="700" fill="var(--fg)">—</text>' +
      '    <text id="v2RingL" x="50" y="62" text-anchor="middle" font-size="10" fill="var(--dim)">条款</text>' +
      "  </svg>" +
      '  <div class="rc"><div class="rh" id="v2StdName">—<b id="v2StdDates">—</b></div>' +
      '  <div class="v2legend" id="v2StdLegend"></div></div>' +
      "</div>"));

    a.appendChild(mk("section", "v2card",
      '<h3>可用工具<span class="vhint" id="v2ToolTx">—</span></h3>' +
      '<div class="v2chips" id="v2Chips"><span class="v2empty">读取中…</span></div>'));

    m.insertBefore(a, m.firstChild);
  }

  /* -------------------------------------------------------------- 右栏骨架 */
  function buildRight() {
    var m = $("main");
    if (!m || $("#v2right")) return;
    var a = mk("aside", "v2rail", "");
    a.id = "v2right";

    a.appendChild(mk("section", "v2card",
      '<h3>后端连通性<span class="vhint" id="v2HealthAt">—</span></h3>' +
      '<div class="v2legend" id="v2Health"><div class="v2empty">读取中…</div></div>'));

    a.appendChild(mk("section", "v2card",
      '<h3>实时审计流水<span class="vhint" id="v2AuditN">—</span></h3>' +
      '<div class="v2stream" id="v2Stream"><div class="v2empty">暂无事件 · 发一句话就有了</div></div>'));

    a.appendChild(mk("section", "v2card",
      '<h3>运行明细<span class="vhint">真实参数</span></h3>' +
      '<div class="v2legend" id="v2Detail"><div class="v2empty">读取中…</div></div>'));

    m.appendChild(a);
  }

  /* ------------------- 语音交互：默认开启 + 入口凸显 + 随时可关 + 手势开麦
     为什么不能"一进页面就开麦"：浏览器硬性要求麦克风必须由用户手势开启，
     自动调 startASR 会被直接拒绝。所以"默认开启"实现为：
     ① SPEAK/VOICE_LOOP 默认为真（播报 + 答完自动回听）；
     ② 页面入口显示"已开启"；
     ③ 用户在页面上第一次点击/触摸时自动进入聆听（这一次点击就是那个手势）。
     ------------------------------------------------------------------- */
  var VKEY = "kb_v2_voice";
  var VOICE_ON = true;      // 默认开启
  var ARMED = false;        // 是否已借某次手势把麦克风打开过
  try { if (localStorage.getItem(VKEY) === "0") VOICE_ON = false; } catch (e) {}

  function micOn() {
    try { return !!(typeof MIC !== "undefined" && MIC && MIC.on); } catch (e) { return false; }
  }
  // 比"AGENT 存在"更严：还要实时通道真的开着，否则点了只会弹"数字人未连接"
  function agentReady() {
    try {
      if (!(typeof AGENT !== "undefined" && AGENT && typeof AGENT.startASR === "function")) return false;
      var c = AGENT.e2eClient;
      if (c && c.isOpen === false) return false;
      return true;
    } catch (e) { return false; }
  }

  function buildVoice() {
    var st = document.querySelector("main > section.stage");
    if (!st || document.getElementById("v2voice")) return;
    var box = mk("div", "", "");
    box.id = "v2voice";
    box.innerHTML =
      '<button id="v2vBtn" type="button">' +
      '<span id="v2vMic">🎙</span>' +
      '<span id="v2vT">' +
      '<span class="t" id="v2vT1">语音对话</span>' +
      '<span class="s"><span id="v2vT2">正在读取状态…</span><span id="v2vPerm"></span></span></span>' +
      "</button>" +
      '<span id="v2vhint" role="button" tabindex="0">👇 点这里就能说话</span>' +
      '<button id="v2vSw" type="button">关闭语音</button>';
    st.insertBefore(box, st.firstChild);

    document.getElementById("v2vBtn").onclick = function () {
      if (!VOICE_ON) { setVoice(true); return; }
      speakGuide();                      // 借这次点击把语音引导放出来（浏览器只认手势）
      if (!agentReady()) {
        // 明确点它却不具备条件时，绝不静默：交给原脚本把真实原因（未上线/通道未通）说出来
        try { toggleMic(); } catch (e) {}
        return;
      }
      armMic(true);
    };
    // 引导气泡本身就是个 CTA：点它 = 重播语音引导（数字人声音）+ 开麦
    var hint = document.getElementById("v2vhint");
    hint.onclick = function () {
      speakGuide(true);                  // 强制重播：万一首次被浏览器拦了，点一下就补上
      if (VOICE_ON) armMic(true);
      else setVoice(true);
    };

    document.getElementById("v2vSw").onclick = function () { setVoice(!VOICE_ON); };

    setVoice(VOICE_ON, true);
    voiceTick();
    setInterval(voiceTick, 700);

    // 开页就申请麦克风权限（拿到即释放，权限留在浏览器，后面识别不再弹框）
    primeMic();
    // 开页先尝试放一次语音引导；被浏览器拦住时状态会标成 blocked，改用"点一下播放"
    speakGuide();
    if (ttsOK() && !speechSynthesis.getVoices().length) {
      // 语音列表是异步来的，第一次调时常为空，等它到位再试一次
      try {
        speechSynthesis.addEventListener("voiceschanged", function () {
          if (GUIDE_STATE === "idle" || GUIDE_STATE === "trying") speakGuide();
        });
      } catch (e) {}
    }

    // 首次手势自动进入聆听；避开会把麦克风自己管起来的按钮与输入框
    ["click", "touchstart"].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
        var t = e.target;
        USER_ACTED = true;
        if (!t || !t.closest) return;
        if (!document.getElementById("v2voice") && !speechSynthesis) return;
        if (GUIDE_STATE === "idle" || GUIDE_STATE === "blocked") speakGuide();  // 引导优先跟着第一次点击走
        if (t.closest("#v2voice, #btnMic")) return;      // 这两个按钮自己管麦克风，别抢
        if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
        if (VOICE_ON) armMic(false);
      }, true);
    });
  }

  /* ------------------ 语音引导（优先用魔珐数字人的声音） --------------------------
     通道优先级：① 数字人语音 say()（星云 SSML + 情绪 + Hello 动作）——正式演示用这条；
                ② 浏览器合成音 speechSynthesis —— 仅在数字人不可用时兜底，
                   音色偏机械，正式场合不该听到它。
     实测：Chrome 对无手势的 speechSynthesis.speak() 回 error="not-allowed"，
     故开页先试一次，被拦就标 blocked，第一次点击时补上。
     ------------------------------------------------------------------------- */
  /* 开场白 = 三段：①自我介绍 ②能咨询什么 ③语音怎么用
     由 say() 按句号切成分段 SSML 播报，段间天然有停顿，不会一口气念完。
     口径纪律：只讲可核验的能力（查知识库/出卡片/转人工），不写覆盖率、准确率一类的承诺。 */
  var GUIDE = "您好，欢迎体验企业知识库智能客服。我是这里的数字员工，可以回答企业知识库里的问题，" +
              "也能现场生成合规自查清单和报价单，需要真人时随时帮您转接。" +
              "您点一下上方的语音对话按钮，再直接说话就行，说完我会自动作答，答完还会继续听您说。";
  var GUIDE_STATE = "idle";     // idle | trying | spoken | blocked | off | unsupported
  var GUIDE_CH = "";            // avatar | browser —— 这次引导实际用的哪条通道
  var MIC_PERM = "unknown";     // unknown | granted | denied | error | unsupported
  var USER_ACTED = false;       // 是否已发生过真实用户手势（决定音频能不能放）
  var HINT_DONE = false;
  try { HINT_DONE = sessionStorage.getItem("kb_v2_hint") === "0"; } catch (e) {}

  function ttsOK() { return !!(window.speechSynthesis && window.SpeechSynthesisUtterance); }
  function convStarted() { try { return !!document.querySelector("#log .msg.me"); } catch (e) { return false; } }
  // 数字人语音通道是否就绪（要求真的有 speak 且实时通道已开）
  function avatarVoiceReady() {
    try {
      if (!(typeof AGENT !== "undefined" && AGENT && typeof AGENT.speak === "function")) return false;
      var c = AGENT.e2eClient;
      if (c && c.isOpen === false) return false;
      return true;
    } catch (e) { return false; }
  }
  // 数字人是否"肯定来不了"（离线模式 / 已明确失败）。只有这种情况才允许退回机械音。
  function avatarUnavailable() {
    try { if (typeof AVATAR_FAILED !== "undefined" && AVATAR_FAILED) return true; } catch (e) {}
    if (CACHE.stats && CACHE.stats.demo_mode === "offline") return true;
    try {
      var S = (typeof SESSION !== "undefined") ? SESSION : null;
      if (S && S.mode && S.mode !== "online") return true;
    } catch (e) {}
    return false;
  }

  /* 开场白同步落到屏幕上：
     ① #subtitle（数字人下方那行"正在说什么"）—— 音频被浏览器拦时，客户至少读得到；
     ② 对话记录里留一条 —— 开场介绍进日志，后面回看也在。
     只在第一次开场时落，点"重播"不会重复刷屏。 */
  var GUIDE_BUBBLED = false;
  function greetOnScreen() {
    if (GUIDE_BUBBLED) return;
    GUIDE_BUBBLED = true;
    try { var sub = document.getElementById("subtitle"); if (sub) sub.textContent = GUIDE; } catch (e) {}
    try { if (typeof bubble === "function") bubble("bot", GUIDE, "开场介绍 · 数字员工"); } catch (e) {}
  }

  function speakGuide(force) {
    if (!VOICE_ON) { GUIDE_STATE = "off"; return; }
    if (!force && GUIDE_STATE === "spoken") return;
    if (!force && convStarted()) { GUIDE_STATE = "spoken"; return; }   // 已在对话，别插嘴

    // ① 首选：数字人自己的声音（星云 SSML 分段 + 情绪 + Hello 动作）
    if (avatarVoiceReady()) {
      try {
        say(GUIDE, { emotion: "happy", ka: "Hello" });
        GUIDE_STATE = "spoken"; GUIDE_CH = "avatar";
        greetOnScreen();
        try { emb("Speak", "开场介绍（数字人声音）"); } catch (e) {}
        return;
      } catch (e) {}
    }

    // ①.5 数字人还没就绪、但也还没判死 → 等它。绝不用机械音先糊弄一遍。
    if (!avatarUnavailable()) { GUIDE_STATE = "waiting"; return; }

    // ② 兜底：浏览器合成音。音色偏机械，只在数字人确定不可用时才用。
    if (!ttsOK()) { GUIDE_STATE = "unsupported"; return; }
    try {
      GUIDE_STATE = "trying";
      var u = new SpeechSynthesisUtterance(GUIDE);
      u.lang = "zh-CN"; u.rate = 1.0;
      var vs = speechSynthesis.getVoices() || [];
      for (var i = 0; i < vs.length; i++) {
        if (/zh|Chinese/i.test(vs[i].lang + " " + vs[i].name)) { u.voice = vs[i]; break; }
      }
      u.onstart = function () { GUIDE_STATE = "spoken"; GUIDE_CH = "browser"; greetOnScreen(); };
      u.onerror = function (e) {
        var er = (e && e.error) || "error";
        GUIDE_STATE = (er === "not-allowed") ? "blocked" : ("error:" + er);
      };
      speechSynthesis.speak(u);
    } catch (e) { GUIDE_STATE = "error"; }
  }

  function primeMic() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { MIC_PERM = "unsupported"; return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
      try { s.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}   // 拿到即释放，不留占用
      MIC_PERM = "granted";
      voiceTick();
    }).catch(function (e) {
      MIC_PERM = (e && e.name === "NotAllowedError") ? "denied" : "error";
      voiceTick();
    });
  }

  function setVoice(on, silent) {
    VOICE_ON = !!on;
    try { localStorage.setItem(VKEY, on ? "1" : "0"); } catch (e) {}
    // 与原脚本的语音状态对齐：VOICE_LOOP=答完自动回听；SPEAK=自动播报
    try { if (typeof VOICE_LOOP !== "undefined") VOICE_LOOP = !!on; } catch (e) {}
    try { if (typeof SPEAK !== "undefined") SPEAK = !!on; } catch (e) {}
    if (!on) {
      ARMED = false;
      if (micOn()) { try { toggleMic(); } catch (e) {} }   // 关掉时若正在听，先把麦关了
    }
    voiceTick();
    if (!silent) { try { emb("VoiceMode", on ? "用户开启语音对话" : "用户关闭语音对话"); } catch (e) {} }
  }

  function armMic(force) {
    if (!VOICE_ON || !agentReady() || micOn()) return;
    if (ARMED && !force) return;
    ARMED = true;
    try { toggleMic(); } catch (e) {}
  }

  function voiceTick() {
    var box = document.getElementById("v2voice");
    if (!box) return;
    var t1 = document.getElementById("v2vT1"), t2 = document.getElementById("v2vT2");
    var sw = document.getElementById("v2vSw"), mic = document.getElementById("v2vMic");
    var hint = document.getElementById("v2vhint");
    var ready = agentReady(), on = micOn();

    if (VOICE_ON && typeof VOICE_LOOP !== "undefined" && !VOICE_LOOP) {
      try { VOICE_LOOP = true; } catch (e) {}      // 开启状态下保证轮次对话不回断
    }
    box.className = !VOICE_ON ? "off" : (ready ? "on" : "wait");
    if (mic) mic.className = on ? "listening" : "";
    var bm = document.getElementById("btnMic");
    if (bm) { if (on) bm.classList.add("mic-on"); else bm.classList.remove("mic-on"); }

    // 真的开始听过一轮之后，就把引导气泡收掉（别一直晃）
    if (on && !HINT_DONE) {
      HINT_DONE = true;
      try { sessionStorage.setItem("kb_v2_hint", "0"); } catch (e) {}
    }
    if (hint) {
      var showHint = VOICE_ON && !HINT_DONE && !on;
      hint.style.display = showHint ? "" : "none";
      hint.textContent = (GUIDE_STATE === "blocked") ? "👇 点这里：听引导 + 说话" : "👇 点这里就能说话";
      // 还没用过之前，整条入口持续发光，进一步把它从整页里"拎"出来
      if (showHint) box.classList.add("spot"); else box.classList.remove("spot");
    }

    // 数字人声音一就绪就开口引导 —— "打开页面就有语音提示"在浏览器策略下的最佳落点
    if (VOICE_ON && GUIDE_STATE !== "spoken" && !convStarted() && avatarVoiceReady()) {
      speakGuide();
    }

    // 麦克风权限预热的结果必须看得见，否则"授权失败"会伪装成"按钮没用"
    var pc = document.getElementById("v2vPerm");
    if (pc) {
      var pm = {
        granted:         ["麦克风已授权", "ok",   "开页时已申请并通过，识别时不会再弹框"],
        denied:          ["麦克风未授权", "bad",  "点地址栏的锁图标 → 允许麦克风 → 刷新页面"],
        error:           ["麦克风异常",   "warn", "未检测到可用麦克风设备，请检查系统设置"],
        unsupported:     ["不支持麦克风", "warn", "当前浏览器不支持网页录音，建议用 Chrome"],
        unknown:         ["正在申请麦克风…", "", "浏览器会弹出授权提示，请点「允许」"]
      }[MIC_PERM] || null;
      if (pm) {
        pc.textContent = pm[0];
        pc.className = "perm " + (pm[1] || "");
        pc.title = pm[2];
      } else { pc.textContent = ""; pc.className = ""; }
    }

    if (!VOICE_ON) {
      t1.textContent = "语音对话 · 已关闭";
      t2.textContent = "只做文字问答，不播报也不开麦";
      sw.textContent = "开启语音";
    } else if (on) {
      t1.textContent = "我正在听，请说话";
      t2.textContent = "说完自动提交 · 答完自动回听";
      sw.textContent = "关闭语音";
    } else if (ready) {
      t1.textContent = "语音对话 · 已开启";
      t2.textContent = "点这里或页面任意处开始说话";
      sw.textContent = "关闭语音";
    } else {
      t1.textContent = "语音对话 · 待命中";
      t2.textContent = (CACHE.stats && CACHE.stats.demo_mode === "offline")
        ? "当前为文字模式；语音需数字人在线"
        : "数字人就绪后自动开启";
      sw.textContent = "关闭语音";
    }
  }

  /* ------------------------------------------------------------ 能力看板弹层 */
  function buildModal() {
    if ($("#v2modal")) return;
    var d = mk("div", "", "");
    d.id = "v2modal";
    d.innerHTML =
      '<div class="box">' +
      '  <div class="mh"><h2>📋 能力看板</h2>' +
      '    <span class="vhint" style="color:var(--dim);font-size:12px">数据全部取自本站实时接口</span>' +
      '    <button class="x" type="button" id="v2modalX">关闭</button></div>' +
      '  <div class="mb">' +
      '    <section class="v2card"><h3>国标条款分布（GB/T 47746—2026）</h3><div id="v2MbSec"><div class="v2empty">读取中…</div></div></section>' +
      '    <section class="v2card"><h3>强制分级与否决项</h3><div id="v2MbLv"><div class="v2empty">读取中…</div></div></section>' +
      '    <section class="v2card mfull"><h3>行动层：可用工具</h3><div id="v2MbTools"><div class="v2empty">读取中…</div></div></section>' +
      '    <section class="v2card mfull"><h3>最近审计流水</h3><div id="v2MbAudit"><div class="v2empty">读取中…</div></div></section>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(d);
    d.onclick = function (e) { if (e.target === d) closeModal(); };
    var x = $("#v2modalX");
    if (x) x.onclick = closeModal;
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeModal();
    });
  }
  function openModal() { var d = $("#v2modal"); if (d) d.classList.add("on"); }
  function closeModal() { var d = $("#v2modal"); if (d) d.classList.remove("on"); }

  /* --------------------------------------------------- 数字人起始画面（poster） */
  function buildPoster() {
    var av = $("#avatar");
    if (!av || $("#v2poster")) return;
    var p = mk("div", "", "");
    p.id = "v2poster";
    p.innerHTML =
      '<div class="halo"><span class="fig"><i class="h"></i><i class="b"></i></span></div>' +
      '<div class="cap"><div class="b1" id="v2p1">数字人画面</div><div class="b2" id="v2p2">正在读取本站运行状态…</div></div>' +
      '<div class="pw" id="v2p3"><span>正在建立会话</span><span class="track"><i></i></span></div>' +
      '<div class="tags" id="v2p4"></div>';
    av.insertBefore(p, av.firstChild);
    posterTick();
    setInterval(posterTick, 700);
    try {
      var f = $("#face");
      if (f && window.MutationObserver) {
        new MutationObserver(posterTick).observe(f, {
          attributes: true, attributeFilter: ["style"], childList: true, subtree: true
        });
      }
    } catch (e) {}
  }

  function posterTick() {
    var p = $("#v2poster"), f = $("#face");
    if (!p) return;
    var faceHidden = !f || f.style.display === "none";
    var failed = false, online = false, mode = "";
    try { failed = (typeof AVATAR_FAILED !== "undefined") ? !!AVATAR_FAILED : false; } catch (e) {}
    try {
      var S = (typeof SESSION !== "undefined") ? SESSION : null;
      if (S) { mode = S.mode || ""; online = (mode === "online" && !!(S.avatar && S.avatar.enabled)); }
    } catch (e) {}
    if (!mode && CACHE.stats) mode = CACHE.stats.demo_mode === "offline" ? "offline" : "";

    // 数字人画面已出现 / 已明确失败（失败原因要让人看清，不挡）→ 收起起始画面
    if (faceHidden || failed) { p.classList.add("off"); return; }
    p.classList.remove("off");

    var b1 = $("#v2p1"), b2 = $("#v2p2"), pw = $("#v2p3"), tg = $("#v2p4");
    if (online) {
      p.classList.remove("static");
      b1.textContent = "正在建立数字人会话…";
      b2.textContent = "会话由服务端代建，浏览器只持一次性凭证；画面就绪后自动切换，无需操作。";
      if (pw) pw.style.display = "";
      if (tg) tg.innerHTML = "<span>实时驱动</span><span>语音 + 口型</span><span>国标合规</span>";
    } else {
      p.classList.add("static");
      b1.textContent = "数字人画面区";
      b2.textContent = (mode === "offline")
        ? "当前为离线演示：文字问答 + 卡片交付照常可用，不消耗数字人额度。"
        : "当前未接入实时数字人驱动，文字问答 + 卡片交付照常可用。";
      if (pw) pw.style.display = "none";
      if (tg) tg.innerHTML = "<span>文字问答</span><span>卡片交付</span><span>审计留痕</span>";
    }
  }

  /* ------------------------------------------------------------------ 取数 */
  var CACHE = { stats: null, standard: null, tools: null, audit: null, health: null, mem: null };
  function getJSON(u) {
    return fetch(u, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function pull() {
    getJSON("/api/stats").then(function (j) { CACHE.stats = j; renderStats(j); }).catch(function () {});
    getJSON("/api/health").then(function (j) { CACHE.health = j; renderHealth(j); }).catch(function () {});
    getJSON("/api/standard").then(function (j) { CACHE.standard = j; renderStandard(j); }).catch(function () {});
    getJSON("/api/tools").then(function (j) { CACHE.tools = j; renderTools(j); }).catch(function () {});
    getJSON("/api/audit?limit=24").then(function (j) { CACHE.audit = j; renderAudit(j); }).catch(function () {});
    // 记忆轮次：/api/memory 必须带 session_id（不带会 422）
    var sid = "";
    try { if (typeof SESSION !== "undefined" && SESSION && SESSION.session_id) sid = SESSION.session_id; } catch (e) {}
    var mem = $("#v2pMem");
    if (sid) {
      getJSON("/api/memory?session_id=" + encodeURIComponent(sid)).then(function (j) {
        CACHE.mem = j;
        if (mem) {
          mem.textContent = num(j && j.turns, 0) + " 轮";
          mem.title = "本会话已记忆 " + num(j && j.turns, 0) + " 轮对话（session " + sid + "）";
        }
      }).catch(function () {});
    } else if (mem) {
      mem.textContent = "待会话";
      mem.title = "会话建立后显示本场记忆轮次";
    }
  }

  /* ------------------------------------------------------------------ 渲染 */
  function renderStats(j) {
    if (!j) return;
    var eff = !!j.avatar_enabled_effective;
    var d = $("#v2dotAv"), a = $("#v2pAv");
    if (d) d.className = "v2dot " + (eff ? "ok live" : "warn");
    if (a) a.textContent = eff ? "在线" : (j.demo_mode === "offline" ? "离线演示" : "未接入");
    var pm = $("#v2pMode");
    if (pm) pm.textContent = ({ offline: "离线演示", text: "文字模式", online: "在线演示" })[j.demo_mode] || (j.demo_mode || "—");
    var pc = $("#v2pCc");
    if (pc) pc.textContent = num(j.busy_now) + " / " + num(j.concurrency);

    var at = $("#v2kpiAt");
    if (at) at.textContent = nowHM();

    kpi("#v2kSess", "#v2kSessD", num(j.day_sessions) + " / " + num(j.day_session_cap), "当日会话总数 / 上限");
    kpi("#v2kPts", "#v2kPtsD", num(j.day_points).toFixed(1) + " / " + num(j.day_points_cap), "数字人积分消耗 / 上限");
    kpi("#v2kCc", "#v2kCcD", num(j.busy_now) + " / " + num(j.concurrency), j.slot_busy ? "当前时段已被占用" : "当前有空闲名额");
    kpi("#v2kTtl", "#v2kTtlD", Math.round(num(j.avatar_ttl) / 60) + " 分钟", "单场数字人演示时长上限");

    var bars = [
      ["会话额度", num(j.day_sessions), num(j.day_session_cap), ""],
      ["积分额度", num(j.day_points), num(j.day_points_cap), " 分"],
      ["并发名额", num(j.busy_now), num(j.concurrency), ""]
    ];
    var box = $("#v2Bars");
    if (box) {
      box.innerHTML = bars.map(function (b) {
        var pct = b[2] ? Math.min(100, (b[1] / b[2]) * 100) : 0;
        var cls = pct >= 95 ? "bad" : (pct >= 80 ? "warn" : "");
        return '<div class="v2bar-row"><div class="lb"><span>' + esc(b[0]) + "</span>" +
          "<b>" + b[1] + (b[2] ? " / " + b[2] : "") + esc(b[3]) + "（" + pct.toFixed(0) + "%）</b></div>" +
          '<div class="v2track ' + cls + '"><i style="width:' + pct.toFixed(1) + '%"></i></div></div>';
      }).join("");
    }

    var det = $("#v2Detail");
    if (det) {
      var rows = [
        ["演示模式", ({ offline: "离线演示", text: "文字模式", online: "在线演示" })[j.demo_mode] || (j.demo_mode || "—"), "ok"],
        ["数字人总开关", j.avatar_enabled ? "已允许" : "已关闭", j.avatar_enabled ? "ok" : "warn"],
        ["本次生效", eff ? "已生效" : "未生效", eff ? "ok" : "warn"],
        ["名额占用", j.slot_busy ? "占用中" : "空闲", j.slot_busy ? "warn" : "ok"],
        ["积分单价", num(j.points_per_min).toFixed(2) + " 分/分钟", "ok"]
      ];
      det.innerHTML = rows.map(function (r) {
        return "<div><i style=\"background:var(--v2-" + (r[2] === "ok" ? "ok" : "warn") + ")\"></i>" +
          esc(r[0]) + "<b>" + esc(r[1]) + "</b></div>";
      }).join("") +
        '<div style="display:block;font-size:11px;color:var(--dim);margin-top:4px;line-height:1.5">开关说明：' +
        esc(j.avatar_reason || "—") + "</div>";
    }
  }
  function kpi(vs, ds, v, d) {
    var e = $(vs); if (e) e.textContent = v;
    var f = $(ds); if (f) f.textContent = d;
  }

  function renderHealth(j) {
    if (!j) return;
    var box = $("#v2Health");
    var at = $("#v2HealthAt");
    if (at) at.textContent = nowHM();
    if (!box) return;
    var rows = [
      ["服务健康", j.ok ? "正常" : "异常", j.ok ? "ok" : "warn"],
      ["大模型接入", j.llm_configured ? "已配置" : "未配置", j.llm_configured ? "ok" : "warn"],
      ["数字人凭证", j.xmov_configured ? "已配置" : "未配置", j.xmov_configured ? "ok" : "warn"],
      ["知识库路径", String(j.kb_path || "—"), "ok"],
      ["运行模式", ({ offline: "离线演示", text: "文字模式", online: "在线演示" })[j.demo_mode] || (j.demo_mode || "—"), "ok"]
    ];
    box.innerHTML = rows.map(function (r) {
      return "<div><i style=\"background:var(--v2-" + (r[2] === "ok" ? "ok" : "warn") + ")\"></i>" +
        esc(r[0]) + "<b>" + esc(r[1]) + "</b></div>";
    }).join("") +
      (j.llm_hint ? '<div style="display:block;font-size:11px;color:var(--warn);margin-top:4px">' + esc(j.llm_hint) + "</div>" : "") +
      (j.xmov_hint ? '<div style="display:block;font-size:11px;color:var(--warn);margin-top:2px">' + esc(j.xmov_hint) + "</div>" : "");
  }

  function renderStandard(j) {
    if (!j) return;
    var n = num(j.total);
    var lv = j.by_level || {};
    var a = num(lv["应"]), b = num(lv["宜"]), c = num(lv["可"]);
    var C = 2 * Math.PI * 40;
    function seg(id, val) {
      var e = $(id); if (!e) return;
      var frac = n ? val / n : 0;
      e.setAttribute("stroke-dasharray", (C * frac).toFixed(2) + " " + (C * (1 - frac)).toFixed(2));
    }
    seg("#v2RingA", a);
    seg("#v2RingB", b);
    seg("#v2RingC", c);
    // 让三段首尾相接
    var rb = $("#v2RingB"), rc = $("#v2RingC");
    var off1 = -90, off2 = -90 + (n ? (a / n) * 360 : 0), off3 = off2 + (n ? (b / n) * 360 : 0);
    if ($("#v2RingA")) $("#v2RingA").setAttribute("transform", "rotate(" + off1 + " 50 50)");
    if (rb) rb.setAttribute("transform", "rotate(" + off2 + " 50 50)");
    if (rc) rc.setAttribute("transform", "rotate(" + off3 + " 50 50)");

    var rn = $("#v2RingN"); if (rn) rn.textContent = n ? String(n) : "—";
    var nm = $("#v2StdName");
    if (nm) nm.innerHTML = esc((j.standard || "").replace(/^GB\/T\s*/, "GB/T ")) +
      "<b>" + esc(j.nature || "") + " · " + esc(j.published || "—") + " 发布 · " + esc(j.effective || "—") + " 实施</b>";
    var sh = $("#v2StdHint"); if (sh) sh.textContent = "GB/T 47746—2026";
    var lg = $("#v2StdLegend");
    if (lg) {
      lg.innerHTML = [
        ["#1a4eda", "强制性「应」", a],
        ["#b7791f", "推荐性「宜」", b],
        ["#9aa5b4", "可选性「可」", c],
        ["#d64550", "一票否决项", (j.veto_ids || []).length]
      ].map(function (r) {
        return '<div><i style="background:' + r[0] + '"></i>' + esc(r[1]) + "<b>" + r[2] + "</b></div>";
      }).join("");
    }
    var sc = $("#v2MbSec");
    if (sc) {
      var secs = j.sections || [];
      sc.innerHTML = secs.length
        ? '<div class="v2legend">' + secs.map(function (s) {
            return "<div><i style=\"background:linear-gradient(90deg,#1a4eda,#3b81f6)\"></i>" +
              esc(s.key + " · " + s.name) + "<b>" + num(s.total) + " 项</b></div>";
          }).join("") + "</div>"
        : '<div class="v2empty">取不到章节数据</div>';
    }
    var lv2 = $("#v2MbLv");
    if (lv2) {
      var vids = j.veto_ids || [];
      lv2.innerHTML = '<div class="v2legend">' +
        '<div><i style="background:#1a4eda"></i>强制性「应」<b>' + a + " 项</b></div>" +
        '<div><i style="background:#b7791f"></i>推荐性「宜」<b>' + b + " 项</b></div>" +
        '<div><i style="background:#9aa5b4"></i>可选性「可」<b>' + c + " 项</b></div>" +
        '<div><i style="background:#d64550"></i>一票否决项<b>' + vids.length + " 项</b></div>" +
        "</div>" + (vids.length
          ? '<div style="margin-top:10px"><div class="v2chips">' + vids.map(function (v) {
              return '<span class="v2chip v2bad"><b>' + esc(v) + "</b></span>";
            }).join("") + "</div></div>"
          : "");
    }
  }

  function renderTools(j) {
    if (!j) return;
    var ts = j.tools || [];
    var box = $("#v2Chips");
    var tx = $("#v2ToolTx");
    if (tx) tx.textContent = ts.length ? ts.length + " 个" : "—";
    if (box) {
      box.innerHTML = ts.length
        ? ts.map(function (t) {
            return '<span class="v2chip" title="' + esc(t.desc) + '"><b>' + esc(t.name) + "</b>" +
              esc(String(t.desc || "").slice(0, 14)) + "</span>";
          }).join("")
        : '<span class="v2empty">取不到工具清单</span>';
    }
    var mb = $("#v2MbTools");
    if (mb) {
      mb.innerHTML = ts.length
        ? '<div class="v2legend">' + ts.map(function (t) {
            return "<div><i style=\"background:linear-gradient(90deg,#1a4eda,#3b81f6)\"></i>" +
              "<b style=\"color:var(--fg)\">" + esc(t.name) + "</b>&nbsp;" + esc(t.desc) + "<b></b></div>";
          }).join("") + "</div>" +
          '<div style="margin-top:10px;font-size:11.5px;color:var(--dim)">通道：' + esc(j.transport || "—") + "</div>"
        : '<div class="v2empty">取不到工具清单</div>';
    }
  }

  function renderAudit(j) {
    if (!j) return;
    var items = j.items || [];
    var n = $("#v2AuditN");
    if (n) n.textContent = "累计 " + num(j.total) + " 条";
    var box = $("#v2Stream");
    if (box) {
      box.innerHTML = items.length
        ? items.slice(0, 24).map(evHTML).join("")
        : '<div class="v2empty">暂无事件 · 发一句话就有了</div>';
    }
    var mb = $("#v2MbAudit");
    if (mb) {
      mb.innerHTML = items.length
        ? '<div class="v2stream" style="max-height:320px">' + items.slice(0, 30).map(evHTML).join("") + "</div>"
        : '<div class="v2empty">暂无事件</div>';
    }
  }
  function evHTML(it) {
    var k = it.kind || "";
    var ts = String(it.ts || "");
    var hm = ts.length >= 19 ? ts.slice(11, 19) : (ts || "—");
    var meta = [];
    if (it.route) meta.push("路由 " + it.route);
    if (it.mode) meta.push("模式 " + it.mode);
    if (it.src != null) meta.push("来源 " + it.src);
    if (it.sources != null) meta.push("来源 " + (Array.isArray(it.sources) ? it.sources.length : it.sources));
    if (it.text) meta.push(String(it.text).slice(0, 26));
    if (it.verdict) meta.push("结论 " + it.verdict);
    if (it.ticket) meta.push("工单 " + it.ticket);
    if (it.reason) meta.push(String(it.reason).slice(0, 26));
    if (it.passed != null) meta.push("通过 " + it.passed);
    return '<div class="v2ev" data-k="' + esc(kindGroup(k)) + '">' +
      '<span class="t">' + esc(hm) + "</span>" +
      '<span class="n">' + esc(kindCN(k)) + "</span>" +
      (meta.length ? '<span class="m">' + meta.slice(0, 3).map(function (m) {
        return "<em>" + esc(m) + "</em>";
      }).join("") + "</span>" : "") +
      "</div>";
  }

  function nowHM() {
    var d = new Date();
    return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2) + ":" + ("0" + d.getSeconds()).slice(-2);
  }

  /* ------------------------------------------------------------------ 启动 */
  /* ------------------ 全屏：只看数字人 + 直接语音对话 ------------------
     全屏由原脚本 #btnFull 发起（已自带 VOICE_LOOP 开麦 + 退出关麦，不另造一套）。这里只叠加三件事：
       ① 全屏态给 body 打标 → CSS 摘掉工具栏/状态条/按钮，只留数字人；
       ② 补一个可见的「退出全屏」键（原控件被摘掉了，必须留退路）；
       ③ 若是别的入口进的全屏（F11 / 浏览器控件），补上原脚本只在按钮路径做的开麦。
     不改原脚本的 fullscreenchange，只做叠加。 */
  var FS_BY_BTN = false, FS_MIC_ARMED = false;
  function fsActive() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }

  function fsSync() {
    var on = fsActive();
    try { document.body.classList.toggle("v2fs", on); } catch (e) {}
    if (!on) { FS_MIC_ARMED = false; return; }
    if (FS_BY_BTN || FS_MIC_ARMED) return;   // 按钮路径原脚本自己会开麦，别重复触发
    FS_MIC_ARMED = true;
    try { VOICE_LOOP = true; } catch (e) {}
    setTimeout(function () {
      if (fsActive() && VOICE_ON && !micOn()) { try { toggleMic(); } catch (e) {} }
    }, 700);
  }

  function buildFs() {
    var box = document.querySelector("section.stage") || document.body;
    if (!document.getElementById("v2fsExit")) {
      var b = document.createElement("button");
      b.id = "v2fsExit"; b.type = "button"; b.title = "退出全屏（Esc）";
      b.textContent = "✕ 退出全屏";
      b.onclick = function () { try { document.exitFullscreen(); } catch (e) {} };
      // 必须挂在被全屏的那个元素内部：全屏元素会被提到浏览器顶层（top layer），
      // 挂在 body 上的浮层会被压在它下面 → 看不见也点不到（实测退出键被 #v2poster 盖住）。
      box.appendChild(b);
    }
    // 捕获阶段先于原脚本 onclick 记录「是不是按按钮进的全屏」
    document.addEventListener("click", function (e) {
      var t = e.target;
      if (t && t.id === "btnFull") { FS_BY_BTN = true; setTimeout(function () { FS_BY_BTN = false; }, 2500); }
    }, true);

    document.addEventListener("fullscreenchange", function () {
      fsSync();
      // 画面尺寸变了要通知 SDK，否则数字人被裁
      setTimeout(function () { try { if (typeof AGENT !== "undefined" && AGENT && AGENT.resize) AGENT.resize(); } catch (e) {} }, 320);
    });
    document.addEventListener("webkitfullscreenchange", fsSync);
    fsSync();
  }

  function boot() {
    buildBar();
    buildLeft();
    buildRight();
    buildModal();
    buildPoster();
    buildVoice();
    buildFs();
    pull();
    setInterval(pull, POLL_MS);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // 暴露给调试用（不改动任何原逻辑）
  window.__v2 = {
    pull: pull,
    applyTheme: applyTheme,
    cache: CACHE,
    speakGuide: speakGuide,
    fs: function () {
      return {
        active: fsActive(), byBtn: FS_BY_BTN, armed: FS_MIC_ARMED,
        cls: document.body.className,
        exitShown: !!document.getElementById("v2fsExit") && getComputedStyle(document.getElementById("v2fsExit")).display !== "none",
        hidden: ["viewbar", "states", "acts", "embody", "tools"].map(function (i) {
          var e = document.getElementById(i); return i + "=" + (e ? getComputedStyle(e).display : "n/a");
        }),
        el: document.fullscreenElement ? (document.fullscreenElement.className || document.fullscreenElement.tagName) : null,
        loop: (typeof VOICE_LOOP !== "undefined") ? VOICE_LOOP : "n/a"
      };
    },
    voice: function () {
      return {
        on: VOICE_ON, guide: GUIDE_STATE, ch: GUIDE_CH, perm: MIC_PERM,
        hintDone: HINT_DONE, mic: micOn(), ready: agentReady(),
        voiceReady: avatarVoiceReady(), unavailable: avatarUnavailable()
      };
    }
  };
})();
