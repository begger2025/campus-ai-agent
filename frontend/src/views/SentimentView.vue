<template>
  <div class="sentiment-page">
    <!-- 统计摘要：**全部是帖子层的数字**。
         改造前这四张卡是「帖子总数 + 高/中/低风险事件」——一张卡属于帖子层、三张属于
         事件层，而事件的统计在首页和舆情关注里各有一份。页面职责混在一起，看板就成了
         "哪都在展示帖子和事件"。现在这一页只做一件事：**帖子层的统计分析**。 -->
    <div class="stat-row">
      <StatCard title="帖子总数" :value="stats.total" :icon="ChatLineSquare" color="primary" desc="已分析帖子" />
      <StatCard title="负面帖子" :value="stats.sentiment.negative" :icon="Warning" color="danger" desc="需重点关注" />
      <StatCard title="争议帖子" :value="stats.sentiment.controversial" :icon="Bell" color="warning" desc="正负声音并存" />
      <StatCard title="覆盖平台" :value="stats.platforms.length" :icon="DataAnalysis" color="success" desc="多平台聚合采集" />
    </div>

    <!-- 搜索 + 筛选（只筛帖子——这一页没有事件了） -->
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
        v-model="sentimentFilter"
        placeholder="全部情绪"
        clearable
        style="width: 140px"
        @change="handleSearch"
      >
        <el-option label="负面" value="negative" />
        <el-option label="争议" value="controversial" />
        <el-option label="中性" value="neutral" />
        <el-option label="正面" value="positive" />
      </el-select>
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="resetFilter">重置</el-button>
      <span class="filter-hint">事件的风险研判在<router-link to="/events">事件列表</router-link>与<router-link to="/opinion">舆情工作台</router-link></span>
    </div>

    <div class="main-grid">
      <!-- 左：帖子列表（服务端检索/筛选/分页） -->
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
                <span :class="['plat-pill', `plat-${post.platform}`]">{{ platformLabel(post.platform) }}</span>
                <!-- 帖子只显示**情绪**：帖子级风险是规则算的，真实分布 low 385 / medium 12 /
                     high 0——一个几乎恒为「低风险」的徽章不携带任何信息。
                     真正的风险研判在事件级、由 LLM 做（事件列表 / 工作台）。 -->
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

            <div v-if="posts.length === 0" class="empty-state">没有匹配的帖子</div>

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

      <!-- 右：数据洞察（帖子层的统计——取代原来那张和别的页重复的事件列表） -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">数据洞察</span>
          <span class="section-count">全库 {{ stats.total }} 条</span>
        </div>
        <div class="section-body insight-body">
          <div v-if="statsLoading" class="loading-state">
            <el-icon class="is-loading"><Loading /></el-icon> 统计中…
          </div>
          <template v-else>
            <!-- 情绪分布：四档一个都不能少（controversial 是第四种，30 条） -->
            <div class="insight-block">
              <div class="insight-title">情绪分布</div>
              <div v-for="row in sentimentRows" :key="row.key" class="dist-row">
                <span class="dist-label">{{ row.label }}</span>
                <div class="dist-track">
                  <span
                    class="dist-fill"
                    :class="`dist-fill--${row.key}`"
                    :style="{ width: pct(row.count, stats.total) }"
                  ></span>
                </div>
                <span class="dist-value">{{ row.count }}<em>{{ pct(row.count, stats.total) }}</em></span>
              </div>
            </div>

            <!-- 平台分布 -->
            <div class="insight-block">
              <div class="insight-title">平台分布</div>
              <div v-for="item in stats.platforms" :key="item.platform" class="dist-row">
                <span class="dist-label"><span :class="['plat-dot', `plat-dot-${item.platform}`]"></span>{{ platformLabel(item.platform) }}</span>
                <div class="dist-track">
                  <span class="dist-fill dist-fill--platform" :style="{ width: pct(item.count, stats.total) }"></span>
                </div>
                <span class="dist-value">{{ item.count }}<em>{{ pct(item.count, stats.total) }}</em></span>
              </div>
            </div>

            <!-- 发帖趋势：末端锚在**最近数据日**，不是今天——语料的最新一天可能是几天前，
                 锚在今天会画出一条尾巴全是 0 的假趋势线 -->
            <div class="insight-block">
              <div class="insight-title">
                发帖趋势
                <span class="insight-sub">近 {{ stats.trend_days }} 天 · 截至 {{ trendEnd }}（最近数据日）</span>
              </div>
              <div class="trend-chart">
                <div
                  v-for="point in stats.daily_trend"
                  :key="point.date"
                  class="trend-bar"
                  :style="{ height: barHeight(point.count) }"
                  :title="`${point.date}：${point.count} 条`"
                ></div>
              </div>
            </div>

            <!-- 热度榜 -->
            <div class="insight-block">
              <div class="insight-title">热度 Top {{ stats.top_posts.length }}</div>
              <ol class="top-list">
                <li v-for="post in stats.top_posts" :key="post.id">
                  <a v-if="isSafeUrl(post.url)" :href="post.url" target="_blank" rel="noopener">{{ post.title }}</a>
                  <span v-else>{{ post.title }}</span>
                  <em>{{ Math.round(post.heat_score) }}</em>
                </li>
              </ol>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Bell, ChatLineSquare, DataAnalysis, Loading, Warning } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { fetchSentimentPosts, fetchSentimentStats } from '@/api/posts'

// ——— 页面职责 ———
// 舆情分析 = **帖子层 × 统计**。它此前有一半版面是事件列表，而事件列表在「事件列表」
// 「舆情工作台」「舆情关注」里各有一份——全站出现 4 次。重新分工后每页 = 唯一的
// （数据层 × 动词）：
//     首页       概览层 × 看
//     舆情分析   帖子层 × 统计    ← 这里
//     事件列表   事件层 × 检索
//     舆情工作台 单事件 × 研判
//     舆情关注   中高风险 × 处置

// 舆情助手的引用角标「站内检索」跳过来时带着 ?keyword=（原帖无外链的帖子
// 用标题前缀在这里溯源），预填并直接按它检索。
const route = useRoute()
const keyword = ref(typeof route.query.keyword === 'string' ? route.query.keyword : '')
const sentimentFilter = ref('')
const currentPage = ref(1)
const pageSize = 8
const loading = ref(true)
const expandedPostId = ref(null)

// ——— 帖子列表（服务端检索/筛选/分页） ———
const posts = ref([])
const postsTotal = ref(0)

async function loadPosts() {
  loading.value = true
  expandedPostId.value = null
  try {
    const data = await fetchSentimentPosts({
      page: currentPage.value,
      pageSize,
      keyword: keyword.value.trim(),
      sentiment: sentimentFilter.value,
    })
    posts.value = data.items
    postsTotal.value = data.total
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

// ——— 全库统计（服务端聚合：前端只看得见当前这 8 条，算不出 395 条的分布） ———
const statsLoading = ref(true)
const stats = ref({
  total: 0,
  sentiment: { negative: 0, controversial: 0, neutral: 0, positive: 0 },
  platforms: [],
  daily_trend: [],
  top_posts: [],
  trend_days: 30,
})

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await fetchSentimentStats()
  } catch (error) {
    console.warn('[sentiment] 统计加载失败', error)
  } finally {
    statsLoading.value = false
  }
}

loadPosts()
loadStats()

// ——— 展示辅助 ———
const SENTIMENT_LABELS = {
  negative: '负面',
  controversial: '争议',
  neutral: '中性',
  positive: '正面',
}

// 四种情绪，不是三种：`controversial`（争议——正负声音都不少）是核心情绪聚合的第四种
// 取值，库里有 30 条。漏掉它，这 30 条的徽章会显示成「—」，分布图上也会缺一块。
const sentimentRows = computed(() =>
  Object.keys(SENTIMENT_LABELS).map((key) => ({
    key,
    label: SENTIMENT_LABELS[key],
    count: stats.value.sentiment[key] || 0,
  })),
)

const trendEnd = computed(() => {
  const trend = stats.value.daily_trend
  if (!trend.length) return '—'
  const [, month, day] = trend[trend.length - 1].date.split('-')
  return `${Number(month)}/${Number(day)}`
})

function pct(count, total) {
  if (!total) return '0%'
  return `${Math.round((count / total) * 100)}%`
}

// 趋势柱高按窗口内的峰值归一化——峰值那天是满格，其余按真实比例。
function barHeight(count) {
  const peak = Math.max(...stats.value.daily_trend.map((p) => p.count), 1)
  return count === 0 ? '2px' : `${Math.max(Math.round((count / peak) * 100), 6)}%`
}

function sentimentBadgeClass(sentiment) {
  if (sentiment === 'negative') return 'badge-high'
  if (sentiment === 'controversial') return 'badge-mid'
  if (sentiment === 'positive') return 'badge-low'
  return 'badge-neutral'
}

function sentimentLabel(sentiment) {
  return SENTIMENT_LABELS[sentiment] || '—'
}

const PLATFORM_LABELS = { xhs: '小红书', weibo: '微博', tieba: '贴吧', zhihu: '知乎', ks: '快手', web: '网页证据' }
function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || '未知'
}

// 帖子链接来自爬取数据，只放行 http(s)，防 javascript: 一类伪协议
function isSafeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//.test(url)
}

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

// ——— 操作 ———
function handleSearch() {
  currentPage.value = 1
  loadPosts()
}

function resetFilter() {
  keyword.value = ''
  sentimentFilter.value = ''
  currentPage.value = 1
  loadPosts()
}

function togglePost(post) {
  expandedPostId.value = expandedPostId.value === post.id ? null : post.id
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

.filter-hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-muted);
}

.filter-hint a {
  color: var(--brand-600);
  text-decoration: none;
}

.filter-hint a:hover {
  text-decoration: underline;
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
  max-height: 560px;
  overflow-y: auto;
}

/* ——— 帖子卡片 ——— */
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

.post-detail {
  margin-top: 10px;
  border-top: 1px dashed var(--color-border-light);
  padding-top: 10px;
}

.detail-text {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.post-link {
  display: inline-block;
  margin-top: 8px;
  color: var(--brand-600);
  font-size: 12px;
  text-decoration: none;
}

.post-link:hover { text-decoration: underline; }

/* ——— 数据洞察 ——— */
.insight-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.insight-block { display: flex; flex-direction: column; gap: 7px; }

.insight-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.insight-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted);
}

.dist-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dist-label {
  width: 72px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* 平台品牌标签：与全站统一（小红书红 / 快手金 / 微博橙 …） */
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

/* 分布行的平台圆点：同一套品牌色（实心） */
.plat-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #94a3b8;
}
.plat-dot-xhs { background: #f43f5e; }
.plat-dot-weibo { background: #ef4444; }
.plat-dot-ks { background: #f59e0b; }
.plat-dot-tieba { background: #3b82f6; }
.plat-dot-zhihu { background: #0284c7; }
.plat-dot-web { background: #10b981; }

.dist-track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: var(--color-surface-2);
  overflow: hidden;
}

.dist-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--brand-500);
  transition: width 0.3s var(--ease-out);
}

/* 情绪配色和徽章一致：负面红 / 争议黄 / 中性灰 / 正面绿 */
.dist-fill--negative { background: #e15b64; }
.dist-fill--controversial { background: #e0a63c; }
.dist-fill--neutral { background: #9aa2b1; }
.dist-fill--positive { background: #4caf7d; }
.dist-fill--platform { background: var(--brand-500); }

.dist-value {
  width: 74px;
  flex-shrink: 0;
  text-align: right;
  font-size: 12px;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.dist-value em {
  margin-left: 5px;
  font-style: normal;
  color: var(--color-text-muted);
}

/* 发帖趋势 */
.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 76px;
  padding-top: 4px;
}

.trend-bar {
  flex: 1;
  min-width: 3px;
  border-radius: 2px 2px 0 0;
  background: var(--brand-400);
  transition: background 0.15s;
}

.trend-bar:hover { background: var(--brand-600); }

/* 热度榜 */
.top-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.8;
}

.top-list li::marker { color: var(--brand-500); }

.top-list a {
  color: var(--brand-600);
  text-decoration: none;
}

.top-list a:hover { text-decoration: underline; }

.top-list em {
  margin-left: 6px;
  font-style: normal;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

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
