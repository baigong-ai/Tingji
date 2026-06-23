// 听记 · 主题切换（A 学者札记 / B 录音棚 / C 中文打字机）

const THEMES = [
  { id: '',         short: 'A', name: '学者札记' },
  { id: 'studio',   short: 'B', name: '录音棚' },
  { id: 'typewriter', short: 'C', name: '中文打字机' },
];

function applyTheme(id) {
  if (id) document.documentElement.setAttribute('data-theme', id);
  else document.documentElement.removeAttribute('data-theme');
  const t = THEMES.find(t => t.id === id) || THEMES[0];
  const nameEl = document.getElementById('theme-name');
  if (nameEl) {
    nameEl.textContent = t.short;
    nameEl.title = `当前：${t.name}（点击切换）`;
  }
  try { localStorage.setItem('tingji-theme', id || ''); } catch {}
}

function cycleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || '';
  const idx = THEMES.findIndex(t => t.id === cur);
  const next = THEMES[(idx + 1) % THEMES.length];
  applyTheme(next.id);
}

(function init() {
  let saved = '';
  try { saved = localStorage.getItem('tingji-theme') || ''; } catch {}
  if (THEMES.some(t => t.id === saved)) applyTheme(saved);
  else applyTheme('');

  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('theme-btn');
    if (btn) btn.addEventListener('click', cycleTheme);
    const cur = document.documentElement.getAttribute('data-theme') || '';
    const t = THEMES.find(t => t.id === cur) || THEMES[0];
    const nameEl = document.getElementById('theme-name');
    if (nameEl) {
      nameEl.textContent = t.short;
      nameEl.title = `当前：${t.name}（点击切换）`;
    }
  });
})();