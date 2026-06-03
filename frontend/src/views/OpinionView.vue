<template>
  <div class="opinion-page">
    <!-- 工具栏：关键词搜索 + 来源选择 + 分析按钮 -->
    <div class="toolbar panel-card">
      <el-input
        v-model="keyword"
        clearable
        placeholder="输入关键词（如：食堂、停电、考试）"
        class="toolbar-search"
        @keyup.enter="runAnalysis"
      />
      <el-select v-model="selectedSources" multiple placeholder="选择来源平台" class="toolbar-sources">
        <el-option v-for="s in sourceOptions" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button type="primary" :loading="analyzing" @click="runAnalysis">
        {{ analyzing ? '分析中...' : '开始分析' }}
      </el-button>
      <el-button @click="resetAnalysis">重置</el-button>
      <DataSourceBadge source="mock" />
    </div>

    <!-- 三栏主体 -->
    <div class="three-col">
      <!-- 左栏：热点事件列表 -->
      <section class="panel-card col-left">
        <div class="panel-header">
          <span class="panel-title">🔥 热点事件</span>
          <span class="panel-count">{{ events.length }} 条</span>
        </div>
        <div class="panel-body scroll-body">
          <div
            v-for="(event, idx) in events"
            :key="event.id"
            :class="['event-row', { 'event-row--active': selectedId === event.id }]"
            @click="selectEvent(event)"
          >
            <span class="event-rank" :class="rankClass(idx)">{{ idx + 1 }}</span>
            <div class="event-text">
              <div class="event-row-title">{{ event.title }}</div>
              <div class="event-row-meta">
                <span :class="['risk-tag', `risk-tag--${event.risk_level}`]">{{ riskLabel(event.risk_level) }}</span>
                <span>热度 {{ event.heat_score }}</span>
                <span>· {{ event.source_count }} 来源</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 中栏：事件研判详情 -->
      <section class="panel-card col-mid">
        <div class="panel-header">
          <span class="panel-title">📋 事件研判详情</span>
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
              <div class="metric-item">
                <strong>{{ selectedEvent.heat_score }}</strong>
                <span>热度</span>
              </div>
              <div class="metric-item">
                <strong>{{ selectedEvent.confidence?.toFixed(2) ?? '—' }}</strong>
                <span>置信度</span>
              </div>
              <div class="metric-item">
                <strong>{{ selectedEvent.source_count }}</strong>
                <span>来源数</span>
              </div>
              <div class="metric-item">
                <strong>{{ riskLabel(selectedEvent.risk_level) }}</strong>
                <span>风险等级</span>
              </div>
            </div>

            <div class="detail-section">
              <h3>话题分类</h3>
              <el-tag>{{ selectedEvent.topic }}</el-tag>
              <el-tag v-if="selectedEvent.event_type" type="info" style="margin-left:8px">{{ selectedEvent.event_type }}</el-tag>
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
            <div class="empty-icon">📌</div>
            <p>请从左侧列表选择一个事件</p>
            <p class="empty-hint">或在上方搜索栏输入关键词开始分析</p>
          </div>
        </div>
      </section>

      <!-- 右栏：Agent 问答 -->
      <section class="panel-card col-right">
        <div class="panel-header">
          <span class="panel-title">🤖 Agent 问答</span>
          <el-tag v-if="agentReady" size="small" type="success">就绪</el-tag>
          <el-tag v-else size="small" type="info">待触发</el-tag>
        </div>
        <div class="panel-body chat-body">
          <div class="chat-messages" ref="chatRef">
            <div
              v-for="(msg, i) in chatMessages"
              :key="i"
              :class="['chat-bubble', msg.role === 'user' ? 'chat-right' : 'chat-left']"
            >
              <div class="chat-role">{{ msg.role === 'user' ? '你' : 'Agent' }}</div>
              <div class="chat-text">{{ msg.text }}</div>
            </div>
          </div>

          <div class="chat-suggest" v-if="suggestQuestions.length">
            <span class="suggest-label">快捷提问：</span>
            <el-button
              v-for="q in suggestQuestions"
              :key="q"
              text
              size="small"
              @click="askQuestion(q)"
            >{{ q }}</el-button>
          </div>

          <div class="chat-input-row">
            <el-input
              v-model="chatInput"
              placeholder="向 Agent 追问事件原因、影响、处置建议..."
              @keyup.enter="askQuestion(chatInput)"
            />
            <el-button type="primary" @click="askQuestion(chatInput)" :disabled="!chatInput.trim()">
              发送
            </el-button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { sourceOptions } from '@/mock/events'
import { fetchPublishedEvents } from '@/api/events'

const router = useRouter()

// —— 搜索 & 筛选 ——
const keyword = ref('')
const selectedSources = ref([])
const analyzing = ref(false)

// —— 事件数据 ——
const events = ref([])
const selectedId = ref('')

const selectedEvent = computed(() => events.value.find(e => e.id === selectedId.value) || null)

// —— Agent 聊天 ——
const chatInput = ref('')
const chatMessages = ref([
  { role: 'agent', text: '你好！我是校园舆情分析 Agent。请从左侧选择一个事件，或在上方输入关键词触发分析，我会为你提炼事件要点、风险判断和处置建议。' },
])
const chatRef = ref(null)
const agentReady = ref(false)

const suggestQuestions = computed(() => {
  if (!selectedEvent.value) return ['最近有哪些高风险事件？', '各平台舆情趋势如何？']
  return [
    `「${selectedEvent.value.title.slice(0, 12)}…」的主要原因是什么？`,
    '该事件的影响范围有多大？',
    '建议采取什么处置措施？',
  ]
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

// —— 触发分析 ——
async function runAnalysis() {
  if (!keyword.value.trim()) {
    ElMessage.info('请输入分析关键词')
    return
  }
  analyzing.value = true
  agentReady.value = true

  // mock: 模拟 Agent 分析延迟
  await new Promise(r => setTimeout(r, 1200))

  chatMessages.value.push(
    { role: 'user', text: `分析关键词：「${keyword.value}」` },
    {
      role: 'agent',
      text: `已对关键词「${keyword.value}」完成分析。当前平台共监测到 ${events.value.length} 条相关事件。其中高风险 ${events.value.filter(e => e.riskLevel === 'high').length} 条，中风险 ${events.value.filter(e => e.riskLevel === 'medium').length} 条，低风险 ${events.value.filter(e => e.riskLevel === 'low').length} 条。建议重点关注高风险事件并及时响应。`,
    },
  )
  analyzing.value = false
  scrollChat()
}

function resetAnalysis() {
  keyword.value = ''
  selectedSources.value = []
  chatMessages.value = [
    { role: 'agent', text: '已重置分析条件。请重新输入关键词，或从左侧选择事件查看详情。' },
  ]
  agentReady.value = false
}

// —— Agent 问答 ——
async function askQuestion(question) {
  const q = question?.trim()
  if (!q) return
  chatMessages.value.push({ role: 'user', text: q })
  chatInput.value = ''

  // mock: 模拟 Agent 回复
  await new Promise(r => setTimeout(r, 800))

  if (q.includes('原因') || q.includes('为什么')) {
    const evt = selectedEvent.value
    chatMessages.value.push({
      role: 'agent',
      text: evt
        ? `「${evt.title}」的主要原因是：${evt.summary} 平台监测到 ${evt.source_count} 条相关讨论，情感倾向为「${sentimentLabel(evt.sentiment)}」，建议相关部门关注并采取适当措施。`
        : '请先从左侧选择一个事件，我可以针对该事件分析原因。',
    })
  } else if (q.includes('影响') || q.includes('范围')) {
    chatMessages.value.push({
      role: 'agent',
      text: '当前监测到的事件影响范围覆盖多个校园场景，包括后勤服务、学习生活、安全管理等方面。建议进入「个人事项」页面查看对你个人的具体影响评估。',
    })
  } else if (q.includes('建议') || q.includes('措施') || q.includes('处置')) {
    chatMessages.value.push({
      role: 'agent',
      text: '建议采取以下措施：① 相关部门及时核实事件信息并公开发布说明；② 通过多渠道向学生推送最新进展；③ 建立快速响应机制，防止舆情进一步扩散。具体事件的处置建议请在左侧选择事件后查看。',
    })
  } else if (q.includes('高风险') || q.includes('严重')) {
    const high = events.value.filter(e => e.riskLevel === 'high')
    chatMessages.value.push({
      role: 'agent',
      text: high.length
        ? `当前共有 ${high.length} 条高风险事件：${high.map(e => e.title).join('；')}。建议优先处理。`
        : '当前暂无高风险事件，整体态势平稳。',
    })
  } else {
    chatMessages.value.push({
      role: 'agent',
      text: '收到你的提问。我正在分析相关数据，请稍候。如需更具体的回答，建议从左侧选择一个事件后追问。',
    })
  }
  scrollChat()
}

function scrollChat() {
  nextTick(() => {
    const el = chatRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
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

.panel-title { font-size: 14px; font-weight: 600; }
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

.event-row:hover { background: #f6f8fc; }
.event-row--active {
  background: #eef4ff;
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.event-rank {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #e5e7eb;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.rank-1 { background: #ef4444; color: #fff; }
.rank-2 { background: #f97316; color: #fff; }
.rank-3 { background: #eab308; color: #fff; }

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

.risk-tag--high { color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; }
.risk-tag--medium { color: #d97706; background: #fffbeb; border: 1px solid #fde68a; }
.risk-tag--low { color: #16a34a; background: #f0fdf4; border: 1px solid #bbf7d0; }

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
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  line-height: 1.4;
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
  background: #f8fafc;
  border-radius: var(--radius-sm);
  text-align: center;
}

.metric-item strong {
  display: block;
  font-size: 20px;
  font-family: "Segoe UI", Arial, sans-serif;
  color: var(--color-text);
}

.metric-item span {
  display: block;
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.detail-section {
  margin-bottom: 14px;
}

.detail-section h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin: 0 0 6px;
}

.sentiment-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.sentiment--negative { color: #dc2626; background: #fef2f2; }
.sentiment--positive { color: #16a34a; background: #f0fdf4; }
.sentiment--neutral { color: #6b7280; background: #f3f4f6; }

.source-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.source-pid {
  padding: 2px 8px;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 4px;
  font-size: 11px;
  font-family: "SF Mono", "Consolas", monospace;
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

.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-state p { margin: 0; font-size: 14px; }
.empty-hint { font-size: 12px !important; margin-top: 4px !important; }

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

.chat-left .chat-text { background: #f3f6fb; color: var(--color-text-secondary); }
.chat-right .chat-text { background: var(--color-primary); color: #fff; }

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
