const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const titleInput = document.getElementById('title');
const submitBtn = document.getElementById('submit-btn');
const progressEl = document.getElementById('progress');
const barFill = document.getElementById('bar-fill');
const progressText = document.getElementById('progress-text');
const errorEl = document.getElementById('error');
const historyList = document.getElementById('history');

let selectedFile = null;

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files.length) setFile(fileInput.files[0]); });

function setFile(f) {
  selectedFile = f;
  dropzone.querySelector('p').textContent = `${f.name} (${(f.size/1024/1024).toFixed(1)} MB)`;
  submitBtn.disabled = !titleInput.value.trim();
}

titleInput.addEventListener('input', () => {
  submitBtn.disabled = !(selectedFile && titleInput.value.trim());
});

submitBtn.addEventListener('click', startUpload);

async function startUpload() {
  errorEl.classList.add('hidden');
  submitBtn.disabled = true;
  progressEl.classList.remove('hidden');
  setProgress(0, '上传中...');
  const fd = new FormData();
  fd.append('audio', selectedFile);
  fd.append('title', titleInput.value.trim());
  try {
    const r = await fetch('/api/upload', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || '上传失败');
    }
    const { task_id, meeting_id } = await r.json();
    pollTask(task_id, meeting_id);
  } catch (e) {
    showError(e.message);
    progressEl.classList.add('hidden');
    submitBtn.disabled = false;
  }
}

function pollTask(taskId, meetingId) {
  const timer = setInterval(async () => {
    try {
      const r = await fetch(`/api/tasks/${taskId}`);
      const s = await r.json();
      setProgress(s.progress, s.step);
      if (s.status === 'done' || s.status === 'asr_done') {
        clearInterval(timer);
        location.href = `/m/${meetingId}`;
      } else if (s.status === 'error') {
        clearInterval(timer);
        showError(s.error || '处理失败');
        submitBtn.disabled = false;
      }
    } catch (e) {
      clearInterval(timer);
      showError(e.message);
    }
  }, 2000);
}

function setProgress(pct, step) {
  barFill.style.width = `${pct}%`;
  progressText.textContent = `${pct}% · ${step || ''}`;
}

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove('hidden');
}

let allMeetings = [];
const activeTags = new Set();
const BUSY_STATUS = ['pending', 'converting', 'asr_running', 'llm_polishing', 'llm_summarizing'];
const isFinished = s => !BUSY_STATUS.includes(s);

async function loadHistory() {
  const r = await fetch('/api/meetings');
  allMeetings = await r.json();
  renderTagFilter();
  renderHistory();
}

function allTagList() {
  const s = new Set();
  for (const m of allMeetings) (m.tags || []).forEach(t => s.add(t));
  return [...s].sort((a, b) => a.localeCompare(b, 'zh'));
}

function renderTagFilter() {
  const bar = document.getElementById('tag-filter');
  const tags = allTagList();
  if (!tags.length) { bar.classList.add('hidden'); bar.innerHTML = ''; return; }
  bar.classList.remove('hidden');
  let html = '<span class="tf-label">按标签筛选</span>';
  const allActive = activeTags.size === 0;
  html += `<button class="tag-chip${allActive ? ' active' : ''}" data-tag="">全部</button>`;
  for (const t of tags) {
    html += `<button class="tag-chip${activeTags.has(t) ? ' active' : ''}" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</button>`;
  }
  bar.innerHTML = html;
  bar.querySelectorAll('.tag-chip').forEach(c => {
    c.addEventListener('click', () => {
      const t = c.dataset.tag;
      if (t === '') activeTags.clear();
      else if (activeTags.has(t)) activeTags.delete(t);
      else activeTags.add(t);
      renderTagFilter();
      renderHistory();
    });
  });
}

function renderHistory() {
  const items = activeTags.size === 0
    ? allMeetings
    : allMeetings.filter(m => (m.tags || []).some(t => activeTags.has(t)));
  historyList.innerHTML = '';
  if (!allMeetings.length) {
    historyList.innerHTML = '<li class="meta" style="justify-content:center;color:#9ca3af;">暂无会议，上传第一段录音开始吧</li>';
    return;
  }
  if (!items.length) {
    historyList.innerHTML = '<li class="meta" style="justify-content:center;color:#9ca3af;">没有匹配所选标签的会议</li>';
    return;
  }
  for (const m of items) historyList.appendChild(buildRow(m));
}

function buildRow(m) {
  const li = document.createElement('li');
  li.dataset.id = m.id;
  const tags = m.tags || [];
  const tagsHtml = tags.map(t =>
    `<button class="tag-chip sm" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join('');
  const sourceBadge = m.source === 'live' ? '<span class="source-badge">实时</span>' : '';
  li.innerHTML = `
    <div class="hmain">
      <span class="title">${escapeHtml(m.title)}${sourceBadge}</span>
      <div class="meta">${fmtDate(m.created_at)}<span class="sep">·</span>${fmtDuration(m.duration_ms)}<span class="sep">·</span>${m.spk_count} 人</div>
      <div class="htags ${tags.length ? '' : 'hidden'}">${tagsHtml}</div>
    </div>
    <div class="hside">
      <span class="status-badge status-${m.status}">${statusLabel(m.status)}</span>
      <div class="hactions">
        ${isFinished(m.status) ? '<button class="mini hact" data-act="rename">改名</button>' : ''}
        <button class="mini hact" data-act="tags">标签</button>
        <button class="mini hact hact-del" data-act="delete">删除</button>
      </div>
    </div>
  `;
  li.addEventListener('click', () => { location.href = `/m/${m.id}`; });
  li.querySelectorAll('.htags .tag-chip').forEach(c => {
    c.addEventListener('click', e => {
      e.stopPropagation();
      const t = c.dataset.tag;
      if (activeTags.has(t)) activeTags.delete(t); else activeTags.add(t);
      renderTagFilter();
      renderHistory();
    });
  });
  li.querySelectorAll('.hact').forEach(b => {
    b.addEventListener('click', e => {
      e.stopPropagation();
      const act = b.dataset.act;
      if (act === 'rename') openRename(m);
      else if (act === 'tags') openTags(m);
      else if (act === 'delete') openDelete(m);
    });
  });
  return li;
}

// --- 通用对话框（改名 / 标签 / 删除） ---
const dlgModal = document.getElementById('dlg-modal');
const dlgTitle = document.getElementById('dlg-title');
const dlgBody = document.getElementById('dlg-body');
const dlgActions = document.getElementById('dlg-actions');

let dlgDirty = false;  // 弹窗内是否改过数据：取消/关闭时不刷新列表，保存过才刷
function closeDlg() {
  dlgModal.classList.add('hidden');
  dlgBody.innerHTML = '';
  dlgActions.innerHTML = '';
  if (dlgDirty) {
    dlgDirty = false;
    renderTagFilter();
    renderHistory();
  }
}
dlgModal.addEventListener('click', e => { if (e.target === dlgModal) closeDlg(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !dlgModal.classList.contains('hidden')) closeDlg();
});

function openRename(m) {
  dlgTitle.textContent = '重命名会议';
  dlgBody.innerHTML = '<input id="dlg-input" type="text" maxlength="120">';
  dlgActions.innerHTML = '<button id="dlg-cancel">取消</button><button id="dlg-ok" class="primary">保存</button>';
  const input = document.getElementById('dlg-input');
  input.value = m.title;
  const ok = async () => {
    const v = input.value.trim();
    if (!v) { input.focus(); return; }
    const r = await fetch(`/api/meetings/${m.id}/title`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: v })
    });
    if (r.ok) {
      m.title = v;
      dlgDirty = true;
      closeDlg();
    }
  };
  document.getElementById('dlg-ok').addEventListener('click', ok);
  document.getElementById('dlg-cancel').addEventListener('click', closeDlg);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') ok(); });
  dlgModal.classList.remove('hidden');
  input.focus();
  input.select();
}

function openTags(m) {
  dlgTitle.textContent = '管理标签';
  dlgBody.innerHTML = `
    <div id="dlg-tags" class="dlg-tags"></div>
    <div class="dlg-add">
      <input id="dlg-input" type="text" placeholder="输入标签后回车添加" maxlength="20">
      <button id="dlg-add-btn" class="mini">添加</button>
    </div>`;
  dlgActions.innerHTML = '<button id="dlg-cancel">关闭</button>';
  document.getElementById('dlg-cancel').addEventListener('click', closeDlg);
  const input = document.getElementById('dlg-input');
  const renderChips = () => {
    const box = document.getElementById('dlg-tags');
    const tags = m.tags || [];
    box.innerHTML = tags.length
      ? tags.map(t => `<button class="tag-chip sm removable">${escapeHtml(t)}<span class="x" data-tag="${escapeHtml(t)}" role="button" aria-label="移除">×</span></button>`).join('')
      : '<span class="he-empty">暂无标签</span>';
    box.querySelectorAll('.x').forEach(x => x.addEventListener('click', async () => {
      const t = x.dataset.tag;
      await saveTags(m, (m.tags || []).filter(s => s !== t));
      renderChips();
    }));
  };
  const add = async () => {
    const v = input.value.trim();
    if (!v) return;
    const tags = (m.tags || []).slice();
    if (!tags.includes(v)) tags.push(v);
    await saveTags(m, tags);
    input.value = '';
    renderChips();
  };
  document.getElementById('dlg-add-btn').addEventListener('click', add);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') add(); });
  renderChips();
  dlgModal.classList.remove('hidden');
  input.focus();
}

async function saveTags(m, tags) {
  const r = await fetch(`/api/meetings/${m.id}/tags`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tags })
  });
  const d = await r.json();
  if (r.ok) {
    m.tags = d.tags;
    dlgDirty = true;
    renderTagFilter();
  }
}

async function openDelete(m) {
  let trashPath = '';
  try { trashPath = (await fetch('/api/settings').then(r => r.json())).trash_dir || ''; } catch {}
  dlgTitle.textContent = '删除会议';
  dlgBody.innerHTML = `
    <p>确定删除「<b>${escapeHtml(m.title)}</b>」？请选择删除方式：</p>
    <div class="dlg-del-options">
      <label>
        <input type="radio" name="delmode" value="keep" checked>
        <b>移到回收站（保留文件）</b>
        <span class="hint">从列表移除，会议文件移到回收站，可自行取回：<code>${escapeHtml(trashPath)}</code></span>
      </label>
      <label>
        <input type="radio" name="delmode" value="full">
        <b>完全删除</b>
        <span class="hint">永久删除全部文件，不可恢复。</span>
      </label>
    </div>`;
  dlgActions.innerHTML = '<button id="dlg-cancel">取消</button><button id="dlg-del" class="primary">删除</button>';
  document.getElementById('dlg-cancel').addEventListener('click', closeDlg);
  document.getElementById('dlg-del').addEventListener('click', async () => {
    const mode = document.querySelector('input[name=delmode]:checked').value;
    const url = `/api/meetings/${m.id}` + (mode === 'keep' ? '?keep=1' : '');
    const r = await fetch(url, { method: 'DELETE' });
    if (r.ok) {
      allMeetings = allMeetings.filter(x => x.id !== m.id);
      dlgDirty = true;
      closeDlg();
    }
  });
  dlgModal.classList.remove('hidden');
}

// --- 回收站 ---
document.getElementById('trash-btn').addEventListener('click', openTrash);

async function openTrash() {
  dlgTitle.textContent = '回收站';
  dlgBody.innerHTML = '<p class="he-empty">加载中…</p>';
  dlgActions.innerHTML = '<button id="dlg-cancel">关闭</button>';
  document.getElementById('dlg-cancel').addEventListener('click', closeDlg);
  dlgModal.classList.remove('hidden');
  await renderTrashList();
}

async function renderTrashList() {
  try {
    const r = await fetch('/api/trash');
    const d = await r.json();
    const items = d.items || [];
    let html = '';
    if (d.trash_dir) html += `<p class="trash-dir">回收站目录：<code>${escapeHtml(d.trash_dir)}</code></p>`;
    if (!items.length) {
      html += '<p class="he-empty">回收站是空的</p>';
    } else {
      html += '<ul class="trash-list">' + items.map(it => `
        <li class="trash-item" data-name="${escapeHtml(it.name)}">
          <div class="hmain">
            <span class="title">${escapeHtml(it.title)}</span>
            <div class="meta">${fmtDate(it.created_at)}<span class="sep">·</span>${statusLabel(it.status)}</div>
          </div>
          <div class="hactions">
            <button class="mini" data-act="restore" type="button">恢复</button>
            <button class="mini hact-del" data-act="del" type="button">彻底删除</button>
          </div>
        </li>`).join('') + '</ul>';
    }
    dlgBody.innerHTML = html;
    dlgBody.querySelectorAll('.trash-item button').forEach(b => {
      b.addEventListener('click', () => {
        const name = b.closest('.trash-item').dataset.name;
        if (b.dataset.act === 'restore') restoreTrash(name);
        else deleteTrash(name);
      });
    });
  } catch (e) {
    dlgBody.innerHTML = `<p class="he-empty">加载失败：${escapeHtml(e.message)}</p>`;
  }
}

async function restoreTrash(name) {
  const r = await fetch(`/api/trash/${encodeURIComponent(name)}/restore`, { method: 'POST' });
  if (r.ok) {
    await renderTrashList();
    loadHistory();
  } else {
    const d = await r.json().catch(() => ({}));
    alert('恢复失败：' + (d.detail || '未知错误'));
  }
}

async function deleteTrash(name) {
  if (!confirm('彻底删除后无法恢复，确定删除？')) return;
  const r = await fetch(`/api/trash/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (r.ok) {
    await renderTrashList();
  } else {
    const d = await r.json().catch(() => ({}));
    alert('删除失败：' + (d.detail || '未知错误'));
  }
}

// fmtDate / statusLabel / escapeHtml 见 static/common.js

function fmtDuration(ms) {
  if (!ms) return '--';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2,'0')}`;
}

// === settings modal: directory browser + LLM config ===
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
let browsePath = '';
let previousDir = null;

settingsBtn.addEventListener('click', openSettings);
document.getElementById('settings-close-btn').addEventListener('click', () => settingsModal.classList.add('hidden'));
settingsModal.addEventListener('click', e => { if (e.target === settingsModal) settingsModal.classList.add('hidden'); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !settingsModal.classList.contains('hidden')) settingsModal.classList.add('hidden');
});

document.querySelectorAll('.stab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.spanel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.querySelector(`.spanel[data-spanel="${btn.dataset.stab}"]`).classList.add('active');
    if (btn.dataset.stab === 'dir') loadDir(window.__tingjiDataDir || '');
    if (btn.dataset.stab === 'llm') loadLLM();
    if (btn.dataset.stab === 'hotwords') loadHotwords();
    if (btn.dataset.stab === 'templates') loadTemplates();
    if (btn.dataset.stab === 'server') { loadAsrStatus(); loadServer(); }
  });
});

async function openSettings() {
  settingsModal.classList.remove('hidden');
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    window.__tingjiDataDir = s.data_dir || '';
  } catch {
    window.__tingjiDataDir = '';
  }
  const active = document.querySelector('.stab.active');
  if (active) active.click();
}

// --- data directory browser ---
async function loadDir(path) {
  try {
    const r = await fetch('/api/browse?path=' + encodeURIComponent(path));
    const d = await r.json();
    browsePath = d.path;
    document.getElementById('dir-current').textContent = d.path;
    const wEl = document.getElementById('dir-writable');
    if (!d.exists) { wEl.textContent = '错误: ' + (d.error || '路径不存在'); wEl.style.color = '#b91c1c'; }
    else if (!d.writable) { wEl.textContent = '警告: 不可写'; wEl.style.color = '#b91c1c'; }
    else { wEl.textContent = '可写'; wEl.style.color = '#15803d'; }
    const list = document.getElementById('dir-list');
    list.innerHTML = '';
    if (d.parent !== null && d.parent !== undefined) {
      const li = document.createElement('li');
      li.className = 'dir-item dir-up';
      li.textContent = '.. (返回上级)';
      li.addEventListener('click', () => loadDir(d.parent));
      list.appendChild(li);
    }
    for (const dir of d.dirs) {
      const li = document.createElement('li');
      li.className = 'dir-item';
      li.textContent = dir.name;
      li.addEventListener('click', () => loadDir(dir.path));
      list.appendChild(li);
    }
  } catch (e) {
    document.getElementById('dir-writable').textContent = '加载失败: ' + e.message;
  }
}
document.getElementById('dir-up-btn').addEventListener('click', async () => {
  const r = await fetch('/api/browse?path=' + encodeURIComponent(browsePath));
  const d = await r.json();
  if (d.parent !== null && d.parent !== undefined) loadDir(d.parent);
});
document.getElementById('dir-goto').addEventListener('click', () => {
  const v = document.getElementById('data-dir-input').value.trim();
  if (v) loadDir(v);
});
document.getElementById('dir-select-btn').addEventListener('click', saveDirFromBrowse);
async function saveDirFromBrowse() {
  const r = await fetch('/api/settings', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data_dir: browsePath})});
  const d = await r.json();
  const res = document.getElementById('dir-result');
  if (r.ok) {
    previousDir = d.previous_dir;
    res.textContent = '已保存: ' + d.data_dir;
    document.getElementById('dir-migrate-btn').classList.toggle('hidden', !(d.previous_dir && d.previous_dir !== d.data_dir));
    loadHistory();
  } else res.textContent = '错误: ' + (d.detail || '保存失败');
}
document.getElementById('dir-migrate-btn').addEventListener('click', async () => {
  if (!previousDir) return;
  document.getElementById('dir-result').textContent = '迁移中...';
  const r = await fetch('/api/settings/migrate', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from_dir: previousDir})});
  const d = await r.json();
  if (r.ok) {
    document.getElementById('dir-result').textContent = `迁移完成: ${d.count} 个会议（${d.to_dir}）`;
    document.getElementById('dir-migrate-btn').classList.add('hidden');
    loadHistory();
  } else document.getElementById('dir-result').textContent = '错误: ' + (d.detail || '迁移失败');
});

// --- LLM config ---
async function loadLLM() {
  try {
    const r = await fetch('/api/settings/llm');
    const d = await r.json();
    const modeRadio = document.querySelector(`input[name=llm-mode][value="${d.mode}"]`);
    if (modeRadio) modeRadio.checked = true;
    toggleLLMFields();
    document.getElementById('ollama-url').value = d.ollama.base_url;
    document.getElementById('ollama-model').innerHTML = `<option>${escapeHtml(d.ollama.model)}</option>`;
    document.getElementById('api-url').value = d.api.base_url;
    document.getElementById('api-model').value = d.api.model;
    document.getElementById('api-key').placeholder = d.api.has_key ? '已设置，留空不改' : '输入 api_key';
    document.getElementById('api-key').value = '';
    document.getElementById('llm-result').textContent = '';
  } catch (e) { document.getElementById('llm-result').textContent = '加载失败: ' + e.message; }
}
function toggleLLMFields() {
  const mode = document.querySelector('input[name=llm-mode]:checked').value;
  document.getElementById('llm-ollama').classList.toggle('hidden', mode !== 'ollama');
  document.getElementById('llm-api').classList.toggle('hidden', mode !== 'api');
}
document.querySelectorAll('input[name=llm-mode]').forEach(r => r.addEventListener('change', toggleLLMFields));
document.getElementById('ollama-refresh').addEventListener('click', async () => {
  const url = document.getElementById('ollama-url').value;
  document.getElementById('llm-result').textContent = '刷新模型列表...';
  const r = await fetch('/api/settings/llm/models?base_url=' + encodeURIComponent(url));
  const d = await r.json();
  const sel = document.getElementById('ollama-model');
  const cur = sel.value;
  sel.innerHTML = (d.models || []).map(m => `<option>${escapeHtml(m)}</option>`).join('');
  if (d.models && d.models.includes(cur)) sel.value = cur;
  document.getElementById('llm-result').textContent = d.error ? ('刷新失败: ' + d.error) : (`找到 ${d.models.length} 个模型`);
});
document.getElementById('ollama-test').addEventListener('click', () => testLLM('ollama'));
document.getElementById('api-test').addEventListener('click', () => testLLM('api'));
async function testLLM(mode) {
  document.getElementById('llm-result').textContent = '测试中...';
  try {
    const r = await fetch('/api/settings/llm/test', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(buildLLMPayload(mode, mode === 'api'))});
    const d = await r.json();
    document.getElementById('llm-result').textContent = d.ok ? ('连接正常: ' + (d.reply || '').slice(0, 80)) : ('失败: ' + (d.error || '未知错误'));
  } catch (e) { document.getElementById('llm-result').textContent = '失败: ' + e.message; }
}
function buildLLMPayload(mode, withKey) {
  const payload = {
    mode,
    api: { base_url: document.getElementById('api-url').value.trim(), model: document.getElementById('api-model').value.trim() },
    ollama: { base_url: document.getElementById('ollama-url').value.trim(), model: document.getElementById('ollama-model').value }
  };
  if (withKey) {
    const k = document.getElementById('api-key').value;
    if (k) payload.api.api_key = k;
  }
  return payload;
}
document.getElementById('llm-save-btn').addEventListener('click', async () => {
  const mode = document.querySelector('input[name=llm-mode]:checked').value;
  const r = await fetch('/api/settings/llm', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(buildLLMPayload(mode, true))});
  const d = await r.json();
  document.getElementById('llm-result').textContent = r.ok ? '已保存' : ('错误: ' + (d.detail || '保存失败'));
});

// --- hotwords ---
async function loadHotwords() {
  try {
    const d = await fetch('/api/settings/hotwords').then(r => r.json());
    document.getElementById('hotwords-text').value = (d.hotwords || []).join('\n');
    document.getElementById('hotwords-result').textContent = '';
  } catch (e) { document.getElementById('hotwords-result').textContent = '加载失败: ' + e.message; }
}
document.getElementById('hotwords-save-btn').addEventListener('click', async () => {
  const words = document.getElementById('hotwords-text').value.split('\n').map(s => s.trim()).filter(Boolean);
  try {
    const r = await fetch('/api/settings/hotwords', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hotwords: words})});
    const d = await r.json();
    if (r.ok) {
      let msg = `已保存 ${d.count} 个热词`;
      if (d.duplicates) msg += `（自动去重 ${d.duplicates} 个重复）`;
      document.getElementById('hotwords-result').textContent = msg;
    } else {
      document.getElementById('hotwords-result').textContent = '错误: ' + (d.detail || '保存失败');
    }
  } catch (e) { document.getElementById('hotwords-result').textContent = '保存失败: ' + e.message; }
});

// --- 总结模板（列表 + 字段编辑） ---
let tplList = [];
let tplIdx = 0;
const TPL_FIELDS = ['name','background','terms','direction','content','framework'];
function blankTpl() { return {id:'', name:'新模板', background:'',terms:'',direction:'',content:'',framework:''}; }
async function loadTemplates() {
  const res = document.getElementById('templates-result');
  try {
    const d = await fetch('/api/settings/templates').then(r => r.json());
    tplList = d.templates || [];
    if (!tplList.length) tplList = [blankTpl()];
    tplIdx = 0;
    renderTplSelect();
    loadTplFields();
    res.textContent = '';
  } catch (e) { res.textContent = '加载失败: ' + e.message; }
}
function renderTplSelect() {
  const sel = document.getElementById('tpl-select');
  sel.innerHTML = '';
  tplList.forEach((t, i) => {
    const o = document.createElement('option');
    o.value = i;
    o.textContent = t.name || '(未命名)';
    if (i === tplIdx) o.selected = true;
    sel.appendChild(o);
  });
}
function loadTplFields() {
  const t = tplList[tplIdx] || {};
  TPL_FIELDS.forEach(f => { const el = document.getElementById('tpl-' + f); if (el) el.value = t[f] || ''; });
}
function saveTplFieldsToList() {
  const t = tplList[tplIdx]; if (!t) return;
  TPL_FIELDS.forEach(f => { const el = document.getElementById('tpl-' + f); if (el) t[f] = el.value; });
}
document.getElementById('tpl-select').addEventListener('change', e => {
  saveTplFieldsToList();
  tplIdx = Number(e.target.value);
  loadTplFields();
});
document.getElementById('tpl-new-btn').addEventListener('click', () => {
  saveTplFieldsToList();
  tplList.push(blankTpl());
  tplIdx = tplList.length - 1;
  renderTplSelect();
  loadTplFields();
  document.getElementById('tpl-name').focus();
});
document.getElementById('tpl-del-btn').addEventListener('click', () => {
  if (!tplList.length) return;
  if (!confirm('删除当前模板？')) return;
  tplList.splice(tplIdx, 1);
  if (!tplList.length) tplList.push(blankTpl());
  tplIdx = Math.min(tplIdx, tplList.length - 1);
  renderTplSelect();
  loadTplFields();
});
document.getElementById('templates-save-btn').addEventListener('click', async () => {
  saveTplFieldsToList();
  const res = document.getElementById('templates-result');
  try {
    const r = await fetch('/api/settings/templates', {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({templates: tplList})});
    const d = await r.json();
    if (r.ok) {
      tplList = d.templates || tplList;
      tplIdx = Math.min(tplIdx, tplList.length - 1);
      renderTplSelect();
      loadTplFields();
      res.textContent = `已保存 ${tplList.length} 个模板`;
    } else {
      res.textContent = '错误: ' + (d.detail || '保存失败');
    }
  } catch (e) { res.textContent = '保存失败: ' + e.message; }
});

// --- onboarding banner ---
async function loadOnboard() {
  try {
    const d = await fetch('/api/settings').then(r => r.json());
    if (d.onboarded) return;  // already accepted / configured a dir
    const bar = document.getElementById('onboard-bar');
    bar.innerHTML = `<span>会议数据将存到 <code>${escapeHtml(d.data_dir)}</code>。</span><button id="ob-config" class="mini">更改位置</button><button id="ob-default" class="mini">就用这个</button>`;
    bar.classList.remove('hidden');
    document.getElementById('ob-config').addEventListener('click', () => settingsBtn.click());
    document.getElementById('ob-default').addEventListener('click', async () => {
      try { await fetch('/api/settings/onboard', { method: 'POST' }); } catch {}
      bar.classList.add('hidden');
    });
  } catch {}
}

// --- ASR 模型状态 + 端口/服务 ---
async function loadAsrStatus() {
  const line = document.getElementById('asr-status-line');
  const res = document.getElementById('asr-result');
  res.textContent = '';
  try {
    const r = await fetch('/api/asr/status');
    const s = await r.json();
    if (!r.ok || s.loaded === undefined) {
      line.textContent = '无法读取模型状态，请重启服务后再试。';
      return;
    }
    const state = s.busy ? '正在识别' : (s.loaded ? '已加载，空闲中' : '未加载（首次识别时自动加载）');
    const rss = (s.rss_mb != null) ? `${s.rss_mb} MB` : '—';
    const last = s.last_used_at ? new Date(s.last_used_at * 1000).toLocaleString('zh-CN') : '—';
    const idle = s.last_used_at ? `${Math.round(s.idle_seconds / 60)} 分钟` : '—';
    line.innerHTML = `状态：<b>${state}</b> · 占用内存：${rss} · 最近使用：${last} · 已空闲：${idle}` +
      (s.loaded ? ` · 空闲 ${s.idle_unload_minutes} 分钟后自动释放` : '');
  } catch (e) { line.textContent = '加载失败：' + e.message; }
}
document.getElementById('asr-refresh-btn').addEventListener('click', loadAsrStatus);
document.getElementById('asr-unload-btn').addEventListener('click', async () => {
  const res = document.getElementById('asr-result');
  res.textContent = '释放中…';
  try {
    const r = await fetch('/api/asr/unload', { method: 'POST' });
    const d = await r.json();
    if (r.ok) {
      res.style.color = '#15803d';
      res.textContent = d.unloaded ? '已释放，模型从内存中移出' : '模型本来就没加载，无需释放';
      loadAsrStatus();
    } else {
      res.style.color = '#b91c1c';
      res.textContent = '无法释放：' + (d.detail || '未知错误');
    }
  } catch (e) { res.style.color = '#b91c1c'; res.textContent = '失败：' + e.message; }
});

async function loadServer() {
  const res = document.getElementById('srv-result');
  try {
    const r = await fetch('/api/settings/server');
    const d = await r.json();
    if (!r.ok || d.host === undefined) {
      // Stale server (endpoint missing) — fall back to defaults, never "undefined".
      document.getElementById('srv-host').value = '0.0.0.0';
      document.getElementById('srv-port').value = 8000;
      document.getElementById('srv-idle').value = 30;
      res.style.color = '#b91c1c';
      res.textContent = '服务版本过旧，请重启服务后重新打开设置。';
      return;
    }
    document.getElementById('srv-host').value = d.host;
    document.getElementById('srv-port').value = d.port;
    document.getElementById('srv-idle').value = d.idle_unload_minutes;
    res.style.color = '';
    res.textContent = (d.port !== d.running_port)
      ? `当前实际运行端口是 ${d.running_port}，改动需重启服务才生效。`
      : '';
  } catch (e) { res.textContent = '加载失败：' + e.message; }
}
document.getElementById('srv-check-btn').addEventListener('click', async () => {
  const res = document.getElementById('srv-result');
  const port = parseInt(document.getElementById('srv-port').value, 10);
  const host = document.getElementById('srv-host').value.trim();
  if (!port || port < 1 || port > 65535) {
    res.style.color = '#b91c1c';
    res.textContent = '端口须在 1–65535 之间。';
    return;
  }
  res.style.color = '';
  res.textContent = '检测中…';
  try {
    const r = await fetch('/api/settings/server/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port, host }),
    });
    const d = await r.json();
    if (!r.ok || d.ok === undefined) {
      res.style.color = '#b91c1c';
      res.textContent = '检测失败：服务版本过旧，请重启服务。';
      return;
    }
    if (d.ok) {
      res.style.color = '#15803d';
      res.textContent = d.self
        ? `端口 ${port}：当前服务正在使用，保存后无需重启。`
        : `端口 ${port}：空闲，可以使用。`;
    } else if (d.permission) {
      res.style.color = '#b91c1c';
      res.textContent = `端口 ${port}：是系统保留端口（小于 1024），请换一个更大的端口。`;
    } else {
      res.style.color = '#b91c1c';
      let msg = `端口 ${port}：已被其他程序占用，请换一个端口试试。`;
      if (d.who) msg += '\n' + d.who;
      res.textContent = msg;
    }
  } catch (e) { res.style.color = '#b91c1c'; res.textContent = '检测失败：' + e.message; }
});
document.getElementById('srv-save-btn').addEventListener('click', async () => {
  const res = document.getElementById('srv-result');
  const port = parseInt(document.getElementById('srv-port').value, 10);
  const host = document.getElementById('srv-host').value.trim() || '0.0.0.0';
  const idle = parseInt(document.getElementById('srv-idle').value, 10);
  if (!port || port < 1 || port > 65535) {
    res.style.color = '#b91c1c';
    res.textContent = '端口须在 1–65535 之间。';
    return;
  }
  try {
    const r = await fetch('/api/settings/server', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port, host, idle_unload_minutes: idle }),
    });
    const d = await r.json();
    if (r.ok) {
      res.style.color = '#15803d';
      res.textContent = d.restart_required
        ? `已保存。端口或监听地址的改动需重启服务才生效（当前仍运行在 ${d.running_port}）。`
        : '已保存。';
      loadAsrStatus();
    } else {
      res.style.color = '#b91c1c';
      res.textContent = '保存失败：' + (d.detail || '未知错误');
    }
  } catch (e) { res.style.color = '#b91c1c'; res.textContent = '保存失败：' + e.message; }
});

loadHistory();
loadOnboard();
if (new URLSearchParams(location.search).get('settings') === '1') {
  openSettings();
  history.replaceState(null, '', '/');
}
