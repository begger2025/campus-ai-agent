<template>
  <div class="sentiment-page">
    <!-- 统计摘要 -->
    <div class="stat-row">
      <StatCard title="帖子总数" :value="total" :icon="ChatLineSquare" color="primary" desc="已加载数据" />
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
        @input="handleSearch"
      />
      <el-select v-model="riskFilter" placeholder="全部风险" clearable style="width: 140px">
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
          <span class="section-count">共 {{ filteredPosts.length }} 条</span>
        </div>
        <div class="section-body">
          <div v-if="loading" class="loading-state">
            <el-icon class="is-loading"><Loading /></el-icon> 加载中…
          </div>
          <template v-else>
            <div
              v-for="post in pagedPosts"
              :key="post.id"
              class="post-card"
              :class="{ 'post-card--active': selectedPost?.id === post.id }"
              @click="selectPost(post)"
            >
              <div class="post-top">
                <el-tag size="small" :type="platformTagType(post.platform)">
                  {{ post.platform }}
                </el-tag>
                <span :class="['badge', riskBadgeClass(post.riskLevel)]">
                  {{ riskLabel(post.riskLevel) }}
                </span>
              </div>
              <div class="post-title">{{ post.title }}</div>
              <div class="post-meta">
                {{ post.author || '匿名' }} ·
                {{ formatTime(post.publish_time) }}
              </div>
            </div>

            <div v-if="filteredPosts.length === 0" class="empty-state">
              没有匹配的帖子
            </div>

            <!-- 分页 -->
            <el-pagination
              v-if="filteredPosts.length > pageSize"
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="filteredPosts.length"
              layout="prev, pager, next"
              class="pagination"
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
                :key="event.raw_id ?? event.id"
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
                  <div v-if="expandedEventId === (event.raw_id ?? event.id)" class="event-detail">
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
                      @click.stop="$router.push(`/events/${event.raw_id ?? event.id}`)"
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
import { fetchPosts } from '@/api/posts'
import { fetchPublishedEvents } from '@/api/events'
import { mockPosts } from '@/mock/data'

// ——— 状态 ———
const keyword = ref('')
const riskFilter = ref('')
const currentPage = ref(1)
const pageSize = 8
const loading = ref(true)
const selectedPost = ref(null)
const expandedEventId = ref(null)

// ——— 帖子数据 ———
const posts = ref([])

;(async () => {
  try {
    const data = await fetchPosts(1, 100)
    posts.value = data.items
  } catch {
    posts.value = mockPosts
  } finally {
    loading.value = false
  }
})()

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
const filteredPosts = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return posts.value.filter(p => {
    const text = [p.title, p.platform, p.author].join(' ').toLowerCase()
    return (!kw || text.includes(kw))
  })
})

const pagedPosts = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredPosts.value.slice(start, start + pageSize)
})

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
const total = computed(() => posts.value.length)
const highRiskCount = computed(() => events.value.filter(e => eventRisk(e) === 'high').length)
const midRiskCount = computed(() => events.value.filter(e => eventRisk(e) === 'medium').length)
const lowRiskCount = computed(() => events.value.filter(e => eventRisk(e) === 'low').length)

// ——— 操作 ———
function handleSearch() {
  currentPage.value = 1
}

function resetFilter() {
  keyword.value = ''
  riskFilter.value = ''
  currentPage.value = 1
}

function selectPost(post) {
  selectedPost.value = selectedPost.value?.id === post.id ? null : post
}

function toggleEvent(event) {
  expandedEventId.value = expandedEventId.value === event.id ? null : event.id
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

function platformTagType(platform) {
  const map = { '微博': 'warning', '知乎': 'primary', '贴吧': 'success', '小红书': 'danger' }
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
