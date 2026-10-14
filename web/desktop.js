// Electrobun's sandbox exposes only this event channel. Ordinary browsers keep
// their standard navigation and clipboard behavior.
if (typeof window.__electrobunSendToHost === 'function') {
  window.bioartDesktop = {
    reveal(path) { window.__electrobunSendToHost({action: 'reveal', path}); }
  };
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin && ['https:', 'http:'].includes(url.protocol)) {
      event.preventDefault();
      window.__electrobunSendToHost({action: 'external', url: url.href});
    }
  });
}
