let ws = null;
let mediaStream = null;
let audioCtx = null;
let proc = null;
let meetingId = null;
let seenSentences = 0;
let timerInterval = null;
let startTime = 0;
let currentEngine = "funasr";

const SPK_COLORS = [
  "var(--spk-0)", "var(--spk-1)", "var(--spk-2)",
  "var(--spk-3)", "var(--spk-4)", "var(--spk-5)", "var(--spk-6)",
];

const $ = (id) => document.getElementById(id);

function esc(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

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

    if (!info.enhanced.available) {
      optEnh.classList.add("disabled");
      hint.textContent = info.enhanced.message || "需要 NVIDIA 独显，当前环境不支持";
    } else if (!info.enhanced.ready) {
      optEnh.classList.remove("disabled");
      hint.textContent = info.enhanced.message || "增强引擎服务未启动";
    } else {
      optEnh.classList.remove("disabled");
      hint.textContent = "已就绪";
    }

    optStd.onclick = () => selectEngine("funasr");
    optEnh.onclick = () => {
      if (!optEnh.classList.contains("disabled")) selectEngine("sidecar");
    };
  } catch (e) {
    setStatus("无法获取引擎信息：" + e.message);
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
  } catch (e) {
    setStatus("切换引擎失败：" + e.message);
  }
}

function appendSentence(s) {
  const ul = $("live-lines");
  const placeholder = ul.querySelector(".live-placeholder");
  if (placeholder) placeholder.remove();

  const li = document.createElement("li");
  li.className = "live-line";
  const color = SPK_COLORS[s.spk % SPK_COLORS.length];
  li.innerHTML = `<span class="live-spk" style="color:${color};border-color:${color}">说话人${s.spk}</span><span class="live-text">${esc(s.text)}</span>`;
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
    partial.innerHTML = `<span class="live-spk" style="color:var(--ink-ghost);border-color:var(--ink-ghost)">…</span><span class="live-text"></span>`;
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
      setStatus("麦克风授权失败：" + e.message);
      stop();
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
      seenSentences++;
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

$("live-start").addEventListener("click", start);
$("live-stop").addEventListener("click", stop);

fetchEngineInfo();
