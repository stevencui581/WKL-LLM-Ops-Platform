/* =====================================================================
 * 历史服务日志独立页（v0.4.3 §3 / TASK-59）
 *
 * 三项能力：
 *   ① 1 / 7 / 30 天切换（默认 30 天），顶部文字随档位变化；
 *   ② 实时日志变化 —— 复用 /ws/logs 通道（不新增后端接口）：
 *        打开后忽略首帧 backfill（历史基线已由 REST 提供），
 *        逐条前插新的 log 行；关闭即主动断开，避免订阅泄漏；
 *   ③ 下载 .log —— 导出**当前所选范围**（不受页面筛选影响）。
 *
 * 每条日志带完整日期时间（YYYY-MM-DD HH:MM:SS），区别于主页的 HH:MM:SS。
 * ===================================================================== */
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  days: 30,
  daysOptions: [1, 7, 30],
  level: '',
  q: '',
  live: false,
  ws: null,
  wsRetry: 0,
  liveCount: 0,
  liveMax: 3000,
  lines: [],          // 已拉取的历史行（倒序，最新在前）
  limit: 15000,       // 单次拉取上限：必须覆盖最大范围，否则 -n 会从旧端截断
  renderLimit: 1000,  // DOM 中实际渲染的行数（「加载更多」递增）
  totalInRange: 0,
  truncated: false,
  available: true,
  loading: false,
  unseen: 0,
  followTop: true
};

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setText(id, s) { const el = $(id); if (el) el.textContent = s; }

/* --------------------------------------------------------------- URL 状态 */
function readDaysFromUrl() {
  const v = new URLSearchParams(location.search).get('days');
  const n = parseInt(v, 10);
  return state.daysOptions.indexOf(n) >= 0 ? n : null;
}

function writeDaysToUrl(d) {
  try {
    const u = new URL(location.href);
    u.searchParams.set('days', String(d));
    history.replaceState(null, '', u.toString());
  } catch (e) { /* ignore */ }
}

/* ---------------------------------------------------------------- 渲染行 */
function lineEl(ln, isLive) {
  const el = document.createElement('div');
  // journalctl 的结构分隔行（跨重启时的 `-- Boot xxx --`）没有时间戳。
  // 后端用 kind="separator" 标注，这里渲染成整行分隔条 ——
  // 早期版本会显示成一行空白时间戳，看起来像数据损坏（实测踩过的坑）。
  if (ln.kind === 'separator') {
    el.className = 'ln sep';
    el.textContent = ln.text || '';
    return el;
  }
  el.className = 'ln ' + (ln.level || 'I') + (isLive ? ' live' : '');
  const ts = document.createElement('span');
  ts.className = 't wide';
  // 完整日期时间（v0.4.3 §3.1 明确要求；取后端下发的 ts_local）
  ts.textContent = ln.ts_local || (ln.ts ? ln.ts.slice(0, 19).replace('T', ' ') : '---------- --:--:--');
  el.appendChild(ts);
  const body = document.createElement('span');
  body.textContent = ln.text || '';
  if (ln.highlight) body.className = 'hl ' + ln.highlight;
  el.appendChild(body);
  return el;
}

function renderHistory() {
  const box = $('logs');
  if (!box) return;
  box.innerHTML = '';
  if (!state.lines.length) {
    box.innerHTML = `<div class="empty">${esc(state.available ? t('lg.empty') : '')}</div>`;
    updateMoreBtn();
    return;
  }
  const frag = document.createDocumentFragment();
  state.lines.slice(0, state.renderLimit).forEach((ln) => frag.appendChild(lineEl(ln, false)));
  box.appendChild(frag);
  updateMoreBtn();
}

function updateMoreBtn() {
  const b = $('moreBtn');
  if (!b) return;
  const more = state.lines.length > state.renderLimit;
  b.hidden = !more;
  b.textContent = t('lg.load_more') + (more ? ` (${state.lines.length - state.renderLimit})` : '');
}

function updateCoverage() {
  const box = $('coverage');
  if (!box) return;
  if (!state.available) {
    box.textContent = t('lg.unavailable', { err: state.error || '' });
    box.className = 'coverage bad';
    return;
  }
  box.className = 'coverage';
  const from = state.coveredFrom || '—';
  const to = state.coveredTo || '—';
  let txt = t('lg.coverage', {
    from: from, to: to, total: state.totalInRange, shown: state.lines.length
  });
  if (state.truncated) {
    txt += ' · ' + t('lg.truncated', { n: state.limit });
  }
  box.textContent = txt + (state.lines.length > state.renderLimit
    ? ` · ${state.renderLimit}/${state.lines.length}` : '');
}

function updateLiveHint() {
  const el = $('liveHint');
  if (!el) return;
  if (state.live) {
    el.textContent = `${t('lg.live_on')} · ${t('lg.live_hint')} · ${state.liveCount}`;
    el.className = 'livehint on';
  } else {
    el.textContent = '';
    el.className = 'livehint';
  }
}

function updateNewLinesBadge() {
  const el = $('newLines');
  if (!el) return;
  if (state.unseen > 0) {
    el.hidden = false;
    el.textContent = t('lg.new_lines', { n: state.unseen });
  } else {
    el.hidden = true;
  }
}

/* ---------------------------------------------------------------- 拉取 */
async function load(force) {
  if (state.loading) return;
  state.loading = true;
  setText('headline', t('lg.showing', { n: state.days }));
  const box = $('logs');
  if (box && !state.lines.length) {
    box.innerHTML = `<div class="empty">${esc(t('lg.loading'))}</div>`;
  }
  const params = new URLSearchParams();
  params.set('days', String(state.days));
  params.set('limit', String(state.limit));
  if (state.level) params.set('level', state.level);
  if (state.q) params.set('q', state.q);
  if (force) params.set('refresh', '1');
  try {
    const r = await fetch('/api/logs/history?' + params.toString(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const data = d.data || {};
    state.available = data.available !== false;
    state.error = data.error || '';
    state.lines = data.lines || [];
    state.totalInRange = data.total_in_range || 0;
    state.truncated = !!data.truncated;
    // 换档位/刷新时回到首批渲染，避免一次插入上万行
    state.renderLimit = Math.min(1000, state.lines.length || 1000);
    state.coveredFrom = data.covered_from || '';
    state.coveredTo = data.covered_to || '';
    state.liveMax = data.live_max_lines || state.liveMax;
    if (Array.isArray(data.days_options) && data.days_options.length) {
      state.daysOptions = data.days_options;
    }
    renderHistory();
    updateCoverage();
    state.unseen = 0;
    updateNewLinesBadge();
  } catch (err) {
    state.available = false;
    state.error = String(err.message || err);
    state.lines = [];
    renderHistory();
    updateCoverage();
  } finally {
    state.loading = false;
  }
}

/* ------------------------------------------------------------ 实时日志 */
function connectLive() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/logs`);
  state.ws = ws;
  ws.onopen = () => { state.wsRetry = 0; updateLiveHint(); };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    // 首帧 backfill 直接忽略：历史基线由 REST 提供，避免重复
    if (msg.type === 'backfill') return;
    if (msg.type === 'log') {
      appendLive(msg.payload);
    } else if (msg.type === 'ping') {
      ws.send('ping');
    }
  };
  ws.onclose = () => {
    if (!state.live) return;
    setText('liveHint', t('lg.live_lost'));
    const delay = Math.min(1000 * Math.pow(1.6, state.wsRetry++), 8000);
    setTimeout(() => { if (state.live) connectLive(); }, delay);
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

function stopLive() {
  if (state.ws) {
    try { state.ws.close(); } catch (e) { /* ignore */ }
    state.ws = null;
  }
  state.liveCount = 0;
  updateLiveHint();
}

function passesFilter(ln) {
  if (state.level) {
    const order = { D: 0, I: 1, W: 2, E: 3 };
    if ((order[ln.level] ?? 1) < (order[state.level] ?? 1)) return false;
  }
  if (state.q && !(ln.text || '').toLowerCase().includes(state.q.toLowerCase())) return false;
  return true;
}

function appendLive(ln) {
  if (!ln || !passesFilter(ln)) return;
  const box = $('logs');
  if (!box) return;
  const empty = box.querySelector('.empty');
  if (empty) empty.remove();
  box.insertBefore(lineEl(ln, true), box.firstChild);
  state.liveCount += 1;
  // 实时区上限：超出丢弃最旧的（防止长时间挂机内存增长）
  while (box.childElementCount > state.liveMax) box.removeChild(box.lastChild);
  if (state.followTop) {
    box.scrollTop = 0;
  } else {
    state.unseen += 1;
    updateNewLinesBadge();
  }
  updateLiveHint();
}

function setLive(on) {
  state.live = on;
  const b = $('liveBtn');
  if (b) {
    b.textContent = t(on ? 'lg.live_on' : 'lg.live_off');
    b.className = on ? 'follow-on' : 'follow-off';
  }
  if (on) {
    state.followTop = true;
    connectLive();
  } else {
    stopLive();
  }
}

/* ---------------------------------------------------------------- 控件 */
function renderDayButtons() {
  const box = $('dayBtns');
  if (!box) return;
  box.innerHTML = '';
  state.daysOptions.forEach((d) => {
    const b = document.createElement('button');
    b.className = 'segbtn' + (d === state.days ? ' on' : '');
    b.textContent = t('lg.day', { n: d });
    b.addEventListener('click', () => {
      if (state.days === d) return;
      state.days = d;
      writeDaysToUrl(d);
      renderDayButtons();
      load(false);
    });
    box.appendChild(b);
  });
}

function bind() {
  $('levelSel').addEventListener('change', (e) => { state.level = e.target.value; load(false); });
  let timer = null;
  $('qInput').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = e.target.value.trim(); load(false); }, 250);
  });
  $('refreshBtn').addEventListener('click', () => load(true));
  $('downloadBtn').addEventListener('click', () => {
    location.href = '/api/logs/history/download?days=' + state.days;
  });
  $('moreBtn').addEventListener('click', () => {
    state.renderLimit += 1000;
    renderHistory();
    updateCoverage();
  });
  $('liveBtn').addEventListener('click', () => setLive(!state.live));
  $('backBtn').addEventListener('click', () => { location.href = '/'; });
  $('logs').addEventListener('scroll', () => {
    const box = $('logs');
    state.followTop = box.scrollTop < 12;
    if (state.followTop && state.unseen > 0) {
      state.unseen = 0;
      updateNewLinesBadge();
    }
  });
  const nl = $('newLines');
  if (nl) {
    nl.addEventListener('click', () => {
      const box = $('logs');
      box.scrollTop = 0;
      state.followTop = true;
      state.unseen = 0;
      updateNewLinesBadge();
    });
  }
}

async function main() {
  I18N.renderLangControl($('langCtl'));
  const fromUrl = readDaysFromUrl();
  if (fromUrl) state.days = fromUrl;
  renderDayButtons();
  setLive(false);
  I18N.applyI18n();
  bind();
  await load(false);
  // 页面隐藏时主动断开实时连接，避免后台挂着订阅
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && state.live) {
      stopLive();
    } else if (!document.hidden && state.live) {
      connectLive();
    }
  });
}

document.addEventListener('DOMContentLoaded', main);
window.addEventListener('beforeunload', stopLive);
