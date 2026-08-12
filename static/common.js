// 听记 · 前端公共工具函数（无构建步骤，直接挂全局，各页面在对应 JS 前引入）

// S2: 可选 LAN 访问令牌。首次以 ?token=xxx 打开时存入 localStorage 并清掉 URL 上的
// token；之后所有 fetch 自动带 X-Tingji-Token 头（服务端开 lan_token 时校验，本机免登录）。
(function () {
  try {
    const p = new URLSearchParams(location.search);
    const t = p.get('token');
    if (t) {
      localStorage.setItem('tingji_lan_token', t);
      p.delete('token');
      const qs = p.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
    }
  } catch (e) { /* localStorage 不可用时忽略 */ }
  const tok = (() => { try { return localStorage.getItem('tingji_lan_token'); } catch (e) { return null; } })();
  if (tok) {
    const _fetch = window.fetch;
    window.fetch = function (input, init) {
      init = init || {};
      const headers = new Headers(init.headers || {});
      if (!headers.has('X-Tingji-Token')) headers.set('X-Tingji-Token', tok);
      init.headers = headers;
      return _fetch.call(this, input, init);
    };
    window.__tingjiLanToken = tok;  // 供 live.js 给 WS URL 拼令牌
  }
})();

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

// === U3/U4：统一的模态焦点管理 + 消息对话框（替代原生 alert/confirm/prompt） ===
// 各页在底部放一个 #msg-modal（见 index.html / meeting.html）；common.js 统一管焦点。
let _modalLastFocus = null;

function _modalFocusables(el) {
  return Array.from(el.querySelectorAll(
    'input:not([disabled]),textarea:not([disabled]),select:not([disabled]),button:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])'
  )).filter(e => e.offsetParent !== null);
}

function openModal(el, opts) {
  opts = opts || {};
  _modalLastFocus = document.activeElement;
  el.classList.remove('hidden');
  el.setAttribute('aria-hidden', 'false');
  const trap = (e) => {
    if (e.key !== 'Tab') return;
    const f = _modalFocusables(el);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  el._modalTrap = trap;
  el.addEventListener('keydown', trap);
  setTimeout(() => {
    const t = opts.focus ? el.querySelector(opts.focus) : null;
    (t || _modalFocusables(el)[0] || el).focus && (t || _modalFocusables(el)[0] || el).focus();
  }, 0);
}

function closeModal(el) {
  el.classList.add('hidden');
  el.setAttribute('aria-hidden', 'true');
  if (el._modalTrap) { el.removeEventListener('keydown', el._modalTrap); el._modalTrap = null; }
  if (_modalLastFocus && _modalLastFocus.focus) {
    try { _modalLastFocus.focus(); } catch (e) { /* 旧焦点可能已不在 DOM */ }
  }
}

function _msgEl() { return document.getElementById('msg-modal'); }

// 用法：await alertDialog('消息'); / const ok = await confirmDialog('确定？');
// / const v = await promptDialog('起名', '默认值');（取消返回 null）
function alertDialog(message, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const m = _msgEl();
    if (!m) { window.alert(message); return resolve(true); }
    document.getElementById('msg-title').textContent = opts.title || '提示';
    document.getElementById('msg-body').innerHTML = `<p>${escapeHtml(message)}</p>`;
    const actions = document.getElementById('msg-actions');
    actions.innerHTML = `<button class="primary" type="button" id="msg-ok">${escapeHtml(opts.okText || '好的')}</button>`;
    openModal(m, { focus: '#msg-ok' });
    const done = () => { actions.innerHTML = ''; closeModal(m); resolve(true); };
    document.getElementById('msg-ok').onclick = done;
    m.onclick = (e) => { if (e.target === m) done(); };
  });
}

function confirmDialog(message, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const m = _msgEl();
    if (!m) { return resolve(window.confirm(message)); }
    document.getElementById('msg-title').textContent = opts.title || '请确认';
    document.getElementById('msg-body').innerHTML = `<p>${escapeHtml(message)}</p>`;
    const actions = document.getElementById('msg-actions');
    actions.innerHTML = `<button type="button" id="msg-cancel">${escapeHtml(opts.cancelText || '取消')}</button><button class="primary" type="button" id="msg-ok">${escapeHtml(opts.okText || '确定')}</button>`;
    openModal(m, { focus: '#msg-ok' });
    let settled = false;
    const done = (val) => { if (settled) return; settled = true; actions.innerHTML = ''; closeModal(m); resolve(val); };
    document.getElementById('msg-ok').onclick = () => done(true);
    document.getElementById('msg-cancel').onclick = () => done(false);
    m.onclick = (e) => { if (e.target === m) done(false); };
  });
}

function promptDialog(message, defaultValue, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const m = _msgEl();
    if (!m) { return resolve(window.prompt(message, defaultValue || '')); }
    document.getElementById('msg-title').textContent = opts.title || '请输入';
    document.getElementById('msg-body').innerHTML = `<p>${escapeHtml(message)}</p><input id="msg-input" type="text" maxlength="120" style="width:100%;box-sizing:border-box;margin-top:8px">`;
    const actions = document.getElementById('msg-actions');
    actions.innerHTML = `<button type="button" id="msg-cancel">取消</button><button class="primary" type="button" id="msg-ok">${escapeHtml(opts.okText || '确定')}</button>`;
    const input = document.getElementById('msg-input');
    input.value = defaultValue || '';
    openModal(m, { focus: '#msg-input' });
    let settled = false;
    const done = (val) => { if (settled) return; settled = true; actions.innerHTML = ''; closeModal(m); resolve(val); };
    document.getElementById('msg-ok').onclick = () => done(input.value);
    document.getElementById('msg-cancel').onclick = () => done(null);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); done(input.value); }
      else if (e.key === 'Escape') { e.preventDefault(); done(null); }
    });
  });
}
