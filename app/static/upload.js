// Chunked uploads: each file is sent in pieces, two files at a time, with retries.
// When the queue empties, the status line gives way to a summary of where everything went.
(function () {
  const input = document.getElementById('files');
  const drop = document.getElementById('drop');
  const queueEl = document.getElementById('queue');
  const bar = document.getElementById('bar');
  const barWrap = bar.parentElement;
  const statusEl = document.getElementById('status');
  const summaryEl = document.getElementById('summary');
  const sumHead = document.getElementById('sum-head');
  const sumWhere = document.getElementById('sum-where');
  const sumFailed = document.getElementById('sum-failed');
  const sumGo = document.getElementById('sum-go');
  const sumRetry = document.getElementById('sum-retry');
  const sumMore = document.getElementById('sum-more');
  const CHUNK = window.CHUNK_SIZE || 16 * 1024 * 1024;
  const CONCURRENT = 2;
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                  'August', 'September', 'October', 'November', 'December'];

  const jobs = [];
  let running = 0;
  let wakeLock = null;

  const CHECK = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#1A1A18" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  const CAM = '<svg class="vid" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1A1A18" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/></svg>';

  function isVideo(f) { return (f.type || '').startsWith('video/') || /\.(mov|mp4|m4v|3gp|avi|mkv|webm)$/i.test(f.name); }

  function addFiles(list) {
    const files = Array.from(list).filter((f) => f.size > 0);
    if (!files.length) return;
    hideSummary();
    for (const f of files) {
      const el = document.createElement('div');
      el.className = 'q waiting';
      if (!isVideo(f) && /^image\/(jpeg|png|webp|gif)$/.test(f.type)) {
        const im = document.createElement('img');
        im.alt = '';
        im.src = URL.createObjectURL(f);
        im.onload = () => URL.revokeObjectURL(im.src);
        el.append(im);
      }
      if (isVideo(f)) el.insertAdjacentHTML('beforeend', CAM);
      el.insertAdjacentHTML('beforeend', '<div class="prog"><div></div></div>');
      queueEl.append(el);
      jobs.push({ file: f, el, sent: 0, state: 'waiting' });
    }
    render();
    pump();
  }

  function render() {
    const total = jobs.reduce((s, j) => s + j.file.size, 0) || 1;
    const sent = jobs.reduce((s, j) => s + (j.state === 'waiting' ? 0 : j.state === 'active' ? j.sent : j.file.size), 0);
    const pct = Math.round((sent / total) * 100);
    bar.style.width = pct + '%';
    barWrap.setAttribute('aria-valuenow', pct);
    const done = jobs.filter((j) => j.state === 'done').length;
    const dup = jobs.filter((j) => j.state === 'dup').length;
    const failed = jobs.filter((j) => j.state === 'failed').length;
    const videos = jobs.filter((j) => isVideo(j.file)).length;
    if (!jobs.length) { statusEl.textContent = ''; return; }
    let msg = `${done + dup + failed} of ${jobs.length} done`;
    if (videos) msg += ` · ${videos} video${videos === 1 ? '' : 's'}`;
    if (dup) msg += ` · ${dup} already there`;
    if (failed) msg += ` · ${failed} failed`;
    statusEl.textContent = msg;
    if (!running && !jobs.some((j) => j.state === 'waiting')) showSummary();
  }

  // --- where a finished file landed ----------------------------------------------

  function placed(job) {
    const m = /^(\d{4})-(\d{2})/.exec(job.takenAt || '');
    if (!m) return null;
    return { kind: job.kind === 'video' ? 'video' : 'photo', year: +m[1], month: +m[2] };
  }

  function linkTo(p) {
    return p.kind === 'video' ? `/videos?year=${p.year}`
                              : `/photos/${p.year}#${MONTHS[p.month - 1].toLowerCase()}`;
  }

  function whereLabel(p) {
    return `${MONTHS[p.month - 1]} ${p.year}`;
  }

  function goLabel(p) {
    return p.kind === 'video' ? `See the ${whereLabel(p)} videos`
                              : `See ${whereLabel(p)} in the album`;
  }

  function alreadyLabel(p) {
    return `Already in the album — see ${whereLabel(p)}`;
  }

  // --- the summary ----------------------------------------------------------------

  function showSummary() {
    const added = jobs.filter((j) => j.state === 'done');
    const dup = jobs.filter((j) => j.state === 'dup').length;
    const failed = jobs.filter((j) => j.state === 'failed');

    const head = [];
    if (added.length) head.push(`${added.length} added`);
    if (dup) head.push(`${dup} already there`);
    if (failed.length) head.push(`${failed.length} failed`);
    sumHead.textContent = head.join(' · ') || 'Nothing to add';

    // one group per kind and month, photos first, oldest month first
    const groups = new Map();
    for (const job of added) {
      const p = placed(job);
      if (!p) continue;
      const key = `${p.kind}-${p.year}-${p.month}`;
      const g = groups.get(key) || Object.assign({ n: 0 }, p);
      g.n++;
      groups.set(key, g);
    }
    const list = Array.from(groups.values()).sort((a, b) =>
      (a.kind === b.kind ? 0 : a.kind === 'photo' ? -1 : 1) || a.year - b.year || a.month - b.month);

    sumWhere.textContent = '';
    list.forEach((g, i) => {
      if (i) sumWhere.append(' · ');
      const a = document.createElement('a');
      a.href = linkTo(g);
      a.textContent = g.kind === 'video'
        ? `${g.n} video${g.n === 1 ? '' : 's'} in ${whereLabel(g)}`
        : `${g.n} in ${whereLabel(g)}`;
      sumWhere.append(a);
    });
    sumWhere.hidden = !list.length;

    sumFailed.textContent = '';
    for (const job of failed) {
      const li = document.createElement('li');
      li.textContent = job.file.name;
      sumFailed.append(li);
    }
    sumFailed.hidden = !failed.length;
    sumRetry.hidden = !failed.length;

    // the primary button goes where the most new photos landed
    const best = list.filter((g) => g.kind === 'photo').sort((a, b) => b.n - a.n)[0] || list[0];
    sumGo.hidden = !best;
    if (best) sumGo.href = linkTo(best);

    statusEl.hidden = true;
    barWrap.hidden = true;
    summaryEl.hidden = false;
  }

  function hideSummary() {
    summaryEl.hidden = true;
    statusEl.hidden = false;
    barWrap.hidden = false;
  }

  function retryFailed() {
    for (const job of jobs) {
      if (job.state !== 'failed') continue;
      job.state = 'waiting';
      job.sent = 0;
      job.el.classList.remove('failed');
      job.el.classList.add('waiting');
      job.el.insertAdjacentHTML('beforeend', '<div class="prog"><div></div></div>');
    }
    hideSummary();
    render();
    pump();
  }

  async function keepAwake(on) {
    try {
      if (on && !wakeLock && 'wakeLock' in navigator) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; });
      }
      if (!on && wakeLock) { await wakeLock.release(); wakeLock = null; }
    } catch (_) { /* not supported */ }
  }

  function pump() {
    while (running < CONCURRENT) {
      const job = jobs.find((j) => j.state === 'waiting');
      if (!job) break;
      running++;
      keepAwake(true);
      run(job).finally(() => {
        running--;
        render();
        if (!running && !jobs.some((j) => j.state === 'waiting')) keepAwake(false);
        pump();
      });
    }
  }

  function sendPart(id, n, blob, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', `/api/upload/${id}/part/${n}`);
      xhr.upload.onprogress = (e) => onProgress(e.loaded);
      xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(xhr.status)));
      xhr.onerror = () => reject(new Error('network'));
      xhr.send(blob);
    });
  }

  async function withRetry(fn, tries = 4) {
    for (let i = 0; ; i++) {
      try { return await fn(); } catch (e) {
        if (i >= tries - 1) throw e;
        await new Promise((r) => setTimeout(r, 1000 * 2 ** i));
      }
    }
  }

  async function run(job) {
    const { file, el } = job;
    const prog = el.querySelector('.prog div');
    job.state = 'active';
    el.classList.remove('waiting');
    try {
      const init = await withRetry(async () => {
        const r = await fetch('/api/upload/init', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: file.name, size: file.size, type: file.type, lastModified: file.lastModified }),
        });
        if (r.status === 415) return { unsupported: true };
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
      if (init.unsupported) throw new Error('unsupported');
      if (init.duplicate) return finish(job, 'dup', init);

      const size = init.chunk_size || CHUNK;
      const parts = Math.max(1, Math.ceil(file.size / size));
      for (let n = 1; n <= parts; n++) {
        const start = (n - 1) * size;
        const blob = file.slice(start, Math.min(file.size, start + size));
        await withRetry(() => sendPart(init.id, n, blob, (loaded) => {
          job.sent = start + loaded;
          prog.style.width = Math.round((job.sent / file.size) * 100) + '%';
          render();
        }));
      }
      job.sent = file.size;
      prog.style.width = '100%';
      const done = await fetch(`/api/upload/${init.id}/complete`, { method: 'POST' });
      if (!done.ok) throw new Error(done.status);
      const result = await done.json();
      finish(job, result.duplicate ? 'dup' : 'done', result);
    } catch (e) {
      finish(job, 'failed');
    }
  }

  function finish(job, state, result) {
    job.state = state;
    if (result && result.id) {
      job.id = result.id;
      job.kind = result.kind;
      job.takenAt = result.taken_at;
      job.el.dataset.mediaId = result.id;
      job.el.dataset.takenAt = result.taken_at || '';
    }
    const p = job.el.querySelector('.prog');
    if (p) p.remove();
    // both new files and skipped duplicates link to where the photo sits in the album
    const where = state === 'done' || state === 'dup' ? placed(job) : null;
    if (where) {
      const a = document.createElement('a');
      a.className = 'q-go';
      a.href = linkTo(where);
      a.setAttribute('aria-label', state === 'dup' ? alreadyLabel(where) : goLabel(where));
      job.el.append(a);
    }
    if (state === 'done') job.el.insertAdjacentHTML('beforeend', `<span class="badge">${CHECK}</span>`);
    if (state === 'dup') job.el.classList.add('dup');
    if (state === 'failed') job.el.classList.add('failed');
  }

  input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    addFiles(e.dataTransfer.files);
  });
  sumRetry.addEventListener('click', retryFailed);
  sumMore.addEventListener('click', () => location.reload());
  window.addEventListener('beforeunload', (e) => {
    if (running || jobs.some((j) => j.state === 'waiting')) { e.preventDefault(); e.returnValue = ''; }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && running) keepAwake(true);
  });
})();
