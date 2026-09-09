let ws = null;
let mediaStream = null;
let audioCtx = null;
let proc = null;
let meetingId = null;
let timerInterval = null;
let startTime = 0;
let stopFallbackTimer = null;  // B6: stop 后等不到 final 的兜底跳转

const $ = (id) => document.getElementById(id);

// escapeHtml 见 static/common.js
// v0.7：增强模式（GPU sidecar）暂不提供，实时页只保留标准模式，引擎选择器已移除。

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
  const tokQs = window.__tingjiLanToken ? `?token=${encodeURIComponent(window.__tingjiLanToken)}` : "";
  ws = new WebSocket(`${proto}//${location.host}/ws/realtime/${meetingId}${tokQs}`);

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
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }  // B6: 畸形帧忽略，不抛
    if (d.type === "sentence") {
      clearPartial();
      appendSentence(d);
    } else if (d.type === "partial") {
      updatePartial(d.text);
    } else if (d.type === "final") {
      if (stopFallbackTimer) { clearTimeout(stopFallbackTimer); stopFallbackTimer = null; }
      setStatus("保存完成，正在跳转…");
      location.href = `/m/${d.meeting_id}`;
    } else if (d.type === "error") {
      setStatus("错误：" + d.message);
      stop();
    }
  };

  ws.onerror = () => setStatus("连接出错");
  ws.onclose = () => {
    // B1: 录音中途断线（meetingId 已建 + stop 可见）→ 跳详情页，让 resume 流程
    // 接管（后端 finalize_live 的 disconnect 分支已落盘，resume 能把 live_recording
    // 标 error 或继续）。否则（连接在进入录音态前就失败）复位开始按钮，避免永久禁用。
    if (meetingId && !$("live-stop").classList.contains("hidden")) {
      setStatus("连接断开，正在跳转详情页…");
      cleanupAudio();
      location.href = `/m/${meetingId}`;
      return;
    }
    setStatus("连接已断开");
    cleanupAudio();
    $("live-start").disabled = false;
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
  // B6: 若服务端不回 type:'final'（崩了/超时），8s 后跳详情页让 resume 接管，
  // 避免用户永久卡在"正在停止并保存…"文案。
  if (stopFallbackTimer) clearTimeout(stopFallbackTimer);
  stopFallbackTimer = setTimeout(() => {
    stopFallbackTimer = null;
    if (meetingId) location.href = `/m/${meetingId}`;
  }, 8000);
}

window.addEventListener("beforeunload", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: "stop" }));
  }
  cleanupAudio();
});

$("live-start").addEventListener("click", start);
$("live-stop").addEventListener("click", stop);
