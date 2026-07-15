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
          <!-- Agent 回答是 Markdown（表格/标题/加粗），渲染前已整体 HTML 转义。
               [来源:pN/eN] 内部编号在这里换成可点击角标（citations 映射随 done 到达）；
               角标的站内跳转（data-nav）由 onBodyClick 代理成 router.push，保持 SPA -->
          <div
            v-if="msg.role === 'agent'"
            class="bubble-text md-body"
            @click="onBodyClick"
            v-html="renderMarkdown(msg.text, { citations: msg.meta?.citations })"
          ></div>
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
              :title="reviewSummary(msg)"
            />

            <!-- 参考来源：正文角标的脚注清单——每个编号是什么、点开去哪，一目了然 -->
            <div v-if="citationItems(msg).length" class="cite-sources">
              <p class="cite-sources-title">参考来源</p>
              <ol>
                <li v-for="c in citationItems(msg)" :key="c.id" :value="c.number">
                  <el-tag size="small" :type="c.kind === 'event' ? 'primary' : 'info'" effect="plain">
                    {{ c.kind === 'event' ? '事件' : '帖子' }}
                  </el-tag>
                  <a v-if="c.external" :href="c.href" target="_blank" rel="noopener">{{ c.title }} ↗</a>
                  <a v-else :href="c.href" @click.prevent="router.push(c.href)">
                    {{ c.title }}{{ c.kind === 'event' ? '（去工作台研判）' : '（站内检索）' }}
                  </a>
                </li>
              </ol>
            </div>

            <!-- 关联事件卡片：done.events 的结构化字段（风险/热度/条数）直接画出来。
                 热度条画的是算术字段，来自后端数据，不经过 LLM——图表不可能被幻觉画歪。
                 有落库 id 的事件整卡可点，跳工作台研判；规则聚类的兜底事件没有 id，保持不可点 -->
            <div v-if="msg.meta.events && msg.meta.events.length" class="event-cards">
              <p class="event-cards-title">关联事件（{{ msg.meta.events.length }}）</p>
              <!-- 全局提问会带回 8 个事件——全量平铺是一面卡片墙，盖过正文。
                   超过 3 张默认收起，想看再展开；话题聚焦时（1~3 张）保持平铺 -->
              <div
                v-for="(ev, ei) in visibleEvents(msg)"
                :key="ei"
                class="event-card"
                :class="{ 'event-card--linkable': ev.id }"
                @click="openEvent(ev)"
              >
                <div class="event-card-head">
                  <span class="event-card-title">{{ ev.title }}</span>
                  <span class="event-card-side">
                    <el-tag size="small" :type="riskTagType(ev.risk_level)" effect="light">
                      {{ riskLabel(ev.risk_level) }}
                    </el-tag>
                    <span v-if="ev.id" class="event-card-go">研判 →</span>
                  </span>
                </div>
                <div class="heat-row">
                  <!-- 热度条是**对比**工具：只有一个事件时没有可比对象，条子必然满格、
                       毫无信息量还像卡住的进度条——单事件只报数字 -->
                  <div v-if="msg.meta.events.length >= 2" class="heat-track">
                    <span class="heat-fill" :style="{ width: heatWidth(ev, msg.meta.events) }"></span>
                  </div>
                  <span class="heat-value">热度 {{ Math.round(ev.heat_score || 0) }} · {{ ev.source_count || 0 }} 条</span>
                </div>
              </div>
              <button
                v-if="msg.meta.events.length > 3"
                class="event-toggle"
                type="button"
                @click="msg.meta.eventsExpanded = !msg.meta.eventsExpanded"
              >
                {{ msg.meta.eventsExpanded ? '收起' : `展开全部 ${msg.meta.events.length} 个事件` }}
              </button>
            </div>

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
import { useRoute, useRouter } from 'vue-router'
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
import { citeTarget, extractCitations, humanizeCiteIds, isSafeUrl } from '@/utils/citations'
import BrandLogo from '@/components/BrandLogo.vue'

const route = useRoute()
const router = useRouter()

// ——— 会话生命周期：前端界面和后端记忆必须对同一件事达成一致 ———
// 后端的会话记忆（话题词 + 最近对话）按用户 ID 存在进程里，切页面不会消失；
// 而聊天记录原本只存在组件状态里，切页即丢。两边一错位就出灵异现象（实测）：
// 用户切去别的栏目再回来，界面空了，以为是新对话——后端却还记着上一段，
// 于是「最近有什么热点？」被扣上旧话题，回答还引用着用户已经看不见的上文。
// 约定：切页回来 → 记录恢复、对话继续（两边都记得）；
//       新标签页/刷新（sessionStorage 为空）→ 界面是空的，第一条消息就带 reset，
//       让后端同步翻篇（两边都不记得）。
const STORAGE_KEY = 'agent-chat-transcript-v1'

function loadTranscript() {
  try {
    const data = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
    return Array.isArray(data) && data.length ? data : null
  } catch {
    return null
  }
}

function saveTranscript() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.value))
  } catch {
    /* 存储失败只影响切页恢复，不影响对话本身 */
  }
}

const restored = loadTranscript()
const messages = ref(restored || [])
// 支持从舆情工作台带问题跳转过来（?q=...），预填不自动发送
const draft = ref(typeof route.query.q === 'string' ? route.query.q : '')
const loading = ref(false)
const listEl = ref(null)
// 界面上没有历史 = 用户眼里这是新对话 → 首条消息带 reset 清后端记忆
const pendingReset = ref(!restored)
// 当前进行中的流；离开页面时 abort，别让请求悬着
let streamHandle = null

function startNewConversation() {
  messages.value = []
  saveTranscript()
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

// ——— 引用溯源：正文角标 + 参考来源脚注 ———
// pN/eN 是后端三方对口径用的内部编号，用户看不懂（实测截图）。markdown 渲染器
// 把它们换成按首次出现编号的角标，这里给出对应的脚注清单：每个编号是帖子还是
// 事件、标题是什么、点开去哪。编号必须与角标同源（同一个 extractCitations 顺序）。
function citationItems(msg) {
  const citations = msg.meta?.citations
  if (!citations) return []
  const items = []
  extractCitations(msg.text).forEach((id, index) => {
    const target = citeTarget(id, citations[id])
    if (target && target.title) {
      items.push({ id, number: index + 1, ...target })
    }
  })
  return items
}

// v-html 里没法用 router-link：角标的站内链接带 data-nav 标记，点击在这里
// 代理成 router.push（原生 href 仍在，中键新开标签页照常工作）
function onBodyClick(event) {
  const link = event.target.closest?.('a[data-nav]')
  if (!link) return
  event.preventDefault()
  router.push(link.getAttribute('href'))
}

// 关联事件卡 → 工作台研判。规则聚类的兜底事件没有落库 id，保持不可点。
function openEvent(ev) {
  if (ev?.id) router.push(`/opinion?event_id=${ev.id}`)
}

// 事件卡片：风险等级 → 标签色 / 文案
const RISK_TAG_TYPES = { high: 'danger', medium: 'warning', low: 'info' }
const RISK_LABELS = { high: '高风险', medium: '中风险', low: '低风险' }

function riskTagType(level) {
  return RISK_TAG_TYPES[level] || 'info'
}

function riskLabel(level) {
  return RISK_LABELS[level] || level || '未知'
}

// 热度条宽度 = 本批事件内的相对占比。纯算术展示，不做对数、不做美化加工——
// 条子的长短就是 heat_score 的真实比例（最短保留 2% 让条子可见）。
function heatWidth(ev, events) {
  const max = Math.max(...events.map((e) => Number(e.heat_score) || 0), 1)
  const ratio = (Number(ev.heat_score) || 0) / max
  return `${Math.max(Math.round(ratio * 100), 2)}%`
}

// 超过 3 张默认只露前 3；归一化仍按全量算（收起状态下条子长度也不许说谎）
function visibleEvents(msg) {
  const events = msg.meta.events || []
  return events.length > 3 && !msg.meta.eventsExpanded ? events.slice(0, 3) : events
}

// 审校提示封顶展示：审校是提示，不是第二份报告。
const REVIEW_ALERT_MAX_ISSUES = 3

// critic 的 issue 原文里带内部编号（[来源:e1]、"p4 仅能支持…"）——那是审计口径，
// 数据里保留；展示前用 citations 映射翻译成「事件“…”」「帖子“…”」（实测截图：
// 编号直接漏给用户就是天书）。
function reviewSummary(msg) {
  const issues = (msg.meta?.review?.issues || []).map((issue) =>
    humanizeCiteIds(issue, msg.meta?.citations),
  )
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
  saveTranscript() // 切页前落盘，回来时记录还在
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
    meta: { intent: '', keyword: '', route_source: '', steps: [], degraded: false, review: null, notes: [], events: [], citations: null, eventsExpanded: false },
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
        bubble.meta.events = data.events || []
        // 引用映射到位，正文里的角标从纯序号变成可点击链接（重渲染由响应式触发）
        bubble.meta.citations = data.citations || null
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
    saveTranscript() // 每轮收尾落盘（不用 deep watch：流式期间每个字都触发序列化太浪费）
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

.md-body :deep(a) {
  color: var(--brand-600);
  text-decoration: none;
  word-break: break-all;
}

.md-body :deep(a:hover) { text-decoration: underline; }

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

/* ——— 引用角标（[来源:pN/eN] 渲染成的上标序号） ——— */
.md-body :deep(.cite-chip) {
  margin: 0 1px;
  line-height: 0;
}

.md-body :deep(.cite-chip a),
.md-body :deep(.cite-chip span) {
  display: inline-block;
  min-width: 15px;
  padding: 0 3px;
  border-radius: 7px;
  background: var(--brand-50);
  color: var(--brand-600);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 15px;
  text-align: center;
  text-decoration: none;
  vertical-align: baseline;
}

.md-body :deep(.cite-chip a:hover) {
  background: var(--brand-500);
  color: #fff;
}

.meta-row {
  margin-top: 10px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.bubble .el-alert {
  margin-top: 8px;
}

/* ——— 参考来源脚注 ——— */
.cite-sources {
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
}

.cite-sources-title {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.cite-sources ol {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.9;
}

.cite-sources li::marker {
  color: var(--brand-500);
  font-weight: 600;
}

.cite-sources .el-tag {
  margin-right: 6px;
}

.cite-sources a {
  color: var(--brand-600);
  text-decoration: none;
  word-break: break-all;
}

.cite-sources a:hover {
  text-decoration: underline;
}

/* ——— 关联事件卡片 ——— */
.event-cards {
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
}

.event-cards-title {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.event-card {
  padding: 6px 0;
}

.event-card + .event-card {
  border-top: 1px dashed var(--color-border-light);
}

.event-card--linkable {
  cursor: pointer;
}

.event-card-side {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.event-card-go {
  font-size: 12px;
  color: var(--brand-600);
  white-space: nowrap;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.event-card--linkable:hover .event-card-go {
  opacity: 1;
}

.event-card--linkable:hover .event-card-title {
  color: var(--brand-600);
}

.event-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.event-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  word-break: break-all;
}

.heat-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.heat-track {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: var(--brand-100);
  overflow: hidden;
}

.heat-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--brand-500);
}

.heat-value {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.event-toggle {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 5px 0;
  border: none;
  background: none;
  color: var(--brand-600);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
}

.event-toggle:hover {
  text-decoration: underline;
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
