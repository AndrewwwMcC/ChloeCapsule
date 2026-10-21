// Video player overlay.
(function () {
  const viewer = document.getElementById('viewer');
  if (!viewer) return;
  const video = document.getElementById('v-video');
  const when = document.getElementById('v-when');
  const dl = document.getElementById('v-download');
  const del = document.getElementById('v-delete');
  const poster = document.getElementById('v-poster');
  const stage = document.getElementById('v-stage');
  let currentBtn = null;

  function open(btn) {
    currentBtn = btn;
    when.textContent = '';
    when.append(btn.dataset.date);
    if (btn.dataset.age) {
      const s = document.createElement('span');
      s.textContent = btn.dataset.age;
      when.append(s);
    }
    dl.href = '/media/' + btn.dataset.id + '/download';
    video.poster = btn.dataset.poster || '';
    video.src = btn.dataset.src;
    viewer.classList.add('open');
    document.body.style.overflow = 'hidden';
    video.play().catch(() => {});
    document.getElementById('v-close').focus();
  }

  function close() {
    video.pause();
    video.removeAttribute('src');
    video.load();
    viewer.classList.remove('open');
    document.body.style.overflow = '';
    if (currentBtn) currentBtn.focus();
  }

  video.addEventListener('error', () => {
    when.textContent = 'This browser can’t play this video — use download instead.';
  });

  document.addEventListener('click', (e) => {
    const b = e.target.closest('.clip');
    if (b) open(b);
  });
  document.getElementById('v-close').addEventListener('click', close);
  stage.addEventListener('click', (e) => { if (e.target === stage) close(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && viewer.classList.contains('open')) close();
  });

  if (poster) {
    poster.addEventListener('click', async () => {
      if (!currentBtn) return;
      poster.disabled = true;
      try {
        const res = await fetch('/api/media/' + currentBtn.dataset.id + '/poster', { method: 'POST' });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          alert(body.detail || 'Couldn’t make a poster for this one.');
          return;
        }
        location.reload();
      } catch (_) {
        alert('Couldn’t make a poster for this one.');
      } finally {
        poster.disabled = false;
      }
    });
  }

  if (del) {
    del.addEventListener('click', async () => {
      if (!currentBtn || !confirm('Delete this video for everyone? This can’t be undone.')) return;
      const res = await fetch('/api/media/' + currentBtn.dataset.id, { method: 'DELETE' });
      if (!res.ok) { alert('Couldn’t delete it. Try again.'); return; }
      close();
      location.reload();
    });
  }
})();
