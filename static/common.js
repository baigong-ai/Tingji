// 听记 · 前端公共工具函数（无构建步骤，直接挂全局，各页面在对应 JS 前引入）

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// marked.parse 输出的 XSS 加固。约定：所有 marked.parse 的输入都先 escapeHtml，
// 这会消灭一切原始 <tag>，所以 marked 只能产出它自己那几种标签（a/em/code/…），
// 不可能注入 <script> 或 on* 事件属性。唯一残留的攻击面是 markdown 链接/图片
// URL 里的危险协议，如 `[x](javascript:alert(1))` → `<a href="javascript:…">`。
// 这里在 marked 输出后用 DOMParser（text/html 不执行脚本/不加载图片）把
// href/src 里的 javascript:/vbscript:/data: 协议删掉。控制字符（浏览器解析
// URL 前会剥掉 \t\r\n）也一并剥除后再判定，避免 `java\tscript:` 绕过。
function sanitizeMdHtml(html) {
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('a[href], img[src]').forEach(el => {
      const attr = el.tagName === 'A' ? 'href' : 'src';
      if (!el.hasAttribute(attr)) return;
      const v = el.getAttribute(attr).replace(/[\t\r\n]/g, '').trim();
      if (/^(javascript|vbscript|data):/i.test(v)) el.removeAttribute(attr);
    });
    return doc.body.innerHTML;
  } catch (e) {
    return html;
  }
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
