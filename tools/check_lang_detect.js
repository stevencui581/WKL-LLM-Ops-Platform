/* =====================================================================
 * 语言解析行为验证（v0.4.3 §4.1 / TASK-61）
 *
 *   node tools/check_lang_detect.js [static/i18n.js]
 *
 * 在 Node 里用最小浏览器桩真实执行 i18n.js，断言解析优先级：
 *   ① 手动选择优先于浏览器语言
 *   ② 浏览器 zh* → 中文；其它语言 → 英文
 *   ③ navigator 不可用时兜底中文
 *
 * 目标 上没有 Node，因此该检查在 selfcheck 中会跳过；
 * 发布前需在开发机上单独跑一次（本脚本即为此准备）。
 * ===================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');

const target = process.argv[2] || path.join(__dirname, '..', 'static', 'i18n.js');
const SRC = fs.readFileSync(target, 'utf8');

function makeWindow(stored, langs) {
  const store = {};
  if (stored) store['llmconsole.lang'] = stored;
  return {
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = v; },
      removeItem: (k) => { delete store[k]; }
    },
    navigator: langs === null ? undefined : { languages: langs, language: langs[0] },
    location: { reload: () => {} },
    console: console,
    document: null
  };
}

function run(stored, langs) {
  const w = makeWindow(stored, langs);
  const fn = new Function('window', 'global', SRC + '\nreturn window.I18N;');
  const i18n = fn(w, w);
  return { lang: i18n.lang, manual: i18n.isManual, ok: i18n.t('state.ok'), accel: i18n.t('top.accel') };
}

const cases = [
  // [localStorage, navigator.languages, 期望语言, 期望是否手动, 说明]
  [null, ['zh-CN', 'zh'], 'zh', false, '中文浏览器 -> 中文'],
  [null, ['zh-TW'], 'zh', false, '繁体中文也归中文'],
  [null, ['en-US', 'en'], 'en', false, '英文浏览器 -> 英文'],
  [null, ['ja-JP'], 'en', false, '日文 -> 回退英文'],
  [null, ['de-DE'], 'en', false, '德文 -> 回退英文'],
  [null, [], 'zh', false, '语言列表为空 -> 兜底中文'],
  [null, null, 'zh', false, 'navigator 不可用 -> 兜底中文'],
  ['en', ['zh-CN'], 'en', true, '手动选英文优先于中文浏览器'],
  ['zh', ['en-US'], 'zh', true, '手动选中文优先于英文浏览器']
];

let bad = 0;
for (const [stored, langs, wantLang, wantManual, note] of cases) {
  let got;
  try {
    got = run(stored, langs);
  } catch (e) {
    console.log('FAIL  ' + note + ' -> 抛异常: ' + e.message);
    bad++;
    continue;
  }
  const ok = got.lang === wantLang && got.manual === wantManual;
  if (!ok) bad++;
  console.log(
    (ok ? 'PASS' : 'FAIL') + '  ' + note +
    '  [stored=' + JSON.stringify(stored) + ' browser=' + JSON.stringify(langs) + ']' +
    ' -> ' + got.lang + ' manual=' + got.manual +
    ' (want ' + wantLang + '/' + wantManual + ')'
  );
}

// 英文模式下不得出现中文（抽查几个关键文案）
const en = run('en', ['en-US']);
if (/[\u4e00-\u9fff]/.test(en.ok) || /[\u4e00-\u9fff]/.test(en.accel)) {
  console.log('FAIL  英文模式文案含中文: ' + en.ok + ' / ' + en.accel);
  bad++;
} else {
  console.log('PASS  英文模式关键文案无中文: "' + en.ok + '" / "' + en.accel + '"');
}

// 算力卡术语（甲方指定 compute card）
if (en.accel.toLowerCase() !== 'compute card') {
  console.log('FAIL  算力卡英文应为 compute card，实际: ' + en.accel);
  bad++;
} else {
  console.log('PASS  算力卡英文 = compute card');
}

console.log(bad === 0 ? 'LANGDETECT_OK' : 'LANGDETECT_FAILED:' + bad);
process.exit(bad === 0 ? 0 : 1);
