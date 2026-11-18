/* mood widget · GUI and AI share /api/mood as one dated state source. */
(function() {
  const root = document.querySelector('.widget-mood');
  if (!root) return;
  const tones = { 糟:'#2a221a', 差:'#57463a', 平:'#9c8b78', 好:'#b8852b', 棒:'#9f2d20' };
  const band = root.querySelector('[data-band]');

  function select(value) {
    root.querySelectorAll('.opt').forEach((opt) => opt.classList.toggle('picked', opt.dataset.val === value));
  }
  function render(data) {
    select(data.value);
    band.replaceChildren();
    (data.series || []).forEach((item) => {
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.style.background = tones[item.value] || 'var(--rule)';
      cell.textContent = item.value || '·';
      cell.title = item.date;
      band.appendChild(cell);
    });
  }
  fetch('/api/mood?days=9').then((res) => res.json()).then(render).catch(() => {});
  root.querySelectorAll('.opt').forEach((opt) => {
    opt.addEventListener('click', async () => {
      const value = opt.dataset.val;
      const response = await fetch('/api/mood', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ value }),
      });
      const result = await response.json();
      if (!result.ok) return window.gatewayToast(result.error || '心情保存失败');
      select(value);
      window.gatewayToast('✓ 今日心情记 "' + value + '"');
      fetch('/api/mood?days=9').then((res) => res.json()).then(render).catch(() => {});
    });
  });
})();
