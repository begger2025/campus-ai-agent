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
        <div v-if="!loading && !pagedEvents.length" class="list-empty">
          <el-icon :size="30"><Search /></el-icon>
          <p>没有符合条件的公开事件</p>
          <span>试试放宽风险等级或时间范围</span>
          <el-button size="small" @click="resetFilters">重置筛选</el-button>
        </div>
        <div v-else ref="tableShell" class="table-shell compact-table-wrap" v-loading="loading">
          <table class="compact-table">
            <thead>
              <tr>
                <th class="col-title">事件标题</th>
                <th>风险</th>
                <th class="heat-head">
                  <el-tooltip :content="HEAT_TOOLTIP" placement="top" :show-after="150">
                    <span class="heat-head-label">热度 ↓ <el-icon :size="13"><InfoFilled /></el-icon></span>
                  </el-tooltip>
                </th>
                <th>来源</th>
                <th>发布时间</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <transition-group tag="tbody" name="rows" appear>
              <tr
                v-for="(event, rowIndex) in pagedEvents"
                :key="event.id"
                :class="{ 'row-active': selectedEvent?.id === event.id }"
                :style="{ '--row-i': rowIndex }"
                @click="selectEvent(event)"
              >
                <td class="title-cell">
                  <span>{{ event.title }}</span>
                </td>
                <td>
                  <span :class="['badge', riskClass(event.riskLevel)]">{{ event.riskLabel }}</span>
                </td>
                <td class="heat-cell" :title="`精确值 ${event.heatScore}`">
                  <span class="heat-num">
                    {{ formatHeat(event.heatScore) }}
                    <span :class="['heat-chip', `heat-chip--${heatLevel(event.heatScore).key}`]">{{ heatLevel(event.heatScore).label }}</span>
                  </span>
                  <span class="heat-bar"><i :style="{ width: heatBarWidth(event.heatScore) }" /></span>
                </td>
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
            </transition-group>
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
            <div :title="`精确值 ${selectedEvent.heatScore}`">
              <strong>{{ formatHeat(selectedEvent.heatScore) }}</strong>
              <span>热度 · {{ heatLevel(selectedEvent.heatScore).label }}</span>
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
              <svg :key="selectedEvent?.id" viewBox="0 0 280 144" class="mini-chart">
                <line x1="18" y1="118" x2="260" y2="118" class="axis-line" />
                <polyline :points="trendLine" class="trend-line" pathLength="1" />
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

        <div v-else class="preview-empty">
          <el-icon :size="26"><Pointer /></el-icon>
          <p>暂无可预览的事件</p>
          <span>调整筛选条件后，点击左侧列表任意一行查看</span>
        </div>
      </aside>
    </div>

    <div class="event-footnote">
      仅展示已发布事件 · 管理员审核请前往后台 <button type="button" @click="router.push('/admin/events')">/admin/events</button>
    </div>

    <EventFeedbackDialog v-model="feedbackVisible" :event="feedbackEvent" />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { InfoFilled, Pointer, Search } from '@element-plus/icons-vue'
import { formatHeat, heatLevel, HEAT_TOOLTIP } from '@/utils/heat'
import { gsap } from 'gsap'
import { Flip } from 'gsap/Flip'

gsap.registerPlugin(Flip)
import EventFeedbackDialog from '@/components/EventFeedbackDialog.vue'
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

// 相对热度条：以当前已发布事件的最大热度为满格，平方根刻度避免小值不可见
const maxHeat = computed(() => Math.max(...publishedEvents.value.map((event) => event.heatScore || 0), 1))

function heatBarWidth(value) {
  const ratio = Math.sqrt(Math.max(value || 0, 0) / maxHeat.value)
  return `${Math.max(Math.round(ratio * 100), 4)}%`
}

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

/* ---- Flip：筛选/排序/翻页时，存留的行从旧位置平滑滑到新位置 ---- */
const tableShell = ref(null)
let flipAnim = null
const reduceMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')

watch(
  () => pagedEvents.value.map((event) => event.id).join('|'),
  (nextIds, prevIds) => {
    // 首次渲染（prevIds 为空）交给入场动画；此 watch 默认 pre 刷新，
    // 回调时 DOM 还是旧行，正好捕获 First 状态
    if (!prevIds || reduceMotionQuery.matches || !tableShell.value) return
    const rows = Array.from(tableShell.value.querySelectorAll('tbody tr'))
    if (!rows.length) return
    const state = Flip.getState(rows)
    nextTick(() => {
      flipAnim?.kill()
      flipAnim = Flip.from(state, { duration: 0.4, ease: 'power2.out' })
    })
  },
)

onBeforeUnmount(() => flipAnim?.kill())

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
  gap: 12px;
  overflow-x: hidden;
}

/* 本页的卡片容器（此前缺失定义，导致各区域无边界感） */
.panel-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
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

.risk-tab strong.high { color: var(--color-danger-text); background: var(--color-danger-bg); }
.risk-tab strong.medium { color: var(--color-warning-text); background: var(--color-warning-bg); }
.risk-tab strong.low { color: var(--color-success-text); background: var(--color-success-bg); }
.risk-tab strong.today { color: var(--brand-700); background: var(--brand-50); }

.events-layout {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 448px;
  gap: 14px;
  align-items: stretch;
}

.event-list-card, .event-preview-card { min-height: 0; display: flex; flex-direction: column; }

/* 面板标题：收敛到产品级字阶（页面主标题在顶栏，这里只是分区名） */
.compact-panel-title, .preview-header {
  height: 46px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid var(--color-border-light);
  color: var(--color-text);
  font-size: 15px;
  font-weight: 600;
}

.compact-table-wrap { min-height: 0; flex: 1 1 auto; overflow-x: auto; overflow-y: hidden; border: 0; }

.compact-table { width: 100%; min-width: 830px; table-layout: fixed; border-collapse: collapse; font-size: 12px; }

/* 定宽内容的列显式定宽，弹性空间全部留给标题列，避免操作列被挤压 */
.compact-table th:nth-child(2) { width: 76px; }   /* 风险 */
.compact-table th:nth-child(3) { width: 122px; }  /* 热度 */
.compact-table th:nth-child(4) { width: 104px; }  /* 来源 */
.compact-table th:nth-child(5) { width: 96px; }   /* 发布时间 */
.compact-table th:nth-child(6) { width: 80px; }   /* 状态 */
.compact-table th:nth-child(7) { width: 116px; }  /* 操作 */

.compact-table th, .compact-table td {
  padding: 0 10px; border-bottom: 1px solid var(--color-border-light);
  text-align: left; vertical-align: middle; white-space: nowrap;
}

.compact-table th { height: 38px; color: var(--color-text-muted); font-weight: 600; background: var(--color-surface-2); }
.compact-table td { height: 48px; }
.compact-table tbody tr { cursor: pointer; transition: background var(--dur-fast) var(--ease-out); }
.compact-table tbody tr:hover { background: var(--color-surface-2); }
.compact-table tbody tr.row-active { background: var(--brand-50); }
.col-title { width: auto; }

.title-cell span { display: block; overflow: hidden; text-overflow: ellipsis; color: var(--color-text); font-weight: 500; }

.heat-head-label { display: inline-flex; align-items: center; gap: 3px; cursor: help; }
.heat-head-label .el-icon { color: var(--color-text-faint); }

.heat-cell { color: var(--color-text); font-weight: 600; }
.heat-num { display: inline-flex; align-items: center; gap: 6px; }
.heat-bar {
  display: block;
  width: 64px;
  height: 3px;
  margin-top: 4px;
  border-radius: 999px;
  background: var(--color-border-light);
  overflow: hidden;
}
.heat-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--brand-400);
  transition: width var(--dur-slow) var(--ease-out);
}

.source-list { display: flex; gap: 5px; overflow: hidden; }
.source-pill { height: 22px; padding: 0 6px; display: inline-flex; align-items: center; border-radius: 5px; font-size: 11px; font-weight: 800; }
.source-weibo { color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa; }
.source-xhs { color: #be123c; background: #fff1f2; border: 1px solid #fecdd3; }
.source-tieba { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }

.published-dot { width: 6px; height: 6px; display: inline-block; margin-right: 6px; border-radius: 50%; background: var(--color-success); vertical-align: 1px; }
.action-cell button { border: 0; background: transparent; color: var(--color-primary); font-weight: 600; font-family: inherit; cursor: pointer; padding: 0; transition: color var(--dur-fast) var(--ease-out); }
.action-cell button:hover { color: var(--color-primary-active); }
.action-cell button + button { margin-left: 8px; }

.table-footer {
  height: 60px; flex: 0 0 auto; padding: 0 14px; display: grid;
  grid-template-columns: 1fr auto 100px; align-items: center; gap: 12px;
  border-top: 1px solid var(--color-border-light); color: var(--color-text-secondary);
}
.table-footer :deep(.el-pagination) { justify-content: center; }
.page-size-select { width: 100px; }

.preview-content { min-height: 0; flex: 1 1 auto; padding: 16px 16px 14px; display: flex; flex-direction: column; overflow: hidden; }
.preview-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.preview-title-row h2 { margin: 0; color: var(--color-text); font-size: 16px; font-weight: 600; line-height: 1.45; }
.preview-summary { min-height: 66px; margin: 10px 0 14px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }

.preview-stats { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--color-border-light); border-radius: var(--radius-sm); overflow: hidden; background: var(--color-surface-2); }
.preview-stats div { min-height: 62px; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 3px; border-right: 1px solid var(--color-border-light); }
.preview-stats div:last-child { border-right: 0; }
.preview-stats strong { color: var(--color-text); font-size: 18px; font-weight: 600; line-height: 1.2; white-space: nowrap; }
/* 最近更新是文本不是量值，降一档字号，不与数字争夺权重 */
.preview-stats div:last-child strong { font-size: 13px; font-weight: 600; color: var(--color-text-secondary); }
.preview-stats span { color: var(--color-text-muted); font-size: 12px; }
.preview-tags { margin-top: 14px; }
.preview-label { display: block; margin-bottom: 6px; color: var(--color-text-muted); font-size: 12px; font-weight: 600; }
.tag-blue { margin-right: 6px; color: var(--brand-700); background: var(--brand-50); border: 1px solid var(--brand-200); }
.preview-actions { margin-top: 18px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }

.preview-bottom { min-height: 182px; margin-top: auto; display: grid; grid-template-columns: minmax(0, 1fr) 164px; gap: 10px; }
.preview-bottom section { min-height: 182px; padding: 12px; border: 1px solid var(--color-border-light); border-radius: var(--radius-sm); background: #fff; }
.preview-bottom h3 { margin: 0 0 8px; color: var(--color-text-secondary); font-size: 13px; font-weight: 600; }
.mini-chart { width: 100%; height: 134px; }
.axis-line { stroke: var(--color-border); stroke-width: 1; }

.trend-line {
  fill: none;
  stroke: var(--color-primary);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: draw-line 0.8s var(--ease-out) 0.1s forwards;
}

@keyframes draw-line {
  to { stroke-dashoffset: 0; }
}

.trend-point {
  fill: #fff;
  stroke: var(--color-primary);
  stroke-width: 2;
  opacity: 0;
  animation: point-in 0.3s var(--ease-out) 0.7s forwards;
}

@keyframes point-in {
  to { opacity: 1; }
}

/* 表格行级联入场（加载/翻页/筛选时作为内容变化反馈） */
.rows-enter-active {
  transition: opacity var(--dur-slow) var(--ease-out), transform var(--dur-slow) var(--ease-out);
  transition-delay: calc(var(--row-i, 0) * 35ms);
}

.rows-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.rows-leave-active {
  display: none;
}
.source-breakdown { display: flex; flex-direction: column; gap: 12px; }
.source-breakdown div { display: grid; grid-template-columns: 24px 1fr auto; gap: 8px; align-items: center; color: var(--color-text-secondary); font-size: 13px; }
.source-breakdown strong { color: var(--color-text); font-weight: 600; }
.source-icon { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; color: #fff; font-size: 12px; font-weight: 800; }
.source-icon-weibo { background: #ef4444; }
.source-icon-xhs { background: #f43f5e; }
.source-icon-tieba { background: #3b82f6; }

.event-footnote { height: 34px; display: flex; align-items: center; justify-content: center; color: var(--color-text-secondary); font-size: 13px; }
.event-footnote button { border: 0; background: transparent; color: var(--color-primary); font-weight: 600; font-family: inherit; cursor: pointer; padding: 0 2px; }

.list-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 0;
  color: var(--color-text-muted);
  font-size: 13px;
}

.list-empty .el-icon { color: var(--color-text-faint); }
.list-empty p { margin: 0; font-weight: 600; font-size: 14px; color: var(--color-text-secondary); }
.list-empty span { font-size: 12px; color: var(--color-text-faint); }
.list-empty .el-button { margin-top: 6px; }

.preview-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 48px 24px;
  text-align: center;
  color: var(--color-text-muted);
}

.preview-empty .el-icon { color: var(--color-text-faint); }
.preview-empty p { margin: 0; font-size: 14px; font-weight: 600; color: var(--color-text-secondary); }
.preview-empty span { font-size: 12px; color: var(--color-text-faint); }

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
