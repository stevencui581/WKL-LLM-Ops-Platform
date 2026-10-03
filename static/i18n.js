/* =====================================================================
 * WKL-LLM运维平台 —— 多语言基础设施（v0.4.3 §4 / TASK-56）
 *
 * 三层策略：
 *   ① 静态文案：HTML 上写 data-i18n="key"，由 applyI18n() 批量替换；
 *   ② 动态文案：JS 里用 t('key', {参数})；
 *   ③ 后端文案：后端只给结构化字段（code / key / value），语言由本文件决定。
 *
 * 语言解析优先级（v0.4.3 §4.1）：
 *   1. 用户手动选择（localStorage）—— 永久优先，不再跟随浏览器；
 *   2. 浏览器语言 —— zh* → 中文；其它 → 英文；
 *   3. 兜底 —— navigator 不可用时用默认语言。
 *
 * 必须同步加载（不要 defer/async），并在 </body> 前调用 applyI18n()，
 * 这样首帧渲染前就完成替换，避免中英闪烁。
 * ===================================================================== */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'llmconsole.lang';
  var FALLBACK = 'zh';           // 探测失败兜底
  var AUTO = 'auto';

  /* ---------------------------------------------------------------- 字典 */
  var DICT = {
    zh: {
      'app.title': 'WKL-LLM运维平台',
      'app.brand': 'WKL-LLM运维平台',

      /* 顶栏 */
      'top.accel': '算力卡',
      'top.model': '模型',
      'top.framework': '框架',
      'top.fw_detecting': '识别中…',
      'top.probing': '探测中…',
      'top.uptime': '服务运行',
      'top.refresh_note': '数据每 2 秒刷新',
      'top.last_refresh': '最后刷新',
      'top.lang_tip': '切换语言',
      'top.tp_on': '张量并行 开',
      'top.tp_off': '张量并行 关',
      'top.refresh_note_fmt': '数据每 {n} 秒刷新',
      'state.reconnecting': '连接断开，重连中',
      'footer.dev': '开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01',
      'footer.dev_fmt': '开发者信息：{dev}　　开发日期：{date}',

      'kv.quant.default': '{v}（默认）',
      'badge.kv_quant': 'KV 量化 {v}',
      'badge.n_ctx': '上下文 {v}K',
      'badge.spec': '投机解码 {v}',
      'badge.spec_off': '投机解码 关闭',
      'badge.draft': 'draft {v}(+1)',
      'badge.flash_on': 'FlashAttn 开',
      'badge.flash_off': 'FlashAttn 关',
      'badge.model_ftype': '模型 {v}',
      'badge.tensor_split': '{n} 卡 tensor-split {s}',
      'badge.metrics_off': '⚠ /metrics 未启用',

      'recent.decode': '生成',
      'recent.total': '共',
      'recent.mtp': 'MTP 接受率',
      'recent.draft': 'draft 平均长',
      'recent.time': '时间',

      'self.line': '控制台自身：CPU {cpu}% · 内存 {rss} MB · 线程 {th} · WS 客户端 {ws} · 运行 {up}',

      'baseline.mtp': 'MTP 基线',
      'baseline.decode': '吞吐基线',
      'baseline.manual': '（人工）',
      'baseline.learning': '学习中',

      'log.backfilled': '已回填 {n} 行',
      'log.buffered': '缓冲 {n} 行',

      /* 状态 */
      'state.connecting': '连接中',
      'state.ok': '服务正常',
      'state.warn': '有告警',
      'state.crit': '严重告警',
      'state.degraded': '降级运行',
      'banner.degraded': '数据源降级：{reasons}',

      /* 降级原因（后端下发 reason_codes，这里本地化） */
      'health.slots_unavailable': '推理服务的 /slots 接口不可用',
      'health.gpu_unavailable': 'nvidia-smi 不可用',
      'health.journal_not_running': 'journalctl 跟随器未运行',

      /* KPI 卡片 */
      'card.decode': '实时解码速率',
      'card.prefill': '上下文填充速度',
      'card.mtp': 'MTP 接受率',
      'card.processing': '生成中请求',
      'card.vram': '显存占用',
      'card.util': 'GPU 利用率',
      'card.temp': 'GPU 温度',
      'card.power': 'GPU 功耗',
      'card.gen': '累计生成 token',
      'card.bw': '显存带宽（近似）',

      'sub.waiting': '等待数据…',
      'sub.decode': '来源：/slots 差分',
      'sub.prefill': '最近一次预填充 {n} tokens',
      'sub.prefill_none': '尚无预填充记录',
      'sub.mtp': 'draft 平均长度 {avg}（上限 {max}）',
      'sub.mtp_none': '尚无投机解码样本',
      'sub.processing': '总槽位 {total} · 排队 {q}',
      'sub.vram': '已用 {pct}% · 剩余 {free} GiB',
      'sub.vram_unknown': '显存容量待探测',
      'sub.util': 'SM 利用率（{n} 卡 · {split}）',
      'sub.temp': '告警线 {warn} °C / {crit} °C',
      'sub.temp_fan': '风扇 {fans} % · 告警线 {warn} °C / {crit} °C',
      'sub.power': '上限 {limit} W / 卡 · 告警 {pct}%',
      'sub.power_unknown': '功耗上限待探测',
      'sub.gen_exact': '来自 /metrics tokens_predicted_total（精确）',
      'sub.gen_estimate': '来自 /slots 估算',
      'sub.gen_unavailable': '需要启用 /metrics',
      'sub.bw': '{mem} 峰值 {bw} GB/s',
      'sub.bw_unknown': '峰值带宽未知（型号未收录）',
      'sub.no_gpu': '该指标无数据（未检测到算力卡）',

      /* KV / 槽位 */
      'kv.title': '推理槽位 · KV 缓存占用',
      'kv.right': 'KV 池 {pct}',
      'kv.pending': '{n} 槽 · 容量待探测',
      'kv.capacity': '{slots} 槽 · 共 {cap} 容量（{mode}）',
      'kv.mode.unified': '-kvu 统一池',
      'kv.mode.per_slot': '每槽独立',
      'kv.mode.unknown': '容量模式未知',
      'kv.remain': '剩余 {n} tokens 可用（输入+输出共享此容量）',
      'kv.hint': 'KV 只增不减：容量到 100% 时才「清空」释放；空闲槽位会存入 prompt cache，新任务时复用。',
      'kv.unsupported': '当前推理框架不提供槽位接口，槽位明细与 KV 容量不可用',
      'panel.unsupported_hint': '这是推理框架的能力差异，不是故障',

      'tbl.slot': '槽位',
      'tbl.state': '状态',
      'tbl.kv_used': 'KV 已用',
      'tbl.ctx': '上下文容量',
      'tbl.source': '来源',

      'slot.generating': '生成中',
      'slot.cached': '缓存待机',
      'slot.idle': '空闲',
      'common.unknown': '未知',

      'recent.title': '最近请求明细',
      'recent.empty': '暂无请求明细',
      'recent.prefill': '预填充 {n} tokens',
      'recent.draft': 'draft 接受 {acc}/{tot}',

      /* 告警 */
      'alerts.title': '告警',
      'alerts.count': '{n} 条',
      'alerts.empty': '当前无告警',
      'alerts.log_btn': '告警日志',
      'alerts.value': '当前值 {v}',

      /* 系统资源 */
      'sys.title': '系统资源',
      'sys.cpu': 'CPU',
      'sys.mem': '内存',
      'sys.load': '负载',
      'sys.swap': '交换',
      'sys.disk': '磁盘',
      'sys.net': '网络',

      /* 硬件与运行环境 */
      'hw.title': '硬件与运行环境',
      'hw.probing': '探测中…',
      'hw.sec1': '① 服务器硬件',
      'hw.sec2': '② 算力卡与依赖环境',
      'hw.sec3': '③ Python 与框架',
      'hw.machine': '整机',
      'hw.bios': 'BIOS',
      'hw.board': '主板',
      'hw.cpu': 'CPU',
      'hw.cpu_spec': 'CPU 规格',
      'hw.cpu_detail': '{sockets} 路 × {cores} 核 = {logical} 逻辑核 · L3 {l3} · NUMA {numa}',
      'hw.cpu_detail_basic': '{sockets} 路 × {cores} 核 = {logical} 逻辑核',
      'hw.mem': '内存',
      'hw.mem_detail': '{total} GiB（可用 {avail}）· Swap {swap} GiB',
      'hw.mem_detail_noswap': '{total} GiB（可用 {avail}）',
      'hw.disk': '磁盘',
      'hw.disk_detail': '{name} {fstype} {size} GiB',
      'hw.disk_used': '已用 {pct}%',
      'hw.accel': '算力卡',
      'hw.accel_detail': '{count} × {model}（{mem} GiB/卡）',
      'hw.no_accel': '未检测到算力卡',
      'hw.model_unknown': '型号未知',
      'hw.compute_cap': '计算能力',
      'hw.bw': '峰值带宽',
      'hw.bw_unknown': '未知（型号未收录）',
      'hw.topo': '卡间拓扑',
      'hw.nvlink_yes': 'NVLink',
      'hw.nvlink_no': '无 NVLink',
      'hw.driver': '驱动',
      'hw.cuda_driver': '驱动支持 CUDA',
      'hw.rocm': 'ROCm',
      'hw.python': 'Python',
      'hw.conda': 'conda',
      'hw.torch': 'PyTorch',
      'hw.torch_missing': '未安装（本机直接调用推理服务，不经过 PyTorch）',
      'hw.installed': '已安装',
      'hw.not_installed': '未安装',
      'hw.age': '{machine} · {n} 秒前探测',
      'hw.unknown_fields': '以下项未能探测（显示为「未知」，不改用默认值）：{list}',
      'hw.hint.NCCL': '多卡通信依赖（未安装时回退框架内置实现）',
      'hw.hint.CUDA Toolkit': 'CUDA 编译与运行工具链',
      'hw.hint.cuDNN': '深度神经网络加速库',
      'hw.hint.NVIDIA Container Toolkit': '容器内使用 GPU 所需（本机未用容器部署）',
      'hw.note.bw_unknown': '型号「{model}」未收录规格表，峰值带宽显示为未知',
      'hw.count_suffix': ' 路',

      /* 服务日志 */
      'log.title': '服务日志',
      'log.level.all': '全部级别',
      'log.level.I': 'I 及以上',
      'log.level.W': 'W 及以上',
      'log.level.E': '仅 E',
      'log.query_ph': '关键字过滤，如 draft acceptance / cancel / truncated',
      'log.follow_on': '跟随：开',
      'log.follow_off': '跟随：关',
      'log.clear': '清空',
      'log.empty': '暂无日志',
      'log.history_btn': '历史服务日志',

      /* 底栏 */

      /* 语言控件 */
      'lang.zh': '中',
      'lang.en': 'EN',
      'lang.auto': '自动（{lang}）',
      'lang.fixed': '已固定（{lang}）',
      'lang.restore': '恢复自动',
      'lang.tip': '点击切换语言；手动选择后长期记住',

      /* 告警日志页 */
      'al.title': '告警日志',
      'al.subtitle': '最近 {n} 条',
      'al.back': '返回控制台',
      'al.col.time': '告警日期时间',
      'al.col.category': '告警服务类型',
      'al.col.name': '告警服务名称',
      'al.col.level': '级别',
      'al.col.message': '内容',
      'al.filter.level': '级别',
      'al.filter.event': '事件',
      'al.level.all': '全部级别',
      'al.level.info': '提示及以上',
      'al.level.warning': '警告及以上',
      'al.level.critical': '仅严重',
      'al.event.all': '全部事件',
      'al.event.raised': '仅产生',
      'al.event.resolved': '仅恢复',
      'al.refresh': '刷新',
      'al.auto': '自动刷新',
      'al.empty': '暂无告警日志',
      'al.empty_hint': '控制台目前未产生过告警；出现告警时会自动记录在这里。',
      'al.returned': '返回 {n} 条 / 共 {total} 条',
      'al.resolved_mark': '已恢复',
      'al.duration': '持续 {n}',
      'al.unavailable': '告警日志不可用',

      /* 历史服务日志页 */
      'lg.title': '历史服务日志',
      'lg.showing': '显示最近 {n} 天日志',
      'lg.back': '返回控制台',
      'lg.days': '天数',
      'lg.day': '{n} 天',
      'lg.live': '实时',
      'lg.live_on': '实时：开',
      'lg.live_off': '实时：关',
      'lg.coverage': '实际覆盖：{from} → {to}（共 {total} 行，已返回 {shown} 行）',
      'lg.coverage_short': '实际覆盖 {n} 天',
      'lg.load_more': '加载更多',
      'lg.download': '下载 .log',
      'lg.empty': '该范围内暂无日志',
      'lg.unavailable': '日志不可用：{err}',
      'lg.new_lines': '↑ {n} 条新日志',
      'lg.live_lost': '实时连接中断，正在重连…',
      'lg.live_hint': '实时新增的行左侧带高亮圆点',
      'lg.truncated': '已达查询上限，仅显示最近 {n} 行；可用「下载」获取完整范围',
      'lg.loading': '加载中…',

      'common.on': '开',
      'common.off': '关'
    },

    en: {
      'app.title': 'WKL-LLM Ops Platform',
      'app.brand': 'WKL-LLM Ops Platform',

      'top.accel': 'Compute card',
      'top.model': 'Model',
      'top.framework': 'Framework',
      'top.fw_detecting': 'detecting...',
      'top.probing': 'probing...',
      'top.uptime': 'Uptime',
      'top.refresh_note': 'refresh every 2s',
      'top.last_refresh': 'Last refresh',
      'top.lang_tip': 'Switch language',
      'top.tp_on': 'Tensor parallel on',
      'top.tp_off': 'Tensor parallel off',
      'top.refresh_note_fmt': 'refresh every {n}s',
      'state.reconnecting': 'Disconnected, reconnecting',
      'footer.dev': 'Developer: WKL-LLM Ops Platform   Release date: 2026.10.01',
      'footer.dev_fmt': 'Developer: {dev}   Release date: {date}',

      'kv.quant.default': '{v} (default)',
      'badge.kv_quant': 'KV quant {v}',
      'badge.n_ctx': 'context {v}K',
      'badge.spec': 'spec decode {v}',
      'badge.spec_off': 'spec decode off',
      'badge.draft': 'draft {v}(+1)',
      'badge.flash_on': 'FlashAttn on',
      'badge.flash_off': 'FlashAttn off',
      'badge.model_ftype': 'model {v}',
      'badge.tensor_split': '{n} cards tensor-split {s}',
      'badge.metrics_off': '⚠ /metrics disabled',

      'recent.decode': 'Decode',
      'recent.total': 'Total',
      'recent.mtp': 'MTP accept',
      'recent.draft': 'draft mean',
      'recent.time': 'Time',

      'self.line': 'Console: CPU {cpu}% - RSS {rss} MB - threads {th} - WS clients {ws} - uptime {up}',

      'baseline.mtp': 'MTP baseline',
      'baseline.decode': 'Throughput baseline',
      'baseline.manual': ' (manual)',
      'baseline.learning': 'learning',

      'log.backfilled': '{n} lines backfilled',
      'log.buffered': '{n} buffered',

      'state.connecting': 'Connecting',
      'state.ok': 'Healthy',
      'state.warn': 'Alerts',
      'state.crit': 'Critical',
      'state.degraded': 'Degraded',
      'banner.degraded': 'Data source degraded: {reasons}',

      'health.slots_unavailable': 'the inference server /slots API is unavailable',
      'health.gpu_unavailable': 'nvidia-smi unavailable',
      'health.journal_not_running': 'journalctl follower not running',

      'card.decode': 'Live decode rate',
      'card.prefill': 'Prompt prefill speed',
      'card.mtp': 'MTP acceptance',
      'card.processing': 'Active requests',
      'card.vram': 'VRAM usage',
      'card.util': 'GPU utilization',
      'card.temp': 'GPU temperature',
      'card.power': 'GPU power',
      'card.gen': 'Tokens generated',
      'card.bw': 'Memory bandwidth (approx.)',

      'sub.waiting': 'waiting for data...',
      'sub.decode': 'source: /slots delta',
      'sub.prefill': 'last prefill {n} tokens',
      'sub.prefill_none': 'no prefill sample yet',
      'sub.mtp': 'draft mean length {avg} (max {max})',
      'sub.mtp_none': 'no speculative sample yet',
      'sub.processing': 'total slots {total} - queued {q}',
      'sub.vram': '{pct}% used - {free} GiB free',
      'sub.vram_unknown': 'VRAM capacity not probed',
      'sub.util': 'SM utilization ({n} cards - {split})',
      'sub.temp': 'thresholds {warn} C / {crit} C',
      'sub.temp_fan': 'fan {fans} % - thresholds {warn} C / {crit} C',
      'sub.power': 'limit {limit} W/card - alert {pct}%',
      'sub.power_unknown': 'power limit not probed',
      'sub.gen_exact': 'from /metrics tokens_predicted_total (exact)',
      'sub.gen_estimate': 'estimated from /slots',
      'sub.gen_unavailable': 'requires /metrics to be enabled',
      'sub.bw': '{mem} peak {bw} GB/s',
      'sub.bw_unknown': 'peak bandwidth unknown (model not in table)',
      'sub.no_gpu': 'no data (no compute card detected)',

      'kv.title': 'Inference slots - KV cache',
      'kv.right': 'KV pool {pct}',
      'kv.pending': '{n} slots - capacity not probed',
      'kv.capacity': '{slots} slots - {cap} total ({mode})',
      'kv.mode.unified': '-kvu unified pool',
      'kv.mode.per_slot': 'per-slot',
      'kv.mode.unknown': 'capacity mode unknown',
      'kv.remain': '{n} tokens remaining (shared by prompt and output)',
      'kv.hint': 'KV only grows: memory is released when usage reaches 100%; idle slots keep a prompt cache reused by new tasks.',
      'kv.unsupported': 'The current inference framework does not expose a slots API; per-slot detail and KV capacity are unavailable',
      'panel.unsupported_hint': 'This is a capability difference between frameworks, not a failure',

      'tbl.slot': 'Slot',
      'tbl.state': 'State',
      'tbl.kv_used': 'KV used',
      'tbl.ctx': 'Context',
      'tbl.source': 'Source',

      'slot.generating': 'generating',
      'slot.cached': 'cached',
      'slot.idle': 'idle',
      'common.unknown': 'unknown',

      'recent.title': 'Recent request detail',
      'recent.empty': 'no request detail yet',
      'recent.prefill': 'prefill {n} tokens',
      'recent.draft': 'draft accepted {acc}/{tot}',

      'alerts.title': 'Alerts',
      'alerts.count': '{n}',
      'alerts.empty': 'No active alerts',
      'alerts.log_btn': 'Alert history',
      'alerts.value': 'current {v}',

      'sys.title': 'System resources',
      'sys.cpu': 'CPU',
      'sys.mem': 'Memory',
      'sys.load': 'Load',
      'sys.swap': 'Swap',
      'sys.disk': 'Disk',
      'sys.net': 'Network',

      'hw.title': 'Hardware & runtime',
      'hw.probing': 'probing...',
      'hw.sec1': '(1) Server hardware',
      'hw.sec2': '(2) Compute cards & dependencies',
      'hw.sec3': '(3) Python & frameworks',
      'hw.machine': 'Machine',
      'hw.bios': 'BIOS',
      'hw.board': 'Motherboard',
      'hw.cpu': 'CPU',
      'hw.cpu_spec': 'CPU spec',
      'hw.cpu_detail': '{sockets} socket(s) x {cores} cores = {logical} logical - L3 {l3} - NUMA {numa}',
      'hw.cpu_detail_basic': '{sockets} socket(s) x {cores} cores = {logical} logical',
      'hw.mem': 'Memory',
      'hw.mem_detail': '{total} GiB ({avail} available) - swap {swap} GiB',
      'hw.mem_detail_noswap': '{total} GiB ({avail} available)',
      'hw.disk': 'Disk',
      'hw.disk_detail': '{name} {fstype} {size} GiB',
      'hw.disk_used': '{pct}% used',
      'hw.accel': 'Compute card',
      'hw.accel_detail': '{count} x {model} ({mem} GiB each)',
      'hw.no_accel': 'No compute card detected',
      'hw.model_unknown': 'model unknown',
      'hw.compute_cap': 'Compute capability',
      'hw.bw': 'Peak bandwidth',
      'hw.bw_unknown': 'unknown (model not in table)',
      'hw.topo': 'Interconnect',
      'hw.nvlink_yes': 'NVLink',
      'hw.nvlink_no': 'no NVLink',
      'hw.driver': 'Driver',
      'hw.cuda_driver': 'Driver CUDA support',
      'hw.rocm': 'ROCm',
      'hw.python': 'Python',
      'hw.conda': 'conda',
      'hw.torch': 'PyTorch',
      'hw.torch_missing': 'not installed (this host calls the inference server directly, without PyTorch)',
      'hw.installed': 'installed',
      'hw.not_installed': 'not installed',
      'hw.age': '{machine} - probed {n}s ago',
      'hw.unknown_fields': 'Not probed (shown as unknown, never substituted): {list}',
      'hw.hint.NCCL': 'required for multi-GPU communication (falls back to the framework built-in implementation)',
      'hw.hint.CUDA Toolkit': 'CUDA build and runtime toolchain',
      'hw.hint.cuDNN': 'deep neural network acceleration library',
      'hw.hint.NVIDIA Container Toolkit': 'needed to use GPUs inside containers (this host does not use containers)',
      'hw.note.bw_unknown': 'model "{model}" is not in the spec table, so peak bandwidth is unknown',
      'hw.count_suffix': ' socket(s)',

      'log.title': 'Service log',
      'log.level.all': 'All levels',
      'log.level.I': 'I and above',
      'log.level.W': 'W and above',
      'log.level.E': 'E only',
      'log.query_ph': 'filter by keyword, e.g. draft acceptance / cancel / truncated',
      'log.follow_on': 'Follow: on',
      'log.follow_off': 'Follow: off',
      'log.clear': 'Clear',
      'log.empty': 'no log lines',
      'log.history_btn': 'Log history',


      'lang.zh': '中',
      'lang.en': 'EN',
      'lang.auto': 'Auto ({lang})',
      'lang.fixed': 'Fixed ({lang})',
      'lang.restore': 'Restore auto',
      'lang.tip': 'Click to switch language; a manual choice is remembered',

      'al.title': 'Alert history',
      'al.subtitle': 'last {n}',
      'al.back': 'Back to console',
      'al.col.time': 'Timestamp',
      'al.col.category': 'Service type',
      'al.col.name': 'Service name',
      'al.col.level': 'Level',
      'al.col.message': 'Detail',
      'al.filter.level': 'Level',
      'al.filter.event': 'Event',
      'al.level.all': 'All levels',
      'al.level.info': 'Info and above',
      'al.level.warning': 'Warning and above',
      'al.level.critical': 'Critical only',
      'al.event.all': 'All events',
      'al.event.raised': 'Raised only',
      'al.event.resolved': 'Resolved only',
      'al.refresh': 'Refresh',
      'al.auto': 'Auto refresh',
      'al.empty': 'No alert history',
      'al.empty_hint': 'No alert has been raised yet; new ones are recorded here automatically.',
      'al.returned': '{n} of {total} shown',
      'al.resolved_mark': 'resolved',
      'al.duration': 'lasted {n}',
      'al.unavailable': 'Alert history unavailable',

      'lg.title': 'Log history',
      'lg.showing': 'Showing logs from the last {n} day(s)',
      'lg.back': 'Back to console',
      'lg.days': 'Range',
      'lg.day': '{n} day(s)',
      'lg.live': 'Live',
      'lg.live_on': 'Live: on',
      'lg.live_off': 'Live: off',
      'lg.coverage': 'Actual coverage: {from} to {to} ({total} lines, {shown} returned)',
      'lg.coverage_short': 'actual coverage {n} day(s)',
      'lg.load_more': 'Load more',
      'lg.download': 'Download .log',
      'lg.empty': 'No logs in this range',
      'lg.unavailable': 'Logs unavailable: {err}',
      'lg.new_lines': '{n} new lines',
      'lg.live_lost': 'Live connection lost, reconnecting...',
      'lg.live_hint': 'Live lines are marked with a dot on the left',
      'lg.truncated': 'Query limit reached, showing the most recent {n} lines; use Download for the full range',
      'lg.loading': 'Loading...',

      'common.on': 'on',
      'common.off': 'off'
    }
  };

  /* ---------------------------------------------------- 语言解析（§4.1） */
  function readStored() {
    try {
      var v = global.localStorage && global.localStorage.getItem(STORAGE_KEY);
      return (v === 'zh' || v === 'en') ? v : null;
    } catch (e) {
      return null;   // 隐私模式等：降级为不记忆
    }
  }

  function browserLangs() {
    try {
      var n = global.navigator;
      if (!n) return [];
      if (n.languages && n.languages.length) return Array.prototype.slice.call(n.languages);
      if (n.language) return [n.language];
    } catch (e) { /* ignore */ }
    return [];
  }

  /** 浏览器语言 → zh / en / null（无法判定）。 */
  function detectBrowserLang() {
    var list = browserLangs();
    if (!list.length) return null;
    for (var i = 0; i < list.length; i++) {
      var tag = String(list[i] || '').toLowerCase();
      if (tag.indexOf('zh') === 0) return 'zh';
      if (tag.indexOf('en') === 0) return 'en';
    }
    // 既不是中文也不是英文（ja/de/...）→ 按方案回退英文
    return 'en';
  }

  function resolveLang() {
    var stored = readStored();
    if (stored) return stored;                      // ① 手动优先
    var detected = detectBrowserLang();
    if (detected && DICT[detected]) return detected; // ② 浏览器语言
    return DICT[FALLBACK] ? FALLBACK : 'en';         // ③ 兜底
  }

  var LANG = resolveLang();
  var MANUAL = readStored() !== null;

  /* ---------------------------------------------------------------- 取值 */
  function t(key, params) {
    var table = DICT[LANG] || DICT.zh;
    var s = table[key];
    if (s === undefined) {
      s = DICT.zh[key];
      if (s === undefined) {
        if (global.console && console.warn) console.warn('[i18n] missing key:', key);
        return key;
      }
    }
    if (params) {
      s = s.replace(/\{(\w+)\}/g, function (m, name) {
        return (params[name] === undefined || params[name] === null) ? m : String(params[name]);
      });
    }
    return s;
  }

  /* ------------------------------------------------------------ 应用文案 */
  function applyI18n(root) {
    var scope = root || global.document;
    if (!scope) return;
    var nodes = scope.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = t(nodes[i].getAttribute('data-i18n'));
    }
    var ph = scope.querySelectorAll('[data-i18n-placeholder]');
    for (var j = 0; j < ph.length; j++) {
      ph[j].setAttribute('placeholder', t(ph[j].getAttribute('data-i18n-placeholder')));
    }
    var ti = scope.querySelectorAll('[data-i18n-title]');
    for (var k = 0; k < ti.length; k++) {
      ti[k].setAttribute('title', t(ti[k].getAttribute('data-i18n-title')));
    }
    var opts = scope.querySelectorAll('[data-i18n-option]');
    for (var m = 0; m < opts.length; m++) {
      opts[m].textContent = t(opts[m].getAttribute('data-i18n-option'));
    }
    if (global.document && global.document.documentElement) {
      global.document.documentElement.lang = (LANG === 'zh') ? 'zh-CN' : 'en';
      global.document.documentElement.setAttribute('data-lang', LANG);
    }
    if (global.document) global.document.title = t('app.title');
  }

  /* ---------------------------------------------------------- 语言切换 */
  function setLang(lang) {
    if (lang !== 'zh' && lang !== 'en') return;
    try {
      if (global.localStorage) global.localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) { /* ignore */ }
    // 重新加载保证三个页面完全一致，避免局部残留
    if (global.location && global.location.reload) global.location.reload();
  }

  function restoreAuto() {
    try {
      if (global.localStorage) global.localStorage.removeItem(STORAGE_KEY);
    } catch (e) { /* ignore */ }
    if (global.location && global.location.reload) global.location.reload();
  }

  function langLabel(code) {
    return code === 'en' ? t('lang.en') : t('lang.zh');
  }

  /* ------------------------------------------- 告警目录（后端为唯一事实源） */
  var CATALOG = null;
  var CATALOG_PENDING = null;

  function loadCatalog() {
    if (CATALOG) return Promise.resolve(CATALOG);
    if (CATALOG_PENDING) return CATALOG_PENDING;
    CATALOG_PENDING = fetch('/api/alert-catalog', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        CATALOG = (d && d.data && d.data.codes) ? d.data.codes : {};
        return CATALOG;
      })
      .catch(function () { CATALOG = {}; return CATALOG; });
    return CATALOG_PENDING;
  }

  function _pick(obj, lang) {
    if (!obj) return '';
    if (typeof obj === 'string') return obj;
    return obj[lang] || obj.zh || obj.en || '';
  }

  function alertCategory(code) {
    var e = CATALOG && CATALOG[code];
    return e ? _pick(e.category, LANG) : '';
  }

  function alertName(code) {
    var e = CATALOG && CATALOG[code];
    // 目录未加载或未知代码：显示代码本身（不编造名称）
    return e ? _pick(e.name, LANG) : code;
  }

  /* ------------------------------------------------------------ 语言控件 */
  function renderLangControl(el) {
    if (!el) return;
    var html = '<button class="langbtn' + (LANG === 'zh' ? ' on' : '') +
      '" data-lang-btn="zh">' + t('lang.zh') + '</button>' +
      '<span class="langsep">/</span>' +
      '<button class="langbtn' + (LANG === 'en' ? ' on' : '') +
      '" data-lang-btn="en">' + t('lang.en') + '</button>';
    var state = MANUAL
      ? '<span class="langstate">' + t('lang.fixed', { lang: langLabel(LANG) }) +
        ' <a href="#" class="langrestore" data-lang-restore="1">' + t('lang.restore') + '</a></span>'
      : '<span class="langstate">' + t('lang.auto', { lang: langLabel(LANG) }) + '</span>';
    el.innerHTML = html + state;
    el.setAttribute('title', t('lang.tip'));
    var btns = el.querySelectorAll('[data-lang-btn]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () { setLang(this.getAttribute('data-lang-btn')); });
    }
    var rs = el.querySelector('[data-lang-restore]');
    if (rs) rs.addEventListener('click', function (e) { e.preventDefault(); restoreAuto(); });
  }

  global.I18N = {
    t: t,
    applyI18n: applyI18n,
    setLang: setLang,
    restoreAuto: restoreAuto,
    renderLangControl: renderLangControl,
    loadCatalog: loadCatalog,
    alertCategory: alertCategory,
    alertName: alertName,
    DICT: DICT
  };
  // lang / isManual 必须是**取值器**而不是值拷贝：
  // setLang() 改的是闭包里的 LANG，若这里写成 `lang: LANG`，
  // 导出的永远是加载那一刻的语言 —— 切换语言后其它模块拿到的还是旧值。
  // 真实后果：框架徽标按错误语言取名字，切到英文仍显示中文名。
  Object.defineProperty(global.I18N, 'lang', {
    get: function () { return LANG; },
    enumerable: true
  });
  Object.defineProperty(global.I18N, 'isManual', {
    get: function () { return MANUAL; },
    enumerable: true
  });
  global.t = t;   // 便捷别名

  // <head> 内同步执行：先定语言与 <html lang>，再尽早替换 <title>
  if (global.document && global.document.documentElement) {
    global.document.documentElement.lang = (LANG === 'zh') ? 'zh-CN' : 'en';
    global.document.documentElement.setAttribute('data-lang', LANG);
  }
})(window);
