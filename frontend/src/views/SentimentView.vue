<template>
  <div class="sentiment-page">
    <!-- 统计摘要 -->
    <div class="stat-row">
      <StatCard title="帖子总数" :value="libraryTotal" :icon="ChatLineSquare" color="primary" desc="已分析帖子" />
      <StatCard title="高风险事件" :value="highRiskCount" :icon="Warning" color="danger" desc="需优先处理" />
      <StatCard title="中风险事件" :value="midRiskCount" :icon="Bell" color="warning" desc="持续跟踪" />
      <StatCard title="低风险事件" :value="lowRiskCount" :icon="CircleCheck" color="success" desc="态势平稳" />
    </div>

    <!-- 搜索 + 筛选 -->
    <div class="filter-bar">
      <DataSourceBadge source="real" style="margin-right:8px" />
      <el-input
        v-model="keyword"
        placeholder="搜索标题、平台、作者…"
        clearable
        prefix-icon="Search"
        style="width: 280px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-select
        v-model="riskFilter"
        placeholder="全部风险"
        clearable
        style="width: 140px"
        @change="handleSearch"
      >
        <el-option label="高风险" value="high" />
        <el-option label="中风险" value="medium" />
        <el-option label="低风险" value="low" />
      </el-select>
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="resetFilter">重置</el-button>
    </div>

    <div class="main-grid">
      <!-- 左：帖子列表 -->
      <div class="section-card posts-panel">
        <div class="section-header">
          <span class="section-title">校园帖子列表</span>
          <span class="section-count">共 {{ postsTotal }} 条</span>
        </div>
        <div class="section-body">
          <div v-if="loading" class="loading-state">
            <el-icon class="is-loading"><Loading /></el-icon> 加载中…
          </div>
          <template v-else>
            <div
              v-for="post in posts"
              :key="post.id"
              class="post-card"
              :class="{ 'post-card--active': expandedPostId === post.id }"
              @click="togglePost(post)"
            >
              <div class="post-top">
                <el-tag size="small" :type="platformTagType(post.platform)">
                  {{ post.platform }}
                </el-tag>
                <span :class="['badge', riskBadgeClass(post.risk_level)]">
                  {{ riskLabel(post.risk_level) }}
                </span>
                <span :class="['badge', sentimentBadgeClass(post.sentiment)]">
                  {{ sentimentLabel(post.sentiment) }}
                </span>
              </div>
              <div class="post-title">{{ post.title }}</div>
              <div class="post-meta">
                {{ post.author || '匿名' }} ·
                {{ formatTime(post.publish_time) }} ·
                热度 {{ Math.round(post.heat_score || 0) }}
              </div>

              <!-- 展开：正文摘要 + 跳原帖。原本点击只是换个边框颜色，什么都不会发生 -->
              <transition name="expand">
                <div v-if="expandedPostId === post.id" class="post-detail">
                  <div v-if="post.content" class="detail-text">{{ post.content }}</div>
                  <a
                    v-if="isSafeUrl(post.url)"
                    class="post-link"
                    :href="post.url"
                    target="_blank"
                    rel="noopener"
                    @click.stop
                  >
                    查看原帖 →
                  </a>
                </div>
              </transition>
            </div>

            <div v-if="posts.length === 0" class="empty-state">
              没有匹配的帖子
            </div>

            <!-- 服务端分页：翻页去服务器拿下一页，不是在已加载的 100 条里翻 -->
            <el-pagination
              v-if="postsTotal > pageSize"
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="postsTotal"
              layout="prev, pager, next"
              class="pagination"
              @current-change="loadPosts"
            />
          </template>
        </div>
      </div>

      <!-- 右：舆情事件列表 + 详情（真实已发布事件） -->
      <div class="right-panel">
        <div class="section-card">
          <div class="section-header">
            <span class="section-title">校园热点事件</span>
            <span class="section-count">已发布 {{ events.length }} 个</span>
          </div>
          <div class="section-body event-list">
            <div v-if="eventsLoading" class="loading-state">
              <el-icon class="is-loading"><Loading /></el-icon> 加载中…
            </div>
            <template v-else>
              <div
                v-for="event in filteredEvents"
                :key="eventId(event)"
                class="event-row"
                :class="{ 'event-row--high': eventRisk(event) === 'high' }"
                @click="toggleEvent(event)"
              >
                <div class="event-row-top">
                  <span class="event-title">{{ event.title }}</span>
                  <span :class="['badge', riskBadgeClass(eventRisk(event))]">
                    {{ riskLabel(eventRisk(event)) }}
                  </span>
                </div>
                <div class="event-row-meta">
                  {{ event.topic || '未分类' }} · 热度 {{ Math.round(event.heatScore ?? event.heat_score ?? 0) }} ·
                  {{ event.updatedAt || '—' }}
                </div>

                <!-- 展开详情（全部真实字段） -->
                <transition name="expand">
                  <div v-if="expandedEventId === eventId(event)" class="event-detail">
                    <div v-if="event.summary" class="detail-block">
                      <div class="detail-label">事件摘要</div>
                      <div class="detail-text">{{ event.summary }}</div>
                    </div>
                    <div v-if="eventRiskReasons(event).length" class="detail-block">
                      <div class="detail-label">风险依据</div>
                      <div class="detail-text">{{ eventRiskReasons(event).join('；') }}</div>
                    </div>
                    <div class="keyword-list">
                      <span v-for="kw in eventKeywords(event)" :key="kw" class="tag">{{ kw }}</span>
                    </div>
                    <el-button
                      text
                      type="primary"
                      size="small"
                      style="margin-top: 8px"
                      @click.stop="$router.push(`/events/${eventId(event)}`)"
                    >
                      查看完整详情 →
                    </el-button>
                  </div>
                </transition>
              </div>

              <div v-if="filteredEvents.length === 0" class="empty-state">没有匹配的事件</div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Bell, ChatLineSquare, CircleCheck, Loading, Warning } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { fetchSentimentPosts } from '@/api/posts'
import { fetchPublishedEvents } from '@/api/events'

// ——— 状态 ———
const keyword = ref('')
const riskFilter = ref('')
const currentPage = ref(1)
const pageSize = 8
const loading = ref(true)
const expandedPostId = ref(null)
const expandedEventId = ref(null)

// ——— 帖子数据（processed_posts：已清洗、已打分） ———
//
// 三个数字必须分清楚，混了就会撒谎：
//   posts        当前这一页的帖子（8 条）
//   postsTotal   **筛选后**的全库条数（面板头「共 N 条」）
//   libraryTotal 全库已分析帖子数（统计卡「帖子总数」）
//
// 原实现只有一个 `posts`，然后拿 `posts.length` 当「帖子总数」——而它一次只请求
// 100 条（page_size 的上限），于是这张卡片永远显示 100，库里有 403 条还是 4000 条
// 都一样。检索也只在这 100 条里做，第 101 条之后的帖子搜索永远找不到。
const posts = ref([])
const postsTotal = ref(0)
const libraryTotal = ref(0)

async function loadPosts() {
  loading.value = true
  expandedPostId.value = null
  try {
    const data = await fetchSentimentPosts({
      page: currentPage.value,
      pageSize,
      keyword: keyword.value.trim(),
      risk: riskFilter.value,
    })
    posts.value = data.items
    postsTotal.value = data.total
    // 没有任何筛选时的 total 就是全库量——记下来给统计卡用
    if (!keyword.value.trim() && !riskFilter.value) {
      libraryTotal.value = data.total
    }
  } catch (error) {
    // 不用 mock 兜底：页面上挂着「真实接口」徽章，塞假数据就是在骗人。
    // 数据库不可用时的正规降级路径是 demo 模式（本地 SQLite 快照），不是前端造数。
    console.warn('[sentiment] 帖子加载失败', error)
    posts.value = []
    postsTotal.value = 0
  } finally {
    loading.value = false
  }
}

loadPosts()

// ——— 事件数据（真实已发布事件） ———
const events = ref([])
const eventsLoading = ref(true)

;(async () => {
  try {
    events.value = await fetchPublishedEvents()
  } finally {
    eventsLoading.value = false
  }
})()

// 一个事件有两个身份标识：id 是展示用的 "EVT-49"（字符串），raw_id 是主键 49（整数）。
// 原实现展开判断用 raw_id、点击时却存 id —— `"EVT-49" === 49` 永远为 false，
// **详情面板永远展不开**。统一从这里取，谁也别再混。
function eventId(event) {
  return event.raw_id ?? event.id
}

function eventRisk(event) {
  return event.riskLevel ?? event.risk_level ?? 'low'
}

function parseJsonList(value) {
  if (Array.isArray(value)) return value
  try {
    const parsed = JSON.parse(value || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function eventRiskReasons(event) {
  return parseJsonList(event.risk_reasons ?? event.risk_reasons_json)
}

function eventKeywords(event) {
  const keywords = parseJsonList(event.source_keywords ?? event.source_keywords_json)
  return keywords.length ? keywords : parseJsonList(event.top_tags ?? event.top_tags_json)
}

// ——— 过滤 ———
// 帖子的检索/筛选/分页**全在服务端**（见 loadPosts）：前端过滤只能覆盖"已经加载进来的
// 那一页"，而库里有 397 条已分析帖——用户搜「食堂」，第 101 条之后的食堂帖一条都搜不到，
// 页面却看起来像搜了全库。那是一个静默的错误答案。
//
// 事件不同：已发布事件只有十几个，一次全取回来，客户端过滤没有任何谎言风险。
const filteredEvents = computed(() => {
  return events.value.filter(e => {
    if (riskFilter.value && eventRisk(e) !== riskFilter.value) return false
    const kw = keyword.value.trim().toLowerCase()
    if (kw) {
      const pool = [e.title, e.summary || '', e.topic || '', ...eventKeywords(e)].join(' ').toLowerCase()
      if (!pool.includes(kw)) return false
    }
    return true
  })
})

// ——— 统计（全部真实数据） ———
// 「帖子总数」= 全库已分析帖子数（libraryTotal，来自服务端）；
// 三张风险卡统计的是**已发布事件**（十几个），与库里的 published 分布一致。
const highRiskCount = computed(() => events.value.filter(e => eventRisk(e) === 'high').length)
const midRiskCount = computed(() => events.value.filter(e => eventRisk(e) === 'medium').length)
const lowRiskCount = computed(() => events.value.filter(e => eventRisk(e) === 'low').length)

// ——— 操作 ———
function handleSearch() {
  currentPage.value = 1
  loadPosts()
}

function resetFilter() {
  keyword.value = ''
  riskFilter.value = ''
  currentPage.value = 1
  loadPosts()
}

function togglePost(post) {
  expandedPostId.value = expandedPostId.value === post.id ? null : post.id
}

function toggleEvent(event) {
  const id = eventId(event)
  expandedEventId.value = expandedEventId.value === id ? null : id
}

// 帖子链接来自爬取数据，只放行 http(s)，防 javascript: 一类伪协议
function isSafeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//.test(url)
}

// ——— 样式辅助 ———
function riskBadgeClass(risk) {
  if (risk === 'high') return 'badge-high'
  if (risk === 'medium') return 'badge-mid'
  return 'badge-low'
}

function riskLabel(risk) {
  if (risk === 'high') return '高风险'
  if (risk === 'medium') return '中风险'
  return risk === 'low' ? '低风险' : '—'
}

function sentimentBadgeClass(sentiment) {
  if (sentiment === 'negative') return 'badge-high'
  if (sentiment === 'positive') return 'badge-low'
  return 'badge-neutral'
}

function sentimentLabel(sentiment) {
  if (sentiment === 'negative') return '负面'
  if (sentiment === 'positive') return '正面'
  return sentiment === 'neutral' ? '中性' : '—'
}

function platformTagType(platform) {
  const map = { '微博': 'warning', '知乎': 'primary', '贴吧': 'success', '小红书': 'danger', '快手': 'info' }
  return map[platform] || 'info'
}

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<style scoped>
.sentiment-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.filter-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  padding: 14px 18px;
  box-shadow: var(--shadow-card);
}

.main-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--color-border-light);
}

.section-title {
  font-size: 14px;
  font-weight: 600;
}

.section-count {
  font-size: 12px;
  color: var(--color-text-muted);
}

.section-body {
  padding: 12px 16px;
  max-height: 540px;
  overflow-y: auto;
}

/* 帖子卡片 */
.post-card {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  padding: 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.post-card:hover { border-color: var(--brand-300); background: var(--color-surface-2); }
.post-card--active { border-color: var(--color-primary); background: var(--color-primary-light); }

.post-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.post-title {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  line-height: 1.4;
}

.post-meta {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 帖子展开：正文摘要 + 原帖链接 */
.post-detail {
  margin-top: 10px;
  border-top: 1px dashed var(--color-border-light);
  padding-top: 10px;
}

.post-link {
  display: inline-block;
  margin-top: 8px;
  color: var(--brand-600);
  font-size: 12px;
  text-decoration: none;
}

.post-link:hover {
  text-decoration: underline;
}

/* 事件行 */
.event-list { display: flex; flex-direction: column; gap: 8px; }

.event-row {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.event-row:hover { border-color: var(--color-primary); }
.event-row--high { border-color: #f4c2c4; background: var(--color-danger-bg); }

.event-row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.event-title {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
}

.event-row-meta {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 展开详情 */
.event-detail {
  margin-top: 10px;
  border-top: 1px dashed var(--color-border-light);
  padding-top: 10px;
}

.detail-block { margin-bottom: 8px; }

.detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 2px;
}

.detail-text {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.keyword-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }

.expand-enter-active,
.expand-leave-active { transition: opacity 0.2s; }
.expand-enter-from,
.expand-leave-to { opacity: 0; }

.pagination { margin-top: 14px; display: flex; justify-content: center; }

.loading-state,
.empty-state {
  padding: 40px 0;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
</style>
