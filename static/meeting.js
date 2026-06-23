// 听记 · 详情页逻辑（从 meeting.html 内联脚本拆出）

const pathParts = location.pathname.split('/');
const meetingId = pathParts[pathParts.length - 1];
const audioPlayer = document.getElementById('audio-player');
let speakerNames = {};
let allSentences = [];
let allSpkCount = 0;
let currentProcessed = '';
let currentSummary = '';
let currentStatus = '';
let activeLine = null;
let lastIdx = -1;

function fmtTs(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2,'0')}`;
}
function fmtDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
const SPEAKER_COLORS = ['#1f3a5f', '#4a6741', '#b78038', '#c0392b', '#8e44ad', '#2c7a7b', '#a04900'];
function spkColor(spk) { return SPEAKER_COLORS[Number(spk) % SPEAKER_COLORS.length] || SPEAKER_COLORS[0]; }
function spkClass(spk) { return `spk-${Number(spk) % SPEAKER_COLORS.length}`; }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function spkLabel(spk) {
  return speakerNames[String(spk)] || speakerNames[spk] || `说话人${spk}`;
}
function applySpeakerNamesToMd(md) {
  if (!md) return md;
  return md.replace(/说话人\s*(\d+)/g, (m, n) => speakerNames[n] ? speakerNames[n] : `说话人${n}`);
}
function renderMd(md) {
  md = applySpeakerNamesToMd(md);
  if (!md) return '<p class="empty-state">（暂无内容）</p>';
  return marked.parse(md);
}

audioPlayer.src = `/api/meetings/${meetingId}/audio`;

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
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
document.getElementById('retry-btn').addEventListener('click', async () => {
  const btn = document.getElementById('retry-btn');
  const msg = currentStatus === 'asr_done' ? '开始整理 + 总结？' : '重新调用 LLM 整理 + 总结？';
  if (!confirm(msg)) return;
  btn.disabled = true;
  const origText = btn.textContent;
  try {
    const r = await fetch(`/api/meetings/${meetingId}/retry-llm`, { method: 'POST' });
    if (!r.ok) throw new Error('提交失败');
    const { task_id } = await r.json();
    btn.textContent = '整理中…';
    await new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const s = await fetch(`/api/tasks/${task_id}`).then(x => x.json());
          btn.textContent = `整理中… ${s.progress}%`;
          if (s.status === 'done') { clearInterval(timer); resolve(); }
          else if (s.status === 'error') { clearInterval(timer); reject(new Error(s.error || '整理失败')); }
        } catch (e) { clearInterval(timer); reject(e); }
      }, 2000);
    });
    location.reload();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = origText;
    alert('整理失败: ' + e.message);
  }
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
    div.title = '单击跳转播放 · 双击编辑';
    // CSS 接管颜色：不再写 inline style
    div.innerHTML = `<span class="ts">[${fmtTs(s.start)}]</span><span class="spk ${spkClass(s.spk)}">${escapeHtml(spkLabel(s.spk))}</span><span class="text">${escapeHtml(s.text)}</span>`;
    if (clickable) {
      div.addEventListener('click', () => {
        audioPlayer.currentTime = s.start / 1000;
        audioPlayer.play();
      });
    }
    div.addEventListener('dblclick', () => editSentence(i));
    container.appendChild(div);
  }
}

audioPlayer.addEventListener('timeupdate', () => {
  const ms = audioPlayer.currentTime * 1000;
  if (document.getElementById('tab-raw').classList.contains('active')) {
    highlightSentence('#transcript .transcript-line', ms);
  } else if (document.getElementById('tab-compare').classList.contains('active')) {
    highlightSentence('#compare-raw-body .transcript-line', ms);
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
    if (m) {
      const spk = m[1];
      const idx = spkPtr[spk] || 0;
      let count = 0;
      for (const t of turns) {
        if (t.spk === spk) {
          if (count === idx) { start = t.start; break; }
          count++;
        }
      }
      spkPtr[spk] = idx + 1;
      block = '## ' + block;
    }
    block = applySpeakerNamesToMd(block);
    html += `<div class="proc-seg" data-start="${start}">${marked.parse(block)}</div>`;
  }
  return html;
}

function renderAll() {
  renderSpeakersBar(allSpkCount);
  renderRaw(document.getElementById('transcript'), allSentences, true);
  renderRaw(document.getElementById('compare-raw-body'), allSentences, false);
  document.getElementById('processed-md').innerHTML = renderProcessedSegments(currentProcessed, allSentences);
  document.getElementById('summary-md').innerHTML = renderMd(currentSummary);
  document.getElementById('compare-processed-body').innerHTML = renderProcessedSegments(currentProcessed, allSentences);
  activeLine = null;
  lastIdx = -1;
}

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
    document.querySelectorAll(`.transcript-line[data-idx="${editingIdx}"]`).forEach(line => {
      const span = line.querySelector('.text');
      if (span) span.textContent = text;
    });
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
    setTimeout(() => { editModal.classList.add('hidden'); doSearch(document.getElementById('search-input').value); }, 700);
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
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK') return NodeFilter.FILTER_REJECT;
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

function bindScrollSync() {
  const a = document.getElementById('compare-raw');
  const b = document.getElementById('compare-processed');
  let syncing = false;
  a.addEventListener('scroll', () => {
    if (syncing) return; syncing = true; b.scrollTop = a.scrollTop;
    setTimeout(() => syncing = false, 50);
  });
  b.addEventListener('scroll', () => {
    if (syncing) return; syncing = true; a.scrollTop = b.scrollTop;
    setTimeout(() => syncing = false, 50);
  });
}

function statusLabel(s) {
  return {done:'完成', asr_done:'待整理', error:'失败', pending:'处理中', converting:'处理中', asr_running:'处理中', llm_polishing:'处理中', llm_summarizing:'处理中'}[s] || s;
}

async function load() {
  try {
    const r = await fetch(`/api/meetings/${meetingId}`);
    if (!r.ok) { alert('会议不存在'); location.href = '/'; return; }
    const data = await r.json();
    const meta = data.meta;
    speakerNames = meta.speaker_names || {};
    allSentences = (data.raw && data.raw.sentences) || [];
    allSpkCount = meta.spk_count || 0;
    currentProcessed = data.processed || '';
    currentSummary = data.summary || '';
    document.getElementById('m-title').textContent = meta.title;
    document.getElementById('m-page-title').textContent = `${meta.title} · 听记`;
    const durationStr = meta.duration_ms
      ? `${Math.floor(meta.duration_ms/60000)}分${Math.floor((meta.duration_ms%60000)/1000)}秒`
      : '--';
    document.getElementById('m-meta').textContent =
      `${fmtDate(meta.created_at)} · ${durationStr} · ${meta.spk_count} 人 · ${statusLabel(meta.status)}`;
    currentStatus = meta.status;
    const retryBtn = document.getElementById('retry-btn');
    const processing = ['pending','converting','asr_running','llm_polishing','llm_summarizing'];
    if (!processing.includes(meta.status)) {
      retryBtn.classList.remove('hidden');
      retryBtn.textContent = meta.status === 'asr_done' ? '开始整理'
        : (meta.status === 'done' ? '重新整理' : '重试 LLM');
    }
    renderAll();
    bindScrollSync();
  } catch (e) {
    alert('加载失败: ' + e.message);
  }
}

load();