// Progress lives in the visitor's browser (localStorage), like the app kept it on-device.
// When someone is logged in, it is also synced to their account (see sync.py for the rules).
(function () {
  const KEY = 'papiamentu:v1';
  const SYNC_KEY = 'papiamentu:sync';   // { uid, rev } — which account/revision the local copy belongs to
  const DEFAULTS = () => ({
    version: 1,
    profile: null,          // { name }
    xp: 0,
    woorden: {},            // wordId -> { correct_count, is_mastered }
    lijsten: [1],           // unlocked word list ids
    lessen: {},             // lesId -> [completed step numbers 1..4]
    scenarios: {},          // scenarioId -> completedAt ISO string
    nieuws: {},             // artikelId -> completedAt ISO string
    theme: 'dark',          // 'system' | 'light' | 'dark' (per device, not synced)
  });

  const meta = document.querySelector('meta[name="papiamentu-user"]');
  const USER = meta ? { id: Number(meta.content), name: meta.dataset.name, csrf: meta.dataset.csrf } : null;

  function readJson(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
  }
  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage unavailable */ }
  }

  function load() {
    const raw = readJson(KEY);
    return raw ? Object.assign(DEFAULTS(), raw) : DEFAULTS();
  }

  function save(state) {
    writeJson(KEY, state);
    if (USER) schedulePush();
  }

  function update(fn) {
    const s = load();
    fn(s);
    save(s);
    return s;
  }

  // ---------- sync ----------
  let pushTimer = null;
  let inflight = null;
  let dirty = false;
  let retryDelay = 5000;

  function schedulePush(delay) {
    dirty = true;
    clearTimeout(pushTimer);
    pushTimer = setTimeout(() => push(), delay ?? 800);
  }

  function withoutTheme(state) {
    const copy = Object.assign({}, state);
    delete copy.theme;
    return copy;
  }

  async function push(opts) {
    opts = opts || {};
    if (!USER) return null;
    clearTimeout(pushTimer);
    if (inflight) { schedulePush(); return inflight; }
    dirty = false;
    const sync = readJson(SYNC_KEY) || {};
    const body = {
      base_rev: sync.uid === USER.id ? sync.rev : null,
      state: withoutTheme(load()),
      replace: !!opts.replace,
    };
    inflight = (async () => {
      try {
        const resp = await fetch('/api/progress', {
          method: 'PUT',
          credentials: 'same-origin',
          keepalive: !!opts.keepalive,
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': USER.csrf },
          body: JSON.stringify(body),
        });
        if (resp.status === 401) return null;  // session expired; keep working locally
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        retryDelay = 5000;
        if (!dirty) {
          // Nothing changed while we were saving: adopt the server's (possibly merged) state.
          writeJson(KEY, Object.assign(DEFAULTS(), data.state, { theme: load().theme }));
          writeJson(SYNC_KEY, { uid: USER.id, rev: data.rev });
        }
        // If something did change meanwhile, keep the old revision so the next save merges.
        return data;
      } catch (e) {
        schedulePush(retryDelay);
        retryDelay = Math.min(retryDelay * 2, 120000);
        return null;
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  function clearLocal() {
    const theme = load().theme;
    writeJson(KEY, Object.assign(DEFAULTS(), { theme }));
    try { localStorage.removeItem(SYNC_KEY); } catch (e) { /* ignore */ }
  }

  const Store = {
    get: load,
    update,
    user: USER,

    setName(name) { update((s) => { s.profile = { name }; }); },

    addXp(n) { return update((s) => { s.xp += n; }).xp; },
    spendXp(n) {
      let ok = false;
      update((s) => { if (s.xp >= n) { s.xp -= n; ok = true; } });
      return ok;
    },

    setWoord(id, count, mastered) {
      update((s) => { s.woorden[id] = { correct_count: count, is_mastered: mastered }; });
    },
    unlockLijst(id) {
      update((s) => { if (!s.lijsten.includes(id)) s.lijsten.push(id); });
    },

    completeLesStap(lesId, stap) {
      update((s) => {
        const done = s.lessen[lesId] || [];
        if (!done.includes(stap)) done.push(stap);
        s.lessen[lesId] = done.sort((a, b) => a - b);
      });
    },

    completeScenario(id) {
      update((s) => { if (!s.scenarios[id]) s.scenarios[id] = new Date().toISOString(); });
    },

    completeNieuws(id) {
      update((s) => { if (!s.nieuws[id]) s.nieuws[id] = new Date().toISOString(); });
    },

    setTheme(theme) {
      const s = load();
      s.theme = theme;
      writeJson(KEY, s);  // device preference: no sync needed
      applyTheme(theme);
    },

    exportJson() {
      return JSON.stringify(Object.assign({ exportedAt: new Date().toISOString() }, load()), null, 2);
    },
    async importJson(text) {
      let data;
      try { data = JSON.parse(text); } catch (e) { throw new Error('Dit is geen geldig back-upbestand.'); }
      if (!data || data.version !== 1) throw new Error('Onbekend back-upformaat.');
      delete data.exportedAt;
      writeJson(KEY, Object.assign(DEFAULTS(), data, { theme: load().theme }));
      if (USER) await push({ replace: true });
    },
    async reset() {
      clearLocal();
      if (USER) {
        await fetch('/api/progress', {
          method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRF-Token': USER.csrf },
        }).catch(() => {});
        if (USER.name) Store.setName(USER.name);
      }
    },
  };

  function applyTheme(pref) {
    const dark = pref === 'dark' ||
      (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(load().theme));

  // Small shared helpers
  Store.shuffle = function (arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };

  // True when an answer refers to the others ("Alle bovenstaande", "Beide a en c", ...).
  Store.refersToOthers = function (options) {
    return options.some((o) => /\b(alle|beide|geen van)\b|bovenstaande|\b[a-e] en [a-e]\b/i.test(o));
  };

  // News articles unlock in order: rule.open at first, then rule.per more for every rule.per read.
  // Returns how many (from the start of ids) are available; already-read ones always stay open.
  Store.nieuwsOpen = function (ids, rule) {
    const done = load().nieuws;
    const read = ids.filter((id) => done[id]).length;
    return Math.min(ids.length, rule.open + rule.per * Math.floor(read / rule.per));
  };

  Store.toast = function (msg, ms) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.setAttribute('role', 'status');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), ms || 2600);
  };

  // ---------- startup ----------
  const params = new URLSearchParams(location.search);
  if (params.has('uitgelogd')) {
    // Logged out (or account deleted): drop this browser's copy of the account's progress.
    clearLocal();
    const removed = params.has('verwijderd');
    params.delete('uitgelogd');
    params.delete('verwijderd');
    history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : ''));
    setTimeout(() => Store.toast(removed ? 'Je account is verwijderd.' : 'Je bent uitgelogd.'), 50);
  }

  if (USER) {
    const sync = readJson(SYNC_KEY) || {};
    if (sync.uid && sync.uid !== USER.id) clearLocal();  // someone else's cached progress
    if (!load().profile && USER.name) writeJson(KEY, Object.assign(load(), { profile: { name: USER.name } }));

    const before = JSON.stringify(withoutTheme(load()));
    push().then((data) => {
      if (!data) return;
      const after = JSON.stringify(withoutTheme(load()));
      if (before !== after) {
        // The account had progress this page didn't know about yet: re-render once.
        let reloaded = false;
        try { reloaded = sessionStorage.getItem('papiamentu:reloaded') === '1'; } catch (e) { /* ignore */ }
        if (!reloaded) {
          try { sessionStorage.setItem('papiamentu:reloaded', '1'); } catch (e) { /* ignore */ }
          location.reload();
          return;
        }
      }
      try { sessionStorage.removeItem('papiamentu:reloaded'); } catch (e) { /* ignore */ }
      document.dispatchEvent(new CustomEvent('papiamentu:synced'));
    });

    // Don't lose a pending save when the visitor navigates away.
    window.addEventListener('pagehide', () => { if (dirty) push({ keepalive: true }); });
  }

  window.Store = Store;
})();
