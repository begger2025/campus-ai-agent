<template>
  <section class="admin-page overview-page" v-loading="loading">
    <!-- 待办队列：管理员进后台的第一个问题是「今天要处理什么」。
         每张卡可点，直达带筛选的目标页；0 待办的卡淡化。 -->
    <div class="todo-row">
      <button v-for="card in todoCards" :key="card.label" type="button"
              :class="['todo-card', { 'todo-card--idle': !card.count }]" @click="router.push(card.to)">
        <strong>{{ card.count }}</strong>
        <span>{{ card.label }}</span>
        <em>{{ card.count ? '去处理 →' : '无待办' }}</em>
      </button>
    </div>

    <div class="main-grid">
      <div class="col-main">
        <!-- 数据管线健康：本页独有的信息（语料体检 / 最近生成 / LLM 用量），不与任何页重复 -->
        <div class="panel-card">
          <h3>数据管线健康</h3>
          <div class="health-grid">
            <div class="health-item">
              <span class="h-label">语料总量（未剔除）</span>
              <strong>{{ corpus.total }}</strong>
              <em>已剔除 {{ corpus.excluded }} 条</em>
            </div>
            <div class="health-item" :class="{ 'h-warn': corpus.recent_ratio < 0.3 }">
              <span class="h-label">近 30 天新鲜度</span>
              <strong>{{ Math.round((corpus.recent_ratio || 0) * 100) }}%</strong>
              <em>{{ corpus.recent_30d }} 条 · 目标 ≥30%（播种计划 KPI）</em>
            </div>
            <div v-if="run" class="health-item" :class="{ 'h-warn': run.warnings_count }">
              <span class="h-label">最近事件生成</span>
              <strong>{{ run.event_count }} 事件</strong>
              <em>输入 {{ run.input_count }} 帖 · {{ Math.round(run.duration_ms / 1000) }}s ·
                警告 {{ run.warnings_count }} · {{ run.finished_at }}</em>
            </div>
            <div class="health-item">
              <span class="h-label">LLM 用量（本次启动以来）</span>
              <strong>{{ llm.calls || 0 }} 次</strong>
              <em>缓存命中 {{ llm.cache_hits || 0 }} · 错误 {{ llm.errors || 0 }}</em>
            </div>
          </div>
        </div>

        <!-- 事件状态分布：每行可点，跳事件审核对应 tab -->
        <div class="panel-card">
          <h3>事件状态分布 <em class="h3-hint">点击状态直达审核页</em></h3>
          <button v-for="row in eventStatusRows" :key="row.key" type="button" class="dist-row"
                  @click="router.push({ path: '/admin/events', query: { status: row.key } })">
            <span class="dist-label">{{ row.label }}</span>
            <span class="dist-track"><span :class="['dist-fill', `dist-${row.key}`]" :style="{ width: row.percent + '%' }" /></span>
            <span class="dist-value">{{ row.count }}</span>
          </button>
          <p class="curated-line" v-if="overview.curated_events_count">
            其中 {{ overview.curated_events_count }} 个事件已人工修正（机器不再更新）
          </p>
        </div>
      </div>

      <!-- 右栏：最近管理操作时间线（动作人话化，行可点跳对象所在页） -->
      <div class="panel-card col-side">
        <h3>最近管理操作 <el-button link type="primary" @click="router.push('/admin/ops')">全部审计 →</el-button></h3>
        <div v-for="log in recentOps" :key="log.id" class="op-item" role="button" @click="jumpTo(log)">
          <div class="op-line"><b>{{ actionLabel(log.action) }}</b><span class="op-target">{{ targetLabel(log) }}</span></div>
          <div class="op-meta">{{ log.created_at }} · 操作人 {{ log.admin_user_id || '—' }}</div>
        </div>
        <div v-if="!recentOps.length && !loading" class="empty-hint">暂无操作记录</div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchOperationLogs, fetchOverview } from '@/api/admin'

const router = useRouter()
const loading = ref(false)
const overview = ref({ events: {}, corpus: {}, llm_usage: {} })
const recentOps = ref([])

const corpus = computed(() => overview.value.corpus || {})
const run = computed(() => overview.value.last_agent_run)
const llm = computed(() => overview.value.llm_usage || {})

const todoCards = computed(() => [
  { label: '待审核事件', count: overview.value.draft_events_count || 0, to: { path: '/admin/events', query: { status: 'draft' } } },
  { label: '待审投稿', count: overview.value.pending_submissions_count || 0, to: '/admin/submissions' },
  { label: '被举报评论', count: overview.value.reported_comments_count || 0, to: '/admin/comments' },
  { label: '待处理反馈', count: overview.value.pending_feedback_count || 0, to: '/admin/ops' },
  { label: '系统错误日志', count: overview.value.recent_system_errors_count || 0, to: '/admin/ops' },
])

const EVENT_STATUS_LABELS = { draft: '待审核', published: '已发布', rejected: '已驳回', archived: '已归档' }

const eventStatusRows = computed(() => {
  const events = overview.value.events || {}
  const total = Object.values(events).reduce((sum, count) => sum + (count || 0), 0) || 1
  return Object.entries(EVENT_STATUS_LABELS).map(([key, label]) => ({
    key, label, count: events[key] || 0, percent: Math.round(((events[key] || 0) / total) * 100),
  }))
})

// 动作翻译必须覆盖全量——漏一个，审计栏就露出 rename_event 这类英文原文（实测截图）
const ACTION_LABELS = {
  update_event_status: '事件审核', 事件审核: '事件审核',
  update_feedback_status: '反馈处理', update_user_status: '用户管理',
  rename_event: '事件改名', create_event: '手工建事件', delete_event: '删除事件',
  merge_events: '合并事件', add_event_post: '事件加帖', remove_event_post: '事件移帖',
  exclude_processed_post: '剔除帖子', restore_processed_post: '恢复帖子',
  submission_approved: '投稿通过', submission_rejected: '投稿驳回',
  hide_comment: '隐藏评论', restore_comment: '恢复评论',
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action
}

const TARGET_LABELS = {
  public_event: '事件', processed_post: '帖子', user_submission: '投稿', event_comment: '评论', user: '用户',
}

function targetLabel(log) {
  return `${TARGET_LABELS[log.target_type] || log.target_type} #${log.target_id}`
}

// 审计行可点：跳到对象所在的管理页（近似定位——审计是线索，处理在目标页）
const TARGET_ROUTES = {
  public_event: '/admin/events', processed_post: '/admin/raw-posts',
  user_submission: '/admin/submissions', event_comment: '/admin/comments', user: '/admin/ops',
}

function jumpTo(log) {
  router.push(TARGET_ROUTES[log.target_type] || '/admin/ops')
}

onMounted(async () => {
  loading.value = true
  try {
    const [overviewData, opsData] = await Promise.all([
      fetchOverview(),
      fetchOperationLogs({ page: 1, page_size: 6 }),
    ])
    overview.value = overviewData
    recentOps.value = opsData.items || []
  } catch (error) {
    ElMessage.error(error.message || '概览数据加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.overview-page { display: flex; flex-direction: column; gap: 14px; }
.todo-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
@media (max-width: 900px) { .todo-row { grid-template-columns: repeat(2, 1fr); } }

.todo-card {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  padding: 14px 16px; border: 1px solid var(--color-border-light); border-radius: var(--radius);
  background: var(--color-surface); cursor: pointer; font-family: inherit; text-align: left;
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.todo-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-card); border-color: var(--brand-300); }
.todo-card strong { font-size: 26px; color: var(--brand-600); line-height: 1.2; }
.todo-card span { font-size: 13px; color: var(--color-text); font-weight: 600; }
.todo-card em { font-size: 11.5px; color: var(--brand-500); font-style: normal; }
.todo-card--idle strong { color: var(--color-text-faint, #c0c4cc); }
.todo-card--idle em { color: var(--color-text-faint, #c0c4cc); }

.main-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; align-items: start; }
@media (max-width: 1100px) { .main-grid { grid-template-columns: 1fr; } }
.col-main { display: flex; flex-direction: column; gap: 14px; }

.panel-card { background: var(--color-surface); border: 1px solid var(--color-border-light); border-radius: var(--radius); padding: 16px 18px; }
.panel-card h3 { display: flex; align-items: center; justify-content: space-between; margin: 0 0 12px; font-size: 15px; }
.h3-hint { font-size: 12px; color: var(--color-text-muted); font-weight: 400; font-style: normal; }

.health-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.health-item { padding: 10px 12px; border-radius: 8px; background: var(--color-surface-2, #fafbfc); display: flex; flex-direction: column; gap: 2px; }
.health-item strong { font-size: 20px; }
.h-label { font-size: 12px; color: var(--color-text-muted); }
.health-item em { font-size: 11.5px; color: var(--color-text-faint, #a8abb2); font-style: normal; }
.h-warn strong { color: #b45309; }

.dist-row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 7px 4px; border: none; background: none; cursor: pointer; font-family: inherit; border-radius: 6px; }
.dist-row:hover { background: var(--color-surface-2, #f5f7fa); }
.dist-label { width: 56px; font-size: 13px; text-align: left; }
.dist-track { flex: 1; height: 8px; border-radius: 999px; background: var(--color-surface-2, #f0f2f5); overflow: hidden; }
.dist-fill { display: block; height: 100%; border-radius: 999px; }
.dist-draft { background: #d9a514; }
.dist-published { background: #2f9e44; }
.dist-rejected { background: #e03131; }
.dist-archived { background: #868e96; }
.dist-value { width: 40px; text-align: right; font-weight: 600; font-size: 13px; }
.curated-line { margin: 8px 0 0; font-size: 12px; color: var(--color-text-muted); }

.op-item { padding: 8px 6px; border-radius: 6px; cursor: pointer; }
.op-item:hover { background: var(--color-surface-2, #f5f7fa); }
.op-item + .op-item { border-top: 1px solid var(--color-border-light); }
.op-line { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; }
.op-target { color: var(--color-text-muted); }
.op-meta { font-size: 11.5px; color: var(--color-text-faint, #a8abb2); margin-top: 2px; }
.empty-hint { color: var(--color-text-muted); font-size: 13px; padding: 8px 0; }
</style>
