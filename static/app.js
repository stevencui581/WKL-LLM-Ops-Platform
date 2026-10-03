/* =====================================================================
 * WKL-LLM运维平台 —— 主页脚本（v0.4.3）
 *
 * 双语原则（v0.4.3 §3.2）：
 *   * 本文件的**可执行代码里不出现任何中文字符串字面量**；
 *   * 所有文案走 t('key') 或 data-i18n；
 *   * 后端只提供**结构化数据**（code / key / value / 布尔量），
 *     语言由前端决定 —— 例如告警名称来自 /api/alert-catalog，
 *     KV 容量文案由 capacity_mode + total_tokens 组合而成。
 * ===================================================================== */
'use strict';

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ 安全写入 */
function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function setHTML(id, html) {
  const el = $(id);
  if (el) el.innerHTML = html;
}

function has(id) { return !!$(id); }

const state = {
  ws: null,
  wsLogs: null,
  wsRetry: 0,
  seq: 0,
  thresholds: {},
  series: { decode: [], prefill: [], mtp: [] },
  logLines: [],
  maxLogLines: 1000,
  level: '',
  query: '',
  follow: true,
  hardware: null,
  hardwareTs: 0,
  lastSnapshot: null,
  catalogReady: false,
  framework: null
};

const MAX_POINTS = 60;

/* ------------------------------------------------------------------ 工具 */
function fmt(v, digits = 1, suffix = '') {
  if (v === null || v === undefined || Number.isNaN(v)) return '—' + suffix;
  return Number(v).toFixed(digits) + suffix;
}

function int(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return 0;
  return Math.round(Number(v));
}

function gib(mib) {
  if (mib === null || mib === undefined) return '—';
  return (mib / 1024).toFixed(1);
}

function hhmmss(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0')).join(':');
}

function dur(sec) {
  if (sec === null || sec === undefined) return '—';
  const s = Math.max(0, Math.round(sec));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function th(key, fallback) {
  const v = state.thresholds ? state.thresholds[key] : undefined;
  return (v === null || v === undefined) ? fallback : v;
}

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* --------------------------------------------------- 迷你趋势（canvas） */
function drawSpark(canvas, values, color, opts) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.clientWidth || 200;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const nums = values.filter((v) => v !== null && v !== undefined);
  if (nums.length < 2) return;
  const lo = opts && opts.min !== undefined ? opts.min : Math.min(...nums);
  const hi = opts && opts.max !== undefined ? opts.max : Math.max(...nums);
  const span = (hi - lo) || 1;
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  values.forEach((v, i) => {
    if (v === null || v === undefined) return;
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - lo) / span) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function pushSeries(key, value) {
  const arr = state.series[key];
  if (!arr) return;
  arr.push(value);
  while (arr.length > MAX_POINTS) arr.shift();
}

/* ------------------------------------------------------------------ 渲染 */
function setState(kind, text) {
  const el = $('state');
  if (el) el.className = 'state ' + kind;
  setText('stateText', text);
}

function renderBranding(b) {
  if (!b) return;
  // 版号与品牌完全来自后端（v0.4 R8 单一事实源）：
  // 前端**不保留任何版本号字面量** —— 否则每次升版都要改前端，
  // 而且很容易漏掉某一处（v0.4.4 就踩过这个坑）。
  const brand = $('brand');
  if (brand) {
    brand.innerHTML = '';
    const s1 = document.createElement('span');
    s1.textContent = t('app.brand');
    const s2 = document.createElement('span');
    s2.className = 'ver';
    s2.textContent = b.product_version || '';
    brand.appendChild(s1); brand.appendChild(s2);
  }
  // 底栏开发者信息：日期用后端下发的值（不写死），文案走 i18n
  if (has('devInfo')) {
    setText('devInfo', t('footer.dev_fmt', {
      dev: b.developer || t('app.brand'),
      date: b.develop_date || ''
    }));
  }
}

/* ------------------------------------------------ 标识1/标识2（R1/R2） */
function renderTopChips(o) {
  const ab = o.accelerator_badge || {};
  const chip = $('accelBadge');
  if (chip) {
    chip.classList.toggle('missing', !ab.present);
    const tp = $('accelTp');
    if (ab.present) {
      setText('accelText', ab.text || '—');
      if (tp) {
        tp.textContent = t(ab.tensor_parallel ? 'top.tp_on' : 'top.tp_off');
        tp.className = 'tp ' + (ab.tensor_parallel ? 'on' : 'off');
      }
    } else {
      setText('accelText', t('hw.no_accel'));
      if (tp) { tp.textContent = ''; tp.className = 'tp'; }
    }
  }
  const mdl = o.model || {};
  const full = mdl.full_name || mdl.name || '';
  setText('modelFull', full || '—');
  const mc = $('modelChip');
  if (mc) {
    mc.classList.toggle('missing', !full);
    mc.title = mdl.path || full || '';
  }
  const up = o.llama_uptime_s;
  setText('uptime', (up === null || up === undefined) ? '—' : dur(up));
  const iv = th('poll_interval_s', 2);
  setText('refreshNote', t('top.refresh_note_fmt', { n: iv }));
  renderFrameworkChip(o.framework);
}

/* --------------------------- v0.5 §1：推理框架与版本（全部来自运行时探测）
 *
 * 名称/说明都由后端下发**中英两份**，这里按当前语言挑一个 —— 页面不写死
 * 任何框架名（llama.cpp / ollama / vLLM / SGLang 都只是被识别的结果）。
 * ---------------------------------------------------------------------- */
function renderFrameworkChip(fw) {
  const chip = $('fwChip');
  if (!chip) return;
  if (!fw || !fw.id) {
    setText('fwText', t('top.fw_detecting'));
    chip.classList.add('missing');
    chip.title = '';
    return;
  }
  const pick = (obj) => (obj ? (obj[I18N.lang] || obj.zh || obj.en || '') : '');
  const name = pick(fw.name) || fw.id;
  const ver = fw.version || '';
  const build = fw.build ? ` (${fw.build})` : '';
  setText('fwText', name + (ver ? ` ${ver}${build}` : ''));
  chip.classList.toggle('missing', fw.confidence === 'unknown');
  chip.title = [
    `id: ${fw.id}`,
    `version: ${fw.version_source || 'unknown'}`,
    `api: ${(fw.capabilities || []).join(', ') || '-'}`,
    pick(fw.note)
  ].filter(Boolean).join('\n');
  state.framework = fw;
}

/** 当前框架是否提供某接口。未识别（无 framework 字段）时按"提供"处理，
 *  避免启动瞬间把面板全部关掉。 */
function fwSupports(cap) {
  const fw = state.framework;
  if (!fw || !fw.id) return true;
  return (fw.capabilities || []).indexOf(cap) >= 0;
}

/* ----------------------------- KV 容量文案：由结构化字段组合（v0.4.3 §6.4） */
function kvLabel(kv) {
  const n = (kv.slots || []).length;
  if (!kv.total_tokens) return t('kv.pending', { n });
  const cap = kv.total_tokens >= 1024
    ? Math.round(kv.total_tokens / 1024) + 'K'
    : String(kv.total_tokens);
  let mode;
  if (kv.capacity_mode === 'unified') mode = t('kv.mode.unified');
  else if (kv.capacity_mode === 'per_slot') mode = t('kv.mode.per_slot');
  else mode = t('kv.mode.unknown');
  return t('kv.capacity', { slots: n, cap: cap, mode: mode });
}

/* --------------------- 配置徽标：由 badge_items 组合（v0.4.3 §6.4） */
function badgeText(item) {
  const key = item.key;
  const val = item.value;

  // KV 量化：未配置 -ctk/-ctv 时显示默认值，必须显式标注「默认」
  if (key === 'kv_quant') {
    const shown = (item.source === 'default') ? t('kv.quant.default', { v: val }) : val;
    return t('badge.kv_quant', { v: shown });
  }
  if (key === 'tensor_split') {
    const p = String(val).split('|');
    return t('badge.tensor_split', { n: p[0], s: p[1] });
  }
  const KEYS = {
    n_ctx: 'badge.n_ctx',
    spec: 'badge.spec',
    spec_off: 'badge.spec_off',
    draft: 'badge.draft',
    flash_on: 'badge.flash_on',
    flash_off: 'badge.flash_off',
    model_ftype: 'badge.model_ftype'
  };
  const dictKey = KEYS[key];
  return dictKey ? t(dictKey, { v: val }) : '';
}

function renderBadges(rt) {
  const box = $('badges');
  if (!box) return;
  const items = rt.badge_items || [];
  box.innerHTML = '';
  items.forEach((it) => {
    const text = badgeText(it);
    if (!text) return;
    const el = document.createElement('span');
    el.className = 'badge';
    const sp = text.indexOf(' ');
    if (sp > 0) {
      const k = document.createElement('span');
      k.textContent = text.slice(0, sp + 1);
      const v = document.createElement('b');
      v.textContent = text.slice(sp + 1);
      el.appendChild(k); el.appendChild(v);
    } else {
      el.textContent = text;
    }
    box.appendChild(el);
  });
  if (rt.metrics_enabled === false) {
    const el = document.createElement('span');
    el.className = 'badge';
    el.style.color = 'var(--orange)';
    el.textContent = t('badge.metrics_off');
    box.appendChild(el);
  }
}

function renderOverview(o) {
  state.lastSnapshot = o;
  state.thresholds = o.thresholds || {};
  renderBranding(o.branding);
  renderTopChips(o);
  maybeFetchHardware(o.hardware_ts);

  const kpi = o.kpi, kv = o.kv, sys = o.system, rt = o.runtime;

  // ---- 第一排 ----
  setHTML('decode', (kpi.decode_tps === null ? '—' : fmt(kpi.decode_tps, 1)) + '<span class="unit">tok/s</span>');
  pushSeries('decode', kpi.decode_tps);
  drawSpark($('sparkDecode'), state.series.decode, 'rgb(34,197,94)');
  setText('decodeSub', t('sub.decode'));

  setHTML('prefill', (kpi.prefill_tps === null ? '—' : fmt(kpi.prefill_tps, 1)) + '<span class="unit">tok/s</span>');
  pushSeries('prefill', kpi.prefill_tps);
  drawSpark($('sparkPrefill'), state.series.prefill, 'rgb(59,130,246)');
  setText('prefillSub', kpi.recent && kpi.recent.prefill_tokens != null
    ? t('sub.prefill', { n: int(kpi.recent.prefill_tokens) })
    : t('sub.prefill_none'));

  setHTML('mtp', (kpi.mtp_accept === null ? '—' : fmt(kpi.mtp_accept * 100, 1)) + '<span class="unit">%</span>');
  pushSeries('mtp', kpi.mtp_accept === null ? null : kpi.mtp_accept * 100);
  drawSpark($('sparkMtp'), state.series.mtp, 'rgb(168,85,247)', { min: 0, max: 100 });
  setText('mtpSub', kpi.draft_mean_len != null
    ? t('sub.mtp', { avg: fmt(kpi.draft_mean_len, 2), max: 3 })
    : t('sub.mtp_none'));

  setHTML('processing', int(kpi.processing) + `<span class="unit">/ ${kpi.slots_total || 0}</span>`);
  setText('processingSub', t('sub.processing', {
    total: kpi.slots_total || '—',
    q: (kpi.deferred === null || kpi.deferred === undefined) ? '—' : int(kpi.deferred)
  }));

  const vu = kpi.vram_used_mib, vt = kpi.vram_total_mib;
  setHTML('vram', gib(vu) + `<span class="unit">/ ${gib(vt)} GiB</span>`);
  const vpct = vu && vt ? (vu / vt * 100) : 0;
  const vbar = $('vramBar');
  if (vbar) {
    vbar.style.width = clamp(vpct, 0, 100).toFixed(1) + '%';
    vbar.style.background = vpct > th('vram_crit_pct', 95) ? 'var(--red)'
      : (vpct > th('vram_color_warn_pct', 85) ? 'var(--orange)' : 'var(--cyan)');
  }
  setText('vramSub', vt ? t('sub.vram', {
    pct: vpct.toFixed(1), free: gib(vt - vu)
  }) : t('sub.vram_unknown'));

  // ---- 第二排：GPU 卡片按实际卡数动态渲染 ----
  renderGpuCards(o.gpus || []);

  if (kpi.generated_total !== null && kpi.generated_total !== undefined) {
    setHTML('genTotal', int(Math.round(kpi.generated_total)) + '<span class="unit">tok</span>');
    setText('genSub', kpi.generated_total_exact ? t('sub.gen_exact') : t('sub.gen_estimate'));
  } else {
    setHTML('genTotal', '—');
    setText('genSub', t('sub.gen_unavailable'));
  }

  // ---- KV 面板 ----
  const pct = kv.pct === null || kv.pct === undefined ? 0 : kv.pct;
  setText('kvPct', fmt(pct, 1) + '%');
  setText('kvRight', t('kv.right', { pct: fmt(pct, 1) + '%' }));
  const kvBar = $('kvBar');
  if (kvBar) {
    kvBar.className = 'kvbar' + (pct > th('kv_crit_pct', 95) ? ' crit'
      : (pct > th('kv_warn_pct', 85) ? ' warn' : ''));
    kvBar.firstElementChild.style.width = clamp(pct, 0, 100).toFixed(1) + '%';
  }
  // v0.5 §1：框架不提供 /slots 时，明确说明"能力差异"而不是显示空白表格
  const slotsOk = fwSupports('slots');
  // v0.4.3 §6.4：不再直接显示后端的中文 label，改为按结构化字段组合
  setText('kvNote', slotsOk ? kvLabel(kv) : t('kv.unsupported'));
  setText('kvRemain', slotsOk ? t('kv.remain', { n: int(kv.remaining_tokens) }) : t('panel.unsupported_hint'));

  renderBadges(rt);

  const tb = $('slotRows');
  if (tb && !slotsOk) {
    tb.innerHTML = `<tr><td colspan="5" class="empty">${esc(t('kv.unsupported'))}</td></tr>`;
  } else if (tb) {
    tb.innerHTML = '';
    const slotList = kv.slots || [];
    if (!slotList.length) {
      tb.innerHTML = `<tr><td colspan="5" class="empty">${esc(t('sub.waiting'))}</td></tr>`;
    } else {
      const lbl = {
        generating: t('slot.generating'),
        cached: t('slot.cached'),
        idle: t('slot.idle')
      };
      slotList.forEach((s) => {
        const tr = document.createElement('tr');
        const src = s.source
          ? esc(s.source)
          : `<span style="color:var(--text-mute)">${esc(t('common.unknown'))}</span>`;
        tr.innerHTML = `<td>${s.id}</td>`
          + `<td class="state-cell"><span class="pill ${s.state}">${esc(lbl[s.state] || s.state || t('common.unknown'))}</span></td>`
          + `<td>${int(s.n_prompt_tokens)}</td>`
          + `<td>${(s.n_ctx / 1024).toFixed(0)}K</td>`
          + `<td>${src}</td>`;
        tb.appendChild(tr);
      });
    }
  }

  const r = kpi.recent || {};
  setHTML('recent', [
    [t('recent.prefill'), r.prefill_tps != null ? `${fmt(r.prefill_tps, 1)} t/s (${int(r.prefill_tokens)} tok)` : '—'],
    [t('recent.decode'), r.decode_tps != null ? `${fmt(r.decode_tps, 1)} t/s (${int(r.decode_tokens)} tok)` : '—'],
    [t('recent.total'), r.total_tokens != null ? `${int(r.total_tokens)} tokens` : '—'],
    [t('recent.mtp'), r.mtp_accept != null ? `${fmt(r.mtp_accept * 100, 1)} %` : '—'],
    [t('recent.draft'), r.draft_mean_len != null ? fmt(r.draft_mean_len, 2) : '—'],
    [t('recent.time'), r.ts ? hhmmss(r.ts) : '—']
  ].map(([k, v]) => `<div><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join(''));

  // ---- 告警（名称来自后端目录，按当前语言渲染）----
  renderAlerts(o.alerts || []);

  // ---- 系统资源 ----
  renderSysGrid(sys);
  const si = o.self || {};
  const base = baselineText(o.baseline);
  const selfLine = t('self.line', {
    cpu: fmt(si.cpu_pct, 2), rss: fmt(si.rss_mb, 1), th: si.threads || '—',
    ws: si.ws_clients || 0, up: dur(si.uptime_s)
  });
  setText('selfInfo', base ? `${selfLine} · ${base}` : selfLine);

  setText('lastRefresh', hhmmss(o.ts));

  const h = o.health || {};
  if (h.ready === false) {
    setState('warn', t('state.degraded'));
    const codes = h.reason_codes || [];
    const reasons = codes.length
      ? codes.map((code) => t('health.' + code)).join(zh ? '；' : '; ')
      : (h.reasons || []).join(zh ? '；' : '; ');
    const b = $('banner');
    if (b) { b.className = 'banner warn show'; b.textContent = t('banner.degraded', { reasons: reasons }); }
  } else if ((o.alerts || []).some((a) => a.level === 'critical')) {
    setState('crit', t('state.crit'));
    const b = $('banner'); if (b) b.className = 'banner';
  } else if ((o.alerts || []).length) {
    setState('warn', t('state.warn'));
    const b = $('banner'); if (b) b.className = 'banner';
  } else {
    setState('ok', t('state.ok'));
    const b = $('banner'); if (b) b.className = 'banner';
  }
}

function renderAlerts(al) {
  setText('alertCount', t('alerts.count', { n: al.length }));
  const box = $('alerts');
  if (!box) return;
  if (!al.length) {
    box.innerHTML = `<div class="empty">${esc(t('alerts.empty'))}</div>`;
    return;
  }
  box.innerHTML = '';
  al.forEach((a) => {
    const d = document.createElement('div');
    d.className = 'alert ' + a.level;
    const lv = { critical: 'crit', warning: 'warn', info: 'info' }[a.level] || a.level;
    d.innerHTML = `<span class="code">${esc(a.code)}</span>`
      + `<span class="lvl">${esc(lv)}</span><span class="msg"></span>`;
    // 名称来自 /api/alert-catalog（后端为唯一事实源），未加载时退化为代码
    const name = I18N.alertName(a.code);
    d.querySelector('.msg').textContent = name === a.code ? a.message : name;
    box.appendChild(d);
  });
}

/* ------------------------------------- GPU 卡片：按实测卡数动态渲染 */
function renderGpuCards(gpus) {
  const n = gpus.length;
  const g0 = gpus[0] || {};
  const dual = (list, fn) => list.map((g, i) =>
    `<span>GPU${g.index !== undefined ? g.index : i} <b>${fn(g)}</b></span>`).join('');

  if (!n) {
    setHTML('util', '—<span class="unit">%</span>');
    setHTML('temp', '—<span class="unit">°C</span>');
    setHTML('power', '—<span class="unit">W</span>');
    setHTML('utilDual', '');
    setHTML('tempDual', '');
    setHTML('powerDual', '');
    setText('utilSub', t('sub.no_gpu'));
    setText('tempSub', '—');
    setText('powerSub', '—');
    setHTML('bw', '—<span class="unit">GB/s</span>');
    setHTML('bwDual', '');
    setText('bwSub', t('sub.bw_unknown'));
    return;
  }

  setHTML('util', fmt(g0.util_gpu_pct, 0) + '<span class="unit">%</span>');
  setHTML('utilDual', dual(gpus, (g) => fmt(g.util_gpu_pct, 0) + '%'));
  const split = state.lastSnapshot && state.lastSnapshot.runtime
    ? (state.lastSnapshot.runtime.tensor_split || '—') : '—';
  setText('utilSub', t('sub.util', { n: n, split: split }));

  setHTML('temp', fmt(g0.temp_c, 0) + '<span class="unit">°C</span>');
  setHTML('tempDual', dual(gpus, (g) => fmt(g.temp_c, 0) + '°C'));
  const tmax = Math.max(...gpus.map((g) => g.temp_c || 0));
  const tw = th('gpu_temp_warn_c', 83), tc = th('gpu_temp_crit_c', 87);
  const tEl = $('temp');
  if (tEl) tEl.style.color = tmax > tc ? 'var(--red)' : (tmax > tw ? 'var(--orange)' : 'var(--cyan)');
  const fans = gpus.map((g) => g.fan_pct).filter((v) => v !== null && v !== undefined);
  setText('tempSub', fans.length
    ? t('sub.temp_fan', { fans: fans.join(' / '), warn: tw, crit: tc })
    : t('sub.temp', { warn: tw, crit: tc }));

  setHTML('power', fmt(g0.power_w, 1) + '<span class="unit">W</span>');
  setHTML('powerDual', dual(gpus, (g) => fmt(g.power_w, 1) + 'W'));
  const limits = gpus.map((g) => g.power_limit_w).filter((v) => v);
  setText('powerSub', limits.length
    ? t('sub.power', { limit: fmt(limits[0], 0), pct: th('power_warn_pct', 90) })
    : t('sub.power_unknown'));

  const bwVals = gpus.map((g) => g.bandwidth_gbps).filter((v) => v !== null && v !== undefined);
  setHTML('bw', (bwVals.length ? fmt(g0.bandwidth_gbps, 1) : '—') + '<span class="unit">GB/s</span>');
  setHTML('bwDual', dual(gpus, (g) => fmt(g.bandwidth_gbps, 1)));
  const rt = state.lastSnapshot && state.lastSnapshot.runtime;
  setText('bwSub', (rt && rt.gpu_bandwidth_label)
    ? rt.gpu_bandwidth_label
    : t('sub.bw_unknown'));
}

/* ------------------------------------- 硬件与运行环境（R3 / R4） */
function maybeFetchHardware(ts) {
  if (ts === null || ts === undefined) return;
  if (ts && ts !== state.hardwareTs) {
    state.hardwareTs = ts;
    fetchHardware();
  } else if (!state.hardware) {
    fetchHardware();
  }
}

function fetchHardware() {
  fetch('/api/hardware', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d) { state.hardware = d; renderHardware(d); } })
    .catch(() => { /* 探测失败时保留上一次结果，不清空 */ });
}

function hwRow(k, v, cls) {
  return `<div class="hwrow"><span class="k">${esc(k)}</span>`
    + `<span class="v ${cls || ''}">${v}</span></div>`;
}

function compRow(name, version, status) {
  const dot = status === 'installed' ? 'ok' : (status === 'missing' ? 'miss' : 'unk');
  const txt = status === 'installed' ? esc(version || t('hw.installed'))
    : (status === 'missing' ? t('hw.not_installed') : t('common.unknown'));
  const cls = status === 'installed' ? '' : 'muted';
  const hint = t('hw.hint.' + name);
  const hintHtml = (hint && hint !== 'hw.hint.' + name)
    ? `<span class="hw-hint">${esc(hint)}</span>` : '';
  return `<div class="hwrow"><span class="k"><span class="dot-s ${dot}"></span> ${esc(name)}</span>`
    + `<span class="v ${cls}">${txt}${hintHtml}</span></div>`;
}

function renderHardware(hw) {
  const box = $('hwBody');
  if (!box) return;
  const secs = [];
  const U = t('common.unknown');

  // ---------- ① 服务器硬件 ----------
  const dmi = hw.dmi || {}, cpu = hw.cpu || {}, mem = hw.memory || {};
  let s1 = '';
  const machine = [dmi.sys_vendor, dmi.product_name].filter(Boolean).join(' · ');
  if (machine) s1 += hwRow(t('hw.machine'), esc(machine));
  const bios = [dmi.bios_vendor, dmi.bios_version, dmi.bios_date].filter(Boolean).join(' · ');
  if (bios) s1 += hwRow(t('hw.bios'), esc(bios));
  const board = [dmi.board_vendor, dmi.board_name].filter(Boolean).join(' · ');
  s1 += hwRow(t('hw.board'), board ? esc(board) : U, board ? '' : 'muted');
  s1 += hwRow(t('hw.cpu'), cpu.model ? esc(cpu.model) : U, cpu.model ? '' : 'muted');
  if (cpu.model) {
    const ext = [];
    if (cpu.l3_cache) ext.push('L3 ' + cpu.l3_cache);
    if (cpu.numa_nodes) ext.push('NUMA ' + cpu.numa_nodes);
    s1 += hwRow(t('hw.cpu_spec'), esc(ext.length
      ? t('hw.cpu_detail', {
        sockets: cpu.sockets, cores: cpu.cores_per_socket, logical: cpu.logical,
        l3: cpu.l3_cache, numa: cpu.numa_nodes
      })
      : t('hw.cpu_detail_basic', {
        sockets: cpu.sockets, cores: cpu.cores_per_socket, logical: cpu.logical
      })));
  }
  if (mem.total_gib) {
    const txt = mem.swap_gib
      ? t('hw.mem_detail', {
        total: fmt(mem.total_gib, 2), avail: fmt(mem.available_gib, 1), swap: fmt(mem.swap_gib, 1)
      })
      : t('hw.mem_detail_noswap', { total: fmt(mem.total_gib, 2), avail: fmt(mem.available_gib, 1) });
    s1 += hwRow(t('hw.mem'), esc(txt));
  } else {
    s1 += hwRow(t('hw.mem'), U, 'muted');
  }
  (hw.disks || []).forEach((d) => {
    const parts = (d.partitions || []).filter((p) => p.mountpoint && p.used_pct !== null);
    const main = parts.find((p) => p.mountpoint === '/') || parts[0];
    if (!main) {
      s1 += hwRow(t('hw.disk'), esc(`${d.name} ${fmt(d.size_gib, 1)} GiB`));
      return;
    }
    s1 += hwRow(t('hw.disk'),
      esc(t('hw.disk_detail', {
        name: main.name, fstype: main.fstype || '', size: fmt(main.size_gib, 1)
      })) + `<span class="hw-sub">${esc(t('hw.disk_used', { pct: fmt(main.used_pct, 1) }))}</span>`);
  });
  const summ = hw.accelerators_summary || {};
  s1 += hwRow(t('hw.accel'), summ.count
    ? esc(t('hw.accel_detail', {
      count: summ.count,
      model: summ.model || t('hw.model_unknown'),
      mem: fmt(summ.memory_gib_each, 0)
    }))
    : t('hw.no_accel'), summ.count ? '' : 'muted');
  secs.push([t('hw.sec1'), s1]);

  // ---------- ② 算力卡与依赖环境（R4：只渲染探测到的厂家） ----------
  let s2 = '';
  if (!(hw.vendors || []).length) s2 += hwRow(t('hw.accel'), t('hw.no_accel'), 'muted');
  ['nvidia', 'amd'].forEach((v) => {
    const b = (hw.accelerators || {})[v];
    if (!b || !b.present) return;
    const display = v === 'nvidia' ? 'NVIDIA' : 'AMD';
    s2 += hwRow(t('hw.accel'),
      esc(`${display} ${b.model || t('hw.model_unknown')} ×${b.count}`));
    if (b.compute_cap) s2 += hwRow(t('hw.compute_cap'), esc(b.compute_cap));
    s2 += hwRow(t('hw.bw'), b.bandwidth_gbps
      ? `${fmt(b.bandwidth_gbps, 0)} GB/s<span class="hw-sub">${esc(b.mem_type || '')}</span>`
      : t('hw.bw_unknown'), b.bandwidth_gbps ? '' : 'muted');
    s2 += hwRow(t('hw.topo'), esc(b.topology || U)
      + (b.nvlink === true ? `<span class="hw-sub">${esc(t('hw.nvlink_yes'))}</span>`
        : (b.nvlink === false ? `<span class="hw-sub">${esc(t('hw.nvlink_no'))}</span>` : '')));
    s2 += hwRow(t('hw.driver'),
      esc(`${b.driver_name || '—'} ${b.driver_version || ''}`.trim() || U));
    if (b.cuda_driver_version) s2 += hwRow(t('hw.cuda_driver'), esc(b.cuda_driver_version));
    if (b.rocm_version) s2 += hwRow(t('hw.rocm'), esc(b.rocm_version));
    (b.components || []).forEach((c) => { s2 += compRow(c.name, c.version, c.status); });
    // v0.4.3：型号未收录时由前端本地化提示（后端只给 bandwidth_known）
    if (b.bandwidth_known === false) {
      s2 += `<div class="hwrow"><span class="k"></span><span class="v hw-sub">`
        + esc(t('hw.note.bw_unknown', { model: b.model || '' })) + '</span></div>';
    }
  });
  secs.push([t('hw.sec2'), s2]);

  // ---------- ③ Python 与框架 ----------
  const py = hw.python || {}, tor = py.torch || {};
  let s3 = hwRow(t('hw.python'),
    esc(`${py.version || U}${py.executable ? ` (${py.executable})` : ''}`));
  s3 += hwRow(t('hw.conda'), py.conda ? t('hw.installed') : t('hw.not_installed'),
    py.conda ? '' : 'muted');
  let torchTxt, torchCls = '';
  if (tor.installed) {
    torchTxt = esc(`${tor.version}${tor.backend ? ` (${tor.backend})` : ''}`);
  } else {
    torchTxt = esc(t('hw.torch_missing'));
    torchCls = 'muted';
  }
  s3 += hwRow(t('hw.torch'), torchTxt, torchCls);
  secs.push([t('hw.sec3'), s3]);

  box.innerHTML = secs.map(([title, body]) =>
    `<div class="hwsec"><h3>${esc(title)}</h3>${body}</div>`).join('');

  const unk = hw.unknown_fields || [];
  const errs = Object.keys(hw.errors || {});
  if (unk.length || errs.length) {
    const note = document.createElement('div');
    note.className = 'hw-note';
    note.textContent = t('hw.unknown_fields', { list: [...unk, ...errs].join(', ') });
    box.appendChild(note);
  }

  setText('hwRight', t('hw.age', { machine: machine || U, n: fmt(hw.age_s, 0) }));
}

/* ------------------------------------- 系统资源（R6：2 列 3 行） */
function renderSysGrid(sys) {
  const box = $('sysgrid');
  if (!box) return;
  const items = [
    [t('sys.cpu'), `${fmt(sys.cpu_pct, 1)} %`],
    [t('sys.mem'), `${sys.mem_used_mb || 0} / ${sys.mem_total_mb || 0} MB<span class="sub">(${fmt(sys.mem_pct, 1)} %)</span>`],
    [t('sys.load'), `${fmt(sys.load1, 2)} / ${fmt(sys.load5, 2)} / ${fmt(sys.load15, 2)}`],
    [t('sys.swap'), `${sys.swap_used_mb || 0} / ${sys.swap_total_mb || 0} MB`],
    [t('sys.disk'), `${fmt(sys.disk_used_gb, 1)} / ${fmt(sys.disk_total_gb, 1)} GB<span class="sub">(${fmt(sys.disk_pct, 1)} %)</span>`],
    [t('sys.net'), `↓ ${fmt(sys.net_rx_kbps, 1)} KB/s · ↑ ${fmt(sys.net_tx_kbps, 1)} KB/s`]
  ];
  box.innerHTML = items.map(([k, v]) =>
    `<div class="syscell"><span class="k">${esc(k)}</span><span class="v">${v}</span></div>`).join('');
}

/* ------------------------------------- 自动基线状态（v0.4 §7） */
function baselineText(b) {
  if (!b) return '';
  const parts = [];
  [['mtp', t('baseline.mtp')], ['decode', t('baseline.decode')]].forEach(([name, label]) => {
    const m = b[name] || {};
    if (m.state === 'ready') {
      const shown = name === 'mtp' ? `${(m.value * 100).toFixed(1)}%` : `${fmt(m.value, 1)} t/s`;
      const manual = m.source === 'manual' ? t('baseline.manual') : '';
      parts.push(`${label} ${shown}${manual}`);
    } else {
      parts.push(`${label} ${t('baseline.learning')} (${m.samples || 0}/${m.required || 0})`);
    }
  });
  return parts.join(' · ');
}

/* ------------------------------------------------------------------ 日志 */
function levelPass(level) {
  if (!state.level) return true;
  const order = { D: 0, I: 1, W: 2, E: 3 };
  return (order[level] ?? 1) >= (order[state.level] ?? 1);
}

function appendLog(line, atTop) {
  if (!levelPass(line.level)) return;
  if (state.query && !(line.text || '').toLowerCase().includes(state.query)) return;
  state.logLines.push(line);
  while (state.logLines.length > state.maxLogLines) state.logLines.shift();

  const box = $('logs');
  if (!box) return;
  const el = document.createElement('div');
  el.className = 'ln ' + (line.level || 'I');
  const ts = document.createElement('span');
  ts.className = 't';
  ts.textContent = line.ts ? line.ts.slice(11, 19) : '--:--:--';
  el.appendChild(ts);
  const body = document.createElement('span');
  body.textContent = line.text || '';
  if (line.highlight) body.className = 'hl ' + line.highlight;
  el.appendChild(body);
  if (atTop) box.insertBefore(el, box.firstChild); else box.appendChild(el);

  while (box.childElementCount > state.maxLogLines) box.removeChild(box.firstChild);
  if (state.follow && !atTop) box.scrollTop = box.scrollHeight;
}

function relogAll() {
  const box = $('logs');
  if (!box) return;
  box.innerHTML = '';
  const keep = state.logLines.filter((l) => levelPass(l.level));
  state.logLines = [];
  keep.forEach((l) => appendLog(l, false));
  if (state.follow) box.scrollTop = box.scrollHeight;
}

function updateFollowBtn() {
  const b = $('followBtn');
  if (!b) return;
  b.textContent = t(state.follow ? 'log.follow_on' : 'log.follow_off');
  b.className = state.follow ? 'follow-on' : 'follow-off';
}

/* ------------------------------------------------------------------ 连接 */
function connectMetrics() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/metrics`);
  state.ws = ws;
  ws.onopen = () => { state.wsRetry = 0; setState('ok', t('state.ok')); };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'snapshot') {
      if (msg.seq && msg.seq < state.seq) return;
      state.seq = msg.seq;
      renderOverview(msg.payload);
    } else if (msg.type === 'ping') {
      ws.send('ping');
    }
  };
  ws.onclose = () => {
    setState('warn', t('state.reconnecting'));
    const delay = Math.min(1000 * Math.pow(1.6, state.wsRetry++), 8000);
    setTimeout(connectMetrics, delay);
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

function connectLogs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/logs`);
  state.wsLogs = ws;
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'backfill') {
      const box = $('logs');
      if (box) box.innerHTML = '';
      state.logLines = [];
      (msg.payload || []).forEach((l) => appendLog(l, true));
      if (state.follow && box) box.scrollTop = box.scrollHeight;
      setText('logRight', t('log.backfilled', { n: (msg.payload || []).length }));
    } else if (msg.type === 'log') {
      appendLog(msg.payload, false);
      setText('logRight', t('log.buffered', { n: state.logLines.length }));
    } else if (msg.type === 'ping') {
      ws.send('ping');
    }
  };
  ws.onclose = () => setTimeout(connectLogs, 2000);
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

async function loadOverview() {
  try {
    const r = await fetch('/api/overview', { cache: 'no-store' });
    if (r.ok) renderOverview(await r.json());
  } catch (e) { /* WebSocket 会补上 */ }
}

/* ------------------------------------------------------------------ 交互 */
function bindUI() {
  $('logLevel').addEventListener('change', (e) => { state.level = e.target.value; relogAll(); });
  let timer = null;
  $('logQuery').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.query = e.target.value.trim().toLowerCase();
      relogAll();
    }, 200);
  });
  $('followBtn').addEventListener('click', () => {
    state.follow = !state.follow;
    updateFollowBtn();
    if (state.follow) $('logs').scrollTop = $('logs').scrollHeight;
  });
  $('clearBtn').addEventListener('click', () => {
    state.logLines = [];
    $('logs').innerHTML = '';
  });
  $('logs').addEventListener('scroll', () => {
    const box = $('logs');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 12;
    if (!atBottom && state.follow) {
      state.follow = false;
      updateFollowBtn();
    }
  });
  const alBtn = $('alertLogBtn');
  if (alBtn) alBtn.addEventListener('click', () => { location.href = '/alerts.html'; });
  const lgBtn = $('logHistoryBtn');
  if (lgBtn) lgBtn.addEventListener('click', () => { location.href = '/logs.html'; });
}

function main() {
  I18N.renderLangControl($('langCtl'));
  updateFollowBtn();
  I18N.applyI18n();
  bindUI();
  loadOverview();
  connectMetrics();
  connectLogs();
  // 告警名称来自后端目录；加载完成后重渲染一次（避免先显示代码后变名称）
  I18N.loadCatalog().then(() => {
    state.catalogReady = true;
    if (state.lastSnapshot) renderAlerts(state.lastSnapshot.alerts || []);
  });
}

document.addEventListener('DOMContentLoaded', main);
