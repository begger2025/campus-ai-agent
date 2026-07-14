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
                :style="{ '--row-i': rowIndex }"
                @click="openWorkbench(event)"
              >
                <!-- 标题列吃掉表格的全部弹性空间（其余列都是定宽）。只放一个 8 字标题的话，
                     标题和风险列之间就是几百像素的空白——用户看到的正是这个。
                     把摘要补进来：空白变成信息，检索页扫一眼就知道这条是什么事。 -->
                <td class="title-cell">
                  <span class="title-main">{{ event.title }}</span>
                  <span v-if="event.summary" class="title-sub">{{ event.summary }}</span>
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
                <!-- 顺序由后端定（PLATFORM_DISPLAY_ORDER），全站一致——原本它跟着代表帖的
                     热度走，同一组平台在不同事件里会排出不同顺序。
                     也不再 slice(0,2)：截断一个只有 2~3 个值的列表毫无必要，
                     超过 3 个才折成 +N。 -->
                <td>
                  <div class="source-list">
                    <span
                      v-for="source in event.sourcePlatforms.slice(0, 3)"
                      :key="source"
                      :class="['source-pill', `source-${source}`]"
                    >{{ sourceLabel(source) }}</span>
                    <span
                      v-if="event.sourcePlatforms.length > 3"
                      class="source-more"
                      :title="event.sourcePlatforms.map(sourceLabel).join('、')"
                    >+{{ event.sourcePlatforms.length - 3 }}</span>
                  </div>
                </td>
                <td>{{ displayTime(event.updatedAt) }}</td>
                <td>
                  <span class="published-dot"></span>
                  已发布
                </td>
                <td class="action-cell">
                  <!-- 「研判」跳工作台并选中这一条：列表负责**找到**事件，工作台负责
                       **研判**它（AI 的风险依据 / 四轴分解 / 状态证据 / 代表帖）。
                       两页因此是互补的，不是各做一半。 -->
                  <button type="button" @click.stop="openWorkbench(event)">研判</button>
                  <button type="button" @click.stop="openDetail(event)">详情</button>
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

      <!-- 「事件预览」侧栏已移除：它和舆情工作台的中栏做同一件事（摘要/热度/置信度/
           标签/趋势），而工作台做得更深（AI 风险依据、四轴分解、状态证据、代表帖溯源）。
           这一页的职责是**检索**——找到事件，然后交给工作台去研判。
           见 docs/page-responsibilities.md。 -->
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
import { InfoFilled, Search } from '@element-plus/icons-vue'
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

// 「事件预览」侧栏连同它的两处假数据一起删了（2026-07-14）：
//   - 「来源分布」的百分比是**写死的**（weibo 56.2 / xhs 28.1 / tieba 15.7，其余按下标瞎算），
//     和这个事件真实的来源构成毫无关系——一个看板不能展示编出来的比例。
//   - 「热度趋势（近7天）」的 `event.trend` 后端**根本不返回**，画出来是一张只有坐标轴的空图。
// 这一页的职责是**检索**（找到事件）；研判交给工作台（那里有 AI 的风险依据、四轴分解、
// 状态证据、代表帖溯源）。见 docs/page-responsibilities.md。

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
  } catch (error) {
    ElMessage.error(error.message || '事件列表加载失败')
  } finally {
    loading.value = false
  }
}

// 找到事件之后去研判它：跳工作台并选中这一条（列表找 → 工作台研判）。
function openWorkbench(event) {
  router.push({ path: '/opinion', query: { event_id: event.raw_id ?? event.id } })
}

function applyFilters() {
  pagination.page = 1
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
}

function setQuick(value) {
  filters.quick = value
  filters.risk = ['high', 'medium', 'low'].includes(value) ? value : 'all'
  pagination.page = 1
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
  if (value === 'zhihu') return '知'
  if (value === 'ks') return '快'
  if (value === 'web') return '网'
  if (value === 'tieba') return '贴'
  return '源'
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
  /* 预览侧栏已移除（见 script 里的说明）——表格独占整幅，检索页就该把列表铺开 */
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  align-items: stretch;
}

.event-list-card { min-height: 0; display: flex; flex-direction: column; }

/* 面板标题：收敛到产品级字阶（页面主标题在顶栏，这里只是分区名） */
.compact-panel-title {
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

/* min-width 要盖得住定宽列之和（692px）再加标题列的下限，否则窄屏下标题会被压没 */
.compact-table { width: 100%; min-width: 940px; table-layout: fixed; border-collapse: collapse; font-size: 12px; }

/* 定宽内容的列显式定宽，弹性空间留给标题列（标题+摘要两行，正好用得上）。
   来源列从 104px 加宽到 168px：原本装不下三个平台胶囊，只能 slice(0,2) 截断。 */
.compact-table th:nth-child(2) { width: 80px; }   /* 风险 */
.compact-table th:nth-child(3) { width: 128px; }  /* 热度 */
.compact-table th:nth-child(4) { width: 168px; }  /* 来源 */
.compact-table th:nth-child(5) { width: 100px; }  /* 发布时间 */
.compact-table th:nth-child(6) { width: 84px; }   /* 状态 */
.compact-table th:nth-child(7) { width: 132px; }  /* 操作 */

.compact-table th, .compact-table td {
  padding: 0 12px; border-bottom: 1px solid var(--color-border-light);
  text-align: left; vertical-align: middle; white-space: nowrap;
}

.compact-table th { height: 38px; color: var(--color-text-muted); font-weight: 600; background: var(--color-surface-2); }
.compact-table td { height: 56px; }
.compact-table tbody tr { cursor: pointer; transition: background var(--dur-fast) var(--ease-out); }
.compact-table tbody tr:hover { background: var(--color-surface-2); }
.col-title { width: auto; }

/* 标题 + 摘要两行：标题列吃掉全部弹性空间，只放一个 8 字标题的话它右边就是几百像素的空白 */
.title-cell { padding-top: 8px; padding-bottom: 8px; }
.title-cell span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.title-main { color: var(--color-text); font-weight: 600; line-height: 1.45; }
.title-sub {
  margin-top: 2px;
  color: var(--color-text-muted);
  font-size: 11.5px;
  font-weight: 400;
  line-height: 1.4;
}

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

.source-list { display: flex; flex-wrap: nowrap; gap: 5px; }
.source-pill { height: 22px; padding: 0 6px; display: inline-flex; align-items: center; border-radius: 5px; font-size: 11px; font-weight: 800; color: var(--color-text-secondary); background: var(--color-surface-2, #f5f7fa); border: 1px solid var(--color-border); white-space: nowrap; }
.source-more { height: 22px; padding: 0 5px; display: inline-flex; align-items: center; border-radius: 5px; font-size: 11px; font-weight: 700; color: var(--color-text-muted); background: var(--color-surface-2); border: 1px solid var(--color-border-light); cursor: help; }
.source-weibo { color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa; }
.source-xhs { color: #be123c; background: #fff1f2; border: 1px solid #fecdd3; }
.source-ks { color: #a16207; background: #fefce8; border: 1px solid #fde68a; }
.source-tieba { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.source-zhihu { color: #0369a1; background: #f0f9ff; border: 1px solid #bae6fd; }
.source-web { color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; }

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
.source-icon { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; color: #fff; font-size: 12px; font-weight: 800; background: #94a3b8; }
.source-icon-weibo { background: #ef4444; }
.source-icon-xhs { background: #f43f5e; }
.source-icon-ks { background: #f59e0b; }
.source-icon-tieba { background: #3b82f6; }
.source-icon-zhihu { background: #0284c7; }
.source-icon-web { background: #10b981; }

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
}
@media (max-width: 1120px) {
  .event-filter, .events-layout { grid-template-columns: 1fr; }
  .risk-tabs { grid-template-columns: repeat(2, 1fr); height: auto; }
  .risk-tab { min-height: 40px; border-right: 0; }
}
</style>
