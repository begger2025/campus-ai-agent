<template>
  <div class="opinion-page">
    <!-- 工具栏：关键词/来源本地筛选 + 跳转真实 Agent -->
    <div class="toolbar panel-card">
      <el-input
        v-model="keyword"
        clearable
        placeholder="筛选事件（如：食堂、停电、考试）"
        class="toolbar-search"
      />
      <el-select v-model="selectedSources" multiple placeholder="来源平台" class="toolbar-sources" clearable>
        <el-option v-for="s in sourceOptions" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" @click="goAgentChat()">用舆情助手深入分析 →</el-button>
      <DataSourceBadge source="real" />
    </div>

    <!-- 三栏主体 -->
    <div class="three-col">
      <!-- 左栏：热点事件列表 -->
      <section class="panel-card col-left">
        <div class="panel-header">
          <span class="panel-title">热点事件</span>
          <span class="panel-count">{{ filteredEvents.length }} 条</span>
        </div>
        <div class="panel-body scroll-body">
          <div
            v-for="(event, idx) in filteredEvents"
            :key="event.id"
            :class="['event-row', { 'event-row--active': selectedId === event.id }]"
            @click="selectEvent(event)"
          >
            <span class="event-rank" :class="rankClass(idx)">{{ idx + 1 }}</span>
            <div class="event-text">
              <div class="event-row-title">{{ event.title }}</div>
              <div class="event-row-meta">
                <span :class="['risk-tag', `risk-tag--${event.risk_level}`]">{{ riskLabel(event.risk_level) }}</span>
                <span :title="`精确值 ${event.heat_score}`">热度 {{ formatHeat(event.heat_score) }}</span>
                <span>· {{ event.source_count }} 来源</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 中栏：事件研判详情 -->
      <section class="panel-card col-mid">
        <div class="panel-header">
          <span class="panel-title">事件研判详情</span>
          <el-button v-if="selectedEvent" text size="small" @click="openDetail">查看完整详情 →</el-button>
        </div>
        <div class="panel-body scroll-body">
          <template v-if="selectedEvent">
            <div class="detail-header">
              <h2>{{ selectedEvent.title }}</h2>
              <span :class="['risk-tag', `risk-tag--${selectedEvent.risk_level}`]">{{ riskLabel(selectedEvent.risk_level) }}</span>
            </div>

            <p class="detail-summary">{{ selectedEvent.summary }}</p>

            <div class="detail-metrics">
              <el-tooltip :content="`${HEAT_TOOLTIP}。精确值：${selectedEvent.heat_score}`" placement="top" :show-after="150">
                <div class="metric-item metric-item--help">
                  <strong>{{ formatHeat(selectedEvent.heat_score) }}</strong>
                  <span>热度 · {{ heatLevel(selectedEvent.heat_score).label }}</span>
                </div>
              </el-tooltip>
              <div class="metric-item">
                <strong>{{ selectedEvent.confidence?.toFixed(2) ?? '—' }}</strong>
                <span>置信度</span>
              </div>
              <div class="metric-item">
                <strong>{{ selectedEvent.source_count }}</strong>
                <span>来源数</span>
              </div>
              <div class="metric-item metric-item--text">
                <strong>{{ riskLabel(selectedEvent.risk_level) }}</strong>
                <span>风险等级</span>
              </div>
            </div>

            <div class="detail-section">
              <h3>话题分类</h3>
              <el-tag>{{ selectedEvent.topic }}</el-tag>
              <el-tag
                v-if="selectedEvent.event_type && selectedEvent.event_type !== selectedEvent.topic"
                type="info"
                style="margin-left:8px"
              >{{ selectedEvent.event_type }}</el-tag>
            </div>

            <div class="detail-section">
              <h3>情感倾向</h3>
              <span :class="['sentiment-tag', `sentiment--${selectedEvent.sentiment}`]">
                {{ sentimentLabel(selectedEvent.sentiment) }}
              </span>
            </div>

            <div class="detail-section">
              <h3>来源帖子</h3>
              <div class="source-tags">
                <span v-for="pid in selectedEvent.source_post_ids?.slice(0, 5)" :key="pid" class="source-pid">{{ pid }}</span>
                <span v-if="selectedEvent.source_post_ids?.length > 5" class="source-more">
                  +{{ selectedEvent.source_post_ids.length - 5 }} 条
                </span>
              </div>
            </div>

            <div class="detail-actions">
              <el-button type="primary" @click="navigateToImpact(selectedEvent)">查看对我的影响 →</el-button>
              <el-button @click="openDetail(selectedEvent)">查看完整详情</el-button>
            </div>
          </template>

          <div v-else class="empty-state">
            <el-icon class="empty-icon" :size="34"><Pointer /></el-icon>
            <p>请从左侧列表选择一个事件</p>
            <p class="empty-hint">或在上方搜索栏输入关键词开始分析</p>
          </div>
        </div>
      </section>

      <!-- 右栏：跳转真实舆情助手 -->
      <section class="panel-card col-right">
        <div class="panel-header">
          <span class="panel-title">智能问答</span>
          <el-tag size="small" type="success">LLM 驱动</el-tag>
        </div>
        <div class="panel-body agent-guide">
          <p class="guide-intro">
            对事件有疑问？舆情助手基于真实数据回答，支持热点、风险、简报和多步推理对比分析。
          </p>
          <div class="guide-questions">
            <span class="suggest-label">试试这样问：</span>
            <button
              v-for="q in suggestQuestions"
              :key="q"
              type="button"
              class="guide-question"
              @click="goAgentChat(q)"
            >
              {{ q }}
            </button>
          </div>
          <el-button type="primary" class="guide-cta" @click="goAgentChat()">
            打开舆情助手 →
          </el-button>
          <p class="guide-note">复杂问题（多话题对比）由 ReAct 多步推理完成，耗时约 1~2 分钟。</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Pointer } from '@element-plus/icons-vue'
import { formatHeat, heatLevel, HEAT_TOOLTIP } from '@/utils/heat'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { sourceOptions } from '@/mock/events'
import { fetchPublishedEvents } from '@/api/events'

const router = useRouter()

// —— 搜索 & 筛选（纯本地过滤，真实分析走舆情助手） ——
const keyword = ref('')
const selectedSources = ref([])

// —— 事件数据 ——
const events = ref([])
const selectedId = ref('')

const selectedEvent = computed(() => events.value.find(e => e.id === selectedId.value) || null)

const filteredEvents = computed(() => {
  const kw = keyword.value.trim()
  return events.value.filter((event) => {
    if (kw && !`${event.title}${event.summary || ''}${event.topic || ''}`.includes(kw)) return false
    if (selectedSources.value.length) {
      const platforms = event.sourcePlatforms || event.source_platforms || []
      if (!selectedSources.value.some((s) => platforms.includes(s))) return false
    }
    return true
  })
})

const suggestQuestions = computed(() => {
  if (!selectedEvent.value) return ['最近有哪些高风险事件？', '给我一份校园舆情简报']
  const topic = (selectedEvent.value.topic || selectedEvent.value.title || '').slice(0, 10)
  return [`${topic}大家怎么看？`, `${topic}有什么风险吗？`, '对比一下各话题哪个风险更高？']
})

onMounted(loadEvents)

async function loadEvents() {
  try {
    events.value = await fetchPublishedEvents()
    if (events.value.length) {
      selectedId.value = events.value[0].id
    }
  } catch {
    ElMessage.warning('事件数据加载失败，请刷新页面重试')
  }
}

// —— 选择事件 ——
function selectEvent(event) {
  selectedId.value = event.id
}

function resetFilters() {
  keyword.value = ''
  selectedSources.value = []
}

// —— 跳转真实舆情助手（可带预填问题） ——
function goAgentChat(question = '') {
  router.push(question ? { path: '/agent-chat', query: { q: question } } : '/agent-chat')
}

// —— 导航 ——
function openDetail(event) {
  if (event?.id) router.push(`/events/${event.id}`)
}

function navigateToImpact(event) {
  if (event?.id) router.push(`/personal?event_id=${event.id}`)
}

// —— 显示辅助 ——
function riskLabel(level) {
  const map = { high: '高风险', medium: '中风险', low: '低风险' }
  return map[level] || level
}

function riskClass(level) {
  if (level === 'high') return 'badge-high'
  if (level === 'medium') return 'badge-mid'
  return 'badge-low'
}

function rankClass(idx) {
  if (idx === 0) return 'rank-1'
  if (idx === 1) return 'rank-2'
  if (idx === 2) return 'rank-3'
  return ''
}

function sentimentLabel(s) {
  const map = { positive: '正向', negative: '负向', neutral: '中性' }
  return map[s] || s || '—'
}
</script>

<style scoped>
.opinion-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 100%;
}

/* ——— 工具栏 ——— */
.toolbar {
  height: 56px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.toolbar-search { width: 240px; }
.toolbar-sources { width: 200px; }
.toolbar-search :deep(.el-input__wrapper),
.toolbar-sources :deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 6px;
}

/* ——— 三栏 ——— */
.three-col {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 280px 1fr 320px;
  gap: 10px;
}

.col-left, .col-mid, .col-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.panel-header {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border-light);
}

.panel-title { font-size: 15px; font-weight: 600; }
.panel-count { font-size: 12px; color: var(--color-text-muted); }
.panel-body { flex: 1; min-height: 0; padding: 10px; }
.scroll-body { overflow-y: auto; }

/* ——— 左栏：事件列表 ——— */
.event-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 4px;
}

.event-row:hover { background: var(--color-surface-2); }
.event-row--active {
  background: var(--brand-50);
}

.event-rank {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #eef1f7;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.rank-1 { background: var(--color-danger); color: #fff; }
.rank-2 { background: #c8830f; color: #fff; }
.rank-3 { background: #d3a04b; color: #fff; }

.event-text { flex: 1; min-width: 0; }
.event-row-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-row-meta {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.risk-tag {
  display: inline-block;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.risk-tag--high { color: var(--color-danger-text); background: var(--color-danger-bg); border: 1px solid #f4c2c4; }
.risk-tag--medium { color: var(--color-warning-text); background: var(--color-warning-bg); border: 1px solid #ecd9ae; }
.risk-tag--low { color: var(--color-success-text); background: var(--color-success-bg); border: 1px solid #c8e5d0; }

/* ——— 中栏：事件详情 ——— */
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.detail-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
  line-height: 1.45;
}

.detail-summary {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.7;
  margin: 0 0 16px;
}

.detail-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.metric-item {
  padding: 10px 8px;
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  text-align: center;
}

.metric-item strong {
  display: block;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text);
}

/* 风险等级是文本不是量值，降一档字号 */
.metric-item--text strong {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.metric-item--help {
  cursor: help;
}

.metric-item span {
  display: block;
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.detail-section {
  margin-bottom: 14px;
}

.detail-section h3 {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin: 0 0 6px;
}

.sentiment-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.sentiment--negative { color: var(--color-danger-text); background: var(--color-danger-bg); }
.sentiment--positive { color: var(--color-success-text); background: var(--color-success-bg); }
.sentiment--neutral { color: var(--color-text-muted); background: #eef1f7; }

.source-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.source-pid {
  padding: 2px 8px;
  background: var(--brand-50);
  color: var(--brand-700);
  border-radius: 4px;
  font-size: 11px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
}
.source-more {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 22px;
}

.detail-actions {
  margin-top: 18px;
  display: flex;
  gap: 10px;
}

/* ——— 空状态 ——— */
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
}

.empty-icon { color: var(--color-text-faint); margin-bottom: 12px; }
.empty-state p { margin: 0; font-size: 14px; }
.empty-hint { font-size: 12px !important; margin-top: 4px !important; }

/* —— 右栏：舆情助手引导 —— */
.agent-guide {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 14px;
}

.guide-intro {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text);
}

.guide-questions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.suggest-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.guide-question {
  border: 1px solid var(--color-border-light);
  background: var(--color-bg);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 12px;
  color: var(--color-primary);
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.guide-question:hover {
  border-color: var(--brand-300);
  background: var(--brand-50);
}

.guide-cta {
  align-self: stretch;
}

.guide-note {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ——— 右栏：Agent 聊天 ——— */
.chat-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
  max-height: 420px;
}

.chat-bubble { max-width: 86%; }
.chat-left { align-self: flex-start; }
.chat-right { align-self: flex-end; }

.chat-role {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 2px;
}

.chat-text {
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  line-height: 1.6;
}

.chat-left .chat-text { background: var(--color-surface-2); color: var(--color-text-secondary); }
.chat-right .chat-text { background: var(--brand-600); color: #fff; }

.chat-suggest {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
}

.suggest-label { font-size: 11px; color: var(--color-text-muted); }

.chat-input-row {
  display: flex;
  gap: 8px;
}

.chat-input-row :deep(.el-input__wrapper) { border-radius: 6px; }

@media (max-width: 1200px) {
  .three-col { grid-template-columns: 1fr; }
  .col-left, .col-right { max-height: 240px; }
}
</style>
