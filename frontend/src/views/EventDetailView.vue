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
        <DataSourceBadge source="mock" style="margin-top: 8px" />
      </div>

      <!-- 摘要 + 指标 -->
      <div class="detail-grid">
        <div class="panel-card summary-card">
          <h3>事件摘要</h3>
          <p>{{ event.summary }}</p>
        </div>

        <div class="panel-card metrics-card">
          <h3>核心指标</h3>
          <div class="metrics-grid">
            <div class="metric">
              <strong>{{ event.heatScore ?? event.heat_score }}</strong>
              <span>热度</span>
            </div>
            <div class="metric">
              <strong>{{ (event.confidence ?? 0).toFixed(2) }}</strong>
              <span>置信度</span>
            </div>
            <div class="metric">
              <strong>{{ event.source_count ?? event.sourcePlatforms?.length }}</strong>
              <span>来源数</span>
            </div>
            <div class="metric">
              <strong>{{ event.representativeCount ?? event.representative_count ?? '—' }}</strong>
              <span>代表内容</span>
            </div>
            <div class="metric">
              <strong>{{ sentimentLabel }}</strong>
              <span>情感倾向</span>
            </div>
            <div class="metric">
              <strong>{{ topicLabel }}</strong>
              <span>话题分类</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 来源 & 标签 -->
      <div class="detail-grid detail-grid-3">
        <div class="panel-card">
          <h3>来源平台</h3>
          <div class="source-list">
            <span v-for="src in sourceList" :key="src" :class="['source-chip', `source-${src}`]">
              {{ sourceLabel(src) }}
            </span>
          </div>
        </div>

        <div class="panel-card">
          <h3>关联标签</h3>
          <div class="tag-list">
            <el-tag v-for="tag in tagList" :key="tag" size="small">{{ tag }}</el-tag>
          </div>
        </div>

        <div class="panel-card">
          <h3>来源帖子</h3>
          <div class="pid-list">
            <code v-for="pid in sourcePostIds.slice(0, 8)" :key="pid">{{ pid }}</code>
            <span v-if="sourcePostIds.length > 8" class="pid-more">+{{ sourcePostIds.length - 8 }} 条</span>
            <span v-if="!sourcePostIds.length" class="pid-none">暂无来源帖子数据</span>
          </div>
        </div>
      </div>

      <!-- 热度趋势 -->
      <div class="panel-card trend-card">
        <h3>热度趋势（近 7 天）</h3>
        <div class="trend-chart" v-if="trendList.length">
          <svg viewBox="0 0 640 200" class="trend-svg">
            <line x1="40" y1="170" x2="620" y2="170" stroke="#e5e7eb" stroke-width="1" />
            <polyline :points="trendLine" class="trend-polyline" />
            <circle v-for="pt in trendDots" :key="pt.label" :cx="pt.x" :cy="pt.y" r="4" class="trend-dot" />
            <text v-for="pt in trendDots" :key="'lbl-' + pt.label" :x="pt.x" y="192" text-anchor="middle" font-size="11" fill="#9ca3af">{{ pt.label }}</text>
          </svg>
        </div>
        <div v-else class="trend-empty">暂无趋势数据</div>
      </div>

      <!-- 操作 -->
      <div class="detail-actions-bar">
        <el-button type="primary" size="large" @click="navigateToImpact">
          🔍 查看对我的影响
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
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { fetchPublicEventDetail } from '@/api/events'

const route = useRoute()
const router = useRouter()
const eventId = computed(() => route.params.id)

const loading = ref(true)
const event = ref(null)

// 后端返回 snake_case 字段，做统一兼容计算属性
const riskLabel = computed(() => {
  const r = event.value?.risk_level ?? event.value?.riskLevel
  return r === 'high' ? '高风险' : r === 'medium' ? '中风险' : '低风险'
})

const riskBadgeClass = computed(() => {
  const r = event.value?.risk_level ?? event.value?.riskLevel
  return r === 'high' ? 'risk-high' : r === 'medium' ? 'risk-mid' : 'risk-low'
})

const sentimentLabel = computed(() => {
  const s = event.value?.sentiment
  const map = { positive: '正向', negative: '负向', neutral: '中性' }
  return map[s] || s || '—'
})

const topicLabel = computed(() => event.value?.topic ?? event.value?.category ?? '—')

// 后端：source_platforms（数组）；mock：sourcePlatforms
const sourceList = computed(() => event.value?.source_platforms ?? event.value?.sourcePlatforms ?? [])

// 后端：top_tags；mock：tags
const tagList = computed(() => event.value?.top_tags ?? event.value?.tags ?? [])

// 后端：source_post_ids（来自 representative_posts 的 raw_post_id 列表）
const sourcePostIds = computed(() => {
  if (event.value?.source_post_ids) return event.value.source_post_ids
  const posts = event.value?.representative_posts
  if (Array.isArray(posts)) return posts.map(p => p.raw_post_id).filter(Boolean)
  return []
})

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
    // 使用 raw_id（整数）调用详情接口
    event.value = await fetchPublicEventDetail(eventId.value)
  } catch {
    ElMessage.error('事件详情加载失败')
  } finally {
    loading.value = false
  }
})

function navigateToImpact() {
  // 使用 raw_id 作为联动参数
  const id = event.value?.raw_id ?? event.value?.id
  if (id) {
    router.push(`/personal?event_id=${id}`)
  }
}

function sourceLabel(val) {
  const map = { weibo: '微博', xhs: '小红书', tieba: '贴吧' }
  return map[val] || val
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
  font-size: 22px;
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

.risk-high { color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; }
.risk-mid { color: #d97706; background: #fffbeb; border: 1px solid #fde68a; }
.risk-low { color: #16a34a; background: #f0fdf4; border: 1px solid #bbf7d0; }

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
  background: #13b26b;
  margin-right: 4px;
  vertical-align: 1px;
}

/* ——— 摘要 + 指标 ——— */
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.detail-grid-3 {
  grid-template-columns: repeat(3, 1fr);
}

.summary-card p {
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text-secondary);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.metric {
  padding: 12px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
  text-align: center;
}

.metric strong {
  display: block;
  font-size: 22px;
  font-family: "Segoe UI", Arial, sans-serif;
  color: var(--color-text);
}

.metric span {
  display: block;
  font-size: 11px;
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
  background: #eef2ff;
  color: #4338ca;
  border-radius: 4px;
  font-size: 11px;
  font-family: "SF Mono", "Consolas", monospace;
}

.pid-more, .pid-none { font-size: 12px; color: var(--color-text-muted); }

/* ——— 趋势 ——— */
.trend-card { padding-bottom: 8px; }

.trend-svg { width: 100%; height: auto; display: block; }

.trend-polyline {
  fill: none;
  stroke: var(--color-primary);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.trend-dot { fill: #fff; stroke: var(--color-primary); stroke-width: 3; }
.trend-empty { color: var(--color-text-muted); font-size: 13px; padding: 20px 0; text-align: center; }

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
