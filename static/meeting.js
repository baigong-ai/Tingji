// 听记 · 详情页逻辑（从 meeting.html 内联脚本拆出）

const pathParts = location.pathname.split('/');
const meetingId = pathParts[pathParts.length - 1];
const audioPlayer = document.getElementById('audio-player');
let speakerNames = {};
let allSentences = [];
let allSpkCount = 0;
let currentProcessed = '';
let currentSummary = '';
let currentSummaryJson = null;
let templates = [];
let meetingTemplate = '';
let currentStatus = '';
let meetingContext = '';
let activeLine = null;
let lastIdx = -1;
let lastCompareScrollIdx = -1;

function fmtTs(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2,'0')}`;
}
// fmtDate / escapeHtml / statusLabel 见 static/common.js
const SPEAKER_COLORS = ['#1f3a5f', '#4a6741', '#b78038', '#c0392b', '#8e44ad', '#2c7a7b', '#a04900'];
function spkColor(spk) { return SPEAKER_COLORS[Number(spk) % SPEAKER_COLORS.length] || SPEAKER_COLORS[0]; }
function spkClass(spk) { return `spk-${Number(spk) % SPEAKER_COLORS.length}`; }
function spkLabel(spk) {
  return speakerNames[String(spk)] || speakerNames[spk] || `说话人${spk}`;
}
function applySpeakerNamesToMd(md) {
  if (!md) return md;
  return md.replace(/说话人\s*(\d+)/g, (m, n) => speakerNames[n] ? speakerNames[n] : `说话人${n}`);
}
// markdown 来源不可信（LLM 输出 / 用户输入的说话人名），先转义再解析，禁掉 inline HTML，
// 再 sanitize 链接协议（见 common.js:sanitizeMdHtml）
function renderMd(md) {
  md = applySpeakerNamesToMd(md);
  if (!md) return '<p class="empty-state">（暂无内容）</p>';
  return sanitizeMdHtml(marked.parse(escapeHtml(md)));
}
function applySpkToText(s) {
  return String(s).replace(/说话人\s*(\d+)/g, (m, n) => speakerNames[n] ? speakerNames[n] : m);
}
function renderSummaryJson(d) {
  if (!d) return '<p class="empty-state">（暂无总结）</p>';
  const section = (title, items) => {
    if (!items || !items.length) return '';
    const lis = items.map(x => `<li>${escapeHtml(applySpkToText(x))}</li>`).join('');
    return `<div class="sum-section"><h4>${title}</h4><ul>${lis}</ul></div>`;
  };
  let html = '';
  if (d.summary) html += `<p class="sum-overview">${escapeHtml(applySpkToText(d.summary))}</p>`;
  html += section('决议', d.decisions);
  html += section('待办', d.action_items);
  html += section('待讨论', d.open_questions);
  return html || '<p class="empty-state">（暂无总结）</p>';
}

audioPlayer.src = `/api/meetings/${meetingId}/audio`;

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (editingTab && editDirty && !confirm('当前编辑尚未保存，切换后将丢弃修改，继续？')) return;
    if (editingTab) { editingTab = null; editDirty = false; renderAll(); }
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    activeLine = null;
    lastIdx = -1;
    doSearch(document.getElementById('search-input').value);
  });
});

document.getElementById('export-btn').addEventListener('click', () => {
  const fmt = document.getElementById('export-format').value;
  location.href = `/api/meetings/${meetingId}/export?format=${fmt}`;
});
async function savePrePolish(payload) {
  try {
    await fetch(`/api/meetings/${meetingId}/context`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
  } catch (e) { /* 静默，整理时再存一次 */ }
}
async function runPolish() {
  const retryBtn = document.getElementById('retry-btn');
  const ctaBtn = document.querySelector('.start-polish-btn');
  const setBusy = (text) => {
    if (retryBtn) { retryBtn.disabled = true; retryBtn.textContent = text; }
    if (ctaBtn) { ctaBtn.disabled = true; ctaBtn.textContent = text; ctaBtn.classList.add('busy'); }
  };
  setBusy('整理中…');
  try {
    const r = await fetch(`/api/meetings/${meetingId}/retry-llm`, { method: 'POST' });
    if (!r.ok) throw new Error('提交失败');
    const { task_id } = await r.json();
    await new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const s = await fetch(`/api/tasks/${task_id}`).then(x => x.json());
          setBusy(`整理中… ${s.progress}%`);
          if (s.status === 'done') { clearInterval(timer); resolve(); }
          else if (s.status === 'error') { clearInterval(timer); reject(new Error(s.error || '整理失败')); }
        } catch (e) { clearInterval(timer); reject(e); }
      }, 2000);
    });
    location.reload();
  } catch (e) {
    alert('整理失败: ' + e.message);
    location.reload();
  }
}
document.getElementById('retry-btn').addEventListener('click', () => {
  // 首次整理和重新整理都先弹确认框（模板 + 会议背景），用户确认后再跑
  openPolishSetup();
});

// === 卡死任务手动恢复 ===
const resumeBtn = document.getElementById('resume-btn');
resumeBtn.addEventListener('click', async () => {
  resumeBtn.disabled = true;
  try {
    const r = await fetch(`/api/meetings/${meetingId}/resume`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || '恢复失败');
    if (d.reason === 'already_running') {
      alert('任务其实仍在运行中，无需恢复。可打开「日志」查看最新进度。');
    } else if (d.action === 'mark_error') {
      alert('实时录音已中断，会议被标记为失败。');
      location.reload();
    } else if ((d.action === 'run_pipeline' || d.action === 'retry_llm') && d.task_id) {
      resumeBtn.textContent = '恢复中…';
      await new Promise((resolve, reject) => {
        const timer = setInterval(async () => {
          try {
            const s = await fetch(`/api/tasks/${d.task_id}`).then(x => x.json());
            resumeBtn.textContent = `恢复中… ${s.progress}%`;
            if (s.status === 'done') { clearInterval(timer); resolve(); }
            else if (s.status === 'error') { clearInterval(timer); reject(new Error(s.error || '处理失败')); }
          } catch (e) { clearInterval(timer); reject(e); }
        }, 2000);
      });
      location.reload();
    } else {
      alert('当前状态无需恢复（' + (d.reason || 'no_action') + '）。');
    }
  } catch (e) {
    alert('恢复失败: ' + e.message);
    location.reload();
  } finally {
    resumeBtn.disabled = false;
    resumeBtn.textContent = '恢复任务';
  }
});
const polishSetupModal = document.getElementById('polish-setup-modal');
function openPolishSetup() {
  const title = document.getElementById('polish-setup-title');
  if (title) title.textContent = currentStatus === 'asr_done' ? '开始整理' : '重新整理';
  const sel = document.getElementById('modal-template-select');
  if (sel) {
    sel.innerHTML = templates.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');
    sel.value = meetingTemplate || 'general';
  }
  const ctx = document.getElementById('modal-meeting-context');
  if (ctx) ctx.value = meetingContext;
  polishSetupModal.classList.remove('hidden');
}
document.getElementById('polish-setup-cancel').addEventListener('click', () => polishSetupModal.classList.add('hidden'));
polishSetupModal.addEventListener('click', e => { if (e.target === polishSetupModal) polishSetupModal.classList.add('hidden'); });
document.getElementById('polish-setup-confirm').addEventListener('click', async () => {
  const sel = document.getElementById('modal-template-select');
  const ctx = document.getElementById('modal-meeting-context');
  const payload = {};
  if (sel) payload.template = sel.value;
  if (ctx) payload.meeting_context = ctx.value;
  await savePrePolish(payload);
  polishSetupModal.classList.add('hidden');
  runPolish();
});
document.getElementById('settings-btn').addEventListener('click', () => {
  location.href = '/?settings=1';
});

function renderRaw(container, sentences, clickable) {
  container.innerHTML = '';
  if (!sentences || !sentences.length) {
    container.innerHTML = '<p class="empty-state">（暂无转录结果）</p>';
    return;
  }
  for (let i = 0; i < sentences.length; i++) {
    const s = sentences[i];
    const div = document.createElement('div');
    div.className = 'transcript-line';
    div.dataset.start = s.start;
    div.dataset.end = s.end;
    div.dataset.idx = i;
    div.title = '单击跳转定位 · 双击编辑';
    // CSS 接管颜色：不再写 inline style
    div.innerHTML = `<span class="ts">[${fmtTs(s.start)}]</span><span class="spk ${spkClass(s.spk)}">${escapeHtml(spkLabel(s.spk))}</span><span class="text">${escapeHtml(s.text)}</span>`;
    if (clickable) {
      div.addEventListener('click', () => {
        audioPlayer.currentTime = s.start / 1000;
      });
    }
    div.addEventListener('dblclick', () => editSentence(i));
    container.appendChild(div);
  }
}

audioPlayer.addEventListener('timeupdate', () => {
  const ms = audioPlayer.currentTime * 1000;
  highlightTimelineSpeaker(ms);
  if (document.getElementById('tab-raw').classList.contains('active')) {
    highlightSentence('#transcript .transcript-line', ms);
  } else if (document.getElementById('tab-compare').classList.contains('active')) {
    highlightCompare(ms);
  } else if (document.getElementById('tab-processed').classList.contains('active')) {
    highlightProcSegment(ms);
  }
});

function highlightSentence(selector, ms) {
  const lines = document.querySelectorAll(selector);
  if (!lines.length || !allSentences.length) return;
  let idx = (lastIdx >= 0 && allSentences[lastIdx] && ms >= allSentences[lastIdx].start) ? lastIdx : 0;
  while (idx + 1 < allSentences.length && allSentences[idx + 1].start <= ms) idx++;
  while (idx > 0 && allSentences[idx].start > ms) idx--;
  lastIdx = idx;
  const line = lines[idx];
  if (!line || activeLine === line) return;
  if (activeLine) activeLine.classList.remove('active');
  line.classList.add('active');
  activeLine = line;
  line.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function highlightCompare(ms) {
  const lines = document.querySelectorAll('#compare-raw-body .compare-raw-line');
  const procBlocks = document.querySelectorAll('#compare-processed-body .compare-proc-block');
  const segs = window.__tingjiCompareSegs || [];
  if (!lines.length || !allSentences.length || !procBlocks.length) return;

  // 二分找当前播放到的原句
  let lo = 0, hi = allSentences.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (allSentences[mid].start <= ms) lo = mid; else hi = mid - 1;
  }
  const currentIdx = lo;
  const targetLine = lines[currentIdx];
  if (!targetLine) return;

  // 按时间区间找当前整理段
  let segIdx = -1;
  for (let i = 0; i < segs.length; i++) {
    if (ms >= segs[i].start && ms < segs[i].end) { segIdx = i; break; }
  }

  lines.forEach(l => l.classList.remove('compare-play-active'));
  targetLine.classList.add('compare-play-active');
  procBlocks.forEach(b => b.classList.remove('compare-play-active'));
  if (segIdx >= 0 && procBlocks[segIdx]) procBlocks[segIdx].classList.add('compare-play-active');

  // 柔和滚动：每 ~5 句滚一次；右栏用 nearest 避免大幅跳动
  if (currentIdx !== lastCompareScrollIdx && Math.abs(currentIdx - (lastCompareScrollIdx || 0)) >= 5) {
    targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
    lastCompareScrollIdx = currentIdx;
    if (segIdx >= 0 && procBlocks[segIdx]) {
      procBlocks[segIdx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
}

function highlightProcSegment(ms) {
  const segs = document.querySelectorAll('#processed-md .proc-seg[data-start]:not([data-start=""])');
  if (!segs.length) return;
  let target = null;
  for (const seg of segs) {
    const s = Number(seg.dataset.start);
    if (!isNaN(s) && s <= ms) target = seg;
    else if (!isNaN(s)) break;
  }
  if (!target || activeLine === target) return;
  if (activeLine) activeLine.classList.remove('active');
  target.classList.add('active');
  activeLine = target;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function buildSpeakerTurns(sentences) {
  const turns = [];
  let cur = null;
  for (const s of sentences) {
    if (!cur || String(cur.spk) !== String(s.spk)) {
      cur = { spk: String(s.spk), start: s.start };
      turns.push(cur);
    }
  }
  return turns;
}

function renderProcessedSegments(md, sentences) {
  if (!md) return '<p class="empty-state">（暂无整理版）</p>';
  const turns = buildSpeakerTurns(sentences || []);
  const spkPtr = {};
  const parts = md.split(/^## /m);
  let html = '';
  for (let i = 0; i < parts.length; i++) {
    let block = parts[i];
    if (!block.trim()) continue;
    const m = block.match(/^说话人\s*(\d+)/);
    let start = '';
    let pair = '';
    if (m) {
      const spk = m[1];
      const idx = spkPtr[spk] || 0;
      let count = 0;
      let tStart = '', tEnd = '';
      for (const t of turns) {
        if (t.spk === spk) {
          if (count === idx) { tStart = t.start; start = t.start; break; }
          count++;
        }
      }
      pair = `${spk}-${idx}`;
      spkPtr[spk] = idx + 1;
      block = '## ' + block;
    }
    block = applySpeakerNamesToMd(block);
    html += `<div class="proc-seg" data-start="${start}" data-pair="${pair}">${sanitizeMdHtml(marked.parse(escapeHtml(block)))}</div>`;
  }
  return html;
}

// 对照视图：左原文逐句，右整理段；按时间区间关联（精确），hover 只高亮不跳，点击定位音频
function renderCompare(md, sentences) {
  if (!sentences || !sentences.length) {
    return { rawHtml: '<p class="empty-state">（暂无原句）</p>', procHtml: '', segs: [] };
  }
  // 左：原文逐句（带时间区间）
  const rawHtml = sentences.map((s, i) =>
    `<div class="compare-raw-line" data-idx="${i}" data-start="${s.start}" data-end="${s.end}">` +
    `<span class="ts">[${fmtTs(s.start)}]</span>` +
    `<span class="spk ${spkClass(s.spk)}">${escapeHtml(spkLabel(s.spk))}</span>` +
    `<span>${escapeHtml(s.text)}</span></div>`
  ).join('');

  // 右：整理段，按"说话人第 N 次发言"映射到原文时间区间
  let procHtml = '';
  const segs = [];
  if (md) {
    const turns = buildSpeakerTurns(sentences);
    const last = sentences[sentences.length - 1];
    const lastEnd = (last && (last.end || last.start)) || 0;
    const starts = [];
    const blocks = [];
    let turnPtr = 0;
    const fallbackStart = turns.length ? turns[turns.length - 1].start : 0;
    for (const part of md.split(/^## /m)) {
      if (!part.trim()) continue;
      const m = part.match(/^(?:说话人|speaker)\s*(\d+)/i);
      if (!m) continue;
      // 按 md 段顺序依次对应原文 turn 时间（单调递增，不重叠）
      const st = turnPtr < turns.length ? turns[turnPtr].start : fallbackStart;
      turnPtr++;
      starts.push(st);
      blocks.push('## ' + part);
    }
    for (let i = 0; i < blocks.length; i++) {
      const end = i + 1 < starts.length ? starts[i + 1] : lastEnd;
      segs.push({ start: starts[i], end });
      procHtml += `<div class="compare-proc-block" data-start="${starts[i]}" data-end="${end}">${sanitizeMdHtml(marked.parse(escapeHtml(applySpeakerNamesToMd(blocks[i]))))}</div>`;
    }
  } else {
    procHtml = '<p class="empty-state">（暂无整理版）</p>';
  }
  window.__tingjiCompareSegs = segs;
  lastCompareScrollIdx = -1;
  return { rawHtml, procHtml, segs };
}

// hover 跨栏高亮（按时间区间，只高亮不滚动，避免乱跳）；点击定位音频
function setupCompareHover(sentences, segs) {
  const rawLines = document.querySelectorAll('#compare-raw-body .compare-raw-line');
  const procBlocks = document.querySelectorAll('#compare-processed-body .compare-proc-block');
  if (!segs || !segs.length) return;
  const clearHover = () => {
    rawLines.forEach(l => l.classList.remove('compare-link-active'));
    procBlocks.forEach(b => b.classList.remove('compare-link-active'));
  };
  rawLines.forEach((line, idx) => {
    const sent = sentences[idx];
    if (!sent) return;
    line.addEventListener('mouseenter', () => {
      clearHover();
      line.classList.add('compare-link-active');
      procBlocks.forEach((b, i) => {
        const seg = segs[i];
        if (seg && sent.start >= seg.start && sent.start < seg.end) b.classList.add('compare-link-active');
      });
    });
    line.addEventListener('mouseleave', clearHover);
    line.addEventListener('click', () => { audioPlayer.currentTime = sent.start / 1000; });
  });
  procBlocks.forEach((block, i) => {
    const seg = segs[i];
    if (!seg) return;
    block.addEventListener('mouseenter', () => {
      clearHover();
      block.classList.add('compare-link-active');
      rawLines.forEach((line, idx) => {
        const s = sentences[idx];
        if (s.start >= seg.start && s.start < seg.end) line.classList.add('compare-link-active');
      });
    });
    block.addEventListener('mouseleave', clearHover);
    block.addEventListener('click', () => { audioPlayer.currentTime = seg.start / 1000; });
  });
}

function renderAll() {
  renderSpeakersBar(allSpkCount);
  renderTimeline();
  renderRaw(document.getElementById('transcript'), allSentences, true);
  const procEl = document.getElementById('processed-md');
  if (!currentProcessed && currentStatus === 'asr_done') {
    procEl.innerHTML = `<div class="empty-cta"><p class="empty-state">原文已识别完成，如果检查没有问题，就可以开始整理会议纪要了</p><button class="primary start-polish-btn">开始整理</button></div>`;
    procEl.querySelector('.start-polish-btn').addEventListener('click', openPolishSetup);
  } else {
    procEl.innerHTML = renderProcessedSegments(currentProcessed, allSentences);
  }
  document.getElementById('summary-md').innerHTML = currentSummaryJson ? renderSummaryJson(currentSummaryJson) : renderMd(currentSummary);
  // 对照视图：左原文逐句，右整理段独立；hover 跨栏关键词定位
  const cmp = renderCompare(currentProcessed, allSentences);
  document.getElementById('compare-raw-body').innerHTML = cmp.rawHtml;
  document.getElementById('compare-processed-body').innerHTML = cmp.procHtml;
  setupCompareHover(allSentences, cmp.segs);
  activeLine = null;
  lastIdx = -1;
  updateEditButtons();
}

// === 整理版 / 总结 二次编辑 ===
let editingTab = null;   // 'processed' | 'summary' | null
let editDirty = false;

function updateEditButtons() {
  const procTools = document.getElementById('proc-tools');
  const sumTools = document.getElementById('sum-tools');
  if (procTools) procTools.classList.toggle('hidden', !currentProcessed || editingTab === 'processed');
  if (sumTools) sumTools.classList.toggle('hidden', (!currentSummary && !currentSummaryJson) || editingTab === 'summary');
}

function cancelEdit() {
  if (editDirty && !confirm('有未保存的修改，确定放弃？')) return;
  editingTab = null;
  editDirty = false;
  renderAll();
}

// --- 整理版编辑 ---
document.getElementById('proc-edit-btn').addEventListener('click', () => {
  editingTab = 'processed';
  editDirty = false;
  document.getElementById('proc-tools').classList.add('hidden');
  const el = document.getElementById('processed-md');
  el.innerHTML = `
    <textarea id="proc-edit-text" class="md-editor" rows="22" aria-label="整理版 markdown"></textarea>
    <div class="md-edit-bar">
      <span id="proc-edit-hint" class="md-edit-hint"></span>
      <button id="proc-edit-cancel" type="button">取消</button>
      <button id="proc-edit-save" type="button" class="primary">保存</button>
    </div>`;
  const ta = document.getElementById('proc-edit-text');
  ta.value = currentProcessed;
  ta.addEventListener('input', () => { editDirty = true; });
  document.getElementById('proc-edit-cancel').addEventListener('click', cancelEdit);
  document.getElementById('proc-edit-save').addEventListener('click', async () => {
    const hint = document.getElementById('proc-edit-hint');
    const saveBtn = document.getElementById('proc-edit-save');
    saveBtn.disabled = true;
    hint.textContent = '';
    try {
      const r = await fetch(`/api/meetings/${meetingId}/processed`, {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ text: ta.value })
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || '保存失败');
      }
      currentProcessed = ta.value;
      editingTab = null;
      editDirty = false;
      renderAll();
    } catch (e) {
      hint.textContent = '保存失败: ' + e.message;
    } finally {
      saveBtn.disabled = false;
    }
  });
  ta.focus();
});

// --- 总结编辑 ---
document.getElementById('sum-edit-btn').addEventListener('click', () => {
  editingTab = 'summary';
  editDirty = false;
  document.getElementById('sum-tools').classList.add('hidden');
  const el = document.getElementById('summary-md');
  const editBar = `
    <div class="md-edit-bar">
      <span id="sum-edit-hint" class="md-edit-hint"></span>
      <button id="sum-edit-cancel" type="button">取消</button>
      <button id="sum-edit-save" type="button" class="primary">保存</button>
    </div>`;
  if (currentSummaryJson) {
    el.innerHTML = `
      <div class="sum-edit">
        <label class="sum-edit-field">概述<textarea id="sum-edit-summary" class="md-editor" rows="4"></textarea></label>
        <label class="sum-edit-field">决议（一行一条）<textarea id="sum-edit-decisions" class="md-editor" rows="4"></textarea></label>
        <label class="sum-edit-field">待办（一行一条）<textarea id="sum-edit-actions" class="md-editor" rows="4"></textarea></label>
        <label class="sum-edit-field">待讨论（一行一条）<textarea id="sum-edit-open" class="md-editor" rows="4"></textarea></label>
      </div>${editBar}`;
    document.getElementById('sum-edit-summary').value = currentSummaryJson.summary || '';
    document.getElementById('sum-edit-decisions').value = (currentSummaryJson.decisions || []).join('\n');
    document.getElementById('sum-edit-actions').value = (currentSummaryJson.action_items || []).join('\n');
    document.getElementById('sum-edit-open').value = (currentSummaryJson.open_questions || []).join('\n');
  } else {
    el.innerHTML = `<textarea id="sum-edit-text" class="md-editor" rows="18" aria-label="总结 markdown"></textarea>${editBar}`;
    document.getElementById('sum-edit-text').value = currentSummary;
  }
  el.querySelectorAll('textarea').forEach(t => t.addEventListener('input', () => { editDirty = true; }));
  document.getElementById('sum-edit-cancel').addEventListener('click', cancelEdit);
  document.getElementById('sum-edit-save').addEventListener('click', async () => {
    const hint = document.getElementById('sum-edit-hint');
    const saveBtn = document.getElementById('sum-edit-save');
    let payload;
    if (currentSummaryJson) {
      const splitLines = id => document.getElementById(id).value.split('\n').map(s => s.trim()).filter(Boolean);
      payload = { summary_json: {
        summary: document.getElementById('sum-edit-summary').value.trim(),
        decisions: splitLines('sum-edit-decisions'),
        action_items: splitLines('sum-edit-actions'),
        open_questions: splitLines('sum-edit-open'),
      }};
    } else {
      payload = { text: document.getElementById('sum-edit-text').value };
    }
    saveBtn.disabled = true;
    hint.textContent = '';
    try {
      const r = await fetch(`/api/meetings/${meetingId}/summary`, {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || '保存失败');
      }
      editingTab = null;
      editDirty = false;
      await load();
    } catch (e) {
      hint.textContent = '保存失败: ' + e.message;
    } finally {
      saveBtn.disabled = false;
    }
  });
  const first = el.querySelector('textarea');
  if (first) first.focus();
});

function renderSpeakersBar(count) {
  const bar = document.getElementById('speakers-bar');
  bar.innerHTML = '<span class="label">说话人</span>';
  for (let i = 0; i < count; i++) {
    const chip = document.createElement('span');
    chip.className = `spk-chip ${spkClass(i)}`;
    chip.innerHTML = `${escapeHtml(spkLabel(i))} <span class="edit">改名</span>`;
    chip.addEventListener('click', () => editSpeaker(i));
    bar.appendChild(chip);
  }
}

function renderTimeline() {
  const el = document.getElementById('speaker-timeline');
  if (!el) return;
  if (!allSentences.length) { el.innerHTML = ''; return; }
  const dur = {}, firstStart = {};
  for (const s of allSentences) {
    const spk = Number(s.spk);
    dur[spk] = (dur[spk] || 0) + Math.max(0, (s.end || s.start) - s.start);
    if (!(spk in firstStart)) firstStart[spk] = s.start;
  }
  const spks = Object.keys(dur).map(Number).sort((a, b) => a - b);
  const total = spks.reduce((a, s) => a + dur[s], 0) || 1;
  el.innerHTML = spks.map(spk => {
    const pct = (dur[spk] / total) * 100;
    return `<div class="tl-seg" data-spk="${spk}" role="button" tabindex="0" style="flex:${dur[spk]};background:var(--spk-${spk % 7})" title="${escapeHtml(spkLabel(spk))} · 发言 ${pct.toFixed(0)}%，点击定位"><span>${escapeHtml(spkLabel(spk))} ${pct.toFixed(0)}%</span></div>`;
  }).join('');
  el.querySelectorAll('.tl-seg').forEach(seg => {
    const go = () => {
      const spk = Number(seg.dataset.spk);
      const start = (firstStart[spk] || 0) / 1000;
      audioPlayer.currentTime = start;
      const rawTab = document.querySelector('.tab-btn[data-tab="raw"]');
      if (rawTab && !document.getElementById('tab-raw').classList.contains('active')) rawTab.click();
      lastIdx = -1;
      highlightSentence('#transcript .transcript-line', start * 1000);
    };
    seg.addEventListener('click', go);
    seg.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
}

function highlightTimelineSpeaker(ms) {
  const segs = document.querySelectorAll('#speaker-timeline .tl-seg');
  if (!segs.length || !allSentences.length) return;
  let idx = 0;
  for (let i = 0; i < allSentences.length; i++) {
    if (allSentences[i].start <= ms) idx = i; else break;
  }
  const cur = allSentences[idx] ? Number(allSentences[idx].spk) : -1;
  segs.forEach(seg => seg.classList.toggle('speaking', Number(seg.dataset.spk) === cur));
}

async function editSpeaker(spk) {
  const fallback = `说话人${spk}`;
  const cur = speakerNames[String(spk)] || fallback;
  const name = prompt(`给「${cur}」起个真实名字（留空恢复默认）:`, cur === fallback ? '' : cur);
  if (name === null) return;
  const trimmed = name.trim();
  if (trimmed && trimmed !== fallback) {
    speakerNames[String(spk)] = trimmed;
  } else {
    delete speakerNames[String(spk)];
  }
  try {
    await fetch(`/api/meetings/${meetingId}/speakers`, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ names: speakerNames })
    });
  } catch (e) { alert('保存失败: ' + e.message); }
  renderAll();
  doSearch(document.getElementById('search-input').value);
}

let editingIdx = -1;
const editModal = document.getElementById('edit-modal');
const editText = document.getElementById('edit-text');
const editHint = document.getElementById('edit-hint');
function editSentence(idx) {
  if (!allSentences[idx]) return;
  editingIdx = idx;
  editText.value = allSentences[idx].text;
  document.getElementById('edit-add-hotword').checked = false;
  editHint.textContent = '';
  editHint.style.color = '';
  editModal.classList.remove('hidden');
  setTimeout(() => editText.focus(), 50);
}
document.getElementById('edit-cancel').addEventListener('click', () => editModal.classList.add('hidden'));
editModal.addEventListener('click', e => { if (e.target === editModal) editModal.classList.add('hidden'); });
document.getElementById('edit-save').addEventListener('click', async () => {
  if (editingIdx < 0) return;
  const text = editText.value.trim();
  if (!text) { editHint.textContent = '内容不能为空'; editHint.style.color = 'var(--seal)'; return; }
  try {
    const r = await fetch(`/api/meetings/${meetingId}/sentence`, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ index: editingIdx, text })
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || '保存失败');
    }
    allSentences[editingIdx].text = text;
    let msg = '已保存';
    if (document.getElementById('edit-add-hotword').checked) {
      const d = await fetch('/api/settings/hotwords').then(r => r.json());
      const words = d.hotwords || [];
      if (!words.includes(text)) {
        words.push(text);
        await fetch('/api/settings/hotwords', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ hotwords: words }) });
        msg += `，并加入热词（当前共 ${words.length} 个）`;
      } else {
        msg += '（热词已存在）';
      }
    }
    editHint.style.color = 'var(--moss)';
    editHint.textContent = msg;
    setTimeout(() => {
      editModal.classList.add('hidden');
      renderAll();  // B5: 编辑单句后原文 DOM + 对照视图都要用新文本重渲
      doSearch(document.getElementById('search-input').value);
    }, 700);
  } catch (e) {
    editHint.style.color = 'var(--seal)';
    editHint.textContent = '保存失败: ' + e.message;
  }
});

// === in-page search ===
let searchHits = [];
let searchIdx = -1;
let searchTimer = null;

function activePanel() {
  return document.querySelector('.panel.active') || document.body;
}
function clearSearchMarks() {
  document.querySelectorAll('mark.search-hit').forEach(m => {
    const parent = m.parentNode;
    parent.replaceChild(document.createTextNode(m.textContent), m);
    parent.normalize();
  });
  searchHits = [];
  searchIdx = -1;
}
function highlightInElement(root, query) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const p = node.parentNode;
      if (!p) return NodeFilter.FILTER_REJECT;
      const tag = p.nodeName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK' || tag === 'TEXTAREA') return NodeFilter.FILTER_REJECT;
      return node.nodeValue && node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  const q = query.toLowerCase();
  for (const node of nodes) {
    const text = node.nodeValue;
    const lower = text.toLowerCase();
    let pos = 0, idx, found = false;
    const frag = document.createDocumentFragment();
    while ((idx = lower.indexOf(q, pos)) !== -1) {
      found = true;
      if (idx > pos) frag.appendChild(document.createTextNode(text.slice(pos, idx)));
      const mark = document.createElement('mark');
      mark.className = 'search-hit';
      mark.textContent = text.slice(idx, idx + q.length);
      frag.appendChild(mark);
      searchHits.push(mark);
      pos = idx + q.length;
    }
    if (found) {
      if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
      node.parentNode.replaceChild(frag, node);
    }
  }
}
function updateSearchCount() {
  const el = document.getElementById('search-count');
  el.textContent = searchHits.length ? `${searchIdx + 1}/${searchHits.length}` : (searchIdx === -1 ? '' : '0/0');
}
function showCurrentHit() {
  document.querySelectorAll('mark.search-hit.current').forEach(m => m.classList.remove('current'));
  if (searchIdx >= 0 && searchHits[searchIdx]) {
    searchHits[searchIdx].classList.add('current');
    searchHits[searchIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
function doSearch(query) {
  clearSearchMarks();
  if (query && query.trim()) {
    highlightInElement(activePanel(), query.trim());
    searchIdx = searchHits.length ? 0 : -1;
  }
  showCurrentHit();
  updateSearchCount();
}
function nextHit() {
  if (!searchHits.length) return;
  searchIdx = (searchIdx + 1) % searchHits.length;
  showCurrentHit();
  updateSearchCount();
}
function prevHit() {
  if (!searchHits.length) return;
  searchIdx = (searchIdx - 1 + searchHits.length) % searchHits.length;
  showCurrentHit();
  updateSearchCount();
}
document.getElementById('search-input').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => doSearch(e.target.value), 250);
});
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (e.shiftKey) prevHit(); else nextHit();
  } else if (e.key === 'Escape') {
    e.target.value = '';
    doSearch('');
  }
});
document.getElementById('search-next').addEventListener('click', nextHit);
document.getElementById('search-prev').addEventListener('click', prevHit);

// === live log viewer ===
// B3: 用递归 setTimeout（每次 await 完再排下一次）替代 setInterval，避免单次
// fetch>间隔时多次重叠竞态写 innerHTML；连续失败 N 次停掉并提示「连接丢失」。
const LOG_POLL_MS = 1500;
const LOG_MAX_FAILS = 5;
let logTimer = null;
let logFailCount = 0;
const logModal = document.getElementById('log-modal');
const logBody = document.getElementById('log-body');
const logStepText = document.getElementById('log-step-text');
const logPct = document.getElementById('log-pct');
const logFill = document.getElementById('log-progress-fill');
const logElapsed = document.getElementById('log-elapsed');
const logStaleness = document.getElementById('log-staleness');
document.getElementById('log-btn').addEventListener('click', async () => {
  logModal.classList.remove('hidden');
  logFailCount = 0;
  await refreshLog();
  scheduleLog();
});
document.getElementById('log-close-btn').addEventListener('click', closeLog);
logModal.addEventListener('click', e => { if (e.target === logModal) closeLog(); });
function closeLog() {
  logModal.classList.add('hidden');
  stopLogPoll();
}
function stopLogPoll() {
  if (logTimer) { clearTimeout(logTimer); logTimer = null; }
}
function scheduleLog() {
  stopLogPoll();
  logTimer = setTimeout(async () => {
    logTimer = null;
    if (logModal.classList.contains('hidden')) return;
    const action = await refreshLog();  // 'continue' | 'terminal' | 'fail'
    if (action === 'fail') {
      logFailCount++;
      if (logFailCount >= LOG_MAX_FAILS) {
        logStaleness.textContent = '⚠ 连接丢失，已停止刷新，关掉重开可重试';
        logStaleness.style.color = '#ff8b8b';
        return;
      }
    } else if (action === 'terminal') {
      return;
    } else {
      logFailCount = 0;
    }
    scheduleLog();
  }, LOG_POLL_MS);
}
function fmtElapsed(sec) {
  if (sec < 60) return sec + 's';
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}m${s}s`;
}
function fmtTotalTimings(timings) {
  if (!timings) return '';
  const total = ['convert','asr','polish','summarize'].reduce((a, k) => a + (timings[k] || 0), 0);
  if (!total) return '';
  const sec = Math.round(total);
  if (sec < 60) return `处理 ${sec}s`;
  const m = Math.floor(sec / 60), s = sec % 60;
  return `处理 ${m}m${s}s`;
}
// 返回 'continue' | 'terminal' | 'fail'，供 scheduleLog 决定是否继续。
async function refreshLog() {
  try {
    const r = await fetch(`/api/meetings/${meetingId}/logs`);
    if (!r.ok) return 'fail';
    const d = await r.json();
    const logs = d.logs || [];
    const pct = d.progress || 0;
    logFill.style.width = pct + '%';
    logPct.textContent = pct + '%';
    logStepText.textContent = d.step || statusLabel(d.status);
    logBody.innerHTML = logs.map(l => {
      const cls = l.level === 'error' ? 'log-err' : (l.level === 'warn' ? 'log-warn' : '');
      let ts = '';
      if (l.ts) {
        const t = new Date(l.ts * 1000);
        const p = n => String(n).padStart(2, '0');
        ts = `${p(t.getHours())}:${p(t.getMinutes())}:${p(t.getSeconds())}`;
      }
      return `<span class="${cls}">[${ts}] ${escapeHtml(l.msg)}</span>`;
    }).join('\n');
    logBody.scrollTop = logBody.scrollHeight;
    const now = Math.floor(Date.now() / 1000);
    if (logs.length && logs[0].ts) {
      logElapsed.textContent = '已用 ' + fmtElapsed(Math.round(Math.max(0, now - logs[0].ts)));
    } else {
      logElapsed.textContent = '';
    }
    const processing = ['pending','converting','asr_running','llm_polishing','llm_summarizing'].includes(d.status);
    if (logs.length && processing) {
      const since = Math.round(Math.max(0, now - logs[logs.length - 1].ts));
      if (since >= 15) {
        logStaleness.textContent = `⚠ ${since}s 无新日志`;
        logStaleness.style.color = '#ff8b8b';
        resumeBtn.classList.remove('hidden');
      } else {
        logStaleness.textContent = `${since}s 前更新`;
        logStaleness.style.color = '';
        if (currentStatus !== 'error') resumeBtn.classList.add('hidden');
      }
    } else {
      logStaleness.textContent = '';
      logStaleness.style.color = '';
    }
    if (['done', 'error', 'asr_done'].includes(d.status)) return 'terminal';
    return 'continue';
  } catch (e) {
    return 'fail';
  }
}

// B4: 从历史打开一个"处理中"的会议时，详情页只 load() 一次，看到的是空/半成品且
// 没有"还会更新"的提示。这里按间隔轮询状态，到终态自动整页刷新。
const STATUS_POLL_MS = 2500;
let statusTimer = null;
function isProcessingStatus(s) {
  return ['pending','converting','asr_running','llm_polishing','llm_summarizing'].includes(s);
}
function pollStatusIfProcessing() {
  if (statusTimer) clearTimeout(statusTimer);
  if (!isProcessingStatus(currentStatus)) return;
  statusTimer = setTimeout(async () => {
    statusTimer = null;
    try {
      const r = await fetch(`/api/meetings/${meetingId}`);
      if (!r.ok) return;
      const data = await r.json();
      const st = (data.meta || {}).status;
      if (st && st !== currentStatus) {
        currentStatus = st;
        const metaEl = document.getElementById('m-meta');
        if (metaEl) {
          // 轻量更新状态徽文，避免整页闪烁；终态交给 reload 全量刷新
          metaEl.textContent = metaEl.textContent.replace(/（[^）]*）\s*$/, '').trimEnd();
        }
      }
      if (!isProcessingStatus(st)) {
        location.reload();
        return;
      }
    } catch (e) { /* 瞬态失败，下轮再试 */ }
    pollStatusIfProcessing();
  }, STATUS_POLL_MS);
}

async function load() {
  try {
    const r = await fetch(`/api/meetings/${meetingId}`);
    if (!r.ok) { alert('会议不存在'); location.href = '/'; return; }
    const data = await r.json();
    const meta = data.meta;
    speakerNames = meta.speaker_names || {};
    meetingContext = meta.meeting_context || '';
    allSentences = (data.raw && data.raw.sentences) || [];
    allSpkCount = meta.spk_count || 0;
    currentProcessed = data.processed || '';
    currentSummary = data.summary || '';
    currentSummaryJson = data.summary_json || null;
    meetingTemplate = meta.template || '';
    try {
      const td = await fetch('/api/settings/templates').then(r => r.json());
      templates = td.templates || [];
    } catch (e) { templates = []; }
    document.getElementById('m-title').textContent = meta.title;
    document.getElementById('m-page-title').textContent = `${meta.title} · 听记`;
    const durationStr = meta.duration_ms
      ? `${Math.floor(meta.duration_ms/60000)}分${Math.floor((meta.duration_ms%60000)/1000)}秒`
      : '--';
    let metaLine = `${fmtDate(meta.created_at)} · ${durationStr} · ${meta.spk_count} 人 · ${statusLabel(meta.status)}`;
    const tStr = fmtTotalTimings(meta.timings);
    if (tStr) metaLine += ' · ' + tStr;
    document.getElementById('m-meta').textContent = metaLine;
    currentStatus = meta.status;
    const retryBtn = document.getElementById('retry-btn');
    const processing = ['pending','converting','asr_running','llm_polishing','llm_summarizing'];
    if (!processing.includes(meta.status)) {
      retryBtn.classList.remove('hidden');
      retryBtn.textContent = meta.status === 'asr_done' ? '开始整理'
        : (meta.status === 'done' ? '重新整理' : '重试 LLM');
    }
    if (meta.status === 'error') resumeBtn.classList.remove('hidden');
    renderAll();
    pollStatusIfProcessing();
  } catch (e) {
    alert('加载失败: ' + e.message);
  }
}

load();