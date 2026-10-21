// Full-screen cover viewer: click a card, arrows/swipe to move, Esc to close.
(function () {
  const viewer = document.getElementById('viewer');
  if (!viewer) return;
  const img = document.getElementById('v-img');
  const when = document.getElementById('v-when');
  const dl = document.getElementById('v-download');
  const edit = document.getElementById('v-edit');
  const del = document.getElementById('v-delete');
  const stage = document.getElementById('v-stage');
  let cards = Array.from(document.querySelectorAll('.cover-card'));
  let current = -1;
  let lastFocus = null;

  function preload(i) {
    const c = cards[i];
    if (c) { const p = new Image(); p.src = c.dataset.full; }
  }

  function show(i) {
    if (!cards.length) return close();
    current = (i + cards.length) % cards.length;
    const c = cards[current];
    img.src = c.dataset.full;
    when.textContent = '';
    when.append(c.dataset.issue || c.dataset.date);
    if (c.dataset.issue && c.dataset.date) {
      const s = document.createElement('span');
      s.textContent = c.dataset.date;
      when.append(s);
    }
    dl.href = '/covers/' + c.dataset.id + '/download';
    if (edit) edit.href = '/covers/new?cover=' + c.dataset.id;
    preload(current + 1);
    preload(current - 1);
  }

  function open(i) {
    lastFocus = document.activeElement;
    viewer.classList.add('open');
    document.body.style.overflow = 'hidden';
    show(i);
    document.getElementById('v-close').focus();
  }

  function close() {
    viewer.classList.remove('open');
    document.body.style.overflow = '';
    img.removeAttribute('src');
    if (lastFocus) lastFocus.focus();
  }

  document.addEventListener('click', (e) => {
    const c = e.target.closest('.cover-card');
    if (!c || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    open(cards.indexOf(c));
  });

  document.getElementById('v-close').addEventListener('click', close);
  document.getElementById('v-prev').addEventListener('click', () => show(current - 1));
  document.getElementById('v-next').addEventListener('click', () => show(current + 1));
  stage.addEventListener('click', (e) => { if (e.target === stage) close(); });

  document.addEventListener('keydown', (e) => {
    if (!viewer.classList.contains('open')) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') show(current - 1);
    else if (e.key === 'ArrowRight') show(current + 1);
  });

  let startX = null, startY = null;
  stage.addEventListener('touchstart', (e) => {
    startX = e.touches[0].clientX; startY = e.touches[0].clientY;
  }, { passive: true });
  stage.addEventListener('touchend', (e) => {
    if (startX === null) return;
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) show(current + (dx < 0 ? 1 : -1));
    else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) close();
    startX = null;
  });

  if (del) {
    del.addEventListener('click', async () => {
      const c = cards[current];
      if (!c || !confirm('Delete this cover for everyone? This can’t be undone.')) return;
      const res = await fetch('/api/covers/' + c.dataset.id, { method: 'DELETE' });
      if (!res.ok) { alert('Couldn’t delete it. Try again.'); return; }
      c.remove();
      cards = Array.from(document.querySelectorAll('.cover-card'));
      if (!cards.length) { close(); location.reload(); return; }
      show(current >= cards.length ? 0 : current);
    });
  }
})();
