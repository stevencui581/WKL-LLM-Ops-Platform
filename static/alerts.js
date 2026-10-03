/* =====================================================================
 * 告警日志独立页（v0.4.3 §6.1 / TASK-58）
 *
 * 数据来源：GET /api/alert-log（默认最近 500 条，含产生与恢复两类事件）
 * 名称来源：GET /api/alert-catalog（后端为唯一事实源，按当前语言挑一种）
 *
 * 与主页一致：可执行代码里不出现任何中文字符串字面量。
 * ===================================================================== */
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  level: '',
  event: '',
  q: '',
  auto: false,
  timer: null,
  limit: 500
};

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setText(id, s) { const el = $(id); if (el) el.textContent = s; }

const LEVEL_CLASS = { critical: 'crit', warning: 'warn', info: 'info' };
const LEVEL_LABEL_KEY = {
  critical: 'al.level.critical',
  warning: 'al.level.warning',
  info: 'al.level.info'
};

function levelLabel(level) {
  // 级别用一个短词显示（不是"及以上"的筛选文案）
  const short = { critical: 'critical', warning: 'warning', info: 'info' };
  return short[level] || level;
}

function durationText(sec) {
  if (sec === null || sec === undefined) return '';
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function renderRows(entries) {
  const tb = $('rows');
  if (!tb) return;
  if (!entries.length) {
    tb.innerHTML = `<tr><td colspan="5" class="empty">${esc(t('al.empty'))}
      <div class="empty-hint">${esc(t('al.empty_hint'))}</div></td></tr>`;
    return;
  }
  tb.innerHTML = '';
  entries.forEach((e) => {
    const tr = document.createElement('tr');
    if (e.event === 'resolved') tr.className = 'row-resolved';
    const cat = I18N.alertCategory(e.code);
    const name = I18N.alertName(e.code);
    const suffix = e.event === 'resolved'
      ? ` <span class="tag-ok">${esc(t('al.resolved_mark'))}</span>`
      : '';
    const durTxt = (e.event === 'resolved' && e.duration_s !== null && e.duration_s !== undefined)
      ? ` <span class="tag-dim">${esc(t('al.duration', { n: durationText(e.duration_s) }))}</span>`
      : '';
    tr.innerHTML =
      `<td class="mono">${esc(e.iso || '')}</td>`
      + `<td>${esc(cat || e.code)}</td>`
      + `<td><b>${esc(name)}</b>${suffix}${durTxt}</td>`
      + `<td><span class="pill ${LEVEL_CLASS[e.level] || ''}">${esc(levelLabel(e.level))}</span></td>`
      + `<td class="msg-cell">${esc(e.message || '')}</td>`;
    tb.appendChild(tr);
  });
}

async function load() {
  const params = new URLSearchParams();
  params.set('limit', String(state.limit));
  if (state.level) params.set('level', state.level);
  if (state.event) params.set('event', state.event);
  if (state.q) params.set('q', state.q);
  try {
    const r = await fetch('/api/alert-log?' + params.toString(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const data = d.data || {};
    const entries = data.entries || [];
    if (data.available === false) {
      renderRows([]);
      setText('subtitle', t('al.unavailable'));
      return;
    }
    renderRows(entries);
    setText('subtitle', t('al.subtitle', { n: state.limit }));
    setText('foot', t('al.returned', { n: data.returned || 0, total: data.total || 0 }));
  } catch (err) {
    setText('subtitle', t('al.unavailable'));
    setText('foot', String(err.message || err));
  }
}

function updateAutoBtn() {
  const b = $('autoBtn');
  if (!b) return;
  b.textContent = t('al.auto') + ': ' + t(state.auto ? 'common.on' : 'common.off');
  b.className = state.auto ? 'follow-on' : 'follow-off';
}

function scheduleAuto() {
  if (state.timer) { clearInterval(state.timer); state.timer = null; }
  if (state.auto) state.timer = setInterval(load, 5000);
}

function bind() {
  $('levelSel').addEventListener('change', (e) => { state.level = e.target.value; load(); });
  $('eventSel').addEventListener('change', (e) => { state.event = e.target.value; load(); });
  let timer = null;
  $('qInput').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = e.target.value.trim(); load(); }, 250);
  });
  $('refreshBtn').addEventListener('click', load);
  $('autoBtn').addEventListener('click', () => {
    state.auto = !state.auto;
    updateAutoBtn();
    scheduleAuto();
  });
  $('backBtn').addEventListener('click', () => { location.href = '/'; });
}

async function main() {
  I18N.renderLangControl($('langCtl'));
  updateAutoBtn();
  I18N.applyI18n();
  bind();
  await I18N.loadCatalog();   // 名称必须就绪后再渲染，避免先显示代码
  await load();
}

document.addEventListener('DOMContentLoaded', main);
