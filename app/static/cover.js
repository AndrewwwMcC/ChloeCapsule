// Cover maker: draws a 1600x2080 magazine cover on a canvas from one album photo
// plus text, and posts the JPEG to /api/covers. Everything the editor needs to
// rebuild a cover later goes into the settings JSON.
(function () {
  const cv = document.getElementById('cv');
  if (!cv) return;
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  const M = 108;                 // page margin
  const INNER = W - M * 2;
  const boot = JSON.parse(document.getElementById('cover-boot').textContent);

  // Google Fonts we offer for the masthead. `italic: false` means the family has no
  // real italic — we leave it upright rather than let the browser fake a slant.
  const FONTS = [
    { name: 'Bodoni Moda',      italic: true,  weights: [400, 700, 900] },
    { name: 'Libre Bodoni',     italic: true,  weights: [700] },
    { name: 'Playfair Display', italic: true,  weights: [400, 700, 900] },
    { name: 'Abril Fatface',    italic: false, weights: [400] },
    { name: 'DM Serif Display', italic: true,  weights: [400] },
    { name: 'Gloock',           italic: false, weights: [400] },
  ];

  const COLOURS = ['#FFFFFF', '#1A1A18', '#B3261E', '#F2D27A'];
  const LAYOUTS = ['classic', 'side', 'minimal'];

  const el = (id) => document.getElementById(id);
  const st = {
    photo: boot.photo || null,
    layout: 'classic',
    masthead: boot.siteName || 'Chloé',
    font: 'Bodoni Moda',
    weight: 900,
    textFont: null,              // null = same family as the masthead
    headline: '', line1: '', line2: '', issue: '',
    colour: '#FFFFFF',
    scrim: true,
    zoom: 1, offsetX: 0, offsetY: 0,
  };

  let img = null;              // the loaded photo
  let photoWhen = '';          // "July 2026", for the default issue line
  let issueDirty = false;      // once you edit the issue line we stop rewriting it
  let placed = { dw: 0, dh: 0 };

  // --- typefaces -------------------------------------------------------------------

  const fontOf = (name) => FONTS.find((f) => f.name === name) || FONTS[0];
  const nearest = (list, want) =>
    list.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a));

  function face(name, weight, wantItalic) {
    const f = fontOf(name);
    return {
      family: f.name,
      weight: nearest(f.weights, weight),
      italic: !!(wantItalic && f.italic),
      at(size) {
        return `${this.italic ? 'italic ' : ''}${this.weight} ${size}px "${this.family}", Georgia, serif`;
      },
      spec(size) {
        return `${this.italic ? 'italic ' : ''}${this.weight} ${size}px "${this.family}"`;
      },
    };
  }

  const textFamily = () => st.textFont || st.font;
  const small = (weight) => face(textFamily(), weight, false);

  const ready = new Set();

  function neededFaces() {
    const t = textFamily();
    return [face(st.font, st.weight, st.layout === 'minimal'), face(st.font, st.weight, false),
            face(t, 400, false), face(t, 400, true), face(t, 700, false)];
  }

  async function ensureFonts() {
    // accents are in the sample so the right glyphs are fetched before we draw
    const sample = [st.masthead, st.headline, st.line1, st.line2, st.issue].join(' ')
      .toUpperCase() + ' ÉÀÇÖ';
    const specs = neededFaces().map((f) => f.spec(100)).filter((s) => !ready.has(s + sample));
    if (!specs.length) return;
    await Promise.all(specs.map(async (s) => {
      try { await document.fonts.load(s, sample); } catch (_) { /* fall back to serif */ }
      ready.add(s + sample);
    }));
  }

  // --- text helpers ----------------------------------------------------------------

  function inkWidth(text, f, size) {
    ctx.font = f.at(size);
    const m = ctx.measureText(text);
    return Math.max(m.width, (m.actualBoundingBoxLeft || 0) + (m.actualBoundingBoxRight || 0));
  }

  /** Largest size (capped) at which `text` fits `maxW`. Metrics scale with size,
   *  so one measurement at a probe size gives the answer. */
  function fitWidth(text, f, maxW, maxSize) {
    const probe = 200;
    const ink = inkWidth(text, f, probe);
    return ink ? Math.min(maxSize, (maxW / ink) * probe) : maxSize;
  }

  /** Draw a line with its *ink top* at topY, so accents like É are never clipped.
   *  Returns the ink height. */
  function drawTop(text, f, size, x, topY, align) {
    ctx.font = f.at(size);
    ctx.textAlign = align;
    ctx.textBaseline = 'alphabetic';
    const m = ctx.measureText(text);
    ctx.fillText(text, x, topY + m.actualBoundingBoxAscent);
    return m.actualBoundingBoxAscent + m.actualBoundingBoxDescent;
  }

  /** Letter-spaced small caps. Drawn glyph by glyph so it looks identical in every
   *  browser — ctx.letterSpacing is too new to rely on. */
  function drawTracked(text, f, size, x, topY, track, align) {
    ctx.font = f.at(size);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    const chars = Array.from(text);
    let total = -track;
    for (const ch of chars) total += ctx.measureText(ch).width + track;
    total = Math.max(0, total);
    const m = ctx.measureText(text);
    let cx = align === 'right' ? x - total : align === 'center' ? x - total / 2 : x;
    const y = topY + (m.actualBoundingBoxAscent || size * 0.72);
    for (const ch of chars) {
      ctx.fillText(ch, cx, y);
      cx += ctx.measureText(ch).width + track;
    }
    return { width: total, height: (m.actualBoundingBoxAscent || size) + (m.actualBoundingBoxDescent || 0) };
  }

  function wrap(text, f, size, maxW) {
    ctx.font = f.at(size);
    const lines = [];
    let line = '';
    for (const word of text.split(/\s+/).filter(Boolean)) {
      const test = line ? line + ' ' + word : word;
      if (line && ctx.measureText(test).width > maxW) { lines.push(line); line = word; }
      else line = test;
    }
    if (line) lines.push(line);
    return lines;
  }

  function fitWrapped(text, f, maxW, startSize, maxLines, minSize) {
    let size = startSize;
    let lines = wrap(text, f, size, maxW);
    while (size > minSize && lines.length > maxLines) {
      size -= 4;
      lines = wrap(text, f, size, maxW);
    }
    return { size, lines };
  }

  function drawLinesBottom(lines, f, size, x, bottomY, lh, align) {
    ctx.font = f.at(size);
    ctx.textAlign = align;
    ctx.textBaseline = 'alphabetic';
    const last = ctx.measureText(lines[lines.length - 1]);
    let base = bottomY - (last.actualBoundingBoxDescent || 0);
    for (let i = lines.length - 1; i >= 0; i--) {
      ctx.fillText(lines[i], x, base);
      base -= lh;
    }
  }

  function rule(x1, x2, y) {
    ctx.save();
    ctx.strokeStyle = st.colour;
    ctx.globalAlpha = 0.85;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
    ctx.restore();
  }

  // --- the three layouts -----------------------------------------------------------

  function layoutClassic() {
    const mast = st.masthead.toUpperCase();
    const mf = face(st.font, st.weight, false);
    const top = 132;
    const inkH = mast ? drawTop(mast, mf, fitWidth(mast, mf, INNER, 420), W / 2, top, 'center') : 0;

    let y = top + inkH + 38;
    if (st.issue) {
      drawTracked(st.issue.toUpperCase(), small(500), 30, W - M, y, 5.5, 'right');
      y += 46;
    }

    let cy = Math.max(y + 56, H * 0.40);
    for (const line of [st.line1, st.line2].filter(Boolean)) {
      const r = drawTracked(line.toUpperCase(), small(500), 36, M, cy, 4.5, 'left');
      cy += r.height + 30;
    }

    if (st.headline) {
      const hf = face(textFamily(), 400, true);
      const { size, lines } = fitWrapped(st.headline, hf, INNER * 0.88, 126, 3, 50);
      drawLinesBottom(lines, hf, size, M, H - M, size * 1.02, 'left');
    }
  }

  function layoutSide() {
    const mast = st.masthead.toUpperCase();
    const mf = face(st.font, st.weight, false);
    const top = 132;
    const inkH = mast ? drawTop(mast, mf, fitWidth(mast, mf, INNER, 360), M, top, 'left') : 0;

    const lines = [st.line1, st.line2].filter(Boolean);
    let cy = Math.max(top + inkH + 110, H * 0.38);
    lines.forEach((line, i) => {
      const r = drawTracked(line.toUpperCase(), small(500), 34, W - M, cy, 4.5, 'right');
      cy += r.height + 26;
      if (i < lines.length - 1) {
        cy += 8;
        rule(W - M - 190, W - M, cy);
        cy += 34;
      }
    });
    if (st.issue) {
      drawTracked(st.issue.toUpperCase(), small(400), 28, W - M, cy + 14, 5, 'right');
    }

    if (st.headline) {
      const hf = face(textFamily(), 700, false);
      const { size, lines: hl } = fitWrapped(st.headline.toUpperCase(), hf, INNER, 94, 3, 42);
      drawLinesBottom(hl, hf, size, M, H - M, size * 1.12, 'left');
    }
  }

  function layoutMinimal() {
    const mast = st.masthead.toUpperCase();
    if (mast) {
      const mf = face(st.font, st.weight, true);
      const size = fitWidth(mast, mf, INNER * 0.9, 300);
      ctx.font = mf.at(size);
      const m = ctx.measureText(mast);
      const inkH = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent;
      drawTop(mast, mf, size, W / 2, Math.max(M, H * 0.46 - inkH / 2), 'center');
    }
    const tail = st.headline || st.issue;
    if (tail) drawTracked(tail.toUpperCase(), small(400), 38, W / 2, H - M - 48, 10, 'center');
  }

  // --- drawing ---------------------------------------------------------------------

  function drawPhoto() {
    ctx.fillStyle = '#242420';
    ctx.fillRect(0, 0, W, H);
    if (!img) { placed = { dw: 0, dh: 0 }; return; }
    const base = Math.max(W / img.naturalWidth, H / img.naturalHeight) * st.zoom;
    const dw = img.naturalWidth * base, dh = img.naturalHeight * base;
    placed = { dw, dh };
    ctx.drawImage(img, (W - dw) / 2 + st.offsetX * (dw - W),
                  (H - dh) / 2 + st.offsetY * (dh - H), dw, dh);
  }

  function drawScrim() {
    // Minimal has only a masthead and one line, so it needs far less shading.
    const soft = st.layout === 'minimal';
    const topH = H * (soft ? 0.32 : 0.56);
    const top = ctx.createLinearGradient(0, 0, 0, topH);
    if (soft) {
      top.addColorStop(0, 'rgba(0,0,0,0.36)');
    } else {
      // the long tail keeps a light wash behind the cover lines near 40% height
      top.addColorStop(0, 'rgba(0,0,0,0.58)');
      top.addColorStop(0.32, 'rgba(0,0,0,0.28)');
      top.addColorStop(0.78, 'rgba(0,0,0,0.22)');
    }
    top.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = top;
    ctx.fillRect(0, 0, W, topH);

    const botY = H * (soft ? 0.62 : 0.50);
    const bot = ctx.createLinearGradient(0, botY, 0, H);
    bot.addColorStop(0, 'rgba(0,0,0,0)');
    bot.addColorStop(0.45, `rgba(0,0,0,${soft ? 0.14 : 0.18})`);
    bot.addColorStop(1, `rgba(0,0,0,${soft ? 0.56 : 0.66})`);
    ctx.fillStyle = bot;
    ctx.fillRect(0, botY, W, H - botY);
  }

  function draw() {
    drawPhoto();
    if (st.scrim) drawScrim();
    ctx.fillStyle = st.colour;
    if (st.layout === 'side') layoutSide();
    else if (st.layout === 'minimal') layoutMinimal();
    else layoutClassic();
    el('cover-empty').hidden = !!img;
  }

  let seq = 0;
  async function render() {
    const mine = ++seq;
    await ensureFonts();
    if (mine !== seq) return;   // a newer render has taken over
    draw();
  }

  // --- photo -----------------------------------------------------------------------

  function loadPhoto(id) {
    return new Promise((resolve) => {
      const next = new Image();
      next.onload = () => { img = next; resolve(true); };
      next.onerror = () => resolve(false);
      next.src = '/media/' + id + '/image';   // same-origin, so we can read the canvas back
    });
  }

  async function usePhoto(id, when) {
    const ok = await loadPhoto(id);
    if (!ok) {
      note('That photo couldn’t be loaded.');
      return;
    }
    st.photo = id;
    st.zoom = 1; st.offsetX = 0; st.offsetY = 0;
    el('zoom').value = '1';
    if (when) {
      photoWhen = when;
      el('photo-when').textContent = when;
      if (!issueDirty) setIssue();
    }
    render();
  }

  function setIssue() {
    st.issue = `No. ${boot.nextNo} · ${photoWhen}`.trim();
    el('issue').value = st.issue;
  }

  // --- drag to reposition ----------------------------------------------------------

  let drag = null;
  cv.addEventListener('pointerdown', (e) => {
    if (!img) return;
    drag = { x: e.clientX, y: e.clientY, ox: st.offsetX, oy: st.offsetY };
    cv.setPointerCapture(e.pointerId);
    cv.classList.add('dragging');
  });
  cv.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const k = W / cv.clientWidth;              // CSS pixels -> canvas pixels
    const spanX = placed.dw - W, spanY = placed.dh - H;
    if (spanX > 1) st.offsetX = clamp(drag.ox - ((e.clientX - drag.x) * k) / spanX, -0.5, 0.5);
    if (spanY > 1) st.offsetY = clamp(drag.oy - ((e.clientY - drag.y) * k) / spanY, -0.5, 0.5);
    draw();
  });
  const endDrag = () => { drag = null; cv.classList.remove('dragging'); };
  cv.addEventListener('pointerup', endDrag);
  cv.addEventListener('pointercancel', endDrag);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  // --- controls --------------------------------------------------------------------

  function buildFontRow() {
    const row = el('fontrow');
    row.textContent = '';
    for (const f of FONTS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'fontsw';
      b.setAttribute('role', 'radio');
      b.dataset.font = f.name;
      const sample = document.createElement('span');
      sample.className = 'fontsw-t';
      sample.style.fontFamily = `"${f.name}", Georgia, serif`;
      sample.style.fontWeight = String(f.weights[f.weights.length - 1]);
      if (!f.italic) sample.style.fontStyle = 'normal';
      const name = document.createElement('span');
      name.className = 'fontsw-n';
      name.textContent = f.name;
      b.append(sample, name);
      row.append(b);
    }
    const sel = document.createElement('option');
    sel.value = '';
    sel.textContent = 'Same as masthead';
    el('textfont').append(sel);
    for (const f of FONTS) {
      const o = document.createElement('option');
      o.value = f.name;
      o.textContent = f.name;
      el('textfont').append(o);
    }
  }

  function syncFontRow() {
    const text = st.masthead.toUpperCase() || 'ABC';
    for (const b of el('fontrow').children) {
      b.querySelector('.fontsw-t').textContent = text;
      b.setAttribute('aria-checked', String(b.dataset.font === st.font));
    }
    const f = fontOf(st.font);
    el('weights').hidden = f.weights.length < 2;
    for (const b of el('weights').children) {
      b.hidden = !f.weights.includes(Number(b.dataset.weight));
      b.setAttribute('aria-checked', String(Number(b.dataset.weight) === st.weight));
    }
  }

  function syncSegments() {
    for (const b of el('layouts').children) {
      b.setAttribute('aria-checked', String(b.dataset.layout === st.layout));
    }
    for (const b of el('colours').children) {
      b.setAttribute('aria-checked', String(b.dataset.colour === st.colour));
    }
    el('layout-note').textContent = st.layout === 'minimal'
      ? 'Minimal shows the headline at the bottom, or the issue line when the headline is empty.'
      : '';
  }

  function bindText(id, key) {
    el(id).addEventListener('input', () => {
      st[key] = el(id).value;
      if (key === 'issue') issueDirty = true;
      if (key === 'masthead') syncFontRow();
      render();
    });
  }

  function note(msg) { el('save-note').textContent = msg; }

  // --- settings in and out ---------------------------------------------------------

  function settingsOut() {
    return {
      layout: st.layout, masthead: st.masthead, font: st.font, weight: st.weight,
      textFont: st.textFont, headline: st.headline, line1: st.line1, line2: st.line2,
      issue: st.issue, colour: st.colour, scrim: st.scrim,
      zoom: st.zoom, offsetX: st.offsetX, offsetY: st.offsetY,
    };
  }

  function applySettings(raw) {
    let s = raw;
    if (typeof s === 'string') { try { s = JSON.parse(s); } catch (_) { return; } }
    if (!s || typeof s !== 'object') return;
    if (LAYOUTS.includes(s.layout)) st.layout = s.layout;
    if (typeof s.masthead === 'string') st.masthead = s.masthead;
    if (FONTS.some((f) => f.name === s.font)) st.font = s.font;
    if (Number.isFinite(s.weight)) st.weight = nearest(fontOf(st.font).weights, s.weight);
    else st.weight = fontOf(st.font).weights[fontOf(st.font).weights.length - 1];
    st.textFont = FONTS.some((f) => f.name === s.textFont) ? s.textFont : null;
    for (const k of ['headline', 'line1', 'line2', 'issue']) {
      if (typeof s[k] === 'string') st[k] = s[k];
    }
    if (COLOURS.includes(s.colour)) st.colour = s.colour;
    st.scrim = s.scrim !== false;
    if (Number.isFinite(s.zoom)) st.zoom = clamp(s.zoom, 1, 3);
    if (Number.isFinite(s.offsetX)) st.offsetX = clamp(s.offsetX, -0.5, 0.5);
    if (Number.isFinite(s.offsetY)) st.offsetY = clamp(s.offsetY, -0.5, 0.5);
    issueDirty = true;
  }

  function fillControls() {
    el('masthead').value = st.masthead;
    el('headline').value = st.headline;
    el('line1').value = st.line1;
    el('line2').value = st.line2;
    el('issue').value = st.issue;
    el('textfont').value = st.textFont || '';
    el('scrim').checked = st.scrim;
    el('zoom').value = String(st.zoom);
    syncFontRow();
    syncSegments();
  }

  // --- saving ----------------------------------------------------------------------

  function toBlob(quality) {
    return new Promise((resolve) => cv.toBlob(resolve, 'image/jpeg', quality));
  }

  async function save() {
    if (!st.photo) { note('Pick a photo first.'); return; }
    const btn = el('save');
    btn.disabled = true;
    note('Saving…');
    try {
      await render();
      const blob = await toBlob(0.92);
      if (!blob) throw new Error('render');
      const fd = new FormData();
      fd.append('image', blob, 'cover.jpg');
      fd.append('settings', JSON.stringify(settingsOut()));
      fd.append('media_id', st.photo);
      if (boot.coverId) fd.append('cover_id', boot.coverId);
      const res = await fetch('/api/covers', { method: 'POST', body: fd });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Save failed');
      }
      const data = await res.json();
      location.href = '/covers#c-' + data.id;
    } catch (e) {
      note(String(e.message || e));
      btn.disabled = false;
    }
  }

  async function download() {
    if (!st.photo) { note('Pick a photo first.'); return; }
    await render();
    const blob = await toBlob(0.95);
    if (!blob) { note('Couldn’t make the image.'); return; }
    const slug = (st.masthead || 'cover').toLowerCase().replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'cover';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${slug}-cover.jpg`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // --- picker ----------------------------------------------------------------------

  const picker = el('picker');

  function openPicker() {
    picker.hidden = false;
    document.body.style.overflow = 'hidden';
    el('picker-close').focus();
  }
  function closePicker() {
    picker.hidden = true;
    document.body.style.overflow = '';
  }

  el('pick').addEventListener('click', openPicker);
  el('pick-empty').addEventListener('click', openPicker);
  el('picker-close').addEventListener('click', closePicker);
  picker.addEventListener('click', (e) => { if (e.target === picker) closePicker(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !picker.hidden) closePicker();
  });

  picker.addEventListener('click', (e) => {
    const t = e.target.closest('.picker-tile');
    if (!t) return;
    closePicker();
    note('');
    usePhoto(t.dataset.id, t.dataset.when);
  });

  const yearNav = el('picker-years');
  if (yearNav) {
    yearNav.addEventListener('click', (e) => {
      const a = e.target.closest('.chip');
      if (!a) return;
      e.preventDefault();
      const year = a.dataset.year;
      for (const chip of yearNav.children) {
        if (chip.dataset.year === year) chip.setAttribute('aria-current', 'true');
        else chip.removeAttribute('aria-current');
      }
      for (const tile of picker.querySelectorAll('.picker-tile')) {
        tile.hidden = !!year && tile.dataset.year !== year;
      }
    });
  }

  // --- wiring ----------------------------------------------------------------------

  buildFontRow();

  el('layouts').addEventListener('click', (e) => {
    const b = e.target.closest('.seg-b');
    if (!b) return;
    st.layout = b.dataset.layout;
    syncSegments();
    render();
  });

  el('fontrow').addEventListener('click', (e) => {
    const b = e.target.closest('.fontsw');
    if (!b) return;
    st.font = b.dataset.font;
    st.weight = nearest(fontOf(st.font).weights, st.weight);
    syncFontRow();
    render();
  });

  el('weights').addEventListener('click', (e) => {
    const b = e.target.closest('.seg-b');
    if (!b) return;
    st.weight = Number(b.dataset.weight);
    syncFontRow();
    render();
  });

  el('colours').addEventListener('click', (e) => {
    const b = e.target.closest('.sw');
    if (!b) return;
    st.colour = b.dataset.colour;
    syncSegments();
    render();
  });

  el('textfont').addEventListener('change', () => {
    st.textFont = el('textfont').value || null;
    render();
  });

  el('scrim').addEventListener('change', () => { st.scrim = el('scrim').checked; render(); });
  el('zoom').addEventListener('input', () => {
    st.zoom = Number(el('zoom').value);
    draw();
  });

  bindText('masthead', 'masthead');
  bindText('headline', 'headline');
  bindText('line1', 'line1');
  bindText('line2', 'line2');
  bindText('issue', 'issue');

  el('save').addEventListener('click', save);
  el('download').addEventListener('click', download);

  // --- start -----------------------------------------------------------------------

  (async () => {
    if (boot.settings) applySettings(boot.settings);
    if (!issueDirty) {
      const first = document.querySelector(
        st.photo ? `.picker-tile[data-id="${st.photo}"]` : '.picker-tile');
      photoWhen = (first && first.dataset.when) || '';
      setIssue();
    }
    fillControls();
    if (st.photo) {
      const tile = document.querySelector(`.picker-tile[data-id="${st.photo}"]`);
      if (tile) el('photo-when').textContent = tile.dataset.when;
      const ok = await loadPhoto(st.photo);
      if (!ok) {
        st.photo = null;
        note('The photo this cover was made from is gone — choose another.');
      }
    } else if (boot.coverId) {
      note('The photo this cover was made from is gone — choose another.');
    }
    render();
  })();
})();
