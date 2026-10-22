// Full-screen photo viewer: click a tile, arrows/swipe to move, Esc to close.
(function () {
  const viewer = document.getElementById('viewer');
  if (!viewer) return;
  const img = document.getElementById('v-img');
  const when = document.getElementById('v-when');
  const dl = document.getElementById('v-download');
  const del = document.getElementById('v-delete');
  const cover = document.getElementById('v-cover');
  const stage = document.getElementById('v-stage');
  let tiles = Array.from(document.querySelectorAll('.tile'));
  let current = -1;       // -1 when showing a photo that isn't a tile on this page
  let shown = null;       // what the viewer has up right now
  let lastFocus = null;

  function preload(i) {
    const t = tiles[i];
    if (t) { const p = new Image(); p.src = t.dataset.full; }
  }

  function paint(item) {
    shown = item;
    img.src = item.full;
    when.textContent = '';
    when.append(item.date || '');
    if (item.age) {
      const s = document.createElement('span');
      s.textContent = item.age;
      when.append(s);
    }
    dl.href = '/media/' + item.id + '/download';
    if (cover) cover.href = '/covers/new?photo=' + item.id;
  }

  function show(i) {
    if (!tiles.length) return close();
    current = (i + tiles.length) % tiles.length;
    const t = tiles[current];
    paint({ id: t.dataset.id, full: t.dataset.full, date: t.dataset.date, age: t.dataset.age });
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

  // Home's "Surprise me" hands us a photo that isn't one of the tiles on the page.
  window.capsule = {
    openItem(item) {
      lastFocus = document.activeElement;
      viewer.classList.add('open');
      document.body.style.overflow = 'hidden';
      current = -1;
      paint(item);
      document.getElementById('v-close').focus();
    },
  };

  function close() {
    viewer.classList.remove('open');
    document.body.style.overflow = '';
    img.removeAttribute('src');
    if (lastFocus) lastFocus.focus();
  }

  document.addEventListener('click', (e) => {
    const t = e.target.closest('.tile');
    if (!t || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    open(tiles.indexOf(t));
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
      if (!shown || !confirm('Delete this photo for everyone? This can’t be undone.')) return;
      const res = await fetch('/api/media/' + shown.id, { method: 'DELETE' });
      if (!res.ok) { alert('Couldn’t delete it. Try again.'); return; }
      const t = tiles[current];
      if (t && t.dataset.id === shown.id) {
        t.remove();
        tiles = Array.from(document.querySelectorAll('.tile'));
      }
      if (current < 0 || !tiles.length) { close(); location.reload(); return; }
      show(current >= tiles.length ? 0 : current);
    });
  }
})();
