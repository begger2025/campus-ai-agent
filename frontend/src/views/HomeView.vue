<template>
  <div class="home-page">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div class="welcome-content">
        <div class="welcome-title">{{ greeting }}，{{ displayName }}</div>
        <div class="welcome-sub">
          今天是{{ todayText }}。当前共
          <strong>{{ publishedEvents.length }}</strong> 个已发布事件，其中
          <strong>{{ highRiskEvents.length }}</strong> 条高风险预警、
          <strong>{{ mediumRiskEvents.length }}</strong> 条中风险事件。
        </div>
      </div>
      <div class="welcome-meta">
        <DataSourceBadge v-if="healthChecked && !backendOk" source="mock" />
        <button
          v-if="highRiskEvents.length > 0"
          class="risk-flag"
          type="button"
          @click="$router.push('/events')"
        >
          <el-icon :size="14"><WarningFilled /></el-icon>
          {{ highRiskEvents.length }} 条高风险预警
        </button>
        <span v-else class="calm-flag">
          <el-icon :size="14"><CircleCheckFilled /></el-icon>
          舆情态势平稳
        </span>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <StatCard
        title="已发布事件"
        :value="publishedEvents.length"
        :icon="Collection"
        desc="事件全链路真实数据"
        color="primary"
        :loading="eventsLoading"
      />
      <StatCard
        title="高风险事件"
        :value="highRiskEvents.length"
        :icon="Warning"
        desc="需要优先关注"
        color="danger"
        :loading="eventsLoading"
      />
      <StatCard
        title="今日新增"
        :value="todayNewCount"
        :icon="Clock"
        desc="按最近数据日统计"
        color="teal"
        :loading="eventsLoading"
      />
      <StatCard
        title="采集帖子"
        :value="postsTotal"
        :icon="ChatLineSquare"
        desc="多平台聚合采集"
        color="purple"
        :loading="postsLoading"
      />
      <StatCard
        title="中风险事件"
        :value="mediumRiskEvents.length"
        :icon="Bell"
        desc="持续跟踪观察"
        color="warning"
        :loading="eventsLoading"
      />
      <StatCard
        title="后端状态"
        :value="backendStatus"
        :icon="Connection"
        :desc="backendDesc"
        :color="backendOk ? 'success' : 'muted'"
      />
    </div>

    <!-- 内容区：趋势图 + 最新帖子 + 中高风险预警快览 -->
    <div class="content-grid">
      <!-- 舆情趋势 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">
            近7天事件热度趋势
            <el-tooltip :content="HEAT_TOOLTIP" placement="top" :show-after="150">
              <el-icon class="title-info" :size="13"><InfoFilled /></el-icon>
            </el-tooltip>
          </span>
          <span v-if="!eventsLoading && !isLatestDayToday" class="section-hint">
            截至 {{ latestDayLabel }} · 最近数据日
          </span>
        </div>
        <div class="section-body">
          <div v-if="eventsLoading" class="chart-skeleton">
            <span v-for="i in 7" :key="i" :style="{ height: 18 + ((i * 37) % 60) + '%' }" />
          </div>
          <div v-else class="mini-chart" role="img" aria-label="近7天事件数量柱状图">
            <div
              v-for="(item, index) in trendData"
              :key="item.name"
              class="chart-bar-wrap"
            >
              <!-- --bar-h 同时驱动柱高和数字标签的锚定位置，数字始终悬在柱顶上方 -->
              <div
                class="chart-bar-area"
                :style="{ '--bar-h': (maxTrend ? (item.value / maxTrend) * 100 : 0) + '%' }"
              >
                <span
                  class="chart-value"
                  :class="{ 'chart-value--pinned': index === maxTrendIndex }"
                >{{ formatHeat(item.value) }}</span>
                <div class="chart-bar"></div>
              </div>
              <div class="chart-label">{{ item.name }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 最新帖子列表 -->
      <div class="section-card span-2">
        <div class="section-header">
          <span class="section-title">最新校园帖子</span>
          <el-button size="small" type="primary" text @click="$router.push('/sentiment')">
            查看全部 →
          </el-button>
        </div>
        <div class="section-body">
          <div v-if="postsLoading" class="table-skeleton">
            <div v-for="i in 5" :key="i" class="skeleton-row">
              <span class="sk sk-tag" />
              <span class="sk sk-title" />
              <span class="sk sk-meta" />
            </div>
          </div>
          <div v-else-if="posts.length === 0" class="empty-state">
            <el-icon :size="28"><FolderOpened /></el-icon>
            <p>暂无帖子数据</p>
            <span>后端未启动时将展示样本数据，可运行 dev.bat 连接真实数据源</span>
          </div>
          <table v-else class="data-table">
            <thead>
              <tr>
                <th>平台</th>
                <th>标题</th>
                <th>作者</th>
                <th>发布时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="post in posts.slice(0, 6)" :key="post.id">
                <td><el-tag size="small">{{ post.platform }}</el-tag></td>
                <td class="post-title">{{ post.title }}</td>
                <td class="text-muted">{{ post.author || '匿名' }}</td>
                <td class="text-muted">{{ formatTime(post.publish_time) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 中高风险预警快览：整行横排 -->
      <div class="section-card span-3">
        <div class="section-header">
          <span class="section-title">中高风险预警快览</span>
          <el-button size="small" type="primary" text @click="$router.push('/personal')">
            舆情关注 →
          </el-button>
        </div>
        <div class="section-body">
          <div v-if="watchEvents.length" class="alert-grid">
            <button
              v-for="event in watchEvents.slice(0, 3)"
              :key="event.id"
              class="alert-card"
              type="button"
              @click="$router.push(`/events/${event.id}`)"
            >
              <div class="alert-top">
                <span :class="['badge', event.riskLevel === 'high' ? 'badge-high' : 'badge-mid']">
                  {{ event.riskLevel === 'high' ? '高风险' : '中风险' }}
                </span>
                <span class="alert-heat" :title="`精确值 ${event.heatScore}`">热度 {{ formatHeat(event.heatScore) }}</span>
              </div>
              <div class="alert-title">{{ event.title }}</div>
              <div class="alert-desc">{{ event.summary || event.riskReason }}</div>
            </button>
          </div>
          <div v-if="!eventsLoading && watchEvents.length === 0" class="empty-state empty-state--calm">
            <el-icon :size="24"><CircleCheckFilled /></el-icon>
            <p>当前暂无中高风险预警</p>
            <span>校园舆情态势平稳</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  Bell,
  ChatLineSquare,
  CircleCheckFilled,
  Clock,
  Collection,
  Connection,
  FolderOpened,
  InfoFilled,
  Warning,
  WarningFilled,
} from '@element-plus/icons-vue'
import { formatHeat, HEAT_TOOLTIP } from '@/utils/heat'
import StatCard from '@/components/StatCard.vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { checkHealth, fetchPosts } from '@/api/posts'
import { fetchPublishedEvents } from '@/api/events'
import { getCurrentUser, getCurrentRole } from '@/auth/session'
import { mockPosts } from '@/mock/data'

// ——— 当前用户 ———
const user = getCurrentUser()
const role = getCurrentRole()
const displayName = computed(() => {
  if (role === 'admin') return user?.displayName || '管理员'
  if (role === 'user') return user?.displayName || '同学'
  return '访客'
})

const now = new Date()
const greeting = computed(() => {
  const h = now.getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})
const todayText = `${now.getMonth() + 1}月${now.getDate()}日 周${'日一二三四五六'[now.getDay()]}`

// ——— 后端状态 ———
const backendOk = ref(false)
const healthChecked = ref(false)
const backendDesc = ref('检测中…')
const backendStatus = computed(() => (backendOk.value ? '正常' : '未连接'))

onMounted(async () => {
  try {
    const data = await checkHealth()
    backendOk.value = data.pong === true
    backendDesc.value = backendOk.value ? '后端响应正常' : '响应异常'
  } catch {
    backendDesc.value = '后端未启动，展示样本数据'
  }
  healthChecked.value = true
  loadPosts()
  loadEvents()
})

// ——— 帖子数据 ———
const posts = ref([])
const postsTotal = ref(0)
const postsLoading = ref(true)

async function loadPosts() {
  try {
    const data = await fetchPosts(1, 10)
    posts.value = data.items
    postsTotal.value = data.total ?? data.items.length
  } catch {
    posts.value = mockPosts
    postsTotal.value = mockPosts.length
  } finally {
    postsLoading.value = false
  }
}

// ——— 事件数据（真实接口，后端不可用时 api 层自动降级样本） ———
const events = ref([])
const eventsLoading = ref(true)

async function loadEvents() {
  try {
    events.value = await fetchPublishedEvents()
  } finally {
    eventsLoading.value = false
  }
}

const publishedEvents = computed(() => events.value.filter((e) => e.status === 'published'))
const highRiskEvents = computed(() =>
  publishedEvents.value
    .filter((e) => e.riskLevel === 'high')
    .sort((a, b) => (b.heatScore || 0) - (a.heatScore || 0))
)

const mediumRiskEvents = computed(() => publishedEvents.value.filter((e) => e.riskLevel === 'medium'))

// 预警快览：高风险优先，其次中风险，按热度排序
const watchEvents = computed(() =>
  publishedEvents.value
    .filter((e) => ['high', 'medium'].includes(e.riskLevel))
    .sort((a, b) => {
      if (a.riskLevel !== b.riskLevel) return a.riskLevel === 'high' ? -1 : 1
      return (b.heatScore || 0) - (a.heatScore || 0)
    })
)

function parseTime(value) {
  const ts = new Date(value).getTime()
  return Number.isFinite(ts) ? ts : null
}

// 以数据里最新一天为锚点（演示快照的数据可能不是"今天"）
const latestTime = computed(() => {
  const times = publishedEvents.value.map((e) => parseTime(e.updatedAt)).filter(Boolean)
  return times.length ? Math.max(...times) : Date.now()
})

// 最近数据日不是"今天"时（如演示快照），在趋势图旁明确标注时间口径
const latestDayLabel = computed(() => {
  const d = new Date(latestTime.value)
  return `${d.getMonth() + 1}/${d.getDate()}`
})

const isLatestDayToday = computed(() => {
  const d = new Date(latestTime.value)
  const t = new Date()
  return (
    d.getFullYear() === t.getFullYear() &&
    d.getMonth() === t.getMonth() &&
    d.getDate() === t.getDate()
  )
})

const todayNewCount = computed(() => {
  const anchor = new Date(latestTime.value)
  return publishedEvents.value.filter((e) => {
    const ts = parseTime(e.updatedAt)
    if (!ts) return false
    const d = new Date(ts)
    return (
      d.getFullYear() === anchor.getFullYear() &&
      d.getMonth() === anchor.getMonth() &&
      d.getDate() === anchor.getDate()
    )
  }).length
})

// ——— 近7天趋势（按事件更新日聚合热度） ———
const trendData = computed(() => {
  const anchor = new Date(latestTime.value)
  anchor.setHours(0, 0, 0, 0)
  const days = []
  for (let i = 6; i >= 0; i -= 1) {
    const dayStart = anchor.getTime() - i * 86400000
    days.push({
      name: `${new Date(dayStart).getMonth() + 1}/${new Date(dayStart).getDate()}`,
      start: dayStart,
      end: dayStart + 86400000,
      value: 0,
    })
  }
  publishedEvents.value.forEach((e) => {
    const ts = parseTime(e.updatedAt)
    if (!ts) return
    const bucket = days.find((d) => ts >= d.start && ts < d.end)
    if (bucket) bucket.value += Math.max(1, Math.round(e.heatScore || 0))
  })
  return days
})

const maxTrend = computed(() => Math.max(...trendData.value.map((d) => d.value), 0))
const maxTrendIndex = computed(() => trendData.value.findIndex((d) => d.value === maxTrend.value))

// ——— 工具函数 ———
function formatTime(ts) {
  if (!ts) return '未知'
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 欢迎横幅 */
.welcome-banner {
  background:
    radial-gradient(circle at 90% 0%, rgba(59, 91, 219, 0.08), transparent 42%),
    linear-gradient(135deg, var(--brand-50) 0%, #fff 55%);
  border: 1px solid var(--brand-100);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.welcome-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.welcome-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.welcome-sub strong {
  color: var(--brand-700);
}

.welcome-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.risk-flag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border: 0;
  border-radius: 999px;
  background: var(--color-danger);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.risk-flag:hover {
  background: #b93238;
}

.risk-flag:active {
  transform: scale(0.97);
}

.calm-flag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  background: var(--color-success-bg);
  border: 1px solid #c8e5d0;
  color: var(--color-success-text);
  font-size: 13px;
  font-weight: 600;
}

/* 统计卡片网格 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}

@media (max-width: 1500px) {
  .stat-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 768px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}

/* 内容区 */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 14px;
}

@media (max-width: 1300px) {
  .content-grid { grid-template-columns: 1fr 1fr; }
  .span-2 { grid-column: span 2; }
}

@media (max-width: 768px) {
  .content-grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: span 1; }
}

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
}

.span-2 { grid-column: span 2; }

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
  color: var(--color-text);
}

.section-hint {
  font-size: 12px;
  color: var(--color-text-faint);
  white-space: nowrap;
}

.title-info {
  vertical-align: -2px;
  margin-left: 3px;
  color: var(--color-text-faint);
  cursor: help;
}

.section-body {
  padding: 14px 18px 16px;
}

/* 迷你柱状图 */
.mini-chart {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 132px;
  padding-top: 20px;
}

.chart-bar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  justify-content: flex-end;
}

/* 柱子的定位容器：数字标签以它为基准，锚在柱顶上方 */
.chart-bar-area {
  position: relative;
  flex: 1;
  width: 100%;
  max-width: 30px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.chart-bar {
  width: 100%;
  height: var(--bar-h, 0%);
  background: var(--brand-400);
  border-radius: 4px 4px 0 0;
  min-height: 3px;
  transition: background var(--dur-fast) var(--ease-out), height var(--dur-slow) var(--ease-out);
}

.chart-bar-wrap:hover .chart-bar {
  background: var(--brand-600);
}

.chart-value {
  position: absolute;
  left: 50%;
  bottom: calc(var(--bar-h, 0%) + 5px);
  transform: translateX(-50%);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  color: var(--color-text-secondary);
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out), bottom var(--dur-slow) var(--ease-out);
}

.chart-value--pinned,
.chart-bar-wrap:hover .chart-value {
  opacity: 1;
}

/* 峰值标签等柱子生长完再浮现，避免动画期间数字悬空 */
.chart-value--pinned {
  animation: value-in 0.3s var(--ease-out) 0.55s backwards;
}

@keyframes value-in {
  from { opacity: 0; }
}

.chart-label {
  font-size: 11px;
  color: var(--color-text-faint);
  margin-top: 6px;
}

.chart-skeleton {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 132px;
  padding-top: 20px;
}

.chart-skeleton span {
  flex: 1;
  max-width: 30px;
  margin: 0 auto;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(90deg, #eef1f7 25%, #f6f8fb 50%, #eef1f7 75%);
  background-size: 200% 100%;
  animation: stat-shimmer 1.4s ease-in-out infinite;
}

@keyframes stat-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* 数据表格 */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th {
  padding: 8px 12px;
  text-align: left;
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  font-weight: 500;
  font-size: 12px;
}

.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border-light);
  color: var(--color-text);
}

.data-table tbody tr {
  transition: background var(--dur-fast) var(--ease-out);
}

.data-table tbody tr:hover {
  background: var(--color-surface-2);
}

.post-title {
  max-width: 320px;
  font-weight: 500;
}

.text-muted { color: var(--color-text-muted); }

/* 表格骨架屏 */
.table-skeleton {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 6px 0;
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sk {
  height: 14px;
  border-radius: 4px;
  background: linear-gradient(90deg, #eef1f7 25%, #f6f8fb 50%, #eef1f7 75%);
  background-size: 200% 100%;
  animation: stat-shimmer 1.4s ease-in-out infinite;
}

.sk-tag { width: 48px; }
.sk-title { flex: 1; }
.sk-meta { width: 90px; }

/* 预警卡片：横排网格 */
.span-3 {
  grid-column: 1 / -1;
}

.alert-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.alert-card {
  display: block;
  width: 100%;
  text-align: left;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  font-family: inherit;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.alert-card:hover {
  border-color: #f4c2c4;
  box-shadow: var(--shadow-card);
  transform: translateY(-1px);
}

.alert-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.alert-heat {
  font-size: 12px;
  color: var(--color-text-muted);
}

.alert-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 4px;
}

.alert-desc {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 空态 */
.empty-state {
  padding: 26px 12px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.empty-state .el-icon {
  color: var(--color-text-faint);
}

.empty-state p {
  margin: 2px 0 0;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.empty-state span {
  font-size: 12px;
  color: var(--color-text-faint);
}

.empty-state--calm .el-icon {
  color: var(--color-success);
}

/* ===========================
   入场动效（backwards 填充：动画结束后回归自然样式，不影响 hover）
   =========================== */
@keyframes rise-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
}

.welcome-banner {
  animation: rise-in 0.35s var(--ease-out) backwards;
}

.stat-grid > .stat-card {
  animation: rise-in 0.35s var(--ease-out) backwards;
}

.stat-grid > .stat-card:nth-child(2) { animation-delay: 40ms; }
.stat-grid > .stat-card:nth-child(3) { animation-delay: 80ms; }
.stat-grid > .stat-card:nth-child(4) { animation-delay: 120ms; }
.stat-grid > .stat-card:nth-child(5) { animation-delay: 160ms; }
.stat-grid > .stat-card:nth-child(6) { animation-delay: 200ms; }

.content-grid > .section-card {
  animation: rise-in 0.4s var(--ease-out) backwards;
}

.content-grid > .section-card:nth-child(2) { animation-delay: 60ms; }
.content-grid > .section-card:nth-child(3) { animation-delay: 120ms; }
.content-grid > .section-card:nth-child(4) { animation-delay: 180ms; }

/* 趋势条从基线生长，逐条推进 */
@keyframes bar-grow {
  from {
    transform: scaleY(0);
  }
}

.chart-bar {
  transform-origin: bottom;
  animation: bar-grow 0.5s var(--ease-out) backwards;
}

.chart-bar-wrap:nth-child(2) .chart-bar { animation-delay: 45ms; }
.chart-bar-wrap:nth-child(3) .chart-bar { animation-delay: 90ms; }
.chart-bar-wrap:nth-child(4) .chart-bar { animation-delay: 135ms; }
.chart-bar-wrap:nth-child(5) .chart-bar { animation-delay: 180ms; }
.chart-bar-wrap:nth-child(6) .chart-bar { animation-delay: 225ms; }
.chart-bar-wrap:nth-child(7) .chart-bar { animation-delay: 270ms; }

/* 列表内容加载后级联浮现 */
.data-table tbody tr,
.alert-card {
  animation: rise-in 0.3s var(--ease-out) backwards;
}

.data-table tbody tr:nth-child(2),
.alert-card:nth-child(2) { animation-delay: 50ms; }

.data-table tbody tr:nth-child(3),
.alert-card:nth-child(3) { animation-delay: 100ms; }

.data-table tbody tr:nth-child(4) { animation-delay: 150ms; }

.data-table tbody tr:nth-child(5) { animation-delay: 200ms; }
.data-table tbody tr:nth-child(6) { animation-delay: 250ms; }
</style>
