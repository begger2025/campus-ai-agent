<template>
  <div class="chat-page">
    <div ref="listEl" class="message-list">
      <div v-if="!messages.length" class="chat-welcome">
        <BrandLogo :size="52" />
        <h2>校园舆情助手</h2>
        <p>基于已采集的公开数据回答，支持多轮追问与多步推理。试试问我：</p>
        <div class="sample-grid">
          <button
            v-for="item in sampleQuestions"
            :key="item.text"
            class="sample-card"
            type="button"
            :disabled="loading"
            @click="send(item.text)"
          >
            <el-icon :size="17"><component :is="item.icon" /></el-icon>
            <span>{{ item.text }}</span>
          </button>
        </div>
      </div>

      <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
        <span v-if="msg.role === 'agent'" class="agent-avatar">
          <BrandLogo :size="30" />
        </span>
        <div class="bubble">
          <!-- Agent 回答是 Markdown（表格/标题/加粗），渲染前已整体 HTML 转义 -->
          <div v-if="msg.role === 'agent'" class="bubble-text md-body" v-html="renderMarkdown(msg.text)"></div>
          <div v-else class="bubble-text" v-text="msg.text"></div>

          <template v-if="msg.role === 'agent' && msg.meta">
            <div class="meta-row">
              <el-tag size="small" type="info">{{ intentLabel(msg.meta.intent) }}</el-tag>
              <el-tag size="small" :type="msg.meta.route_source === 'llm' ? 'success' : 'warning'">
                路由：{{ msg.meta.route_source === 'llm' ? 'LLM' : '规则' }}
              </el-tag>
              <el-tag v-if="msg.meta.keyword" size="small">话题：{{ msg.meta.keyword }}</el-tag>
            </div>

            <el-alert
              v-if="msg.meta.degraded"
              type="warning"
              :closable="false"
              show-icon
              title="大模型暂不可用，已降级为规则摘要"
            />
            <el-alert
              v-if="msg.meta.review && msg.meta.review.verdict === 'warn'"
              type="warning"
              :closable="false"
              show-icon
              :title="reviewSummary(msg.meta.review)"
            />

            <!-- search 兜底找到的帖子清单：后端一直带回，之前从未渲染——用户只看到
                 "已找到 10 条内容"却看不见任何一条，等于白找 -->
            <div v-if="msg.meta.notes && msg.meta.notes.length" class="note-list">
              <p class="note-list-title">找到的相关内容</p>
              <ol>
                <li v-for="(note, ni) in msg.meta.notes" :key="ni">
                  <a v-if="isSafeUrl(note.url)" :href="note.url" target="_blank" rel="noopener">
                    {{ note.title }}
                  </a>
                  <span v-else>{{ note.title }}</span>
                </li>
              </ol>
            </div>

            <el-collapse v-if="msg.meta.steps && msg.meta.steps.length" class="steps-collapse">
              <el-collapse-item :title="`查看推理过程（${msg.meta.steps.length} 步）`">
                <ol class="steps">
                  <li v-for="(step, si) in msg.meta.steps" :key="si">
                    <p class="step-thought">{{ step.thought }}</p>
                    <p v-if="step.action" class="step-action">
                      调用工具 <code>{{ step.action }}</code>
                      <span v-if="step.action_input.keyword">（关键词：{{ step.action_input.keyword }}）</span>
                    </p>
                  </li>
                </ol>
              </el-collapse-item>
            </el-collapse>
          </template>
        </div>
      </div>

      <div v-if="loading" class="message agent">
        <span class="agent-avatar agent-avatar--thinking">
          <BrandLogo :size="30" />
        </span>
        <div class="bubble bubble-loading">
          <div class="loading-head">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            <span class="loading-stage">{{ loadingStage }}</span>
          </div>
          <div class="loading-sub">
            已用时 {{ elapsedLabel }} · 正文一开始生成就会实时显示
          </div>
          <div class="loading-track">
            <span class="loading-glow"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="input-bar">
      <el-button
        class="new-chat-btn"
        :disabled="loading || !messages.length"
        @click="startNewConversation"
      >
        <el-icon style="margin-right: 4px"><Plus /></el-icon>
        新对话
      </el-button>
      <el-input
        v-model="draft"
        placeholder="问我热点、风险、观点，或要一份简报…（支持多轮追问）"
        :disabled="loading"
        maxlength="500"
        @keyup.enter="send()"
      />
      <el-button type="primary" :loading="loading" @click="send()">
        <el-icon v-if="!loading" style="margin-right: 4px"><Promotion /></el-icon>
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis,
  Document,
  Plus,
  Promotion,
  TrendCharts,
  Warning,
} from '@element-plus/icons-vue'
import { streamAgentChat } from '@/api/agentChat'
import { renderMarkdown } from '@/utils/markdown'
import BrandLogo from '@/components/BrandLogo.vue'

const route = useRoute()

const messages = ref([])
// 支持从舆情工作台带问题跳转过来（?q=...），预填不自动发送
const draft = ref(typeof route.query.q === 'string' ? route.query.q : '')
const loading = ref(false)
const listEl = ref(null)
// 点过"新对话"后，下一条消息带 reset 让后端清空会话记忆
const pendingReset = ref(false)
// 当前进行中的流；离开页面时 abort，别让请求悬着
let streamHandle = null

function startNewConversation() {
  messages.value = []
  pendingReset.value = true
}

const sampleQuestions = [
  { text: '最近有什么热点？', icon: TrendCharts },
  { text: '食堂有什么风险吗？', icon: Warning },
  { text: '对比一下食堂和宿舍哪个风险更高？', icon: DataAnalysis },
  { text: '给我一份校园舆情简报', icon: Document },
]

const INTENT_LABELS = {
  hotspots: '热点分析',
  risk_analysis: '风险预警',
  opinion_answer: '观点问答',
  report: '舆情简报',
  search: '内容检索',
  complex_analysis: '多步推理',
}

function intentLabel(intent) {
  return INTENT_LABELS[intent] || intent
}

// 帖子链接来自爬取数据，只放行 http(s)，防 javascript: 一类伪协议（与 citations 同口径）
function isSafeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//.test(url)
}

// 审校提示封顶展示（与后端追加进正文的口径一致）：审校是提示，不是第二份报告。
const REVIEW_ALERT_MAX_ISSUES = 3

function reviewSummary(review) {
  const issues = review?.issues || []
  const shown = issues.slice(0, REVIEW_ALERT_MAX_ISSUES).join('；')
  return issues.length > REVIEW_ALERT_MAX_ISSUES
    ? `审校提示（共 ${issues.length} 条，仅展示前 ${REVIEW_ALERT_MAX_ISSUES} 条）：${shown}`
    : `审校提示：${shown}`
}

// ——— 等待期的进度显示 ———
// 改流式之前，这里是按 elapsed 秒数**猜**阶段文案的（"8 秒了，那大概在检索吧"）——
// 一个会说谎的进度条。现在后端会实时告诉我们它到底在干什么，直接说真话。
const elapsed = ref(0)
let elapsedTimer = null
const liveStage = ref('')

watch(loading, (active) => {
  if (active) {
    elapsed.value = 0
    elapsedTimer = setInterval(() => {
      elapsed.value += 1
    }, 1000)
  } else if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
})

onBeforeUnmount(() => {
  if (elapsedTimer) clearInterval(elapsedTimer)
  streamHandle?.abort()
})

const TOOL_LABELS = {
  search_notes: '检索原始帖子',
  hotspots: '聚合热点事件',
  risks: '排查风险事件',
  overview: '统计全局概览',
}

const loadingStage = computed(() => liveStage.value || '正在理解你的问题')

const elapsedLabel = computed(() => {
  const m = Math.floor(elapsed.value / 60)
  const s = elapsed.value % 60
  return m ? `${m} 分 ${s} 秒` : `${s} 秒`
})

async function scrollToBottom() {
  await nextTick()
  if (listEl.value) {
    listEl.value.scrollTop = listEl.value.scrollHeight
  }
}

async function send(preset) {
  const text = (preset || draft.value).trim()
  if (!text || loading.value) return
  draft.value = ''
  messages.value.push({ role: 'user', text })
  loading.value = true
  liveStage.value = '正在理解你的问题'
  await scrollToBottom()

  // 占位气泡：正文一到就往里追加，用户看着它一个字一个字长出来。
  const bubble = reactive({
    role: 'agent',
    text: '',
    meta: { intent: '', keyword: '', route_source: '', steps: [], degraded: false, review: null, notes: [] },
  })
  let bubbleShown = false
  let streamError = null

  const showBubble = () => {
    if (!bubbleShown) {
      messages.value.push(bubble)
      bubbleShown = true
      loading.value = false // 正文开始流了，收起等待动画
    }
  }

  streamHandle = streamAgentChat(text, {
    reset: pendingReset.value,
    onEvent: (event, data) => {
      if (event === 'meta') {
        bubble.meta.intent = data.intent
        bubble.meta.keyword = data.keyword
        bubble.meta.route_source = data.route_source
        liveStage.value =
          data.intent === 'complex_analysis'
            ? '正在规划多步推理'
            : `正在生成${INTENT_LABELS[data.intent] || '回答'}`
      } else if (event === 'step') {
        // ReAct 每走完一步就到——这是真实进度，不是猜的
        bubble.meta.steps.push(data)
        const tool = TOOL_LABELS[data.action] || data.action
        const kw = data.action_input?.keyword
        liveStage.value = kw ? `正在${tool}：「${kw}」` : `正在${tool}`
      } else if (event === 'delta') {
        showBubble()
        bubble.text += data.text
        scrollToBottom()
      } else if (event === 'done') {
        showBubble()
        bubble.meta.steps = data.steps || bubble.meta.steps
        bubble.meta.degraded = data.degraded || false
        bubble.meta.review = data.review || null
        bubble.meta.notes = data.notes || []
      } else if (event === 'error') {
        streamError = new Error(data.message || '对话失败')
      }
    },
  })

  try {
    await streamHandle.promise
    pendingReset.value = false
    if (streamError) throw streamError
  } catch (error) {
    if (error?.name === 'AbortError') return // 用户离开页面，不是错误
    ElMessage.error(error?.message || '对话失败，请稍后重试')
    if (!bubbleShown) {
      messages.value.push({ role: 'agent', text: '抱歉，本次分析失败了，请稍后重试。', meta: null })
    } else if (!bubble.text) {
      bubble.text = '抱歉，本次分析失败了，请稍后重试。'
    }
  } finally {
    streamHandle = null
    loading.value = false
    liveStage.value = ''
    await scrollToBottom()
  }
}
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 140px);
  height: calc(100dvh - 140px);
  max-width: 880px;
  margin: 0 auto;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 8px;
}

/* ——— 欢迎空态 ——— */
.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding-top: 56px;
}

.chat-welcome h2 {
  margin: 16px 0 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
}

.chat-welcome p {
  margin: 8px 0 22px;
  font-size: 14px;
  color: var(--color-text-muted);
}

.sample-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 280px));
  gap: 10px;
  justify-content: center;
}

@media (max-width: 640px) {
  .sample-grid { grid-template-columns: 1fr; }
}

.sample-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 13px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.sample-card .el-icon {
  color: var(--brand-500);
  flex-shrink: 0;
}

.sample-card:hover:not(:disabled) {
  border-color: var(--brand-300);
  box-shadow: var(--shadow-card);
  color: var(--color-text);
  transform: translateY(-1px);
}

.sample-card:active:not(:disabled) {
  transform: translateY(0) scale(0.99);
}

.sample-card:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ——— 消息 ——— */
.message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 16px;
  /* 新消息入场：只在节点挂载时触发一次 */
  animation: msg-in 0.3s var(--ease-out) backwards;
}

@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
}

.message.user {
  justify-content: flex-end;
}

.agent-avatar {
  flex-shrink: 0;
  margin-top: 2px;
  border-radius: 9px;
  overflow: hidden;
  box-shadow: var(--shadow-xs);
}

.agent-avatar--thinking {
  animation: avatar-pulse 2s var(--ease-out) infinite;
}

@keyframes avatar-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 91, 219, 0.25); }
  50% { box-shadow: 0 0 0 6px rgba(59, 91, 219, 0); }
}

.bubble {
  max-width: 78%;
  border-radius: var(--radius);
  padding: 10px 14px;
  line-height: 1.65;
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-xs);
}

.message.user .bubble {
  background: var(--brand-600);
  border-color: var(--brand-600);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message.agent .bubble {
  border-top-left-radius: 4px;
  max-width: 86%;
  min-width: 0;
}

.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* ——— Agent 回答的 Markdown 排版 ——— */
.md-body {
  white-space: normal;
  font-size: 13.5px;
  line-height: 1.7;
}

.md-body :deep(h3),
.md-body :deep(h4),
.md-body :deep(h5),
.md-body :deep(h6) {
  margin: 14px 0 6px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.4;
}

.md-body :deep(h3) { font-size: 15px; }
.md-body :deep(h4) { font-size: 14px; }
.md-body :deep(h5),
.md-body :deep(h6) { font-size: 13.5px; }

.md-body :deep(h3:first-child),
.md-body :deep(h4:first-child),
.md-body :deep(p:first-child) { margin-top: 0; }

.md-body :deep(p) {
  margin: 0 0 8px;
}

.md-body :deep(p:last-child) { margin-bottom: 0; }

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 4px 0 8px;
  padding-left: 20px;
}

.md-body :deep(li) { margin: 2px 0; }
.md-body :deep(li)::marker { color: var(--brand-500); }

.md-body :deep(strong) { font-weight: 600; color: var(--color-text); }

.md-body :deep(code) {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-family: 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
}

.md-body :deep(hr) {
  border: 0;
  border-top: 1px solid var(--color-border-light);
  margin: 10px 0;
}

/* 表格：气泡内横向滚动，不撑破布局 */
.md-body :deep(.md-table-wrap) {
  margin: 8px 0;
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
}

.md-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  line-height: 1.5;
}

.md-body :deep(th),
.md-body :deep(td) {
  padding: 7px 10px;
  text-align: left;
  border-bottom: 1px solid var(--color-border-light);
  vertical-align: top;
  min-width: 64px;
}

.md-body :deep(th) {
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  font-weight: 600;
  white-space: nowrap;
}

.md-body :deep(tbody tr:last-child td) { border-bottom: 0; }
.md-body :deep(tbody tr:hover) { background: var(--color-surface-2); }

.meta-row {
  margin-top: 10px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.bubble .el-alert {
  margin-top: 8px;
}

/* ——— search 兜底的帖子清单 ——— */
.note-list {
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
}

.note-list-title {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.note-list ol {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
}

.note-list li::marker {
  color: var(--brand-500);
}

.note-list a {
  color: var(--brand-600);
  text-decoration: none;
  word-break: break-all;
}

.note-list a:hover {
  text-decoration: underline;
}

.steps-collapse {
  margin-top: 10px;
  border: none;
  --el-collapse-header-height: 36px;
}

.steps-collapse :deep(.el-collapse-item__header) {
  font-size: 13px;
  color: var(--color-text-muted);
  border-bottom-color: var(--color-border-light);
}

.steps {
  margin: 0;
  padding-left: 18px;
}

.steps li::marker {
  color: var(--brand-500);
  font-weight: 600;
}

.step-thought {
  margin: 4px 0 0;
}

.step-action {
  margin: 2px 0 8px;
  color: var(--color-text-muted);
  font-size: 13px;
}

.step-action code {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-family: 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
}

/* ——— 长等待态 ——— */
.bubble-loading {
  min-width: 300px;
}

.loading-head {
  display: flex;
  align-items: center;
  gap: 4px;
}

.loading-stage {
  margin-left: 8px;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.loading-sub {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-faint);
}

.loading-track {
  position: relative;
  height: 3px;
  margin-top: 10px;
  border-radius: 999px;
  background: var(--brand-100);
  overflow: hidden;
}

.loading-glow {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 36%;
  border-radius: 999px;
  background: var(--brand-500);
  animation: track-slide 1.8s var(--ease-out) infinite;
}

@keyframes track-slide {
  from { left: -36%; }
  to { left: 100%; }
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand-400);
  animation: blink 1.2s infinite;
}

.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink {
  0%, 80%, 100% { opacity: 0.3; }
  40% { opacity: 1; }
}

/* ——— 输入栏 ——— */
.input-bar {
  display: flex;
  gap: 8px;
  padding: 12px;
  margin: 0 8px 4px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.input-bar :deep(.el-input__wrapper) {
  box-shadow: none;
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
  transition: box-shadow var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}

.input-bar :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 3px rgba(59, 91, 219, 0.12);
}

.input-bar .el-button {
  transition: transform var(--dur-fast) var(--ease-out), background-color var(--dur-fast), border-color var(--dur-fast);
}

.input-bar .el-button:active {
  transform: scale(0.97);
}

@media (max-width: 640px) {
  .new-chat-btn span { display: inline; }
  .bubble { max-width: 88%; }
  .bubble-loading { min-width: 0; }
}
</style>
