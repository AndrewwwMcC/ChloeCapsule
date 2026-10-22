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

// The year picker above the heatmap: swap in another year's grid, no reload.
(function () {
  const year = document.getElementById('heat-year');
  const grid = document.getElementById('heat-grid');
  if (!year || !grid) return;
  const inner = document.getElementById('heat-inner');
  const scroll = document.getElementById('heat-scroll');
  const months = document.getElementById('heat-months');
  const title = document.getElementById('heat-title');
  const caption = document.getElementById('heat-caption');
  const chars = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
  const seen = {};

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => chars[c]);

  function square(day) {
    if (!day) return '<i class="sq empty"></i>';
    if (day.future) return '<i class="sq future"></i>';
    const t = esc(day.title);
    if (day.href) {
      return `<a class="sq lvl-${day.level}" href="${esc(day.href)}" title="${t}" aria-label="${t}"></a>`;
    }
    return `<i class="sq lvl-0" title="${t}"></i>`;
  }

  function draw(heat) {
    inner.style.setProperty('--cols', heat.columns);
    grid.innerHTML = heat.weeks.map((week) => week.map(square).join('')).join('');
    months.innerHTML = heat.months
      .map((m) => `<span style="grid-column: ${m.col + 1}">${esc(m.label)}</span>`).join('');
    title.textContent = heat.year + ', day by day';
    caption.textContent = heat.caption;
    scroll.scrollLeft = 0;
  }

  year.addEventListener('change', async () => {
    const want = year.value;
    year.disabled = true;
    try {
      if (!seen[want]) {
        const res = await fetch('/api/heatmap?year=' + encodeURIComponent(want));
        if (!res.ok) { caption.textContent = 'Couldn’t load that year.'; return; }
        seen[want] = await res.json();
      }
      draw(seen[want]);
    } catch (err) {
      caption.textContent = 'Couldn’t load that year.';
    } finally {
      year.disabled = false;
    }
  });
})();
