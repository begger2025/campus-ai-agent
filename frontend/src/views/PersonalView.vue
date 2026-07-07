<template>
  <div class="watch-page">
    <!-- 统计（全部来自真实已发布事件） -->
    <div class="stat-row">
      <StatCard title="已发布事件" :value="publishedEvents.length" :icon="Collection" color="primary" desc="事件全链路真实数据" :loading="eventsLoading" />
      <StatCard title="高风险事件" :value="highRiskCount" :icon="Warning" color="danger" desc="需要优先关注" :loading="eventsLoading" />
      <StatCard title="中风险事件" :value="mediumRiskCount" :icon="Bell" color="warning" desc="持续跟踪观察" :loading="eventsLoading" />
      <StatCard title="需关注合计" :value="watchEvents.length" :icon="View" color="teal" desc="已发布的中高风险事件" :loading="eventsLoading" />
    </div>

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

    <!-- 中高风险事件关注列表 -->
    <div class="section-card">
      <div class="section-header">
        <span class="section-title">需关注的舆情事件</span>
        <DataSourceBadge source="real" />
      </div>
      <div class="section-body" v-loading="eventsLoading">
        <div v-if="!watchEvents.length && !eventsLoading" class="calm-empty">
          <el-icon :size="26"><CircleCheckFilled /></el-icon>
          <p>当前没有中高风险的已发布事件</p>
          <span>校园舆情态势平稳</span>
        </div>
        <div v-for="event in watchEvents" :key="event.raw_id ?? event.id" class="watch-row">
          <div class="watch-info">
            <div class="watch-title">{{ event.title }}</div>
            <div class="watch-meta">
              <span :class="['risk-tag', `risk-tag--${event.riskLevel ?? event.risk_level}`]">
                {{ event.riskLabel || riskLabel(event.riskLevel ?? event.risk_level) }}
              </span>
              <span :title="`精确值 ${event.heatScore ?? event.heat_score ?? 0}`">
                热度 {{ formatHeat(event.heatScore ?? event.heat_score ?? 0) }}
              </span>
            </div>
          </div>
          <div class="watch-actions">
            <el-button text size="small" @click="router.push(`/events/${event.raw_id ?? event.id}`)">详情</el-button>
            <el-button text size="small" type="primary" @click="showImpact(event)">影响评估</el-button>
          </div>
        </div>

        <el-button class="agent-cta" @click="goAgentChat('最近有哪些高风险事件？对学生有什么影响？')">
          <el-icon style="margin-right: 6px"><ChatDotRound /></el-icon>
          让舆情助手分析校园风险 →
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, ChatDotRound, CircleCheckFilled, Collection, View, Warning } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { fetchPublishedEvents } from '@/api/events'
import { formatHeat } from '@/utils/heat'

const route = useRoute()
const router = useRouter()

// ------------------------------------------------------------------ 真实舆情关注
const events = ref([])
const eventsLoading = ref(false)

const publishedEvents = computed(() => events.value.filter((e) => (e.status ?? 'published') === 'published'))
const highRiskCount = computed(
  () => publishedEvents.value.filter((e) => (e.riskLevel ?? e.risk_level) === 'high').length,
)
const mediumRiskCount = computed(
  () => publishedEvents.value.filter((e) => (e.riskLevel ?? e.risk_level) === 'medium').length,
)
const watchEvents = computed(() =>
  publishedEvents.value.filter((e) => ['high', 'medium'].includes(e.riskLevel ?? e.risk_level)),
)

function riskLabel(level) {
  return level === 'high' ? '高风险' : level === 'medium' ? '中风险' : '低风险'
}

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
.watch-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1080px;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
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

@media (max-width: 1100px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
