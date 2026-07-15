<template>
  <div class="opinion-page">
    <!-- 工具栏：关键词/来源本地筛选 + 跳转真实 Agent -->
    <div class="toolbar panel-card">
      <el-input
        v-model="keyword"
        clearable
        placeholder="筛选事件（如：食堂、停电、考试）"
        class="toolbar-search"
      />
      <el-select v-model="selectedSources" multiple placeholder="来源平台" class="toolbar-sources" clearable>
        <el-option v-for="s in sourceOptions" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" @click="goAgentChat()">用舆情助手深入分析 →</el-button>
      <DataSourceBadge source="real" />
    </div>

    <!-- 三栏主体 -->
    <div class="three-col">
      <!-- 左栏：热点事件列表 -->
      <section class="panel-card col-left">
        <div class="panel-header">
          <span class="panel-title">热点事件</span>
          <span class="panel-count">{{ filteredEvents.length }} 条</span>
        </div>
        <div class="panel-body scroll-body">
          <div
            v-for="(event, idx) in filteredEvents"
            :key="event.id"
            :class="['event-row', { 'event-row--active': selectedId === event.id }]"
            @click="selectEvent(event)"
          >
            <span class="event-rank" :class="rankClass(idx)">{{ idx + 1 }}</span>
            <div class="event-text">
              <div class="event-row-title">{{ event.title }}</div>
              <div class="event-row-meta">
                <span :class="['risk-tag', `risk-tag--${event.risk_level}`]">{{ riskLabel(event.risk_level) }}</span>
                <!-- 中段数字（热度·来源·时龄）合为一段弹性文本，空间不足时整体省略，保证两侧色标签不被挤断 -->
                <span class="event-row-stats">
                  <span :title="`精确值 ${event.heat_score}`">{{ formatHeat(event.heat_score) }}</span>
                  <span>· {{ event.source_count }}源</span>
                  <!-- 年龄要看得见：列表已按时效性排序，但陈旧事件不能"默默"留在列表里冒充新闻。 -->
                  <span
                    :class="['event-age', { 'event-age--stale': isStale(event.age_days) }]"
                    :title="event.event_time ? `事件代表时间（成员帖发布时间中位数）：${formatEventTime(event.event_time)}` : '该事件没有可用的发布时间'"
                  >· {{ formatAge(event.age_days) }}</span>
                </span>
                <!-- 状态要看得见：一个 3.5 个月前的火情排第 4、一个 2 个月前的举报排第 1，
                     光看年龄解释不了这个顺序——管理员有权一眼看到「已了结」还是「悬而未决」。
                     未研判（LLM 关掉/失败/老数据）时不显示徽标：不知道结没结 ≠ 已经结了。 -->
                <span
                  v-if="hasLifecycle(event.lifecycle)"
                  :class="['lifecycle-tag', `lifecycle-tag--${event.lifecycle}`]"
                  :title="lifecycleTitle(event.lifecycle, event.lifecycle_reason, event.growth)"
                >{{ lifecycleLabel(event.lifecycle) }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 中栏：事件研判详情 -->
      <section class="panel-card col-mid">
        <div class="panel-header">
          <span class="panel-title">事件研判详情</span>
          <el-button v-if="selectedEvent" text size="small" @click="openDetail">查看完整详情 →</el-button>
        </div>
        <div class="panel-body scroll-body">
          <template v-if="selectedEvent">
            <div class="detail-header">
              <h2>{{ selectedEvent.title }}</h2>
              <span :class="['risk-tag', `risk-tag--${selectedEvent.risk_level}`]">{{ riskLabel(selectedEvent.risk_level) }}</span>
              <span
                v-if="hasLifecycle(selectedEvent.lifecycle)"
                :class="['lifecycle-tag', `lifecycle-tag--${selectedEvent.lifecycle}`]"
                :title="lifecycleTitle(selectedEvent.lifecycle, selectedEvent.lifecycle_reason, selectedEvent.growth)"
              >{{ lifecycleLabel(selectedEvent.lifecycle) }}</span>
            </div>

            <p class="detail-summary">{{ selectedEvent.summary }}</p>

            <div class="detail-metrics">
              <el-tooltip :content="`${HEAT_TOOLTIP}。精确值：${selectedEvent.heat_score}`" placement="top" :show-after="150">
                <div class="metric-item metric-item--help">
                  <strong>{{ formatHeat(selectedEvent.heat_score) }}</strong>
                  <span>热度 · {{ heatLevel(selectedEvent.heat_score).label }}</span>
                </div>
              </el-tooltip>
              <div class="metric-item">
                <strong>{{ selectedEvent.confidence?.toFixed(2) ?? '—' }}</strong>
                <span>置信度</span>
              </div>
              <div class="metric-item">
                <strong>{{ selectedEvent.source_count }}</strong>
                <span>来源数</span>
              </div>
              <div class="metric-item metric-item--text">
                <strong>{{ sentimentLabel(selectedEvent.sentiment) }}</strong>
                <span>情感倾向</span>
              </div>
            </div>

            <!-- ============ 这一段是工作台的立身之本：AI 研判的「凭什么」 ============
                 事件列表回答"有哪些事件"，工作台回答"**这件事到底怎么回事、凭什么这么判**"。
                 下面每一块都是一次可追问的研判，而不是一个不容置疑的结论。 -->

            <!-- ① 排序：凭什么它排第一 —— 四根正交轴的乘积，每根都能单独解释 -->
            <div v-if="breakdown" class="detail-section">
              <h3>
                展示优先级
                <span class="section-hint">四轴乘积 · 决定它在列表里排第几</span>
              </h3>
              <div class="axis-row">
                <div class="axis-chip">
                  <strong>{{ breakdown.severity }}</strong>
                  <span>严重性</span>
                  <em>{{ riskLabel(selectedEvent.risk_level) }} · LLM 研判</em>
                </div>
                <span class="axis-op">×</span>
                <div class="axis-chip">
                  <strong>{{ breakdown.recency.toFixed(3) }}</strong>
                  <span>时效性</span>
                  <em>{{ formatAge(selectedEvent.age_days) }} · 算术衰减</em>
                </div>
                <span class="axis-op">×</span>
                <div class="axis-chip">
                  <strong>{{ breakdown.lifecycle }}</strong>
                  <span>生命周期</span>
                  <em>{{ hasLifecycle(selectedEvent.lifecycle) ? lifecycleLabel(selectedEvent.lifecycle) : '未研判' }}</em>
                </div>
                <span class="axis-op">=</span>
                <div class="axis-chip axis-chip--result">
                  <strong>{{ breakdown.score.toFixed(2) }}</strong>
                  <span>优先级</span>
                  <em>排序键</em>
                </div>
              </div>
              <p class="axis-note">
                严重性与热度<b>不被时间打折</b>（火灾不会因为过了三个月变得不严重）；
                时效性与生命周期只影响<b>顺序</b>。生命周期未研判时因子为 1.0，逐位退化回两轴排序。
              </p>
            </div>

            <!-- ② 风险：凭什么判成高风险 —— LLM 给的依据，原样摆出来 -->
            <div v-if="riskReasons.length" class="detail-section">
              <h3>
                风险依据
                <span :class="['risk-tag', `risk-tag--${selectedEvent.risk_level}`]">{{ riskLabel(selectedEvent.risk_level) }}</span>
                <span class="section-hint">LLM 研判 · 不是规则算的</span>
              </h3>
              <ol class="reason-list">
                <li v-for="(reason, i) in riskReasons" :key="i">{{ reason }}</li>
              </ol>
            </div>

            <!-- ③ 状态：凭什么说它还没完 —— 判断（一句话理由）+ 测量（一组时间戳） -->
            <div v-if="hasLifecycle(selectedEvent.lifecycle) || growthText" class="detail-section">
              <h3>
                事件状态
                <span
                  v-if="hasLifecycle(selectedEvent.lifecycle)"
                  :class="['lifecycle-tag', `lifecycle-tag--${selectedEvent.lifecycle}`]"
                >{{ lifecycleLabel(selectedEvent.lifecycle) }}</span>
              </h3>
              <!-- 「悬而未决」是**判断**：模型读完帖子，说出还有什么事没了结。 -->
              <p v-if="selectedEvent.lifecycle_reason" class="evidence-line">
                <span class="evidence-kind evidence-kind--llm">判断</span>
                {{ selectedEvent.lifecycle_reason }}
              </p>
              <!-- 「还在发酵」是**测量**：新帖还在不在来，成员帖的时间戳就摆在那儿。
                   不问 LLM——问它「这件事还在扩大吗」，和问它「这条帖子有多火」是同一类错误。 -->
              <p v-if="growthText" class="evidence-line">
                <span class="evidence-kind evidence-kind--math">测量</span>
                {{ growthText }}
              </p>
            </div>

            <!-- ④ 关注点：模型从帖子里提炼的诉求 -->
            <div v-if="concerns.length" class="detail-section">
              <h3>
                关注点
                <span class="section-hint">LLM 从成员帖里提炼</span>
              </h3>
              <div class="concern-tags">
                <span v-for="c in concerns" :key="c" class="tag">{{ c }}</span>
              </div>
            </div>

            <!-- ⑤ 代表帖子：**可溯源**。原本这里只显示三个光秃秃的数字 ID（4 365 334）——
                 那是主键，不是证据。研判的每一句话都该能点回原帖。 -->
            <div class="detail-section">
              <h3>
                代表帖子
                <span class="section-hint">共 {{ selectedEvent.source_count }} 条 · 展示热度前 {{ representatives.length }}</span>
              </h3>
              <div v-if="detailLoading" class="rep-loading">加载中…</div>
              <ol v-else-if="representatives.length" class="rep-list">
                <li v-for="post in representatives" :key="post.processed_post_id || post.raw_post_id">
                  <a v-if="isSafeUrl(post.url)" :href="post.url" target="_blank" rel="noopener">{{ post.title || '（无标题）' }}</a>
                  <span v-else>{{ post.title || '（无标题）' }}</span>
                  <em>{{ post.platform }} · {{ post.author || '匿名' }}</em>
                </li>
              </ol>
              <p v-else class="rep-empty">该事件没有可展示的代表帖。</p>
            </div>

            <div class="detail-actions">
              <el-button type="primary" @click="navigateToImpact(selectedEvent)">查看对我的影响 →</el-button>
              <el-button @click="openDetail(selectedEvent)">查看完整详情</el-button>
            </div>
          </template>

          <div v-else class="empty-state">
            <el-icon class="empty-icon" :size="34"><Pointer /></el-icon>
            <p>请从左侧列表选择一个事件</p>
            <p class="empty-hint">或在上方搜索栏输入关键词开始分析</p>
          </div>
        </div>
      </section>

      <!-- 右栏：跳转真实舆情助手 -->
      <section class="panel-card col-right">
        <div class="panel-header">
          <span class="panel-title">智能问答</span>
          <el-tag size="small" type="success">LLM 驱动</el-tag>
        </div>
        <div class="panel-body agent-guide">
          <p class="guide-intro">
            对事件有疑问？舆情助手基于真实数据回答，支持热点、风险、简报和多步推理对比分析。
          </p>
          <div class="guide-questions">
            <span class="suggest-label">试试这样问：</span>
            <button
              v-for="q in suggestQuestions"
              :key="q"
              type="button"
              class="guide-question"
              @click="goAgentChat(q)"
            >
              {{ q }}
            </button>
          </div>
          <el-button type="primary" class="guide-cta" @click="goAgentChat()">
            打开舆情助手 →
          </el-button>
          <p class="guide-note">复杂问题（多话题对比）由 ReAct 多步推理完成，耗时约 1~2 分钟。</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Pointer } from '@element-plus/icons-vue'
import { formatHeat, heatLevel, HEAT_TOOLTIP } from '@/utils/heat'
import { formatAge, formatEventTime, isStale } from '@/utils/age'
import { growthEvidence, hasLifecycle, lifecycleLabel, lifecycleTitle } from '@/utils/lifecycle'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { sourceOptions } from '@/constants/eventOptions'
import { fetchEventDetail, fetchPublishedEvents } from '@/api/events'

const router = useRouter()
const route = useRoute()

// —— 页面职责 ——
// 舆情工作台 = **单事件 × 研判**：回答"这件事到底怎么回事、**凭什么这么判**"。
// （"有哪些事件"是事件列表的活；"数据在说什么"是舆情分析的活。见 docs/page-responsibilities.md）
//
// 所以这一页的中栏必须把 AI 研判的**证据链**全摆出来：
//     排序     四轴分解（严重性 × 时效性 × 生命周期 = 优先级）
//     风险     LLM 给的依据（不是规则算的）
//     状态     判断（模型的一句话理由）+ 测量（成员帖时间戳算出来的发酵证据）
//     关注点   模型从帖子里提炼的诉求
//     代表帖   **可点回原帖**——改造前这里只显示三个光秃秃的数字主键（4 365 334）

// —— 搜索 & 筛选（纯本地过滤，真实分析走舆情助手） ——
const keyword = ref('')
const selectedSources = ref([])

// —— 事件数据 ——
const events = ref([])
const selectedId = ref('')

// 列表接口不返回 risk_reasons / concerns / 代表帖标题（只有 raw json 串和一串主键），
// 选中一个事件才去取它的完整详情——研判证据要的就是这些。
const detail = ref(null)
const detailLoading = ref(false)

const selectedEvent = computed(() => events.value.find(e => e.id === selectedId.value) || null)

const breakdown = computed(() => selectedEvent.value?.priority_breakdown || null)

// 详情里的解析好的字段；详情还没到时优雅地空着（列表项已经把标题/风险/热度撑起来了）
const riskReasons = computed(() => detail.value?.risk_reasons || [])
const concerns = computed(() => detail.value?.concerns || [])
const representatives = computed(() => detail.value?.representative_posts || [])

// 「还在发酵」是算出来的：近 N 天几条 / 一共几条 / 速率。不止 escalating 时才该看见——
// 一个「已了结」的事件如果新帖还在来，那本身就是要复核的信号。
const growthText = computed(() => growthEvidence(selectedEvent.value?.growth))

const filteredEvents = computed(() => {
  const kw = keyword.value.trim()
  return events.value.filter((event) => {
    if (kw && !`${event.title}${event.summary || ''}${event.topic || ''}`.includes(kw)) return false
    if (selectedSources.value.length) {
      const platforms = event.sourcePlatforms || event.source_platforms || []
      if (!selectedSources.value.some((s) => platforms.includes(s))) return false
    }
    return true
  })
})

const suggestQuestions = computed(() => {
  if (!selectedEvent.value) return ['最近有哪些高风险事件？', '给我一份校园舆情简报']
  const topic = (selectedEvent.value.topic || selectedEvent.value.title || '').slice(0, 10)
  return [`${topic}大家怎么看？`, `${topic}有什么风险吗？`, '对比一下各话题哪个风险更高？']
})

onMounted(loadEvents)

async function loadEvents() {
  try {
    events.value = await fetchPublishedEvents()
    if (!events.value.length) return
    // 从事件列表点「研判」跳过来时带着 ?event_id=——直接选中那一条（列表找 → 工作台研判）
    const wanted = String(route.query.event_id || '')
    const target =
      events.value.find((e) => String(e.raw_id) === wanted || String(e.id) === wanted) ||
      events.value[0]
    selectEvent(target)
  } catch {
    ElMessage.warning('事件数据加载失败，请刷新页面重试')
  }
}

// —— 选择事件：拉它的完整研判证据 ——
async function selectEvent(event) {
  selectedId.value = event.id
  detail.value = null
  detailLoading.value = true
  const requested = event.id
  try {
    const data = await fetchEventDetail(event.raw_id ?? event.id)
    // 用户可能在请求飞行途中点了别的事件——晚到的响应不许覆盖当前选中项
    if (selectedId.value === requested) detail.value = data
  } catch {
    // 详情拿不到不影响列表和四轴分解（那些来自列表接口）——证据区留空，不弹错。
    if (selectedId.value === requested) detail.value = null
  } finally {
    if (selectedId.value === requested) detailLoading.value = false
  }
}

function resetFilters() {
  keyword.value = ''
  selectedSources.value = []
}

// —— 跳转真实舆情助手（可带预填问题） ——
function goAgentChat(question = '') {
  router.push(question ? { path: '/agent-chat', query: { q: question } } : '/agent-chat')
}

// —— 导航 ——
function openDetail(event) {
  if (event?.id) router.push(`/events/${event.id}`)
}

function navigateToImpact(event) {
  if (event?.id) router.push(`/personal?event_id=${event.id}`)
}

// —— 显示辅助 ——
function riskLabel(level) {
  const map = { high: '高风险', medium: '中风险', low: '低风险' }
  return map[level] || level
}

function riskClass(level) {
  if (level === 'high') return 'badge-high'
  if (level === 'medium') return 'badge-mid'
  return 'badge-low'
}

function rankClass(idx) {
  if (idx === 0) return 'rank-1'
  if (idx === 1) return 'rank-2'
  if (idx === 2) return 'rank-3'
  return ''
}

function sentimentLabel(s) {
  const map = { positive: '正向', negative: '负向', neutral: '中性', controversial: '争议' }
  return map[s] || s || '—'
}

// 代表帖链接来自爬取数据，只放行 http(s)，防 javascript: 一类伪协议
function isSafeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//.test(url)
}
</script>

<style scoped>
/* ——— AI 研判证据区（工作台的立身之本） ——— */
.section-hint {
  margin-left: 8px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted);
}

/* 四轴分解：严重性 × 时效性 × 生命周期 = 优先级 */
.axis-row {
  display: flex;
  align-items: stretch;
  gap: 6px;
  flex-wrap: wrap;
}

.axis-chip {
  flex: 1;
  min-width: 76px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 8px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
}

.axis-chip strong {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.axis-chip span {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.axis-chip em {
  font-style: normal;
  font-size: 10.5px;
  color: var(--color-text-muted);
}

.axis-chip--result {
  border-color: var(--brand-300);
  background: var(--brand-50);
}

.axis-chip--result strong { color: var(--brand-700); }

.axis-op {
  align-self: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.axis-note {
  margin: 8px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.axis-note b { color: var(--color-text-secondary); font-weight: 600; }

/* 风险依据（LLM 给的理由） */
.reason-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.reason-list li::marker { color: var(--brand-500); font-weight: 600; }

/* 证据行：判断（LLM）vs 测量（算术）——两种东西，两种标记 */
.evidence-line {
  margin: 0 0 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.evidence-kind {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
}

.evidence-kind--llm {
  background: var(--brand-50);
  color: var(--brand-700);
  border: 1px solid var(--brand-100);
}

.evidence-kind--math {
  background: var(--color-success-bg);
  color: var(--color-success-text);
  border: 1px solid #c8e5d0;
}

.concern-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* 代表帖：可点回原帖（改造前这里是三个光秃秃的数字主键） */
.rep-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.7;
}

.rep-list li::marker { color: var(--brand-500); }

.rep-list a {
  color: var(--brand-600);
  text-decoration: none;
}

.rep-list a:hover { text-decoration: underline; }

.rep-list em {
  display: block;
  font-style: normal;
  font-size: 11px;
  color: var(--color-text-muted);
}

.rep-loading,
.rep-empty {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 定高（不是 min-height）：把三栏锁进视口高度，各栏内部滚动、底部持平，
   而不是让最长的左栏把整页撑成长长一条 */
.opinion-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}

/* ——— 工具栏 ——— */
.toolbar {
  height: 56px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.toolbar-search { width: 240px; }
.toolbar-sources { width: 200px; }
.toolbar-search :deep(.el-input__wrapper),
.toolbar-sources :deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 6px;
}

/* ——— 三栏 ——— */
.three-col {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 280px 1fr 320px;
  gap: 10px;
}

.col-left, .col-mid, .col-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.panel-header {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border-light);
}

.panel-title { font-size: 15px; font-weight: 600; }
.panel-count { font-size: 12px; color: var(--color-text-muted); }
.panel-body { flex: 1; min-height: 0; padding: 10px; }
.scroll-body { overflow-y: auto; }

/* ——— 左栏：事件列表 ——— */
.event-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 4px;
}

.event-row:hover { background: var(--color-surface-2); }
.event-row--active {
  background: var(--brand-50);
}

.event-rank {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #eef1f7;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.rank-1 { background: var(--color-danger); color: #fff; }
.rank-2 { background: #c8830f; color: #fff; }
.rank-3 { background: #d3a04b; color: #fff; }

.event-text { flex: 1; min-width: 0; }
.event-row-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-row-meta {
  margin-top: 4px;
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 5px;
  font-size: 11px;
  color: var(--color-text-muted);
  min-width: 0;
}

/* 两侧色标签固定尺寸不被挤断；中段数字承担收缩 */
.event-row-meta > .risk-tag,
.event-row-meta > .lifecycle-tag {
  flex-shrink: 0;
}

.event-row-stats {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-row-stats > span {
  white-space: nowrap;
}

.risk-tag {
  display: inline-block;
  padding: 0 5px;
  height: 18px;
  line-height: 18px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.risk-tag--high { color: var(--color-danger-text); background: var(--color-danger-bg); border: 1px solid #f4c2c4; }
.risk-tag--medium { color: var(--color-warning-text); background: var(--color-warning-bg); border: 1px solid #ecd9ae; }
.risk-tag--low { color: var(--color-success-text); background: var(--color-success-bg); border: 1px solid #c8e5d0; }

/* 事件年龄：陈旧的（>= 90 天）标黄，用户一眼看得出这不是今天的舆情 */
.event-age { color: var(--color-text-muted); }
.event-age--stale { color: var(--color-warning-text); font-weight: 600; }

/* 事件状态（第四根轴）：已了结 / 非事件 = 灰（学校不必动作）；悬而未决/持续发酵 = 醒目（口子还开着）。
   「非事件」比「已了结」还要淡一档：它连"曾经是一件事"都不是（咨询/攻略/分享）。 */
.lifecycle-tag {
  display: inline-block;
  padding: 0 5px;
  height: 18px;
  line-height: 18px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  cursor: help;
}

.lifecycle-tag--resolved { color: var(--color-text-muted); background: var(--color-fill-2, #f2f3f5); border: 1px solid #dcdfe6; }
.lifecycle-tag--ongoing { color: var(--color-warning-text); background: var(--color-warning-bg); border: 1px solid #ecd9ae; }
.lifecycle-tag--escalating { color: var(--color-danger-text); background: var(--color-danger-bg); border: 1px solid #f4c2c4; }
.lifecycle-tag--not_applicable { color: var(--color-text-muted); background: transparent; border: 1px dashed #dcdfe6; font-weight: 500; }

.detail-lifecycle {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* 「持续发酵」的算术证据：等宽字体，因为它是一组**可以复核的数字**，不是一句判词。 */
.detail-growth {
  margin: -6px 0 12px;
  font-size: 12px;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  color: var(--color-text-muted);
}

/* ——— 中栏：事件详情 ——— */
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.detail-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
  line-height: 1.45;
}

.detail-summary {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.7;
  margin: 0 0 16px;
}

.detail-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.metric-item {
  padding: 10px 8px;
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  text-align: center;
}

.metric-item strong {
  display: block;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text);
}

/* 风险等级是文本不是量值，降一档字号 */
.metric-item--text strong {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.metric-item--help {
  cursor: help;
}

.metric-item span {
  display: block;
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.detail-section {
  margin-bottom: 14px;
}

.detail-section h3 {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin: 0 0 6px;
}

.sentiment-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.sentiment--negative { color: var(--color-danger-text); background: var(--color-danger-bg); }
.sentiment--positive { color: var(--color-success-text); background: var(--color-success-bg); }
.sentiment--neutral { color: var(--color-text-muted); background: #eef1f7; }
.sentiment--controversial { color: var(--color-warning-text); background: var(--color-warning-bg); }

.source-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.source-pid {
  padding: 2px 8px;
  background: var(--brand-50);
  color: var(--brand-700);
  border-radius: 4px;
  font-size: 11px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
}
.source-more {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 22px;
}

.detail-actions {
  margin-top: 18px;
  display: flex;
  gap: 10px;
}

/* ——— 空状态 ——— */
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
}

.empty-icon { color: var(--color-text-faint); margin-bottom: 12px; }
.empty-state p { margin: 0; font-size: 14px; }
.empty-hint { font-size: 12px !important; margin-top: 4px !important; }

/* —— 右栏：舆情助手引导 —— */
.agent-guide {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 14px;
}

.guide-intro {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text);
}

.guide-questions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.suggest-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.guide-question {
  border: 1px solid var(--color-border-light);
  background: var(--color-bg);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 12px;
  color: var(--color-primary);
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.guide-question:hover {
  border-color: var(--brand-300);
  background: var(--brand-50);
}

.guide-cta {
  align-self: stretch;
}

.guide-note {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ——— 右栏：Agent 聊天 ——— */
.chat-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
  max-height: 420px;
}

.chat-bubble { max-width: 86%; }
.chat-left { align-self: flex-start; }
.chat-right { align-self: flex-end; }

.chat-role {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 2px;
}

.chat-text {
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  line-height: 1.6;
}

.chat-left .chat-text { background: var(--color-surface-2); color: var(--color-text-secondary); }
.chat-right .chat-text { background: var(--brand-600); color: #fff; }

.chat-suggest {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
}

.suggest-label { font-size: 11px; color: var(--color-text-muted); }

.chat-input-row {
  display: flex;
  gap: 8px;
}

.chat-input-row :deep(.el-input__wrapper) { border-radius: 6px; }

@media (max-width: 1200px) {
  .three-col { grid-template-columns: 1fr; }
  .col-left, .col-right { max-height: 240px; }
}
</style>
