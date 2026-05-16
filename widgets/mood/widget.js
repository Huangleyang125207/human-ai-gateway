/* mood widget · v0.3 demo
 * 5 档：糟差平好棒，颜色由 ink 到 vermillion 渐变
 * v0.4: parse frontmatter mood field; v0.5: writeback on pick
 */
(function() {
  const root = document.querySelector('.widget-mood');
  if (!root) return;

  const tones = {
    糟:'#2a221a', 差:'#57463a', 平:'#9c8b78', 好:'#b8852b', 棒:'#9f2d20'
  };

  // demo band: 9 days
  const demoSeries = ['平','好','平','棒','好','差','平','好','平'];
  const band = root.querySelector('[data-band]');
  demoSeries.forEach(v => {
    const cell = document.createElement('div');
    cell.className = 'cell';
    cell.style.background = tones[v];
    cell.textContent = v;
    band.appendChild(cell);
  });

  // picker
  root.querySelectorAll('.opt').forEach(opt => {
    opt.addEventListener('click', () => {
      root.querySelectorAll('.opt').forEach(o => o.classList.remove('picked'));
      opt.classList.add('picked');
      window.gatewayToast('✓ 今日心情记 "' + opt.dataset.val + '"');
    });
  });
})();
