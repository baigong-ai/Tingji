// 听记 · Header 局域网地址（首页和详情页通用）

const ACCESS_HTML = `
  <span class="access-label">局域网访问地址</span>
  <button class="access-chip" type="button" title="复制到剪贴板">
    <span class="access-url"></span>
    <svg class="copy-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2"/>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
    </svg>
  </button>
`;

async function loadAccessInfo() {
  const slot = document.getElementById('access-info-slot');
  if (!slot) return;
  slot.innerHTML = ACCESS_HTML;
  const chip = slot.querySelector('.access-chip');
  const urlEl = slot.querySelector('.access-url');
  try {
    const r = await fetch('/api/info');
    if (!r.ok) { slot.classList.add('hidden'); return; }
    const info = await r.json();
    const lanUrls = (info.urls || []).filter(u =>
      !u.includes('127.0.0.1') && !u.includes('localhost'));
    if (!lanUrls.length) { slot.classList.add('hidden'); return; }
    const primary = lanUrls[0];
    urlEl.textContent = primary;
    chip.dataset.url = primary;
    slot.classList.remove('hidden');
    chip.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(chip.dataset.url);
        chip.classList.add('copied');
        setTimeout(() => chip.classList.remove('copied'), 1500);
      } catch { /* 复制失败静默 */ }
    });
  } catch {
    slot.classList.add('hidden');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadAccessInfo);
} else {
  loadAccessInfo();
}