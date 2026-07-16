<template>
  <div class="home-page">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div class="welcome-content">
        <div class="welcome-title">{{ greeting }}，{{ displayName }}</div>
        <!-- 结论必须等数据：加载中/失败时绝不显示「0 个事件」和「态势平稳」。
             此前空数组被当真实结论渲染，首屏先亮几秒绿色「平稳」，数据到了
             才翻成「5 条高风险预警」（用户实测截图）——不知道 ≠ 平稳。 -->
        <div class="welcome-sub">
          <template v-if="eventsLoading">今天是{{ todayText }}。事件数据加载中…</template>
          <template v-else-if="eventsError">今天是{{ todayText }}。事件数据加载失败，请刷新重试。</template>
          <template v-else>
            今天是{{ todayText }}。当前共
            <strong>{{ publishedEvents.length }}</strong> 个已发布事件，其中
            <strong>{{ highRiskEvents.length }}</strong> 条高风险预警、
            <strong>{{ mediumRiskEvents.length }}</strong> 条中风险事件。
          </template>
        </div>
      </div>
      <div class="welcome-meta">
        <span v-if="eventsLoading" class="calm-flag calm-flag--pending">
          <el-icon :size="14" class="is-loading"><Loading /></el-icon>
          数据加载中…
        </span>
        <span v-else-if="eventsError" class="calm-flag calm-flag--pending">
          <el-icon :size="14"><WarningFilled /></el-icon>
          数据加载失败
        </span>
        <button
          v-else-if="highRiskEvents.length > 0"
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
        title="最近新增"
        :value="todayNewCount"
        :icon="Clock"
        desc="最近数据日发生的事件"
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
      <div class="section-card chart-card">
        <div class="section-header">
          <span class="section-title">
            近{{ trendDays }}天发帖趋势
            <el-tooltip :content="TREND_TOOLTIP" placement="top" :show-after="150">
              <el-icon class="title-info" :size="13"><InfoFilled /></el-icon>
            </el-tooltip>
          </span>
          <span v-if="!trendLoading && trendEnd" class="section-hint">
            截至 {{ trendEnd }} · 最近数据日
          </span>
        </div>
        <div class="section-body">
          <div v-if="trendLoading" class="chart-skeleton">
            <span v-for="i in 7" :key="i" :style="{ height: 18 + ((i * 37) % 60) + '%' }" />
          </div>
          <div v-else class="mini-chart" role="img" :aria-label="`近${trendDays}天每日发帖数量柱状图`">
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
                >{{ item.value }}</span>
                <!-- 峰值柱用数据强调色（琥珀）：图上唯一的焦点，其余柱保持品牌蓝 -->
                <div class="chart-bar" :class="{ 'chart-bar--peak': index === maxTrendIndex }"></div>
              </div>
              <!-- 30 根柱子放不下 30 个日期标签——每 5 天一个 + 收尾那天 -->
              <div class="chart-label">{{ showLabel(index) ? item.name : '' }}</div>
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
          <EmptyState
            v-else-if="posts.length === 0"
            title="暂无帖子数据"
            hint="请确认后端已启动（运行 dev.bat）后刷新重试"
          />
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
                <td><span :class="['plat-pill', `plat-${post.platform}`]">{{ platformLabel(post.platform) }}</span></td>
                <td class="post-title">
                  <CoverThumb :seed="post.title" :size="26" />
                  <span class="post-title-text">{{ post.title }}</span>
                </td>
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
              v-spotlight
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
  InfoFilled,
  Loading,
  Warning,
  WarningFilled,
} from '@element-plus/icons-vue'
import { formatHeat } from '@/utils/heat'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import CoverThumb from '@/components/effects/CoverThumb.vue'
import { checkHealth, fetchPosts, fetchSentimentStats } from '@/api/posts'
import { fetchPublishedEvents } from '@/api/events'
import { getCurrentUser, getCurrentRole } from '@/auth/session'

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
const healthChecking = ref(true)
const backendDesc = ref('检测中…')
// 没检测完就显示「未连接」也是抢答——三态：检测中 / 正常 / 未连接
const backendStatus = computed(() => {
  if (healthChecking.value) return '检测中'
  return backendOk.value ? '正常' : '未连接'
})

async function checkBackendHealth() {
  try {
    const data = await checkHealth()
    backendOk.value = data.pong === true
    backendDesc.value = backendOk.value ? '后端响应正常' : '响应异常'
  } catch {
    backendDesc.value = '后端未启动'
  } finally {
    healthChecking.value = false
  }
}

onMounted(() => {
  // 四个请求并行：健康检查此前被 await 在最前面，后端冷启动时它一慢，
  // 帖子/事件/趋势全被拖着不发，「平稳假象」的窗口被拉得更长。
  checkBackendHealth()
  loadPosts()
  loadEvents()
  loadPostTrend()
})

// ——— 发帖趋势（服务端按天聚合，复用舆情分析页的统计接口） ———
const postTrend = ref([])
const trendDays = ref(30)
const trendLoading = ref(true)

async function loadPostTrend() {
  try {
    const stats = await fetchSentimentStats()
    postTrend.value = stats.daily_trend || []
    trendDays.value = stats.trend_days || 30
  } catch {
    postTrend.value = []
  } finally {
    trendLoading.value = false
  }
}

// ——— 帖子数据 ———
const posts = ref([])
const postsTotal = ref(0)
const postsLoading = ref(true)

async function loadPosts() {
  try {
    const data = await fetchPosts(1, 10)
    posts.value = data.items
    postsTotal.value = data.total ?? data.items.length
  } catch (error) {
    // 不垫 mock 假数据：失败就空列表。顶栏徽标会同步显示「后端未连接」。
    console.warn('[home] 帖子加载失败', error)
    posts.value = []
    postsTotal.value = 0
  } finally {
    postsLoading.value = false
  }
}

// ——— 事件数据（加载失败就空列表，不再由 api 层降级假数据） ———
const events = ref([])
const eventsLoading = ref(true)
const eventsError = ref(false) // 失败和「真的没有事件」不许长一样

async function loadEvents() {
  eventsError.value = false
  try {
    events.value = await fetchPublishedEvents()
  } catch (error) {
    console.warn('[home] 事件加载失败', error)
    events.value = []
    eventsError.value = true
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
  // 与事件列表页同口径：后端时间是 "2026-05-24 12:00" 带空格格式，
  // 不换成 T 的话部分浏览器解析为 Invalid Date，「最近新增」会算错
  const text = String(value || '').trim()
  if (!text) return null
  const ts = new Date(text.replace(' ', 'T')).getTime()
  return Number.isFinite(ts) ? ts : null
}

// —— 时间口径：一律用 `event_time`（事件**发生**的时间），不是 `updated_at`（入库时间）——
//
// 这三个数字此前全都建在 updated_at 上，而所有事件都是同一次流水线生成的：
//   - 「今日新增 9」的真实含义是"上一次流水线生成了 9 个事件"，和"今天新增 9 个舆情事件"
//     毫无关系（真实值是 0——最新的事件也在 50 天前）；
//   - 「近7天事件热度趋势」画的是"我们什么时候跑的流水线"，7/13 那根 6.2 万的巨柱就是
//     那天入了 9 个事件，不是那天爆了 6.2 万热度的舆情。
const latestTime = computed(() => {
  const times = publishedEvents.value.map((e) => parseTime(e.event_time)).filter(Boolean)
  return times.length ? Math.max(...times) : Date.now()
})

// 最近数据日不是"今天"时（语料是历史数据），明确标注时间口径
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

// 「最近数据日新增」：和最新事件同一天**发生**的事件数。锚在最近数据日而不是今天——
// 语料不是实时的，锚在今天会恒为 0。卡片文案已如实写明"按最近数据日统计"。
const todayNewCount = computed(() => {
  const anchor = new Date(latestTime.value)
  return publishedEvents.value.filter((e) => {
    const ts = parseTime(e.event_time)
    if (!ts) return false
    const d = new Date(ts)
    return (
      d.getFullYear() === anchor.getFullYear() &&
      d.getMonth() === anchor.getMonth() &&
      d.getDate() === anchor.getDate()
    )
  }).length
})

// ——— 近 30 天**发帖**趋势（按帖子发布日聚合，服务端算好） ———
//
// 为什么改用帖子而不是事件：10 个已发布事件分布在 340 天里，任何 7 天窗口最多 1 个——
// 用事件做趋势，图上永远是一根孤零零的柱子。帖子有 397 条、每天都有，趋势才有形状。
// 复用舆情分析页的 /api/sentiment/stats（服务端按天聚合，锚在最近数据日、空白天补 0）。
const trendData = computed(() =>
  postTrend.value.map((point) => ({
    name: point.date.slice(5).replace('-', '/'), // 2026-05-24 -> 5/24
    value: point.count,
  })),
)

const maxTrend = computed(() => Math.max(...trendData.value.map((d) => d.value), 0))
const maxTrendIndex = computed(() => trendData.value.findIndex((d) => d.value === maxTrend.value))

// 趋势图的收尾日（= 最近数据日，服务端锚定的）
const trendEnd = computed(() => {
  const last = postTrend.value[postTrend.value.length - 1]
  return last ? last.date.slice(5).replace('-', '/') : ''
})

// 30 根柱子塞不下 30 个日期标签：每 5 天标一个，外加最后一天
function showLabel(index) {
  const total = trendData.value.length
  if (total <= 10) return true
  return index % 5 === 0 || index === total - 1
}

const TREND_TOOLTIP =
  '每日新采集的帖子数（按帖子的发布时间聚合）。用帖子而不是事件做趋势：' +
  '已发布事件只有十几个、跨度大半年，任何一个短窗口里都最多一两个，画不出趋势。'

// ——— 工具函数 ———
function formatTime(ts) {
  if (!ts) return '未知'
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

const PLATFORM_LABELS = { xhs: '小红书', weibo: '微博', tieba: '贴吧', zhihu: '知乎', ks: '快手', web: '网页证据', campus: '校园投稿' }
function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || '未知'
}

</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 平台品牌标签：小红书红 / 快手金 / 微博橙 …，与事件详情、数据管理全站统一 */
.plat-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: var(--color-surface-2, #f5f7fa);
  border: 1px solid var(--color-border);
}
.plat-xhs { color: #be123c; background: #fff1f2; border-color: #fecdd3; }
.plat-weibo { color: #c2410c; background: #fff7ed; border-color: #fed7aa; }
.plat-ks { color: #a16207; background: #fefce8; border-color: #fde68a; }
.plat-tieba { color: #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }
.plat-zhihu { color: #0369a1; background: #f0f9ff; border-color: #bae6fd; }
.plat-web { color: #047857; background: #ecfdf5; border-color: #a7f3d0; }

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

/* 加载中/失败的中性徽章：灰色，不许长得像任何结论 */
.calm-flag--pending {
  background: var(--color-surface-2, #f5f7fa);
  border-color: var(--color-border-light);
  color: var(--color-text-muted);
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

/* 趋势卡按内容高度收缩、顶部对齐——不被右侧「最新帖子」强行撑高，
   这样卡片内部没有多余空白，柱子直接锚在固定高度图表的底部 */
.chart-card {
  align-self: start;
}

/* 迷你柱状图：固定高度，柱子锚在底部；30 根柱子放不下时横向滚动 */
.mini-chart {
  height: 210px;
  display: flex;
  align-items: flex-end;
  gap: 5px;
  padding-top: 20px;
  /* 底部留出一条独立空隙给横向滚动条，避免它压在日期标签上 */
  padding-bottom: 14px;
  overflow-x: auto;
  overflow-y: hidden;
}

/* 仅趋势图的横向滚动条稍作弱化，避免抢镜 */
.mini-chart::-webkit-scrollbar {
  height: 6px;
}
.mini-chart::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}
.mini-chart::-webkit-scrollbar-thumb:hover {
  background: #cbd5e1;
}

.chart-bar-wrap {
  /* 可增长填满宽屏，但不缩小到 16px 以下——窄屏/放大时溢出触发横向滚动 */
  flex: 1 0 16px;
  min-width: 16px;
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
  /* 顶浅底深的纵向渐变：柱体有了"受光面"，比平涂多一层材质 */
  background: linear-gradient(180deg, var(--brand-300), var(--brand-500));
  border-radius: 4px 4px 0 0;
  min-height: 3px;
  transition: background var(--dur-fast) var(--ease-out), height var(--dur-slow) var(--ease-out);
}

.chart-bar-wrap:hover .chart-bar {
  background: var(--brand-600);
}

.chart-bar--peak {
  background: linear-gradient(180deg, #f2a950, var(--color-data-accent));
}

.chart-bar-wrap:hover .chart-bar--peak {
  background: var(--color-data-accent-text);
}

.chart-value {
  font-family: var(--font-numeric);
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

/* 峰值标签等柱子生长完再浮现，避免动画期间数字悬空；颜色与峰值柱同为琥珀 */
.chart-value--pinned {
  color: var(--color-data-accent-text);
  font-weight: 700;
  animation: value-in 0.3s var(--ease-out) 0.55s backwards;
}

@keyframes value-in {
  from { opacity: 0; }
}

/* 日期标签：单行不换行，居中；只在每 5 天显示一个，稀疏所以横向溢出到相邻空标签格无碰撞。
   它在柱子基线下方 8px，与柱子分属两层，不会再和柱子混叠。 */
.chart-label {
  height: 14px;
  line-height: 14px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-text-faint);
  white-space: nowrap;
  pointer-events: none;
}

.chart-skeleton {
  height: 210px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding-top: 20px;
  padding-bottom: 14px;
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
  display: flex;
  align-items: center;
  gap: 8px;
}

.post-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
