#!/usr/bin/env node
/* =============================================================================
 * 前端渲染冒烟测试（v0.5）
 *
 *   node tools/check_frontend_render.js static/ /path/to/overview.json
 *
 * 为什么需要它
 *   `deploy/check_frontend.py` 只做**静态字符串扫描**（有没有某个 id、某个词条），
 *   完全无法发现"渲染函数抛异常"这类问题。
 *
 *   真实踩过的坑：框架徽标一直显示「识别中…」。后端下发了数据、
 *   HTML 有元素、JS 有函数 —— 静态检查全部通过，但运行时抛了异常，
 *   导致徽标停在初始占位文案上。
 *
 * 做法
 *   用最小浏览器桩加载**真实的** i18n.js 与 app.js，
 *   然后用真实的 /api/overview 响应调用渲染函数，捕获任何异常。
 * ========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC_DIR = process.argv[2] || 'static';
const OVERVIEW_JSON = process.argv[3] || null;

let failed = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`  [PASS] ${name}`);
  } else {
    failed++;
    console.log(`  [FAIL] ${name}${detail ? ' — ' + detail : ''}`);
  }
}

// ---------------------------------------------------------------- 最小 DOM 桩
function makeEl(id) {
  const el = {
    id,
    _text: '',
    innerHTML: '',
    title: '',
    className: '',
    style: {},
    children: [],
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      toggle(c, on) { if (on) this._s.add(c); else this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    setAttribute(k, v) { this[k] = v; },
    getAttribute(k) { return this[k]; },
    removeAttribute(k) { delete this[k]; },
    addEventListener() {},
    appendChild(c) { this.children.push(c); return c; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    get firstElementChild() { return this.children[0] || makeEl(id + '-child'); },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
  };
  return el;
}

const elements = new Map();
function el(id) {
  if (!elements.has(id)) elements.set(id, makeEl(id));
  return elements.get(id);
}

// 页面里实际存在的元素（可从 index.html 解析，这里显式列出关键项）
const IDS_IN_PAGE = [
  'accelBadge', 'accelText', 'accelTp', 'modelChip', 'modelFull', 'fwChip', 'fwText',
  'uptime', 'refreshNote', 'langCtl', 'brand', 'kvNote', 'kvRemain', 'kvBar',
  'slotRows', 'alertRows', 'logRows', 'followBtn', 'logHistoryBtn', 'alertLogBtn',
  'badges', 'gpuCards', 'hwPanel', 'selfLine', 'statusPill',
];
for (const id of IDS_IN_PAGE) el(id);

const document = {
  documentElement: { lang: '', setAttribute() {} },
  body: makeEl('body'),
  getElementById: (id) => (IDS_IN_PAGE.includes(id) ? el(id) : null),
  querySelector: (sel) => {
    const m = /^#([\w-]+)$/.exec(sel);
    return m ? document.getElementById(m[1]) : null;
  },
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};

// ---------------------------------------------------------------- 加载真实脚本
const sandbox = {
  console,
  document,
  navigator: { language: 'zh-CN', languages: ['zh-CN', 'zh'] },
  location: { href: 'http://127.0.0.1:8081/', origin: 'http://127.0.0.1:8081' },
  setTimeout, clearTimeout, setInterval, clearInterval,
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }),
  WebSocket: function () { this.close = () => {}; this.send = () => {}; },
  localStorage: {
    _d: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
  },
  requestAnimationFrame: (fn) => setTimeout(fn, 0),
  addEventListener() {},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

function load(rel) {
  const p = path.join(STATIC_DIR, rel);
  const code = fs.readFileSync(p, 'utf8');
  try {
    vm.runInNewContext(code, sandbox, { filename: rel });
    return true;
  } catch (e) {
    check(`${rel} 可加载`, false, `${e.name}: ${e.message}`);
    return false;
  }
}

console.log('=== 1. 加载前端脚本 ===');
const okI18n = load('i18n.js');
const okApp = load('app.js');
check('i18n.js 加载成功', okI18n);
check('app.js 加载成功', okApp);
if (!okI18n || !okApp) {
  console.log(`\nFRONTEND_RENDER_FAILED: 脚本加载失败`);
  process.exit(1);
}
check('I18N 全局可用', typeof sandbox.I18N === 'object');
check('I18N.lang 可用', typeof sandbox.I18N.lang === 'string', String(sandbox.I18N.lang));

console.log('\n=== 2. 关键渲染函数存在 ===');
for (const fn of ['renderTopChips', 'renderFrameworkChip', 'fwSupports']) {
  check(`${fn} 已定义`, typeof sandbox[fn] === 'function');
}

// ---------------------------------------------------------------- 真实数据渲染
const overview = OVERVIEW_JSON && fs.existsSync(OVERVIEW_JSON)
  ? JSON.parse(fs.readFileSync(OVERVIEW_JSON, 'utf8'))
  : {
      accelerator_badge: { present: true, text: 'NVIDIA Tesla V100-SXM2-16GB x2', tensor_parallel: true },
      model: { full_name: 'qwen3-27b.gguf', path: '/srv/models/qwen3-27b.gguf' },
      llama_uptime_s: 23460,
      framework: {
        id: 'llama.cpp',
        name: { zh: 'llama.cpp（llama-server）', en: 'llama.cpp (llama-server)' },
        version: 'b11146',
        build: '7fe450e19',
        version_source: 'http:/props',
        capabilities: ['health', 'metrics', 'models', 'props', 'slots'],
        metrics_prefix: 'llamacpp:',
        note: { zh: '提供 /props 与 /slots', en: 'exposes /props and /slots' },
        confidence: 'exact',
        probes: { '/props': 200 },
      },
    };

console.log('\n=== 3. 用真实数据调用渲染函数（捕获异常）===');
let renderErr = null;
try {
  sandbox.renderTopChips(overview);
} catch (e) {
  renderErr = e;
}
check('renderTopChips 未抛异常', renderErr === null,
  renderErr ? `${renderErr.name}: ${renderErr.message}` : '');

const fwText = el('fwText').textContent;
console.log(`  #fwText 实际内容 = ${JSON.stringify(fwText)}`);
check('框架徽标显示了识别结果', /llama\.cpp/.test(fwText), fwText);
check('框架徽标不再停留于占位文案',
  fwText !== sandbox.I18N.t('top.fw_detecting'), fwText);
check('显示了版本号', /b11146/.test(fwText), fwText);
check('徽标 title 含能力清单',
  el('fwChip').title.includes('slots'), el('fwChip').title);

console.log('\n=== 4. 未识别时的降级行为 ===');
try {
  sandbox.renderTopChips({ ...overview, framework: null });
  check('framework 缺失时不抛异常', true);
  check('framework 缺失时显示占位文案',
    el('fwText').textContent === sandbox.I18N.t('top.fw_detecting'),
    el('fwText').textContent);
  check('framework 缺失时标记 missing', el('fwChip').classList.contains('missing'));
} catch (e) {
  check('framework 缺失时不抛异常', false, `${e.name}: ${e.message}`);
}

console.log('\n=== 5. 英文语言下的显示（模拟整页重载）===');
// 注意：setLang() 是「写 localStorage 后整页重载」，不会在当前页改变语言。
// 因此测试英文必须**新建一个页面上下文**并预设 localStorage —— 这才是真实行为。
function loadPage(store, navLangs) {
  const langs = navLangs || ['en-US', 'en'];
  const els = new Map();
  const mk = (id) => {
    const e = makeEl(id);
    els.set(id, e);
    return e;
  };
  for (const id of IDS_IN_PAGE) mk(id);
  const doc = {
    documentElement: { lang: '', setAttribute() {} },
    body: makeEl('body'),
    getElementById: (id) => els.get(id) || null,
    querySelector: (sel) => {
      const m = /^#([\w-]+)$/.exec(sel);
      return m ? els.get(m[1]) || null : null;
    },
    querySelectorAll: () => [],
    createElement: (tag) => makeEl(tag),
    addEventListener() {},
  };
  const s = {
    console,
    document: doc,
    navigator: { language: langs[0], languages: langs },
    location: { href: 'http://127.0.0.1:8081/', origin: 'http://127.0.0.1:8081' },
    setTimeout, clearTimeout, setInterval, clearInterval,
    fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }),
    WebSocket: function () { this.close = () => {}; this.send = () => {}; },
    localStorage: {
      _d: Object.assign({}, store),
      getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
      setItem(k, v) { this._d[k] = String(v); },
      removeItem(k) { delete this._d[k]; },
    },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    addEventListener() {},
  };
  s.window = s;
  s.globalThis = s;
  vm.runInNewContext(fs.readFileSync(path.join(STATIC_DIR, 'i18n.js'), 'utf8'), s, { filename: 'i18n.js' });
  vm.runInNewContext(fs.readFileSync(path.join(STATIC_DIR, 'app.js'), 'utf8'), s, { filename: 'app.js' });
  return { sandbox: s, els };
}

try {
  const enPage = loadPage({ 'llmconsole.lang': 'en' });
  check('英文页上下文语言为 en', enPage.sandbox.I18N.lang === 'en',
    String(enPage.sandbox.I18N.lang));
  enPage.sandbox.renderTopChips(overview);
  const en = enPage.els.get('fwText').textContent;
  console.log(`  #fwText (en) = ${JSON.stringify(en)}`);
  check('英文下显示英文框架名', /llama\.cpp \(llama-server\)/.test(en), en);
  check('英文下不含中文', !/[\u4e00-\u9fff]/.test(en), en);

  // 中文页上下文：无手动选择 + 浏览器语言为中文
  const zhPage = loadPage({}, ['zh-CN', 'zh']);
  zhPage.sandbox.renderTopChips(overview);
  const zh = zhPage.els.get('fwText').textContent;
  console.log(`  #fwText (zh) = ${JSON.stringify(zh)}`);
  check('中文下显示中文框架名', /（llama-server）/.test(zh), zh);
} catch (e) {
  check('英文渲染不抛异常', false, `${e.name}: ${e.message}`);
}

console.log();
if (failed) {
  console.log(`FRONTEND_RENDER_FAILED: ${failed} 项`);
  process.exit(1);
}
console.log('FRONTEND_RENDER_OK: 框架徽标渲染正常');
