<template>
  <div class="detail-page" v-loading="loading">
    <template v-if="event">
      <!-- 头部 -->
      <div class="detail-hero panel-card">
        <div class="hero-top">
          <div class="hero-title-row">
            <h1>{{ event.title }}</h1>
            <span :class="['risk-badge', riskBadgeClass]">{{ riskLabel }}</span>
          </div>
          <div class="hero-meta">
            <span>事件 ID：{{ event.id }}</span>
            <span>发布时间：{{ event.updatedAt || event.created_at }}</span>
            <span>状态：<span class="status-dot"></span>已发布</span>
          </div>
        </div>
      </div>

      <!-- 摘要与研判 + 指标 -->
      <div class="detail-grid">
        <div class="panel-card summary-card">
          <h3>事件摘要</h3>
          <p>{{ event.summary }}</p>

          <template v-if="concerns.length">
            <h4 class="sub-label">数据中反映的关注点</h4>
            <ul class="point-list">
              <li v-for="(item, i) in concerns" :key="i">{{ item }}</li>
            </ul>
          </template>

          <template v-if="riskReasons.length">
            <h4 class="sub-label">风险依据</h4>
            <ul class="point-list point-list--risk">
              <li v-for="(item, i) in riskReasons" :key="i">{{ item }}</li>
            </ul>
          </template>
        </div>

        <div class="panel-card metrics-card">
          <h3>核心指标</h3>
          <div class="metrics-grid">
            <el-tooltip :content="`${HEAT_TOOLTIP}。精确值：${event.heatScore ?? event.heat_score}`" placement="top" :show-after="150">
              <div class="metric metric--help">
                <strong>{{ formatHeat(event.heatScore ?? event.heat_score) }}</strong>
                <span>热度 · {{ heatLevel(event.heatScore ?? event.heat_score).label }}</span>
              </div>
            </el-tooltip>
            <div class="metric">
              <strong>{{ (event.confidence ?? 0).toFixed(2) }}</strong>
              <span>置信度</span>
            </div>
            <div class="metric">
              <strong>{{ event.source_count ?? event.sourcePlatforms?.length }}</strong>
              <span>来源数</span>
            </div>
            <div class="metric">
              <strong>{{ representativePosts.length || (event.representativeCount ?? event.representative_count ?? '—') }}</strong>
              <span>代表内容</span>
            </div>
            <div class="metric metric--text">
              <strong>{{ sentimentLabel }}</strong>
              <span>情感倾向</span>
            </div>
            <div class="metric metric--text">
              <strong>{{ topicLabel }}</strong>
              <span>话题分类</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 代表内容：事件聚合的原始帖子 -->
      <div v-if="representativePosts.length" class="panel-card">
        <h3>
          代表内容
          <em class="count-hint">{{ representativePosts.length }} 条 · 原帖直链的访问凭证会随时间失效，打不开时请用"站内搜索"</em>
        </h3>
        <article v-for="post in representativePosts" :key="post.processed_post_id ?? post.rank" class="rep-post">
          <div class="rep-head">
            <span :class="['source-chip', `source-${post.platform}`]">{{ sourceLabel(post.platform) }}</span>
            <strong class="rep-title">{{ post.title || '（无标题）' }}</strong>
            <!-- 评审场景下直链凭证多已过期：站内搜索为主入口，直链降为次入口 -->
            <a
              v-if="postSearchUrl(post)"
              class="rep-link"
              :href="postSearchUrl(post)"
              target="_blank"
              rel="noopener"
            >站内搜索 ↗</a>
            <el-tooltip v-if="post.url" :content="LINK_EXPIRY_TIP" placement="top" :show-after="150">
              <a class="rep-link rep-link--alt" :href="post.url" target="_blank" rel="noopener">原帖直链</a>
            </el-tooltip>
          </div>
          <p v-if="post.content" class="rep-content">{{ post.content }}</p>
          <div class="rep-meta">
            <span>{{ post.author || '匿名' }}</span>
            <span v-if="post.publish_time">{{ post.publish_time }}</span>
            <span>赞 {{ post.like_count ?? 0 }}</span>
            <span>评论 {{ post.comment_count ?? 0 }}</span>
            <span>收藏 {{ post.collect_count ?? 0 }}</span>
          </div>
        </article>
      </div>

      <!-- 事件属性：来源 / 关键词 / 标签 / 帖子 ID 合并为一张卡 -->
      <div class="panel-card attrs-card">
        <h3>事件属性</h3>
        <div class="attr-row">
          <span class="attr-label">来源平台</span>
          <div class="attr-value source-list">
            <span v-for="src in sourceList" :key="src" :class="['source-chip', `source-${src}`]">
              {{ sourceLabel(src) }}
            </span>
          </div>
        </div>
        <div v-if="sourceKeywords.length" class="attr-row">
          <span class="attr-label">采集关键词</span>
          <div class="attr-value tag-list">
            <el-tag v-for="kw in sourceKeywords" :key="kw" size="small" type="info">{{ kw }}</el-tag>
          </div>
        </div>
        <div v-if="tagList.length" class="attr-row">
          <span class="attr-label">关联标签</span>
          <div class="attr-value tag-list">
            <el-tag v-for="tag in tagList" :key="tag" size="small">{{ tag }}</el-tag>
          </div>
        </div>
        <div class="attr-row">
          <span class="attr-label">来源帖子</span>
          <div class="attr-value pid-list">
            <code v-for="pid in sourcePostIds.slice(0, 8)" :key="pid">{{ pid }}</code>
            <span v-if="sourcePostIds.length > 8" class="pid-more">+{{ sourcePostIds.length - 8 }} 条</span>
            <span v-if="!sourcePostIds.length" class="pid-none">暂无来源帖子数据</span>
          </div>
        </div>
      </div>

      <!-- 热度趋势：仅有数据时展示 -->
      <div v-if="trendList.length" class="panel-card trend-card">
        <h3>热度趋势（近 7 天）</h3>
        <div class="trend-chart">
          <svg viewBox="0 0 640 200" class="trend-svg">
            <line x1="40" y1="170" x2="620" y2="170" stroke="#e2e7f0" stroke-width="1" />
            <polyline :points="trendLine" class="trend-polyline" pathLength="1" />
            <circle v-for="pt in trendDots" :key="pt.label" :cx="pt.x" :cy="pt.y" r="4" class="trend-dot">
              <title>{{ pt.label }}</title>
            </circle>
            <text v-for="pt in trendDots" :key="'lbl-' + pt.label" :x="pt.x" y="192" text-anchor="middle" font-size="11" fill="#8a95ab">{{ pt.label }}</text>
          </svg>
        </div>
      </div>

      <!-- 操作 -->
      <div class="detail-actions-bar">
        <el-button type="primary" size="large" @click="navigateToImpact">
          <el-icon style="margin-right: 6px"><Aim /></el-icon>
          查看对我的影响
        </el-button>
        <el-button size="large" @click="router.push('/opinion')">返回舆情工作台</el-button>
        <el-button size="large" @click="router.push('/events')">返回事件列表</el-button>
      </div>
    </template>

    <!-- 事件不存在 -->
    <div v-else-if="!loading" class="panel-card not-found">
      <h2>事件不存在</h2>
      <p>未找到事件 ID：{{ eventId }}</p>
      <el-button @click="router.push('/events')">返回事件列表</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Aim } from '@element-plus/icons-vue'
import { formatHeat, heatLevel, HEAT_TOOLTIP } from '@/utils/heat'
import { LINK_EXPIRY_TIP, platformSearchUrl } from '@/utils/postLink'
import { fetchEventDetail } from '@/api/events'

const route = useRoute()
const router = useRouter()
const eventId = computed(() => route.params.id)

const loading = ref(true)
const event = ref(null)

// —— 兼容两种 mock 数据字段名 ——
const riskLabel = computed(() => {
  const r = event.value?.riskLevel ?? event.value?.risk_level
  return r === 'high' ? '高风险' : r === 'medium' ? '中风险' : '低风险'
})

const riskBadgeClass = computed(() => {
  const r = event.value?.riskLevel ?? event.value?.risk_level
  return r === 'high' ? 'risk-high' : r === 'medium' ? 'risk-mid' : 'risk-low'
})

const sentimentLabel = computed(() => {
  const s = event.value?.sentiment
  const map = { positive: '正向', negative: '负向', neutral: '中性' }
  return map[s] || s || '—'
})

const topicLabel = computed(() => event.value?.topic ?? event.value?.category ?? '—')

const sourceList = computed(() => event.value?.sourcePlatforms ?? event.value?.source_platforms ?? [])

const tagList = computed(() => event.value?.tags ?? [])

const sourcePostIds = computed(() => event.value?.source_post_ids ?? [])

// 详情接口独有的研判字段（列表接口没有）
const concerns = computed(() => event.value?.concerns ?? [])
const riskReasons = computed(() => event.value?.risk_reasons ?? [])
const representativePosts = computed(() => event.value?.representative_posts ?? [])
const sourceKeywords = computed(() => event.value?.source_keywords ?? [])

const trendList = computed(() => event.value?.trend ?? [])

const trendDots = computed(() => {
  const t = trendList.value
  if (!t.length) return []
  const maxH = Math.max(...t.map(d => d.heat), 1)
  const step = 580 / Math.max(t.length - 1, 1)
  return t.map((d, i) => ({
    label: d.label,
    x: 40 + i * step,
    y: 170 - (d.heat / maxH) * 140,
  }))
})

const trendLine = computed(() => trendDots.value.map(p => `${p.x},${p.y}`).join(' '))

onMounted(async () => {
  try {
    event.value = await fetchEventDetail(eventId.value)
  } catch (error) {
    // 404 由页面的"未找到"空态展示，其余错误弹提示
    if (error.response?.status !== 404) {
      ElMessage.error(error.message || '事件数据加载失败')
    }
    event.value = null
  } finally {
    loading.value = false
  }
})

function navigateToImpact() {
  if (event.value?.id) {
    router.push(`/personal?event_id=${event.value.id}`)
  }
}

function sourceLabel(val) {
  const map = { weibo: '微博', xhs: '小红书', tieba: '贴吧' }
  return map[val] || val
}

// 直链凭证可能过期，提供平台站内搜索作为备用入口
function postSearchUrl(post) {
  return platformSearchUrl(post.platform, post.title || post.content)
}
</script>

<style scoped>
.detail-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 960px;
}

.panel-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 18px 20px;
}

.panel-card h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

/* ——— 头部 ——— */
.detail-hero { padding-bottom: 14px; }

.hero-top { display: flex; flex-direction: column; gap: 8px; }

.hero-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.hero-title-row h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.4;
}

.risk-badge {
  flex-shrink: 0;
  display: inline-block;
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
}

.risk-high { color: var(--color-danger-text); background: var(--color-danger-bg); border: 1px solid #f4c2c4; }
.risk-mid { color: var(--color-warning-text); background: var(--color-warning-bg); border: 1px solid #ecd9ae; }
.risk-low { color: var(--color-success-text); background: var(--color-success-bg); border: 1px solid #c8e5d0; }

.hero-meta {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  margin-right: 4px;
  vertical-align: 1px;
}

/* ——— 摘要 + 指标 ——— */
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

@media (max-width: 900px) {
  .detail-grid { grid-template-columns: 1fr; }
}

.summary-card p {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--color-text-secondary);
}

.sub-label {
  margin: 14px 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.point-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.point-list li::marker {
  color: var(--brand-400);
}

.point-list--risk li::marker {
  color: var(--color-danger);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.metric {
  padding: 12px;
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  text-align: center;
}

.metric strong {
  display: block;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text);
}

/* 文本型指标（情感/话题）不是量值，降一档字号 */
.metric--text strong {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.metric--help {
  cursor: help;
}

.metric span {
  display: block;
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

/* ——— 来源 ——— */
.source-list { display: flex; gap: 8px; flex-wrap: wrap; }

.source-chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.source-weibo { color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa; }
.source-xhs { color: #be123c; background: #fff1f2; border: 1px solid #fecdd3; }
.source-tieba { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }

/* ——— 标签 ——— */
.tag-list { display: flex; gap: 6px; flex-wrap: wrap; }

/* ——— 来源帖子 ——— */
.pid-list { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

.pid-list code {
  padding: 2px 8px;
  background: var(--brand-50);
  color: var(--brand-700);
  border-radius: 4px;
  font-size: 11px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
}

.pid-more, .pid-none { font-size: 12px; color: var(--color-text-muted); }

/* ——— 代表内容 ——— */
.count-hint {
  margin-left: 6px;
  font-style: normal;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-text-faint);
}

.rep-post {
  padding: 12px 14px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
}

.rep-post + .rep-post {
  margin-top: 10px;
}

.rep-head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.rep-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rep-link {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
}

.rep-link:hover {
  color: var(--color-primary-active);
}

.rep-link--alt {
  color: var(--color-text-muted);
}

.rep-link--alt:hover {
  color: var(--color-text-secondary);
}

.rep-content {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.rep-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-faint);
}

/* ——— 事件属性 ——— */
.attr-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 0;
}

.attr-row + .attr-row {
  border-top: 1px solid var(--color-border-light);
}

.attr-label {
  flex-shrink: 0;
  width: 78px;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 24px;
}

.attr-value {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

/* ——— 趋势 ——— */
.trend-card { padding-bottom: 8px; }

.trend-svg { width: 100%; height: auto; display: block; }

.trend-polyline {
  fill: none;
  stroke: var(--color-primary);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: draw-line 0.9s var(--ease-out) 0.15s forwards;
}

@keyframes draw-line {
  to { stroke-dashoffset: 0; }
}

.trend-dot {
  fill: #fff;
  stroke: var(--color-primary);
  stroke-width: 2;
  opacity: 0;
  animation: dot-in 0.3s var(--ease-out) 0.85s forwards;
}

@keyframes dot-in {
  to { opacity: 1; }
}

/* ——— 操作栏 ——— */
.detail-actions-bar {
  display: flex;
  gap: 12px;
  padding: 8px 0;
}

/* ——— 404 ——— */
.not-found {
  text-align: center;
  padding: 60px 20px;
}

.not-found h2 { margin: 0 0 8px; font-size: 24px; }
.not-found p { color: var(--color-text-muted); margin: 0 0 20px; }
</style>
