const params = new URLSearchParams(location.search);
document.getElementById('version').textContent = `v${params.get('version') || '1.0.0'}`;
if (params.get('state') === 'error') {
  document.getElementById('heading').textContent = 'Stüdyo açılamadı';
  document.getElementById('message').textContent = params.get('message') || 'Uygulamayı yeniden başlatmayı deneyin.';
  document.getElementById('spinner').hidden = true;
  document.getElementById('actions').hidden = false;
}
document.getElementById('retry').addEventListener('click', () => window.dikeyDesktop.retry());
document.getElementById('logs').addEventListener('click', () => window.dikeyDesktop.openLogs());
