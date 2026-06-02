<template>
  <section class="events-page">
    <div class="event-filter panel-card">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索事件标题、关键词、来源"
        class="filter-search"
        @keyup.enter="applyFilters"
      />
      <el-select v-model="filters.risk" class="filter-select">
        <el-option label="风险等级：全部" value="all" />
        <el-option v-for="item in riskOptions" :key="item.value" :label="`风险等级：${item.label}`" :value="item.value" />
      </el-select>
      <el-select v-model="filters.source" class="filter-select">
        <el-option label="来源平台：全部" value="all" />
        <el-option v-for="item in sourceOptions" :key="item.value" :label="`来源平台：${item.label}`" :value="item.value" />
      </el-select>
      <el-select v-model="filters.timeRange" class="filter-select">
        <el-option label="时间范围：近7天" value="7d" />
        <el-option label="时间范围：近24小时" value="24h" />
        <el-option label="时间范围：近30天" value="30d" />
      </el-select>
      <el-select v-model="filters.sortBy" class="filter-select">
        <el-option label="排序：热度优先" value="heat" />
        <el-option label="排序：时间优先" value="time" />
        <el-option label="排序：风险优先" value="risk" />
      </el-select>
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button class="workbench-btn" @click="router.push('/opinion')">进入舆情工作台 →</el-button>
    </div>

    <div class="risk-tabs panel-card">
      <button
        v-for="item in quickTabs"
        :key="item.value"
        type="button"
        :class="['risk-tab', { 'risk-tab--active': filters.quick === item.value }]"
        @click="setQuick(item.value)"
      >
        <span>{{ item.label }}</span>
        <strong :class="item.value">{{ item.count }}</strong>
      </button>
    </div>

    <div class="events-layout">
      <section class="panel-card event-list-card">
        <div class="compact-panel-title">公开事件</div>
        <div class="table-shell compact-table-wrap" v-loading="loading">
          <table class="compact-table">
            <thead>
              <tr>
                <th class="col-title">事件标题</th>
                <th>风险</th>
                <th class="heat-head">热度 ↓</th>
                <th>来源</th>
                <th>发布时间</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="event in pagedEvents"
                :key="event.id"
                :class="{ 'row-active': selectedEvent?.id === event.id }"
                @click="selectEvent(event)"
              >
                <td class="title-cell">
                  <span>{{ event.title }}</span>
                </td>
                <td>
                  <span :class="['badge', riskClass(event.riskLevel)]">{{ event.riskLabel }}</span>
                </td>
                <td class="heat-cell">{{ event.heatScore }}</td>
                <td>
                  <div class="source-list">
                    <span v-for="source in event.sourcePlatforms.slice(0, 2)" :key="source" :class="['source-pill', `source-${source}`]">
                      {{ sourceLabel(source) }}
                    </span>
                  </div>
                </td>
                <td>{{ displayTime(event.updatedAt) }}</td>
                <td>
                  <span class="published-dot"></span>
                  已发布
                </td>
                <td class="action-cell">
                  <button type="button" @click.stop="openDetail(event)">查看详情</button>
                  <button type="button" @click.stop="openFeedback(event)">反馈</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="table-footer">
          <span>共 {{ filteredEvents.length }} 条</span>
          <el-pagination
            v-model:current-page="pagination.page"
            v-model:page-size="pagination.pageSize"
            background
            layout="prev, pager, next"
            :page-sizes="[10]"
            :total="filteredEvents.length"
          />
          <el-select v-model="pagination.pageSize" class="page-size-select">
            <el-option label="10条/页" :value="10" />
          </el-select>
        </div>
      </section>

      <aside class="panel-card event-preview-card">
        <div class="preview-header">
          <span>事件预览</span>
        </div>

        <div v-if="selectedEvent" class="preview-content">
          <div class="preview-title-row">
            <h2>{{ selectedEvent.title }}</h2>
            <span :class="['badge', riskClass(selectedEvent.riskLevel)]">{{ selectedEvent.riskLabel }}</span>
          </div>
          <p class="preview-summary">{{ selectedEvent.summary }}</p>

          <div class="preview-stats">
            <div>
              <strong>{{ selectedEvent.heatScore }}</strong>
              <span>热度</span>
            </div>
            <div>
              <strong>{{ selectedEvent.representativeCount }}</strong>
              <span>代表内容</span>
            </div>
            <div>
              <strong>{{ selectedEvent.confidence.toFixed(2) }}</strong>
              <span>置信度</span>
            </div>
            <div>
              <strong>{{ displayTime(selectedEvent.updatedAt).replace('今天 ', '') }}</strong>
              <span>最近更新</span>
            </div>
          </div>

          <div class="preview-tags">
            <span class="preview-label">关联标签</span>
            <div>
              <span v-for="tag in selectedEvent.tags.slice(0, 3)" :key="tag" class="tag tag-blue">{{ tag }}</span>
            </div>
          </div>

          <div class="preview-actions">
            <el-button type="primary" @click="openDetail(selectedEvent)">查看详情</el-button>
            <el-button @click="openFeedback(selectedEvent)">提交反馈</el-button>
            <el-button @click="router.push('/opinion')">返回工作台</el-button>
          </div>

          <div class="preview-bottom">
            <section>
              <h3>热度趋势（近7天）</h3>
              <svg viewBox="0 0 280 144" class="mini-chart">
                <line x1="18" y1="118" x2="260" y2="118" class="axis-line" />
                <polyline :points="trendLine" class="trend-line" />
                <circle v-for="point in trendPoints" :key="point.label" :cx="point.x" :cy="point.y" r="3.5" class="trend-point" />
              </svg>
            </section>
            <section>
              <h3>来源分布</h3>
              <div class="source-breakdown">
                <div v-for="item in sourceBreakdown" :key="item.value">
                  <span :class="['source-icon', `source-icon-${item.value}`]">{{ sourceShort(item.value) }}</span>
                  <span>{{ sourceLabel(item.value) }}</span>
                  <strong>{{ item.percent }}%</strong>
                </div>
              </div>
            </section>
          </div>
        </div>
      </aside>
    </div>

    <div class="event-footnote">
      <DataSourceBadge source="mock" style="margin-right:10px" />
      仅展示已发布事件 · 管理员审核请前往后台 <button type="button" @click="router.push('/admin/events')">/admin/events</button>
    </div>

    <EventFeedbackDialog v-model="feedbackVisible" :event="feedbackEvent" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import EventFeedbackDialog from '@/components/EventFeedbackDialog.vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { fetchPublishedEvents } from '@/api/events'
import { riskOptions, sourceOptions } from '@/mock/events'

const router = useRouter()

const loading = ref(false)
const events = ref([])
const selectedId = ref('')
const feedbackVisible = ref(false)
const feedbackEvent = ref(null)

const filters = reactive({
  keyword: '',
  risk: 'all',
  source: 'all',
  timeRange: '7d',
  sortBy: 'heat',
  quick: 'all',
})

const pagination = reactive({
  page: 1,
  pageSize: 10,
})

const riskWeight = {
  high: 3,
  medium: 2,
  low: 1,
}

const publishedEvents = computed(() => events.value.filter((event) => event.status === 'published'))
const latestTime = computed(() => {
  const times = publishedEvents.value.map((event) => parseTime(event.updatedAt)).filter(Boolean)
  return times.length ? Math.max(...times) : Date.now()
})

const highRiskCount = computed(() => publishedEvents.value.filter((event) => event.riskLevel === 'high').length)
const mediumRiskCount = computed(() => publishedEvents.value.filter((event) => event.riskLevel === 'medium').length)
const lowRiskCount = computed(() => publishedEvents.value.filter((event) => event.riskLevel === 'low').length)
const todayCount = computed(() => publishedEvents.value.filter((event) => isLatestDay(event.updatedAt)).length)

const quickTabs = computed(() => [
  { label: '全部', value: 'all', count: publishedEvents.value.length },
  { label: '高风险', value: 'high', count: highRiskCount.value },
  { label: '中风险', value: 'medium', count: mediumRiskCount.value },
  { label: '低风险', value: 'low', count: lowRiskCount.value },
  { label: '今日新增', value: 'today', count: todayCount.value },
])

const filteredEvents = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  const rangeMs = timeRangeToMs(filters.timeRange)

  const rows = publishedEvents.value.filter((event) => {
    const keywordMatched = !keyword || [event.title, event.summary, event.id, ...event.tags, ...event.sourcePlatforms]
      .join(' ')
      .toLowerCase()
      .includes(keyword)
    const riskMatched = filters.risk === 'all' || event.riskLevel === filters.risk
    const sourceMatched = filters.source === 'all' || event.sourcePlatforms.includes(filters.source)
    const timeMatched = !rangeMs || latestTime.value - parseTime(event.updatedAt) <= rangeMs
    const quickMatched =
      filters.quick === 'all' ||
      event.riskLevel === filters.quick ||
      (filters.quick === 'today' && isLatestDay(event.updatedAt))

    return keywordMatched && riskMatched && sourceMatched && timeMatched && quickMatched
  })

  return [...rows].sort((a, b) => {
    if (filters.sortBy === 'time') return parseTime(b.updatedAt) - parseTime(a.updatedAt)
    if (filters.sortBy === 'risk') return riskWeight[b.riskLevel] - riskWeight[a.riskLevel] || b.heatScore - a.heatScore
    return b.heatScore - a.heatScore
  })
})

const pagedEvents = computed(() => {
  const start = (pagination.page - 1) * pagination.pageSize
  return filteredEvents.value.slice(start, start + pagination.pageSize)
})

const selectedEvent = computed(() => {
  return filteredEvents.value.find((event) => event.id === selectedId.value) || pagedEvents.value[0] || null
})

const trendPoints = computed(() => {
  const trend = selectedEvent.value?.trend || []
  if (!trend.length) return []
  const maxHeat = Math.max(...trend.map((item) => item.heat), 1)
  const step = 240 / Math.max(trend.length - 1, 1)
  return trend.map((item, index) => ({
    label: item.label,
    x: 20 + index * step,
    y: 118 - (item.heat / maxHeat) * 92,
  }))
})

const trendLine = computed(() => trendPoints.value.map((point) => `${point.x},${point.y}`).join(' '))

const sourceBreakdown = computed(() => {
  const sources = selectedEvent.value?.sourcePlatforms || []
  const weights = { weibo: 56.2, xhs: 28.1, tieba: 15.7 }
  return sources.map((value, index) => ({
    value,
    percent: weights[value] || Math.max(12, Math.round(100 / (index + 2))),
  }))
})

watch(
  () => [pagination.page, filteredEvents.value.length],
  () => {
    if (pagination.page > Math.max(1, Math.ceil(filteredEvents.value.length / pagination.pageSize))) {
      pagination.page = 1
    }
  },
)

onMounted(loadEvents)

async function loadEvents() {
  loading.value = true
  try {
    events.value = await fetchPublishedEvents()
    selectedId.value = events.value[0]?.id || ''
  } catch (error) {
    ElMessage.error(error.message || '事件列表加载失败')
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  pagination.page = 1
  selectedId.value = ''
  if (!filteredEvents.value.length) {
    ElMessage.info('当前筛选条件下没有公开事件')
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.risk = 'all'
  filters.source = 'all'
  filters.timeRange = '7d'
  filters.sortBy = 'heat'
  filters.quick = 'all'
  pagination.page = 1
  selectedId.value = ''
}

function setQuick(value) {
  filters.quick = value
  filters.risk = ['high', 'medium', 'low'].includes(value) ? value : 'all'
  pagination.page = 1
  selectedId.value = ''
}

function selectEvent(event) {
  selectedId.value = event.id
}

function openDetail(event) {
  router.push(`/events/${event.id}`)
}

function openFeedback(event) {
  feedbackEvent.value = event
  feedbackVisible.value = true
}

function displayTime(value) {
  const timestamp = parseTime(value)
  const latest = new Date(latestTime.value).toISOString().slice(0, 10)
  const current = new Date(timestamp).toISOString().slice(0, 10)
  const hm = value.slice(11, 16)
  return current === latest ? `今天 ${hm}` : `昨天 ${hm}`
}

function parseTime(value) {
  return new Date(value.replace(' ', 'T')).getTime()
}

function timeRangeToMs(value) {
  if (value === '24h') return 24 * 60 * 60 * 1000
  if (value === '7d') return 7 * 24 * 60 * 60 * 1000
  if (value === '30d') return 30 * 24 * 60 * 60 * 1000
  return 0
}

function isLatestDay(value) {
  const date = new Date(parseTime(value)).toISOString().slice(0, 10)
  const latest = new Date(latestTime.value).toISOString().slice(0, 10)
  return date === latest
}

function riskClass(value) {
  if (value === 'high') return 'badge-high'
  if (value === 'medium') return 'badge-mid'
  return 'badge-low'
}

function sourceLabel(value) {
  return sourceOptions.find((item) => item.value === value)?.label || value
}

function sourceShort(value) {
  if (value === 'weibo') return '微'
  if (value === 'xhs') return '红'
  return '贴'
}
</script>

<style scoped>
.events-page {
  min-height: 100%;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  gap: 8px;
  overflow-x: hidden;
}

.event-filter {
  min-height: 58px;
  padding: 12px;
  display: grid;
  grid-template-columns: minmax(260px, 1.5fr) repeat(4, minmax(112px, 0.68fr)) 58px 58px 132px;
  gap: 10px;
  align-items: center;
}

.filter-search :deep(.el-input__wrapper),
.filter-select :deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 6px;
}

.workbench-btn {
  min-width: 132px;
}

.risk-tabs {
  height: 44px;
  padding: 0 14px;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  align-items: center;
}

.risk-tab {
  height: 100%;
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-right: 1px solid var(--color-border-light);
  background: transparent;
  color: var(--color-text-secondary);
  font-weight: 600;
  cursor: pointer;
}

.risk-tab:last-child { border-right: 0; }

.risk-tab--active { color: var(--color-primary); }

.risk-tab--active::after {
  content: '';
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: -1px;
  height: 3px;
  border-radius: 999px;
  background: var(--color-primary);
}

.risk-tab strong {
  min-width: 24px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #eef5ff;
  color: var(--color-primary);
}

.risk-tab strong.high { color: #e03137; background: #fff1f0; }
.risk-tab strong.medium { color: #d46b08; background: #fff7e6; }
.risk-tab strong.low { color: #099250; background: #ecfdf3; }
.risk-tab strong.today { color: #2563eb; background: #eff6ff; }

.events-layout {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 448px;
  gap: 10px;
  align-items: stretch;
}

.event-list-card, .event-preview-card { min-height: 0; display: flex; flex-direction: column; }

.compact-panel-title, .preview-header {
  height: 48px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border-light);
  color: var(--color-text);
  font-size: 18px;
  font-weight: 700;
}

.compact-table-wrap { min-height: 0; flex: 1 1 auto; overflow: hidden; border: 0; }

.compact-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12px; }

.compact-table th, .compact-table td {
  padding: 0 10px; border-bottom: 1px solid var(--color-border-light);
  text-align: left; vertical-align: middle; white-space: nowrap;
}

.compact-table th { height: 38px; color: var(--color-text-muted); font-weight: 600; background: #f8fafd; }
.compact-table td { height: 48px; }
.compact-table tbody tr { cursor: pointer; }
.compact-table tbody tr:hover, .compact-table tbody tr.row-active { background: #f6f9ff; }
.compact-table tbody tr.row-active { box-shadow: inset 2px 0 0 var(--color-primary); }
.col-title { width: auto; }

.title-cell span { display: block; overflow: hidden; text-overflow: ellipsis; color: var(--color-text); font-weight: 500; }
.heat-cell { color: var(--color-text); font-family: "Segoe UI", Arial, sans-serif; font-weight: 600; }

.source-list { display: flex; gap: 5px; overflow: hidden; }
.source-pill { height: 22px; padding: 0 6px; display: inline-flex; align-items: center; border-radius: 5px; font-size: 11px; font-weight: 800; }
.source-weibo { color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa; }
.source-xhs { color: #be123c; background: #fff1f2; border: 1px solid #fecdd3; }
.source-tieba { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }

.published-dot { width: 6px; height: 6px; display: inline-block; margin-right: 6px; border-radius: 50%; background: #13b26b; vertical-align: 1px; }
.action-cell button { border: 0; background: transparent; color: var(--color-primary); font-weight: 700; cursor: pointer; padding: 0; }
.action-cell button + button { margin-left: 8px; }

.table-footer {
  height: 60px; flex: 0 0 auto; padding: 0 14px; display: grid;
  grid-template-columns: 1fr auto 100px; align-items: center; gap: 12px;
  border-top: 1px solid var(--color-border-light); color: var(--color-text-secondary);
}
.table-footer :deep(.el-pagination) { justify-content: center; }
.page-size-select { width: 100px; }

.preview-content { min-height: 0; flex: 1 1 auto; padding: 18px 18px 16px; display: flex; flex-direction: column; overflow: hidden; }
.preview-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.preview-title-row h2 { margin: 0; color: var(--color-text); font-size: 21px; font-weight: 600; }
.preview-summary { min-height: 72px; margin: 12px 0 16px; color: var(--color-text-secondary); line-height: 1.7; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }

.preview-stats { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--color-border-light); border-radius: var(--radius-sm); overflow: hidden; }
.preview-stats div { min-height: 68px; display: flex; flex-direction: column; justify-content: center; align-items: center; border-right: 1px solid var(--color-border-light); }
.preview-stats div:last-child { border-right: 0; }
.preview-stats strong { color: var(--color-text); font-size: 23px; font-family: "Segoe UI", Arial, sans-serif; font-weight: 500; }
.preview-stats span { margin-top: 4px; color: var(--color-text-muted); }
.preview-tags { margin-top: 14px; }
.preview-label { display: block; margin-bottom: 8px; color: var(--color-text); font-weight: 800; }
.tag-blue { margin-right: 6px; color: var(--color-primary); background: var(--color-primary-light); border: 1px solid #b7d5ff; }
.preview-actions { margin-top: 18px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }

.preview-bottom { min-height: 182px; margin-top: auto; display: grid; grid-template-columns: minmax(0, 1fr) 164px; gap: 10px; }
.preview-bottom section { min-height: 182px; padding: 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-sm); background: #fff; }
.preview-bottom h3 { margin: 0 0 8px; color: var(--color-text); font-size: 14px; }
.mini-chart { width: 100%; height: 134px; }
.axis-line { stroke: #d8e2ef; stroke-width: 1; }
.trend-line { fill: none; stroke: var(--color-primary); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.trend-point { fill: #fff; stroke: var(--color-primary); stroke-width: 3; }
.source-breakdown { display: flex; flex-direction: column; gap: 12px; }
.source-breakdown div { display: grid; grid-template-columns: 24px 1fr auto; gap: 8px; align-items: center; color: var(--color-text-secondary); }
.source-breakdown strong { color: var(--color-text-secondary); font-weight: 700; }
.source-icon { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; color: #fff; font-size: 12px; font-weight: 800; }
.source-icon-weibo { background: #ef4444; }
.source-icon-xhs { background: #f43f5e; }
.source-icon-tieba { background: #3b82f6; }

.event-footnote { height: 34px; display: flex; align-items: center; justify-content: center; color: var(--color-text-secondary); font-size: 13px; }
.event-footnote button { border: 0; background: transparent; color: var(--color-primary); font-weight: 800; cursor: pointer; padding: 0 2px; }

@media (max-width: 1380px) {
  .event-filter { grid-template-columns: minmax(200px, 1fr) repeat(4, minmax(98px, 0.42fr)) 56px 56px 118px; gap: 8px; }
  .events-layout { grid-template-columns: minmax(0, 1fr) 410px; }
}
@media (max-width: 1120px) {
  .event-filter, .events-layout { grid-template-columns: 1fr; }
  .risk-tabs { grid-template-columns: repeat(2, 1fr); height: auto; }
  .risk-tab { min-height: 40px; border-right: 0; }
}
</style>
