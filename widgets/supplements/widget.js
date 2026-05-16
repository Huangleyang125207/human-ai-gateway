/* supplements widget · interactions
 * v0.3: demo toggle + toast (no md writeback)
 * v0.5 planned: POST to server → patch md
 */
document.querySelectorAll('.widget-supplements .supp input').forEach(cb => {
  cb.addEventListener('change', e => {
    e.target.parentElement.classList.toggle('on', e.target.checked);
    const name = e.target.dataset.name;
    window.gatewayToast(e.target.checked ? '✓ ' + name + ' 已勾' : '— ' + name + ' 取消');
  });
});
