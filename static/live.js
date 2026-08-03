let ws = null;
let mediaStream = null;
let audioCtx = null;
let proc = null;
let meetingId = null;
let timerInterval = null;
let startTime = 0;
let currentEngine = "funasr";
let engineReady = false;

const $ = (id) => document.getElementById(id);

// escapeHtml 见 static/common.js

function setStatus(msg) {
  $("live-status-line").textContent = msg;
}

function formatTimer(ms) {
  const totalSec = Math.floor(ms / 1000);
  const m = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const s = String(totalSec % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function updateTimer() {
  if (!startTime) return;
  $("live-timer").textContent = formatTimer(Date.now() - startTime);
}

async function fetchEngineInfo() {
  try {
    const r = await fetch("/api/realtime/info");
    const info = await r.json();
    currentEngine = info.current || "funasr";
    const optStd = $("opt-standard");
    const optEnh = $("opt-enhanced");
    const hint = $("enhanced-hint");

    optStd.classList.toggle("active", currentEngine === "funasr");
    optEnh.classList.toggle("active", currentEngine === "sidecar");
    optStd.querySelector(".engine-radio").textContent = currentEngine === "funasr" ? "●" : "○";
    optEnh.querySelector(".engine-radio").textContent = currentEngine === "sidecar" ? "●" : "○";

    if (!info.enhanced.available) {
      optEnh.classList.add("disabled");
      if (info.enhanced.reason === "coming_soon") {
        hint.textContent = info.enhanced.message || "v0.6 提供";
        hint.title = "增强模式将在 v0.6 中提供，当前版本请使用标准模式。";
      } else {
        hint.textContent = info.enhanced.message || "需要 NVIDIA 独显，当前环境不支持";
        hint.title = "增强模式需要 WSL/Linux + NVIDIA 独显（8GB+ 显存），当前环境不满足，请使用标准模式。";
      }
      engineReady = currentEngine !== "sidecar";
    } else if (!info.enhanced.ready) {
      optEnh.classList.add("disabled");
      hint.textContent = info.enhanced.message || "增强引擎服务未启动";
      hint.title = "增强引擎 sidecar 未运行。在 WSL 中参考 docs/wsl-deploy.md 启动 Fun-ASR-Nano sidecar（默认 ws://localhost:10095）。";
      engineReady = currentEngine !== "sidecar";
    } else {
      optEnh.classList.remove("disabled");
      hint.textContent = "已就绪";
      hint.title = "";
      engineReady = true;
    }

    optStd.onclick = () => selectEngine("funasr");
    optEnh.onclick = () => {
      if (!optEnh.classList.contains("disabled")) selectEngine("sidecar");
    };

    const statusLine = $("live-status-line");
    if (!engineReady && currentEngine === "sidecar") {
      if (info.enhanced.reason === "no_gpu") {
        statusLine.textContent = "增强模式需要 NVIDIA 独显，当前环境不支持，请切换到标准模式。";
      } else {
        statusLine.textContent = "增强引擎未就绪，请切换到标准模式或启动 sidecar 服务。";
      }
    } else if (statusLine.textContent.includes("增强引擎未就绪") || statusLine.textContent.includes("增强模式需要")) {
      statusLine.textContent = "就绪，点击「开始」授权麦克风";
    }

    updateStartButton();
  } catch (e) {
    setStatus("无法获取引擎信息：" + e.message);
    engineReady = false;
    updateStartButton();
  }
}

async function selectEngine(engine) {
  try {
    const r = await fetch("/api/settings/asr", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stream_engine: engine }),
    });
    if (!r.ok) throw new Error("保存失败");
    currentEngine = engine;
    $("opt-standard").classList.toggle("active", engine === "funasr");
    $("opt-enhanced").classList.toggle("active", engine === "sidecar");
    $("opt-standard").querySelector(".engine-radio").textContent = engine === "funasr" ? "●" : "○";
    $("opt-enhanced").querySelector(".engine-radio").textContent = engine === "sidecar" ? "●" : "○";
    await fetchEngineInfo();
  } catch (e) {
    setStatus("切换引擎失败：" + e.message);
  }
}

function updateStartButton() {
  const btn = $("live-start");
  if (!engineReady) {
    btn.disabled = true;
    btn.title = currentEngine === "sidecar" ? "增强引擎未就绪，无法开始" : "";
  } else {
    btn.disabled = false;
    btn.title = "";
  }
}

function appendSentence(s) {
  const ul = $("live-lines");
  const placeholder = ul.querySelector(".live-placeholder");
  if (placeholder) placeholder.remove();

  const li = document.createElement("li");
  li.className = "live-line";
  li.innerHTML = `<span class="live-text">${escapeHtml(s.text)}</span>`;
  ul.appendChild(li);
  ul.scrollTop = ul.scrollHeight;
}

function updatePartial(text) {
  const ul = $("live-lines");
  let partial = ul.querySelector(".live-partial");
  if (!partial) {
    const placeholder = ul.querySelector(".live-placeholder");
    if (placeholder) placeholder.remove();
    partial = document.createElement("li");
    partial.className = "live-line live-partial";
    partial.innerHTML = `<span class="live-text"></span>`;
    ul.appendChild(partial);
  }
  partial.querySelector(".live-text").textContent = text;
  ul.scrollTop = ul.scrollHeight;
}

function clearPartial() {
  const partial = $("live-lines").querySelector(".live-partial");
  if (partial) partial.remove();
}

async function start() {
  if (!window.isSecureContext) {
    setStatus("当前地址不是安全上下文，浏览器不会授予麦克风权限。请使用 http://localhost:8000 访问，或在 config.yaml 中设置 server.ssl.enabled: true 后通过 HTTPS 访问。");
    $("live-start").disabled = false;
    return;
  }
  if (!engineReady) {
    setStatus("当前选择的引擎未就绪，请切换到标准模式或启动增强引擎服务。");
    $("live-start").disabled = false;
    return;
  }

  const title = $("live-title").value.trim() || "实时会议";
  $("live-start").disabled = true;
  setStatus("创建会议…");

  try {
    const r = await fetch("/api/live/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const data = await r.json();
    meetingId = data.meeting_id;
  } catch (e) {
    setStatus("创建会议失败：" + e.message);
    $("live-start").disabled = false;
    return;
  }

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/realtime/${meetingId}`);

  ws.onopen = async () => {
    setStatus("连接成功，正在请求麦克风…");
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
      });
    } catch (e) {
      setStatus("麦克风授权失败：" + e.message + "（请检查浏览器权限设置，并确保通过 localhost 或 HTTPS 访问）");
      $("live-start").disabled = false;
      cleanupAudio();
      if (ws) {
        ws.close();
        ws = null;
      }
      return;
    }

    audioCtx = new AudioContext({ sampleRate: 16000 });
    const src = audioCtx.createMediaStreamSource(mediaStream);
    proc = audioCtx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const floats = e.inputBuffer.getChannelData(0);
      const out = new Int16Array(floats.length);
      for (let i = 0; i < floats.length; i++) {
        out[i] = Math.max(-32768, Math.min(32767, Math.round(floats[i] * 32768)));
      }
      ws.send(out.buffer);
    };
    src.connect(proc);
    proc.connect(audioCtx.destination);

    $("live-start").classList.add("hidden");
    $("live-stop").classList.remove("hidden");
    $("live-stop").disabled = false;
    $("live-timer").classList.remove("hidden");
    startTime = Date.now();
    timerInterval = setInterval(updateTimer, 1000);
    setStatus("正在实时记录…");
  };

  ws.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.type === "sentence") {
      clearPartial();
      appendSentence(d);
    } else if (d.type === "partial") {
      updatePartial(d.text);
    } else if (d.type === "final") {
      setStatus("保存完成，正在跳转…");
      location.href = `/m/${d.meeting_id}`;
    } else if (d.type === "error") {
      setStatus("错误：" + d.message);
      stop();
    }
  };

  ws.onerror = () => setStatus("连接出错");
  ws.onclose = () => {
    if ($("live-stop").classList.contains("hidden")) return;
    setStatus("连接已断开");
    cleanupAudio();
  };
}

function cleanupAudio() {
  if (proc) { proc.disconnect(); proc = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function stop() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: "stop" }));
  }
  $("live-stop").disabled = true;
  setStatus("正在停止并保存…");
  cleanupAudio();
}

window.addEventListener("beforeunload", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: "stop" }));
  }
  cleanupAudio();
});

$("live-start").disabled = true;
$("live-start").addEventListener("click", start);
$("live-stop").addEventListener("click", stop);

fetchEngineInfo();
