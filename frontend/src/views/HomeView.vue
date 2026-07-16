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
        <!-- 语料不是实时的：明确标注数据口径（最近数据日），首页早该有这个 -->
        <span v-if="!eventsLoading && !eventsError" class="asof-tag">数据截至 {{ latestDayLabel }}</span>
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
      <!-- 中风险数字挪进下方「风险结构」；「后端状态」卡删除——顶栏徽标已实时显示连接状态 -->
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
          <!-- 手绘 SVG 折线（维持全站零图表库路线）：面积渐变 + 描线入场 +
               峰值琥珀常显 + 末点常显；逐日数值走纯 CSS 悬停提示 -->
          <div v-else class="trend-chart" role="img" :aria-label="`近${trendDays}天每日发帖数量折线图`">
            <svg class="trend-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stop-color="#5a74dd" stop-opacity="0.22" />
                  <stop offset="1" stop-color="#5a74dd" stop-opacity="0.02" />
                </linearGradient>
              </defs>
              <path class="trend-area" :d="trendAreaPath" fill="url(#trendFill)" />
              <polyline class="trend-line" :points="trendLinePoints" pathLength="1" />
            </svg>
            <div
              v-for="(point, index) in chartPoints"
              :key="point.name"
              class="trend-hit"
              :style="{ left: `${point.x - 50 / chartPoints.length}%`, width: `${100 / chartPoints.length}%`, '--dot-y': `${point.y}%` }"
              :data-tip="`${point.name} · ${point.value} 条`"
            />
            <span
              class="trend-mark trend-mark--peak"
              :style="{ left: `${peakPoint.x}%`, top: `${peakPoint.y}%` }"
            >{{ peakPoint.value }}</span>
            <span
              v-if="peakPoint !== lastPoint"
              class="trend-mark trend-mark--last"
              :style="{ left: `${lastPoint.x}%`, top: `${lastPoint.y}%` }"
            >{{ lastPoint.value }}</span>
            <div class="trend-labels">
              <span v-for="(point, index) in chartPoints" :key="`l-${point.name}`">
                {{ showLabel(index) ? point.name : '' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 风险结构：已发布事件按风险分层（全部由已加载的事件现算，无造假环比） -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">风险结构</span>
          <span class="section-hint">已发布事件按风险分层</span>
        </div>
        <div class="section-body risk-structure" v-loading="eventsLoading">
          <div v-for="row in riskStructure" :key="row.key" class="risk-row">
            <span :class="['risk-dot', `risk-dot--${row.key}`]"></span>
            <span class="risk-name">{{ row.label }}</span>
            <span class="risk-track">
              <span :class="['risk-fill', `risk-fill--${row.key}`]" :style="{ width: `${row.pct}%` }" />
            </span>
            <span class="risk-num">{{ row.count }}</span>
            <span class="risk-pct">{{ row.pct }}%</span>
          </div>
          <p class="risk-total">
            总计 <b>{{ publishedEvents.length }}</b> 个已发布事件 ·
            风险等级由 LLM 研判、发布前经人工审核
          </p>
        </div>
      </div>

      <!-- 需要关注：按四轴优先级取前 5（复用舆情关注页的口径——热度是"多少人在看"，
           不是"该先动哪个"），行可点进详情 -->
      <div class="section-card span-3">
        <div class="section-header">
          <span class="section-title">
            需要关注
            <span class="section-hint">按处置优先级排序 · 前 5 条</span>
          </span>
          <el-button size="small" type="primary" text @click="$router.push('/personal')">
            查看更多 →
          </el-button>
        </div>
        <div class="section-body">
          <table v-if="focusEvents.length" class="data-table focus-table">
            <thead>
              <tr>
                <th>事件</th>
                <th>风险等级</th>
                <th>热度</th>
                <th>事件年龄</th>
                <th>处置状态</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="event in focusEvents"
                :key="eventKey(event)"
                class="focus-row"
                @click="$router.push(`/events/${eventKey(event)}`)"
              >
                <td class="focus-title">
                  <CoverThumb :seed="event.title" :size="28" />
                  <span class="focus-title-text">{{ event.title }}</span>
                </td>
                <td>
                  <span :class="['risk-tag', `risk-tag--${event.riskLevel}`]">
                    {{ event.riskLevel === 'high' ? '高风险' : '中风险' }}
                  </span>
                </td>
                <td class="text-num" :title="`精确值 ${event.heatScore}`">{{ formatHeat(event.heatScore) }}</td>
                <td class="text-muted">{{ formatAge(event.age_days) }}</td>
                <td>
                  <span
                    v-if="hasLifecycle(event.lifecycle)"
                    :class="['lifecycle-tag', `lifecycle-tag--${event.lifecycle}`]"
                    :title="event.lifecycle_reason || ''"
                  >{{ lifecycleLabel(event.lifecycle) }}</span>
                  <span v-else class="text-muted">—</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!eventsLoading && !focusEvents.length" class="empty-state empty-state--calm">
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
  ChatLineSquare,
  CircleCheckFilled,
  Clock,
  Collection,
  InfoFilled,
  Loading,
  Warning,
  WarningFilled,
} from '@element-plus/icons-vue'
import { formatHeat } from '@/utils/heat'
import { formatAge } from '@/utils/age'
import { hasLifecycle, lifecycleLabel } from '@/utils/lifecycle'
import StatCard from '@/components/StatCard.vue'
import CoverThumb from '@/components/effects/CoverThumb.vue'
import { fetchPosts, fetchSentimentStats } from '@/api/posts'
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

// 「后端状态」卡已删（顶栏徽标实时显示连接状态），健康检查随之退场
onMounted(() => {
  // 三个请求并行发出，互不阻塞
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

// ——— 采集帖子总数（帖子列表已删——帖子层是舆情分析页的职责，这里只要计数） ———
const postsTotal = ref(0)
const postsLoading = ref(true)

async function loadPosts() {
  try {
    const data = await fetchPosts(1, 1)
    postsTotal.value = data.total ?? 0
  } catch (error) {
    // 不垫假数据：失败就 0。顶栏徽标会同步显示「后端未连接」。
    console.warn('[home] 帖子计数加载失败', error)
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

// —— 风险结构：已发布事件按风险分层（全部现算，不做没有历史快照的假环比） ——
const RISK_ROWS = [
  { key: 'high', label: '高风险' },
  { key: 'medium', label: '中风险' },
  { key: 'low', label: '低风险' },
]

const riskStructure = computed(() => {
  const total = publishedEvents.value.length || 1
  return RISK_ROWS.map((row) => {
    const count = publishedEvents.value.filter((e) => e.riskLevel === row.key).length
    return { ...row, count, pct: Math.round((count / total) * 100) }
  })
})

// —— 需要关注：按**四轴优先级**取前 5（与舆情关注页同口径）——
// 不按热度排：热度是"多少人在看"，不是"该先动哪个"（那页已实测论证：
// 热度第一的事件是已了结的，悬而未决的反而沉在第二）。
const focusEvents = computed(() =>
  publishedEvents.value
    .filter((e) => ['high', 'medium'].includes(e.riskLevel))
    .slice()
    .sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0))
    .slice(0, 5),
)

function eventKey(event) {
  return event.raw_id ?? event.id
}

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

// —— 折线图坐标（0-100 归一化，SVG viewBox 同尺度）——
// 上下各留 8% 呼吸空间：峰值数字不顶天、零值线不贴底
const chartPoints = computed(() => {
  const rows = trendData.value
  const max = maxTrend.value
  return rows.map((row, index) => ({
    ...row,
    x: rows.length > 1 ? (index / (rows.length - 1)) * 100 : 50,
    y: max ? 92 - (row.value / max) * 84 : 92,
  }))
})

const trendLinePoints = computed(() => chartPoints.value.map((p) => `${p.x},${p.y}`).join(' '))

const trendAreaPath = computed(() => {
  const points = chartPoints.value
  if (!points.length) return ''
  const line = points.map((p) => `L ${p.x} ${p.y}`).join(' ')
  return `M ${points[0].x} 100 ${line} L ${points[points.length - 1].x} 100 Z`
})

const peakPoint = computed(() => chartPoints.value[maxTrendIndex.value] || { x: 0, y: 0, value: 0 })
const lastPoint = computed(() => chartPoints.value[chartPoints.value.length - 1] || peakPoint.value)

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

</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 平台品牌标签已随「最新校园帖子」一起移除——帖子层是舆情分析页的职责 */

/* 欢迎横幅 */
.welcome-banner {
  /* 双光晕（右上品牌靛 + 左下极淡雾绿）：登录页极光的白天低配版——静态、极淡 */
  background:
    radial-gradient(circle at 90% 0%, rgba(59, 91, 219, 0.1), transparent 46%),
    radial-gradient(circle at 4% 120%, rgba(76, 143, 116, 0.07), transparent 40%),
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

/* 数据口径角标：语料不是实时的，"截至哪天"必须看得见 */
.asof-tag {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: var(--font-numeric);
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

/* 统计卡片网格：4 张（中风险并入风险结构，后端状态归顶栏徽标） */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

@media (max-width: 1100px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}

/* 内容区：左折线图（宽）+ 右风险结构，第二行「需要关注」通栏 */
.content-grid {
  display: grid;
  grid-template-columns: 1.45fr 1fr;
  gap: 14px;
}

@media (max-width: 1100px) {
  .content-grid { grid-template-columns: 1fr; }
}

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
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

/* 趋势卡与风险结构卡同行拉伸等高（网格默认 stretch），边框线齐平 */

/* —— 折线趋势图：SVG 归一化到 0-100，容器控制真实尺寸 —— */
.trend-chart {
  position: relative;
  height: 210px;
  margin-bottom: 22px; /* 给绝对定位的日期标签行留出空间 */
}

.trend-svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

.trend-line {
  fill: none;
  stroke: var(--brand-500);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
  /* preserveAspectRatio=none 会拉伸坐标系，这条让描边不跟着变形 */
  vector-effect: non-scaling-stroke;
  /* 描线入场：pathLength=1 归一化后 dashoffset 从 1 收到 0 */
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: trend-draw 1s var(--ease-out) 0.15s forwards;
}

@keyframes trend-draw {
  to { stroke-dashoffset: 0; }
}

/* 面积渐变等折线画完再淡入，避免"地基先于轮廓"的怪相 */
.trend-area {
  opacity: 0;
  animation: trend-fade 0.5s ease 0.9s forwards;
}

@keyframes trend-fade {
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .trend-line { animation: none; stroke-dashoffset: 0; }
  .trend-area { animation: none; opacity: 1; }
}

/* 逐日悬停命中区：纯 CSS 提示（悬停出点 + 顶部气泡），无 JS 状态 */
.trend-hit {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 1;
}

.trend-hit::before {
  content: '';
  position: absolute;
  left: 50%;
  top: var(--dot-y, 50%);
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand-600);
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px var(--brand-200, #b9c6f2);
  transform: translate(-50%, -50%);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.trend-hit::after {
  content: attr(data-tip);
  position: absolute;
  left: 50%;
  top: calc(var(--dot-y, 50%) - 14px);
  transform: translate(-50%, -100%);
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--color-text);
  color: #fff;
  font-size: 11px;
  font-family: var(--font-numeric);
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.trend-hit:hover::before,
.trend-hit:hover::after {
  opacity: 1;
}

/* 常显标注：峰值（琥珀）与末点（品牌蓝），点 + 数字一体 */
.trend-mark {
  position: absolute;
  transform: translate(-50%, calc(-100% - 10px));
  font-family: var(--font-numeric);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  pointer-events: none;
  animation: trend-fade 0.3s var(--ease-out) 1s backwards;
}

.trend-mark::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -8px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 2px solid #fff;
  transform: translateX(-50%);
}

.trend-mark--peak { color: var(--color-data-accent-text); }
.trend-mark--peak::after { background: var(--color-data-accent); box-shadow: 0 0 0 1px #f2a950; }
.trend-mark--last { color: var(--brand-700); }
.trend-mark--last::after { background: var(--brand-600); box-shadow: 0 0 0 1px var(--brand-200, #b9c6f2); }

/* 日期标签行：与折线同一横向坐标系（等分格），贴在图下方 */
.trend-labels {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -22px;
  display: flex;
}

.trend-labels span {
  flex: 1;
  text-align: center;
  font-size: 11px;
  color: var(--color-text-faint);
  white-space: nowrap;
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

.text-muted { color: var(--color-text-muted); }
.text-num { font-family: var(--font-numeric); }

/* —— 风险结构：点 + 名称 + 生长条 + 计数/占比 —— */
.risk-structure { gap: 0; }

.risk-row {
  display: grid;
  grid-template-columns: 8px 52px 1fr 34px 42px;
  align-items: center;
  gap: 10px;
  padding: 11px 0;
  font-size: 13px;
}

.risk-row + .risk-row { border-top: 1px dashed var(--color-border-light); }

.risk-dot { width: 8px; height: 8px; border-radius: 50%; }
.risk-dot--high { background: var(--color-danger); }
.risk-dot--medium { background: var(--color-warning); }
.risk-dot--low { background: var(--color-success); }

.risk-name { color: var(--color-text-secondary); }

.risk-track {
  height: 8px;
  border-radius: 999px;
  background: var(--color-surface-2, #f0f2f5);
  overflow: hidden;
}

.risk-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  transform-origin: left;
  animation: risk-grow 0.6s var(--ease-out) backwards;
}

.risk-row:nth-child(2) .risk-fill { animation-delay: 100ms; }
.risk-row:nth-child(3) .risk-fill { animation-delay: 200ms; }

@keyframes risk-grow {
  from { transform: scaleX(0); }
}

@media (prefers-reduced-motion: reduce) {
  .risk-fill { animation: none; }
}

.risk-fill--high { background: linear-gradient(90deg, #e5484d, var(--color-danger)); }
.risk-fill--medium { background: linear-gradient(90deg, #edb95e, var(--color-warning)); }
.risk-fill--low { background: linear-gradient(90deg, #58b77d, var(--color-success)); }

.risk-num {
  text-align: right;
  font-weight: 700;
  font-family: var(--font-numeric);
}

.risk-pct {
  text-align: right;
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: var(--font-numeric);
}

.risk-total {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.risk-total b { color: var(--color-text-secondary); font-family: var(--font-numeric); }

/* —— 需要关注表格 —— */
.span-3 {
  grid-column: 1 / -1;
}

.focus-row { cursor: pointer; }

.focus-title {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 420px;
  font-weight: 600;
}

.focus-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.risk-tag--high { background: var(--color-danger-bg); color: var(--color-danger-text); }
.risk-tag--medium { background: var(--color-warning-bg); color: var(--color-warning-text); }

.lifecycle-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.lifecycle-tag--escalating { background: var(--color-danger-bg); color: var(--color-danger-text); }
.lifecycle-tag--ongoing { background: var(--color-warning-bg); color: var(--color-warning-text); }
.lifecycle-tag--resolved { background: var(--color-success-bg); color: var(--color-success-text); }
.lifecycle-tag--not_applicable { background: var(--color-surface-2); color: var(--color-text-muted); }

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

.content-grid > .section-card {
  animation: rise-in 0.4s var(--ease-out) backwards;
}

.content-grid > .section-card:nth-child(2) { animation-delay: 60ms; }
.content-grid > .section-card:nth-child(3) { animation-delay: 120ms; }

/* 表格行加载后级联浮现 */
.data-table tbody tr {
  animation: rise-in 0.3s var(--ease-out) backwards;
}

.data-table tbody tr:nth-child(2) { animation-delay: 50ms; }
.data-table tbody tr:nth-child(3) { animation-delay: 100ms; }
.data-table tbody tr:nth-child(4) { animation-delay: 150ms; }
.data-table tbody tr:nth-child(5) { animation-delay: 200ms; }
</style>
