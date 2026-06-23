// 听记 · 字体切换（衬线 ⇄ 无衬线）

const FONTS = [
  { id: '',     short: '衬', name: '衬线（学者札记）' },
  { id: 'sans', short: '无', name: '无衬线（PingFang 系）' },
];

function applyFont(id) {
  if (id) document.documentElement.setAttribute('data-font', id);
  else document.documentElement.removeAttribute('data-font');
  const f = FONTS.find(f => f.id === id) || FONTS[0];
  const el = document.getElementById('font-name');
  if (el) {
    el.textContent = f.short;
    el.title = `当前字体：${f.name}（点击切换）`;
  }
  try { localStorage.setItem('tingji-font', id || ''); } catch {}
}

function cycleFont() {
  const cur = document.documentElement.getAttribute('data-font') || '';
  const idx = FONTS.findIndex(f => f.id === cur);
  const next = FONTS[(idx + 1) % FONTS.length];
  applyFont(next.id);
}

(function init() {
  let saved = '';
  try { saved = localStorage.getItem('tingji-font') || ''; } catch {}
  if (FONTS.some(f => f.id === saved)) applyFont(saved);
  else applyFont('');
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('font-btn');
    if (btn) btn.addEventListener('click', cycleFont);
    const cur = document.documentElement.getAttribute('data-font') || '';
    const f = FONTS.find(f => f.id === cur) || FONTS[0];
    const el = document.getElementById('font-name');
    if (el) {
      el.textContent = f.short;
      el.title = `当前字体：${f.name}（点击切换）`;
    }
  });
})();