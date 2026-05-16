/* steps widget · v0.3 demo data
 * v0.4 planned: parse MD vivo 步数 ~XXX from latest 9 daily files
 *              → fill .big with today, .avg with mean, .spark with sparkline
 *
 * 当前用硬编码 demo 数据展示 widget API。真 parser 进 v0.4。
 */
(function() {
  const root = document.querySelector('.widget-steps');
  if (!root) return;

  // demo data (replace with real parse in v0.4)
  const series = [3200, 4100, 7800, 5600, 8366, 6900, 7200, 9100, 8800];
  const today = series[series.length - 1];
  const avg = Math.round(series.reduce((a,b)=>a+b,0) / series.length);

  // unicode sparkline
  const max = Math.max(...series), min = Math.min(...series);
  const bars = ['▁','▂','▃','▄','▅','▆','▇','█'];
  const spark = series.map(v => bars[Math.round((v-min)/(max-min)*7)]).join('');

  root.querySelector('[data-field=today]').textContent = today.toLocaleString();
  root.querySelector('[data-field=avg]').textContent = avg.toLocaleString();
  root.querySelector('[data-field=spark]').textContent = spark;
})();
