// 听记 · 前端公共工具函数（无构建步骤，直接挂全局，各页面在对应 JS 前引入）

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function statusLabel(s) {
  return {
    pending: '排队', converting: '转换中', asr_running: '识别中', asr_done: '待整理',
    live_recording: '实时中', llm_polishing: '整理中', llm_summarizing: '总结中', done: '完成', error: '失败',
  }[s] || s;
}
