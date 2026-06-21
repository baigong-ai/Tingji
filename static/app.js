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
  dropzone.querySelector('p').textContent = `📎 ${f.name} (${(f.size/1024/1024).toFixed(1)} MB)`;
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
      if (s.status === 'done') {
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
    historyList.innerHTML = '<li class="meta">暂无</li>';
    return;
  }
  for (const m of items) {
    const li = document.createElement('li');
    li.innerHTML = `
      <div>
        <a href="/m/${m.id}">${escapeHtml(m.title)}</a>
        <div class="meta">${m.created_at} · ${fmtDuration(m.duration_ms)} · ${m.spk_count} 人</div>
      </div>
      <div class="status-${m.status}">${statusLabel(m.status)}</div>
    `;
    historyList.appendChild(li);
  }
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
    pending: '排队',
    converting: '转换中',
    asr_running: '识别中',
    llm_polishing: '整理中',
    llm_summarizing: '总结中',
    done: '完成',
    error: '失败',
  }[s] || s;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

loadHistory();
