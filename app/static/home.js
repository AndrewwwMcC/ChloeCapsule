// "Surprise me": choose a slice of the album, then open one random photo from it
// in the same full-screen viewer the grids use.
(function () {
  const scope = document.getElementById('sc-scope');
  const go = document.getElementById('sc-go');
  const msg = document.getElementById('sc-msg');
  if (!scope || !go) return;
  const values = Array.from(document.querySelectorAll('.sc-value'));

  function currentValue() {
    return values.find((s) => s.dataset.scope === scope.value) || null;
  }

  function sync() {
    const pick = currentValue();
    values.forEach((s) => { s.hidden = s !== pick; });
  }

  scope.addEventListener('change', () => { msg.textContent = ''; sync(); });
  sync();

  go.addEventListener('click', async () => {
    const pick = currentValue();
    const query = new URLSearchParams({ scope: scope.value });
    if (pick) query.set('value', pick.value);
    go.disabled = true;
    msg.textContent = 'Looking…';
    try {
      const res = await fetch('/api/random?' + query.toString());
      if (!res.ok) { msg.textContent = 'Nothing matches that one.'; return; }
      const photo = await res.json();
      msg.textContent = [photo.date, photo.where].filter(Boolean).join(' · ');
      window.capsule.openItem(photo);
    } catch (err) {
      msg.textContent = 'Couldn’t reach the album. Try again.';
    } finally {
      go.disabled = false;
    }
  });
})();
