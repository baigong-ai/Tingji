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

async function loadHistory() {
  const r = await fetch('/api/meetings');
  const items = await r.json();
  historyList.innerHTML = '';
  if (!items.length) {
    historyList.innerHTML = '<li class="meta" style="justify-content:center;color:#9ca3af;">暂无会议，上传第一段录音开始吧</li>';
    return;
  }
  for (const m of items) {
    const li = document.createElement('li');
    li.dataset.href = `/m/${m.id}`;
    li.innerHTML = `
      <div>
        <span class="title">${escapeHtml(m.title)}</span>
        <div class="meta">${fmtDate(m.created_at)}<span class="sep">·</span>${fmtDuration(m.duration_ms)}<span class="sep">·</span>${m.spk_count} 人</div>
      </div>
      <span class="status-badge status-${m.status}">${statusLabel(m.status)}</span>
    `;
    li.addEventListener('click', () => { location.href = li.dataset.href; });
    historyList.appendChild(li);
  }
}

function fmtDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDuration(ms) {
  if (!ms) return '--';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2,'0')}`;
}

function statusLabel(s) {
  return {
    pending: '排队', converting: '转换中', asr_running: '识别中', asr_done: '待整理',
    llm_polishing: '整理中', llm_summarizing: '总结中', done: '完成', error: '失败',
  }[s] || s;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// === settings modal: directory browser + LLM config ===
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
let browsePath = '';
let previousDir = null;

settingsBtn.addEventListener('click', openSettings);
document.getElementById('settings-close-btn').addEventListener('click', () => settingsModal.classList.add('hidden'));
settingsModal.addEventListener('click', e => { if (e.target === settingsModal) settingsModal.classList.add('hidden'); });

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

// --- 整理模板（自定义） ---
async function loadTemplates() {
  try {
    const d = await fetch('/api/settings/templates').then(r => r.json());
    const lines = (d.custom || []).map(t => `${t.name}｜${t.hint || ''}`);
    document.getElementById('templates-text').value = lines.join('\n');
    document.getElementById('templates-result').textContent = '';
  } catch (e) { document.getElementById('templates-result').textContent = '加载失败: ' + e.message; }
}
document.getElementById('templates-save-btn').addEventListener('click', async () => {
  const lines = document.getElementById('templates-text').value.split('\n').map(s => s.trim()).filter(Boolean);
  const custom = lines.map(line => {
    const i = line.search(/[｜|]/);
    if (i < 0) return { name: line, hint: '' };
    return { name: line.slice(0, i).trim(), hint: line.slice(i + 1).trim() };
  }).filter(t => t.name);
  try {
    const r = await fetch('/api/settings/templates', {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({custom})});
    const d = await r.json();
    if (r.ok) {
      document.getElementById('templates-result').textContent = `已保存 ${(d.custom || []).length} 个自定义模板`;
    } else {
      document.getElementById('templates-result').textContent = '错误: ' + (d.detail || '保存失败');
    }
  } catch (e) { document.getElementById('templates-result').textContent = '保存失败: ' + e.message; }
});

// --- onboarding banner ---
async function loadOnboard() {
  if (localStorage.getItem('onboarded')) return;
  try {
    const r = await fetch('/api/settings');
    const d = await r.json();
    const bar = document.getElementById('onboard-bar');
    bar.innerHTML = `<span>会议数据将存到 <code>${escapeHtml(d.data_dir)}</code>。</span><button id="ob-config" class="mini">更改位置</button><button id="ob-default" class="mini">就用这个</button>`;
    bar.classList.remove('hidden');
    document.getElementById('ob-config').addEventListener('click', () => settingsBtn.click());
    document.getElementById('ob-default').addEventListener('click', () => { localStorage.setItem('onboarded', '1'); bar.classList.add('hidden'); });
  } catch {}
}

loadHistory();
loadOnboard();
if (new URLSearchParams(location.search).get('settings') === '1') {
  openSettings();
  history.replaceState(null, '', '/');
}
