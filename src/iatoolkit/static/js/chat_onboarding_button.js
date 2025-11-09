(function (global) {
  function qs(root, sel) { return (typeof sel === 'string') ? root.querySelector(sel) : sel; }

  function createDots(container, count, activeIdx, activeColor) {
    container.innerHTML = '';
    for (let i = 0; i < count; i++) {
      const d = document.createElement('div');
      if (i === activeIdx) d.classList.add('active');
      d.style.width = '10px';
      d.style.height = '10px';
      d.style.borderRadius = '50%';
      d.style.backgroundColor = i === activeIdx ? (activeColor || 'var(--brand-primary-color, #FF5100)') : '#ddd';
      d.style.transition = 'background-color .3s';
      container.appendChild(d);
    }
  }

  function initOnboarding(opts) {
    const {
      mode = 'modal',
      cards = [],
      ui = {},
      autoRotateMs = 5000,
      shell = {}
    } = opts;

    const root = document;
    const elIcon = qs(root, ui.icon);
    const elTitle = qs(root, ui.title);
    const elText = qs(root, ui.text);
    const elExample = qs(root, ui.example);
    const elDots = qs(root, ui.dots);
    const elPrev = qs(root, ui.prev);
    const elNext = qs(root, ui.next);

    let idx = 0;
    let autoTimer = null;

    function hasCards() { return Array.isArray(cards) && cards.length > 0; }

    function render() {
      if (!hasCards()) return;
      const c = cards[idx] || {};
      if (elIcon) elIcon.innerHTML = `<i class="${c.icon || 'bi bi-lightbulb'}"></i>`;
      if (elTitle) elTitle.textContent = c.title || '';
      if (elText) elText.innerHTML = c.text || '';
      if (c.example) {
          elExample.innerHTML = ('Ejemplo: ' + c.example) || '';
      }
      if (elDots) createDots(elDots, cards.length, idx);
    }

    function next() { if (!hasCards()) return; idx = (idx + 1) % cards.length; render(); }
    function prev() { if (!hasCards()) return; idx = (idx - 1 + cards.length) % cards.length; render(); }

    function startAuto() {
      stopAuto();
      if (!hasCards()) return;
      autoTimer = setInterval(next, autoRotateMs);
    }
    function stopAuto() { if (autoTimer) { clearInterval(autoTimer); autoTimer = null; } }

    function setupShellIfNeeded() {
      if (mode !== 'shell') return;
      const loader = ui.loader ? qs(root, ui.loader) : null;
      const container = ui.container ? qs(root, ui.container) : null;
      if (!container || !shell.iframeSrc) return;

      const iframe = document.createElement('iframe');
      iframe.src = shell.iframeSrc;
      iframe.style.width = '100%';
      iframe.style.height = '100%';
      iframe.style.border = 'none';
      iframe.style.display = 'none';

      iframe.onload = function () {
        iframe.style.display = 'block';
        if (loader) {
          loader.style.opacity = '0';
          setTimeout(() => loader.style.display = 'none', 500);
        }
      };
      container.appendChild(iframe);
    }

    if (elPrev) elPrev.addEventListener('click', () => { prev(); startAuto(); });
    if (elNext) elNext.addEventListener('click', () => { next(); startAuto(); });

    function start() {
      idx = 0;
      render();
      startAuto();
      if (mode === 'shell') setupShellIfNeeded();
    }

    return { start, stop: stopAuto, next, prev, hasCards };
  }

  // Export global
  global.initOnboarding = initOnboarding;
})(window);