<template>
  <div class="watch-page">
    <!-- 四张统计卡已移除（2026-07-14）：「已发布事件 / 高风险 / 中风险」在**首页**已经有一份，
         「需关注合计」不过是前两者之和。三处展示同一组数字，是页面重叠的典型症状。
         这一页的职责是**处置**（中高风险事件的跟进清单 + 影响评估），不是再做一次仪表盘。
         见 docs/page-responsibilities.md。 -->

    <!-- 事件影响评估（从事件详情页 ?event_id= 跳转，全部真实字段） -->
    <div v-if="impactEvent" class="section-card impact-card">
      <div class="section-header">
        <span class="section-title">事件影响评估</span>
        <el-button text size="small" @click="closeImpact">关闭</el-button>
      </div>
      <div class="section-body">
        <div class="impact-head">
          <div class="impact-event-title">
            <span class="impact-label">关联事件</span>
            <strong>{{ impactEvent.title }}</strong>
            <span :class="['risk-tag', `risk-tag--${impactRisk}`]">{{ impactRiskLabel }}</span>
          </div>
        </div>

        <p v-if="impactEvent.summary" class="impact-summary">{{ impactEvent.summary }}</p>

        <div v-if="impactConcerns.length" class="impact-actions-section">
          <div class="impact-section-label">数据中反映的关注点</div>
          <ul>
            <li v-for="(item, i) in impactConcerns" :key="i">{{ item }}</li>
          </ul>
        </div>

        <div v-if="impactRiskReasons.length" class="impact-actions-section">
          <div class="impact-section-label">风险依据</div>
          <ul>
            <li v-for="(item, i) in impactRiskReasons" :key="i">{{ item }}</li>
          </ul>
        </div>

        <div class="impact-footer">
          <el-button size="small" @click="router.push(`/events/${impactEvent.raw_id ?? impactEvent.id}`)">
            查看事件详情
          </el-button>
          <el-button size="small" type="primary" @click="askAgentAboutImpact">
            问舆情助手：对我有什么影响 →
          </el-button>
        </div>
      </div>
    </div>

    <div class="watch-grid">
      <!-- ========== 左：处置队列（按四轴优先级排，不是按热度） ========== -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">
            处置队列
            <el-tooltip :content="PRIORITY_TOOLTIP" placement="top" :show-after="150">
              <el-icon class="title-info" :size="13"><InfoFilled /></el-icon>
            </el-tooltip>
          </span>
          <DataSourceBadge source="real" />
        </div>
        <div class="section-body" v-loading="eventsLoading">
          <div v-if="!watchEvents.length && !eventsLoading" class="calm-empty">
            <el-icon :size="26"><CircleCheckFilled /></el-icon>
            <p>当前没有中高风险的已发布事件</p>
            <span>校园舆情态势平稳</span>
          </div>

          <div v-for="(event, index) in watchEvents" :key="eventKey(event)" class="queue-row">
            <span :class="['queue-rank', { 'queue-rank--done': isSettled(event) }]">{{ index + 1 }}</span>

            <div class="queue-info">
              <div class="queue-title">{{ event.title }}</div>

              <div class="queue-meta">
                <span :class="['risk-tag', `risk-tag--${riskOf(event)}`]">{{ riskLabel(riskOf(event)) }}</span>
                <span
                  v-if="hasLifecycle(event.lifecycle)"
                  :class="['lifecycle-tag', `lifecycle-tag--${event.lifecycle}`]"
                  :title="event.lifecycle_reason || ''"
                >{{ lifecycleLabel(event.lifecycle) }}</span>
                <span class="queue-age" :class="{ 'queue-age--stale': isStale(event.age_days) }">
                  {{ formatAge(event.age_days) }}
                </span>
                <span class="queue-heat">热度 {{ formatHeat(event.heat_score ?? event.heatScore ?? 0) }}</span>
              </div>

              <!-- 「凭什么它排第一」：四轴分解，当场可复核。
                   这一页此前按**热度**排——于是「中大课间缩短争议」（已了结、校方已致歉）
                   排在第一位，而悬而未决的「康某论文调查」排第二。热度是"多少人在看"，
                   不是"我该先动哪个"。 -->
              <div v-if="event.priority_breakdown" class="queue-why">
                <b>{{ event.priority_score.toFixed(2) }}</b>
                = 严重性 {{ event.priority_breakdown.severity }}
                × 时效 {{ event.priority_breakdown.recency.toFixed(3) }}
                × 状态 {{ event.priority_breakdown.lifecycle }}
              </div>

              <p v-if="event.lifecycle_reason" class="queue-reason">{{ event.lifecycle_reason }}</p>
            </div>

            <div class="queue-actions">
              <el-button text size="small" @click="router.push(`/opinion?event_id=${eventKey(event)}`)">研判</el-button>
              <el-button text size="small" type="primary" @click="showImpact(event)">影响评估</el-button>
            </div>
          </div>

          <el-button class="agent-cta" @click="goAgentChat('最近有哪些高风险事件？对学生有什么影响？')">
            <el-icon style="margin-right: 6px"><ChatDotRound /></el-icon>
            让舆情助手分析校园风险 →
          </el-button>
        </div>
      </div>

      <!-- ========== 右：处置态势 ========== -->
      <div class="insight-col">
        <!-- 状态看板：哪些口子还开着 -->
        <div class="section-card">
          <div class="section-header">
            <span class="section-title">处置状态</span>
          </div>
          <div class="section-body">
            <div v-for="bucket in lifecycleBuckets" :key="bucket.key" class="bucket-row">
              <span :class="['bucket-dot', `bucket-dot--${bucket.key}`]"></span>
              <span class="bucket-label">{{ bucket.label }}</span>
              <div class="bucket-track">
                <span
                  :class="['bucket-fill', `bucket-fill--${bucket.key}`]"
                  :style="{ width: pct(bucket.count, watchEvents.length) }"
                ></span>
              </div>
              <span class="bucket-count">{{ bucket.count }}</span>
            </div>
            <p class="bucket-note">
              「悬而未决」是 LLM 读完帖子给出的<b>判断</b>（还有什么事没了结），
              不是关键词匹配——它让这些事件在排序里抗住时效衰减。
            </p>
          </div>
        </div>

        <!-- 诉求聚合：LLM 从成员帖里提炼的 concerns，不是词频 -->
        <div class="section-card">
          <div class="section-header">
            <span class="section-title">
              学生诉求聚合
              <el-tooltip :content="CONCERN_TOOLTIP" placement="top" :show-after="150">
                <el-icon class="title-info" :size="13"><InfoFilled /></el-icon>
              </el-tooltip>
            </span>
            <span class="section-count">{{ concernRanking.length }} 类</span>
          </div>
          <div class="section-body">
            <div v-if="!concernRanking.length" class="calm-empty calm-empty--tight">
              <p>暂无可聚合的诉求</p>
            </div>
            <!-- 词云式：字号跟着"有几个事件在提" -->
            <div class="concern-cloud">
              <span
                v-for="item in concernRanking"
                :key="item.text"
                class="concern-word"
                :style="concernStyle(item.count)"
                :title="`${item.count} 个中高风险事件提到「${item.text}」`"
                @click="goAgentChat(`学生在${item.text}方面有哪些诉求？`)"
              >{{ item.text }}</span>
            </div>
          </div>
        </div>

        <!-- 风险依据汇总：LLM 判高/中风险的理由，全摊开 -->
        <div class="section-card">
          <div class="section-header">
            <span class="section-title">风险依据汇总</span>
            <span class="section-count">{{ riskReasonList.length }} 条</span>
          </div>
          <div class="section-body">
            <ol class="reason-list">
              <li v-for="item in riskReasonList" :key="item.key">
                <span :class="['risk-dot', `risk-dot--${item.risk}`]"></span>
                <span class="reason-text">{{ item.reason }}</span>
                <em>{{ item.title }}</em>
              </li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, CircleCheckFilled, InfoFilled } from '@element-plus/icons-vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { fetchPublishedEvents } from '@/api/events'
import { formatHeat } from '@/utils/heat'
import { formatAge, isStale } from '@/utils/age'
import { hasLifecycle, lifecycleLabel } from '@/utils/lifecycle'

const route = useRoute()
const router = useRouter()

// —— 页面职责：中高风险 × **处置** ——
//
// 「有哪些事件」是事件列表的活，「这件事怎么回事」是工作台的活。这一页只回答一个问题：
// **我该先动哪个，凭什么。**（见 docs/page-responsibilities.md）
//
// 它此前是「事件列表 filter(中高风险)」——难怪和别的页重叠：它没有自己的动词。

const PRIORITY_TOOLTIP =
  '按四轴优先级排序：严重性(LLM研判) × 时效性(算术衰减) × 生命周期(LLM研判"这事完了没有")。' +
  '不按热度排——热度是"多少人在看"，不是"我该先动哪个"。'

const CONCERN_TOOLTIP =
  '关注点由 LLM 从每个事件的成员帖里提炼（"学生在要求什么"），再按有几个事件提到它来聚合。' +
  '这不是词频统计——词频回答"哪个词出现得多"，提炼回答"大家在诉求什么"。'

// ------------------------------------------------------------------ 数据
const events = ref([])
const eventsLoading = ref(false)

const publishedEvents = computed(() => events.value.filter((e) => (e.status ?? 'published') === 'published'))

function riskOf(event) {
  return event.riskLevel ?? event.risk_level ?? 'low'
}

function eventKey(event) {
  return event.raw_id ?? event.id
}

function riskLabel(level) {
  return level === 'high' ? '高风险' : level === 'medium' ? '中风险' : '低风险'
}

// 已了结 / 不适用 = 不需要再动的（排在队尾，序号灰掉）
function isSettled(event) {
  return ['resolved', 'not_applicable'].includes(event.lifecycle)
}

// —— 处置队列：按**四轴优先级**排，不是按热度 ——
//
// 实测（真库）两种排序的差别，正是这一页存在的理由：
//
//     按热度   1. 中大课间缩短争议  ← **已了结**（校方已致歉、暂停问卷）
//              2. 中大康某论文调查
//     按优先级 1. 中大康某论文调查  ← 悬而未决，高风险，两个月还没结论
//              2. 耿同学举报副院长  ← 悬而未决
//              ...
//              8. 刘一阳去世（340 天前，not_applicable）
//
// 一个叫「需关注」的清单，把热度最高但**已经处理完**的事排在第一位——那不是关注，
// 那是噪声。四轴优先级早就算好了（后端 priority_score），这一页此前没用。
const watchEvents = computed(() =>
  publishedEvents.value
    .filter((e) => ['high', 'medium'].includes(riskOf(e)))
    .slice()
    .sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0)),
)

// —— 处置状态看板：哪些口子还开着 ——
const LIFECYCLE_BUCKETS = [
  { key: 'escalating', label: '持续发酵' },
  { key: 'ongoing', label: '悬而未决' },
  { key: 'resolved', label: '已了结' },
  { key: 'not_applicable', label: '无需处置' },
]

const lifecycleBuckets = computed(() =>
  LIFECYCLE_BUCKETS.map((bucket) => ({
    ...bucket,
    count: watchEvents.value.filter((e) => e.lifecycle === bucket.key).length,
  })).filter((bucket) => bucket.count > 0),
)

function pct(count, total) {
  return total ? `${Math.round((count / total) * 100)}%` : '0%'
}

// —— 诉求聚合：LLM 提炼的 concerns，按"有几个事件在提"排 ——
// 不是词频词云：词频回答"哪个词出现得多"（算术），提炼回答"大家在诉求什么"（判断）。
const concernRanking = computed(() => {
  const counts = new Map()
  watchEvents.value.forEach((event) => {
    ;(event.concerns || []).forEach((text) => {
      const key = String(text || '').trim()
      if (key) counts.set(key, (counts.get(key) || 0) + 1)
    })
  })
  return [...counts.entries()]
    .map(([text, count]) => ({ text, count }))
    .sort((a, b) => b.count - a.count || a.text.localeCompare(b.text))
})

const maxConcern = computed(() => Math.max(...concernRanking.value.map((c) => c.count), 1))

// 词云的字号/浓度跟着"有几个事件在提"走——一个只有一个事件提到的诉求，不该和三个
// 事件共同指向的诉求长得一样大。
function concernStyle(count) {
  const ratio = count / maxConcern.value
  return {
    fontSize: `${12 + ratio * 10}px`,
    fontWeight: ratio > 0.6 ? 700 : 500,
    opacity: 0.55 + ratio * 0.45,
  }
}

// —— 风险依据汇总：LLM 判高/中风险的理由，全摊开（按优先级序，高风险在前） ——
const riskReasonList = computed(() =>
  watchEvents.value.flatMap((event) =>
    (event.risk_reasons || []).map((reason, i) => ({
      key: `${eventKey(event)}-${i}`,
      reason,
      title: event.title,
      risk: riskOf(event),
    })),
  ),
)

onMounted(async () => {
  eventsLoading.value = true
  try {
    events.value = await fetchPublishedEvents()
  } finally {
    eventsLoading.value = false
  }
})

// ------------------------------------------------------------------ 事件影响评估（真实字段）
const impactEvent = ref(null)

const impactRisk = computed(() => impactEvent.value?.riskLevel ?? impactEvent.value?.risk_level ?? 'low')
const impactRiskLabel = computed(() => riskLabel(impactRisk.value))

function parseJsonList(value) {
  if (Array.isArray(value)) return value
  try {
    const parsed = JSON.parse(value || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const impactConcerns = computed(() =>
  impactEvent.value ? parseJsonList(impactEvent.value.concerns ?? impactEvent.value.concerns_json) : [],
)
const impactRiskReasons = computed(() =>
  impactEvent.value
    ? parseJsonList(impactEvent.value.risk_reasons ?? impactEvent.value.risk_reasons_json)
    : [],
)

function showImpact(event) {
  impactEvent.value = event
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function closeImpact() {
  impactEvent.value = null
  if (route.query.event_id) router.replace({ query: {} })
}

function askAgentAboutImpact() {
  const topic = (impactEvent.value?.topic || impactEvent.value?.title || '').slice(0, 12)
  goAgentChat(`${topic}这件事对学生有什么影响？需要注意什么？`)
}

function goAgentChat(question = '') {
  router.push(question ? { path: '/agent-chat', query: { q: question } } : '/agent-chat')
}

// 从事件详情页 ?event_id= 跳转进来时定位事件
watch(
  () => route.query.event_id,
  async (eventId) => {
    if (!eventId) {
      impactEvent.value = null
      return
    }
    try {
      const all = events.value.length ? events.value : await fetchPublishedEvents()
      if (!events.value.length) events.value = all
      impactEvent.value =
        all.find((e) => String(e.raw_id ?? '').replace(/^EVT-/i, '') === String(eventId).replace(/^EVT-/i, '')
          || String(e.id) === String(eventId)) || null
    } catch {
      impactEvent.value = null
    }
  },
  { immediate: true },
)
</script>

<style scoped>
/* max-width 1080 去掉了：这一页原本是一根窄柱子居左，右边一大片空白——用户看到的
   「中间空太多」就是它。改成两栏（左队列 / 右态势），版面才用得起来。 */
.watch-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.watch-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 1fr);
  gap: 16px;
  align-items: start;
}

.insight-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.title-info { margin-left: 4px; color: var(--color-text-faint); cursor: help; vertical-align: -1px; }
.section-count { font-size: 12px; color: var(--color-text-muted); }

/* —— 处置队列 —— */
.queue-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  margin-bottom: 8px;
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.queue-row:hover { border-color: var(--color-border); box-shadow: var(--shadow-xs); }

.queue-rank {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: var(--brand-500);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

/* 已了结 / 无需处置：序号灰掉——它还在队列里（可复核），但不该抢注意力 */
.queue-rank--done { background: var(--color-border); color: var(--color-text-muted); }

.queue-info { flex: 1; min-width: 0; }
.queue-title { font-size: 13.5px; font-weight: 600; color: var(--color-text); }

.queue-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 5px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.queue-age--stale { color: var(--color-danger); font-weight: 600; }
.queue-heat { font-variant-numeric: tabular-nums; }

/* 四轴分解：「凭什么它排第一」当场可复核 */
.queue-why {
  margin-top: 6px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
  font-size: 11.5px;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.queue-why b { color: var(--brand-700); font-size: 12.5px; }

.queue-reason {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.queue-actions { flex-shrink: 0; display: flex; align-items: center; }

.lifecycle-tag {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.lifecycle-tag--escalating { background: var(--color-danger-bg); color: var(--color-danger-text); }
.lifecycle-tag--ongoing { background: var(--color-warning-bg); color: var(--color-warning-text); }
.lifecycle-tag--resolved { background: var(--color-success-bg); color: var(--color-success-text); }
.lifecycle-tag--not_applicable { background: var(--color-surface-2); color: var(--color-text-muted); }

/* —— 处置状态看板 —— */
.bucket-row {
  display: grid;
  grid-template-columns: 8px 64px 1fr 24px;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
}

.bucket-dot { width: 8px; height: 8px; border-radius: 50%; }
.bucket-dot--escalating { background: var(--color-danger); }
.bucket-dot--ongoing { background: var(--color-warning); }
.bucket-dot--resolved { background: var(--color-success); }
.bucket-dot--not_applicable { background: var(--color-border); }

.bucket-label { color: var(--color-text-secondary); }
.bucket-track { height: 6px; border-radius: 999px; background: var(--color-surface-2); overflow: hidden; }
.bucket-fill { display: block; height: 100%; border-radius: 999px; }
.bucket-fill--escalating { background: var(--color-danger); }
.bucket-fill--ongoing { background: var(--color-warning); }
.bucket-fill--resolved { background: var(--color-success); }
.bucket-fill--not_applicable { background: var(--color-border); }
.bucket-count { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }

.bucket-note {
  margin: 10px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.bucket-note b { color: var(--color-text-secondary); font-weight: 600; }

/* —— 诉求聚合（词云式；字号跟着"有几个事件在提"走） —— */
.concern-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  line-height: 1.9;
}

.concern-word {
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  background: var(--brand-50);
  color: var(--brand-700);
  border: 1px solid var(--brand-100);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.concern-word:hover {
  background: var(--brand-100);
  transform: translateY(-1px);
}

/* —— 风险依据汇总 —— */
.reason-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 320px;
  overflow-y: auto;
}

.reason-list li {
  display: grid;
  grid-template-columns: 8px 1fr;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--color-border-light);
  font-size: 12px;
  line-height: 1.6;
}

.reason-list li:last-child { border-bottom: 0; }

.risk-dot { width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; }
.risk-dot--high { background: var(--color-danger); }
.risk-dot--medium { background: var(--color-warning); }

.reason-text { color: var(--color-text-secondary); }

.reason-list em {
  display: block;
  grid-column: 2;
  margin-top: 2px;
  font-style: normal;
  font-size: 11px;
  color: var(--color-text-muted);
}

.calm-empty--tight { padding: 14px 0; }

@media (max-width: 1180px) {
  .watch-grid { grid-template-columns: 1fr; }
}

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-xs);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 18px;
  border-bottom: 1px solid var(--color-border-light);
}

.section-title {
  font-size: 14px;
  font-weight: 600;
}

.section-body {
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* —— 舆情关注 —— */
.watch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.watch-row:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-xs);
}

.watch-title {
  font-size: 13px;
  font-weight: 500;
}

.watch-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 4px;
}

.watch-actions {
  display: flex;
  align-items: center;
}

.agent-cta {
  margin-top: 6px;
}

.calm-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 26px 0;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted);
}

.calm-empty .el-icon { color: var(--color-success); }
.calm-empty p { margin: 2px 0 0; font-weight: 500; color: var(--color-text-secondary); }
.calm-empty span { font-size: 12px; color: var(--color-text-faint); }

.risk-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
}

.risk-tag--high { background: var(--color-danger-bg); color: var(--color-danger-text); }
.risk-tag--medium { background: var(--color-warning-bg); color: var(--color-warning-text); }
.risk-tag--low { background: var(--color-success-bg); color: var(--color-success-text); }

/* —— 影响评估 —— */
.impact-card {
  border-color: #ecd9ae;
  background: linear-gradient(180deg, var(--color-warning-bg) 0%, var(--color-surface) 56px);
}

.impact-event-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.impact-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.impact-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
}

.impact-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 6px;
}

.impact-actions-section ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
}

.impact-footer {
  display: flex;
  gap: 10px;
}

</style>
