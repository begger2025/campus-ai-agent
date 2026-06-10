<template>
  <section class="admin-page">
    <div class="page-header">
      <h2>运维反馈</h2>
    </div>

    <!-- Tabs -->
    <el-tabs v-model="activeTab" class="ops-tabs" @tab-change="onTabChange">

      <!-- 用户反馈 -->
      <el-tab-pane label="用户反馈" name="feedback">
        <div class="filter-bar">
          <el-select v-model="feedbackFilters.status" clearable placeholder="全部状态" @change="loadFeedback">
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="handling" />
            <el-option label="已解决" value="resolved" />
            <el-option label="已忽略" value="ignored" />
          </el-select>
          <el-button type="primary" @click="loadFeedback">刷新</el-button>
        </div>
        <el-alert v-if="feedbackError" :title="feedbackError" type="error" show-icon :closable="false" style="margin-bottom:10px" />
        <OpsTable
          :loading="feedbackLoading"
          :items="feedbackItems"
          :total="feedbackTotal"
          :page="feedbackPage"
          :columns="feedbackColumns"
          empty-text="暂无用户反馈"
          @page-change="p => { feedbackPage = p; loadFeedback() }"
        >
          <template #action="{ item }">
            <el-button v-if="item.status === 'pending'" size="small" type="primary" plain @click="handleFeedback(item, 'handling')">处理中</el-button>
            <el-button v-if="['pending','handling'].includes(item.status)" size="small" type="success" plain @click="handleFeedback(item, 'resolved')">已解决</el-button>
            <el-button v-if="item.status === 'pending'" size="small" @click="handleFeedback(item, 'ignored')">忽略</el-button>
          </template>
        </OpsTable>
      </el-tab-pane>

      <!-- 爬虫任务 -->
      <el-tab-pane label="爬虫任务" name="crawl">
        <div class="filter-bar">
          <el-select v-model="crawlFilters.platform" clearable placeholder="全部平台" @change="loadCrawl">
            <el-option label="xhs" value="xhs" />
            <el-option label="weibo" value="weibo" />
            <el-option label="tieba" value="tieba" />
          </el-select>
          <el-select v-model="crawlFilters.status" clearable placeholder="全部状态" @change="loadCrawl">
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
            <el-option label="运行中" value="running" />
          </el-select>
          <el-button type="primary" @click="loadCrawl">刷新</el-button>
        </div>
        <el-alert v-if="crawlError" :title="crawlError" type="error" show-icon :closable="false" style="margin-bottom:10px" />
        <OpsTable :loading="crawlLoading" :items="crawlItems" :total="crawlTotal" :page="crawlPage" :columns="crawlColumns" empty-text="暂无爬虫任务" @page-change="p => { crawlPage = p; loadCrawl() }" />
      </el-tab-pane>

      <!-- Agent 记录 -->
      <el-tab-pane label="Agent 记录" name="agent">
        <el-alert title="当前展示 Agent 操作记录和失败日志；完整 agent_run_logs 列表接口待后端补充。" type="info" :closable="false" style="margin-bottom:10px" />
        <el-button type="primary" size="small" style="margin-bottom:10px" @click="loadAgentLogs">刷新</el-button>
        <el-alert v-if="agentError" :title="agentError" type="error" show-icon :closable="false" style="margin-bottom:10px" />
        <OpsTable :loading="agentLoading" :items="agentItems" :total="agentTotal" :page="agentPage" :columns="agentColumns" empty-text="暂无 Agent 记录" @page-change="p => { agentPage = p; loadAgentLogs() }" />
      </el-tab-pane>

      <!-- 系统日志 -->
      <el-tab-pane label="系统日志" name="system-logs">
        <div class="filter-bar">
          <el-select v-model="sysFilters.level" clearable placeholder="全部级别" @change="loadSysLogs">
            <el-option label="ERROR" value="error" />
            <el-option label="WARN" value="warning" />
            <el-option label="INFO" value="info" />
          </el-select>
          <el-input v-model="sysFilters.module" clearable placeholder="模块名" @keyup.enter="loadSysLogs" style="width:140px" />
          <el-button type="primary" @click="loadSysLogs">刷新</el-button>
        </div>
        <el-alert v-if="sysError" :title="sysError" type="error" show-icon :closable="false" style="margin-bottom:10px" />
        <OpsTable :loading="sysLoading" :items="sysItems" :total="sysTotal" :page="sysPage" :columns="sysColumns" empty-text="暂无系统日志" @page-change="p => { sysPage = p; loadSysLogs() }" />
      </el-tab-pane>

      <!-- 管理员操作日志 -->
      <el-tab-pane label="操作日志" name="operation-logs">
        <el-button type="primary" size="small" style="margin-bottom:10px" @click="loadOpLogs">刷新</el-button>
        <el-alert v-if="opError" :title="opError" type="error" show-icon :closable="false" style="margin-bottom:10px" />
        <OpsTable :loading="opLoading" :items="opItems" :total="opTotal" :page="opPage" :columns="opColumns" empty-text="暂无操作日志" @page-change="p => { opPage = p; loadOpLogs() }" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup>
import { defineComponent, h, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElPagination } from 'element-plus'
import {
  fetchAdminFeedback,
  fetchCrawlTasks,
  fetchOperationLogs,
  fetchSystemLogs,
  updateFeedbackStatus,
} from '@/api/adminOps'

const route = useRoute()
const activeTab = ref(route.query.tab || 'feedback')

function onTabChange(tab) {
  switch (tab) {
    case 'feedback': if (!feedbackItems.value.length) loadFeedback(); break
    case 'crawl': if (!crawlItems.value.length) loadCrawl(); break
    case 'agent': if (!agentItems.value.length) loadAgentLogs(); break
    case 'system-logs': if (!sysItems.value.length) loadSysLogs(); break
    case 'operation-logs': if (!opItems.value.length) loadOpLogs(); break
  }
}

// —— 通用表格组件 ——
const OpsTable = defineComponent({
  props: ['loading', 'items', 'total', 'page', 'columns', 'emptyText'],
  emits: ['page-change'],
  setup(props, { emit, slots }) {
    return () => h('div', { class: 'ops-table-wrap' }, [
      h('table', { class: 'admin-table' }, [
        h('thead', h('tr', props.columns.map(col => h('th', col.label)))),
        h('tbody', props.loading
          ? [h('tr', h('td', { colspan: props.columns.length, class: 'empty-cell' }, '加载中...'))]
          : props.items.length === 0
            ? [h('tr', h('td', { colspan: props.columns.length, class: 'empty-cell' }, props.emptyText || '暂无数据'))]
            : props.items.map(item => h('tr', [
                ...props.columns.filter(c => c.key !== 'action').map(col => h('td', item[col.key] ?? '—')),
                slots.action ? h('td', { class: 'action-cell' }, slots.action({ item })) : null,
              ].filter(Boolean)))
        ),
      ]),
      props.total > 0
        ? h('div', { class: 'table-footer' }, [
            h('span', `共 ${props.total} 条`),
            h(ElPagination, {
              'currentPage': props.page,
              'pageSize': 20,
              'background': true,
              'layout': 'prev, pager, next',
              'total': props.total,
              'onCurrentChange': p => emit('page-change', p),
            }),
          ])
        : null,
    ])
  },
})

// —— 用户反馈 ——
const feedbackLoading = ref(false)
const feedbackError = ref('')
const feedbackItems = ref([])
const feedbackTotal = ref(0)
const feedbackPage = ref(1)
const feedbackFilters = reactive({ status: route.query.status || '' })
const feedbackColumns = [
  { key: 'id', label: 'ID' },
  { key: 'target_type', label: '目标类型' },
  { key: 'target_id', label: '目标 ID' },
  { key: 'feedback_type', label: '类型' },
  { key: 'content', label: '内容' },
  { key: 'contact', label: '联系' },
  { key: 'status', label: '状态' },
  { key: 'created_at', label: '时间' },
  { key: 'action', label: '操作' },
]

async function loadFeedback() {
  feedbackLoading.value = true
  feedbackError.value = ''
  try {
    const resp = await fetchAdminFeedback({ page: feedbackPage.value, status: feedbackFilters.status })
    feedbackItems.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    feedbackTotal.value = resp?.total ?? feedbackItems.value.length
  } catch (err) {
    feedbackError.value = err.message || '反馈列表加载失败'
  } finally {
    feedbackLoading.value = false
  }
}

async function handleFeedback(item, status) {
  try {
    await updateFeedbackStatus(item.id, status)
    ElMessage.success('操作成功')
    loadFeedback()
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  }
}

// —— 爬虫任务 ——
const crawlLoading = ref(false)
const crawlError = ref('')
const crawlItems = ref([])
const crawlTotal = ref(0)
const crawlPage = ref(1)
const crawlFilters = reactive({ platform: '', status: '' })
const crawlColumns = [
  { key: 'id', label: 'ID' },
  { key: 'task_name', label: '任务名' },
  { key: 'task_type', label: '类型' },
  { key: 'platform', label: '平台' },
  { key: 'keyword', label: '关键词' },
  { key: 'status', label: '状态' },
  { key: 'success_count', label: '成功' },
  { key: 'failed_count', label: '失败' },
  { key: 'started_at', label: '开始时间' },
]

async function loadCrawl() {
  crawlLoading.value = true
  crawlError.value = ''
  try {
    const resp = await fetchCrawlTasks({ page: crawlPage.value, platform: crawlFilters.platform, status: crawlFilters.status })
    crawlItems.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    crawlTotal.value = resp?.total ?? crawlItems.value.length
  } catch (err) {
    crawlError.value = err.message || '爬虫任务加载失败'
  } finally {
    crawlLoading.value = false
  }
}

// —— Agent 记录（临时：operation-logs?action=run_public_opinion_analysis） ——
const agentLoading = ref(false)
const agentError = ref('')
const agentItems = ref([])
const agentTotal = ref(0)
const agentPage = ref(1)
const agentColumns = [
  { key: 'id', label: 'ID' },
  { key: 'admin_user_id', label: '操作者' },
  { key: 'action', label: '操作' },
  { key: 'target_type', label: '目标类型' },
  { key: 'target_id', label: '目标 ID' },
  { key: 'detail', label: '详情' },
  { key: 'created_at', label: '时间' },
]

async function loadAgentLogs() {
  agentLoading.value = true
  agentError.value = ''
  try {
    const resp = await fetchOperationLogs({ page: agentPage.value, action: 'run_public_opinion_analysis' })
    agentItems.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    agentTotal.value = resp?.total ?? agentItems.value.length
  } catch (err) {
    agentError.value = err.message || 'Agent 记录加载失败'
  } finally {
    agentLoading.value = false
  }
}

// —— 系统日志 ——
const sysLoading = ref(false)
const sysError = ref('')
const sysItems = ref([])
const sysTotal = ref(0)
const sysPage = ref(1)
const sysFilters = reactive({ level: '', module: '' })
const sysColumns = [
  { key: 'id', label: 'ID' },
  { key: 'level', label: '级别' },
  { key: 'module', label: '模块' },
  { key: 'message', label: '消息' },
  { key: 'trace_id', label: 'trace_id' },
  { key: 'created_at', label: '时间' },
]

async function loadSysLogs() {
  sysLoading.value = true
  sysError.value = ''
  try {
    const resp = await fetchSystemLogs({ page: sysPage.value, level: sysFilters.level, module: sysFilters.module })
    sysItems.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    sysTotal.value = resp?.total ?? sysItems.value.length
  } catch (err) {
    sysError.value = err.message || '系统日志加载失败'
  } finally {
    sysLoading.value = false
  }
}

// —— 操作日志 ——
const opLoading = ref(false)
const opError = ref('')
const opItems = ref([])
const opTotal = ref(0)
const opPage = ref(1)
const opColumns = [
  { key: 'id', label: 'ID' },
  { key: 'admin_user_id', label: '管理员' },
  { key: 'action', label: '操作' },
  { key: 'target_type', label: '目标类型' },
  { key: 'target_id', label: '目标 ID' },
  { key: 'ip_address', label: 'IP' },
  { key: 'created_at', label: '时间' },
]

async function loadOpLogs() {
  opLoading.value = true
  opError.value = ''
  try {
    const resp = await fetchOperationLogs({ page: opPage.value })
    opItems.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    opTotal.value = resp?.total ?? opItems.value.length
  } catch (err) {
    opError.value = err.message || '操作日志加载失败'
  } finally {
    opLoading.value = false
  }
}

onMounted(() => {
  loadFeedback()
})
</script>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 12px; }
.page-header h2 { margin: 0; font-size: 20px; color: var(--color-text); }
.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.ops-tabs :deep(.el-tabs__header) { margin-bottom: 14px; }

.ops-table-wrap { overflow-x: auto; }
.admin-table { width: 100%; border-collapse: collapse; font-size: 12px; background: var(--color-surface); border-radius: var(--radius); overflow: hidden; border: 1px solid var(--color-border-light); box-shadow: var(--shadow-card); }
.admin-table th { padding: 10px 10px; background: #f8fafd; color: var(--color-text-muted); font-weight: 600; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--color-border-light); }
.admin-table td { padding: 9px 10px; border-bottom: 1px solid var(--color-border-light); vertical-align: middle; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.admin-table tbody tr:hover { background: #f9fafb; }
.admin-table tbody tr:last-child td { border-bottom: 0; }
.empty-cell { text-align: center; color: var(--color-text-muted); padding: 32px; }
.action-cell { white-space: nowrap; }
.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-top: 1px solid var(--color-border-light); color: var(--color-text-secondary); font-size: 13px; }
</style>
