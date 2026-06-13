<template>
  <section class="admin-page">
    <div class="page-header">
      <h2>运营管理</h2>
    </div>

    <el-tabs v-model="activeTab" @tab-change="onTabChange" class="ops-tabs">

      <!-- ===== Tab 1: 用户反馈 ===== -->
      <el-tab-pane label="用户反馈" name="feedback">
        <div class="filter-bar panel-card">
          <el-select v-model="fb.filters.status" class="filter-select" @change="fb.load">
            <el-option label="全部状态" value="" />
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="handling" />
            <el-option label="已解决" value="resolved" />
            <el-option label="已忽略" value="ignored" />
          </el-select>
          <el-button type="primary" @click="fb.load">查询</el-button>
          <el-button @click="() => { fb.filters.status = ''; fb.page = 1; fb.load() }">重置</el-button>
        </div>

        <el-alert v-if="fb.error" :title="fb.error" type="error" show-icon :closable="false" />

        <div class="panel-card table-card" v-loading="fb.loading">
          <table class="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>类型</th>
                <th>内容摘要</th>
                <th>联系方式</th>
                <th>目标</th>
                <th>状态</th>
                <th>提交时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!fb.loading && !fb.items.length">
                <td colspan="8" class="empty-cell">暂无反馈数据</td>
              </tr>
              <tr v-for="item in fb.items" :key="item.id">
                <td class="id-cell">{{ item.id }}</td>
                <td>
                  <span :class="['type-tag', `type-${item.feedback_type ?? item.type}`]">
                    {{ fbTypeLabel(item.feedback_type ?? item.type) }}
                  </span>
                </td>
                <td class="content-cell" :title="item.content">{{ truncate(item.content, 50) }}</td>
                <td class="text-muted">{{ item.contact ?? '—' }}</td>
                <td class="text-muted">{{ item.target_type ?? '—' }} {{ item.target_id ? `#${item.target_id}` : '' }}</td>
                <td>
                  <span :class="['status-chip', `fb-status-${item.status}`]">
                    {{ fbStatusLabel(item.status) }}
                  </span>
                </td>
                <td class="time-cell">{{ formatTime(item.created_at) }}</td>
                <td class="action-cell">
                  <template v-if="item.status === 'pending'">
                    <el-button size="small" type="primary" @click="openFbReview(item, 'handling')">受理</el-button>
                    <el-button size="small" plain @click="openFbReview(item, 'ignored')">忽略</el-button>
                  </template>
                  <template v-else-if="item.status === 'handling'">
                    <el-button size="small" type="success" @click="openFbReview(item, 'resolved')">解决</el-button>
                  </template>
                  <template v-else>
                    <span class="text-muted">—</span>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
          <div class="table-footer" v-if="fb.total > 0">
            <span>共 {{ fb.total }} 条</span>
            <el-pagination v-model:current-page="fb.page" :page-size="fb.pageSize" background layout="prev, pager, next" :total="fb.total" @current-change="fb.load" />
          </div>
        </div>

        <!-- 反馈处理对话框 -->
        <el-dialog v-model="fbDialog.visible" :title="fbDialog.title" width="400px" :close-on-click-modal="false">
          <el-input v-model="fbDialog.handleNote" type="textarea" :rows="3" placeholder="处理备注（可选）" />
          <template #footer>
            <el-button @click="fbDialog.visible = false">取消</el-button>
            <el-button type="primary" :loading="fbDialog.submitting" @click="confirmFbReview">确认</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ===== Tab 2: 爬虫任务 ===== -->
      <el-tab-pane label="爬虫任务" name="crawl">
        <div class="filter-bar panel-card">
          <el-select v-model="crawl.filters.status" class="filter-select" @change="crawl.load">
            <el-option label="全部状态" value="" />
            <el-option label="等待中" value="pending" />
            <el-option label="运行中" value="running" />
            <el-option label="已完成" value="done" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-select v-model="crawl.filters.platform" class="filter-select" @change="crawl.load">
            <el-option label="全部平台" value="" />
            <el-option label="微博" value="weibo" />
            <el-option label="微信" value="wechat" />
            <el-option label="贴吧" value="tieba" />
            <el-option label="知乎" value="zhihu" />
            <el-option label="小红书" value="xiaohongshu" />
          </el-select>
          <el-button :loading="crawl.loading" @click="crawl.load">刷新</el-button>
        </div>

        <el-alert v-if="crawl.error" :title="crawl.error" type="error" show-icon :closable="false" />

        <div class="panel-card table-card" v-loading="crawl.loading">
          <table class="admin-table">
            <thead>
              <tr>
                <th>任务ID</th>
                <th>平台</th>
                <th>关键词</th>
                <th>状态</th>
                <th>采集数量</th>
                <th>开始时间</th>
                <th>完成时间</th>
                <th>错误信息</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!crawl.loading && !crawl.items.length">
                <td colspan="8" class="empty-cell">暂无爬虫任务</td>
              </tr>
              <tr v-for="item in crawl.items" :key="item.id">
                <td class="id-cell">{{ item.id }}</td>
                <td>{{ platformLabel(item.platform) }}</td>
                <td class="content-cell">{{ item.keyword ?? '—' }}</td>
                <td>
                  <span :class="['status-chip', `crawl-status-${item.status}`]">
                    {{ crawlStatusLabel(item.status) }}
                  </span>
                </td>
                <td>{{ item.fetched_count ?? '—' }}</td>
                <td class="time-cell">{{ formatTime(item.started_at) }}</td>
                <td class="time-cell">{{ formatTime(item.finished_at) }}</td>
                <td class="error-cell" :title="item.error_message">{{ truncate(item.error_message, 40) }}</td>
              </tr>
            </tbody>
          </table>
          <div class="table-footer" v-if="crawl.total > 0">
            <span>共 {{ crawl.total }} 条</span>
            <el-pagination v-model:current-page="crawl.page" :page-size="crawl.pageSize" background layout="prev, pager, next" :total="crawl.total" @current-change="crawl.load" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== Tab 3: 系统日志 ===== -->
      <el-tab-pane label="系统日志" name="system-logs">
        <div class="filter-bar panel-card">
          <el-select v-model="syslog.filters.level" class="filter-select" @change="syslog.load">
            <el-option label="全部级别" value="" />
            <el-option label="INFO" value="info" />
            <el-option label="WARNING" value="warning" />
            <el-option label="ERROR" value="error" />
            <el-option label="CRITICAL" value="critical" />
          </el-select>
          <el-input v-model="syslog.filters.module" placeholder="模块名称" clearable class="filter-input" @keyup.enter="syslog.load" />
          <el-button :loading="syslog.loading" @click="syslog.load">查询</el-button>
          <el-button @click="() => { syslog.filters.level = ''; syslog.filters.module = ''; syslog.page = 1; syslog.load() }">重置</el-button>
        </div>

        <el-alert v-if="syslog.error" :title="syslog.error" type="error" show-icon :closable="false" />

        <div class="panel-card table-card" v-loading="syslog.loading">
          <table class="admin-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>级别</th>
                <th>模块</th>
                <th>消息</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!syslog.loading && !syslog.items.length">
                <td colspan="4" class="empty-cell">暂无系统日志</td>
              </tr>
              <tr v-for="(item, idx) in syslog.items" :key="idx">
                <td class="time-cell">{{ formatTime(item.timestamp ?? item.created_at) }}</td>
                <td>
                  <span :class="['level-tag', `level-${item.level?.toLowerCase()}`]">
                    {{ item.level?.toUpperCase() ?? '—' }}
                  </span>
                </td>
                <td class="module-cell">{{ item.module ?? '—' }}</td>
                <td class="message-cell" :title="item.message">{{ item.message }}</td>
              </tr>
            </tbody>
          </table>
          <div class="table-footer" v-if="syslog.total > 0">
            <span>共 {{ syslog.total }} 条</span>
            <el-pagination v-model:current-page="syslog.page" :page-size="syslog.pageSize" background layout="prev, pager, next" :total="syslog.total" @current-change="syslog.load" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== Tab 4: 操作日志 ===== -->
      <el-tab-pane label="操作日志" name="oplog">
        <div class="filter-bar panel-card">
          <el-input v-model="oplog.filters.action" placeholder="操作类型（如 publish）" clearable class="filter-input" @keyup.enter="oplog.load" />
          <el-input v-model="oplog.filters.target_type" placeholder="目标类型（如 event）" clearable class="filter-input" @keyup.enter="oplog.load" />
          <el-button :loading="oplog.loading" @click="oplog.load">查询</el-button>
          <el-button @click="() => { oplog.filters.action = ''; oplog.filters.target_type = ''; oplog.page = 1; oplog.load() }">重置</el-button>
        </div>

        <el-alert v-if="oplog.error" :title="oplog.error" type="error" show-icon :closable="false" />

        <div class="panel-card table-card" v-loading="oplog.loading">
          <table class="admin-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作者</th>
                <th>操作类型</th>
                <th>目标类型</th>
                <th>目标ID</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!oplog.loading && !oplog.items.length">
                <td colspan="6" class="empty-cell">暂无操作日志</td>
              </tr>
              <tr v-for="(item, idx) in oplog.items" :key="idx">
                <td class="time-cell">{{ formatTime(item.created_at ?? item.timestamp) }}</td>
                <td>{{ item.operator ?? item.admin_username ?? '—' }}</td>
                <td><code class="action-code">{{ item.action }}</code></td>
                <td class="text-muted">{{ item.target_type ?? '—' }}</td>
                <td class="id-cell">{{ item.target_id ?? '—' }}</td>
                <td class="content-cell" :title="item.comment ?? item.remark">{{ truncate(item.comment ?? item.remark, 50) }}</td>
              </tr>
            </tbody>
          </table>
          <div class="table-footer" v-if="oplog.total > 0">
            <span>共 {{ oplog.total }} 条</span>
            <el-pagination v-model:current-page="oplog.page" :page-size="oplog.pageSize" background layout="prev, pager, next" :total="oplog.total" @current-change="oplog.load" />
          </div>
        </div>
      </el-tab-pane>

    </el-tabs>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchAdminFeedback,
  updateFeedbackStatus,
  fetchCrawlTasks,
  fetchSystemLogs,
  fetchOperationLogs,
} from '@/api/adminOps'

const route = useRoute()

// 初始 tab：支持 query 参数 ?tab=xxx
const activeTab = ref(route.query.tab || 'feedback')

// ---- 反馈 Tab 状态 ----
const fb = reactive({
  loading: false,
  error: '',
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  filters: { status: route.query.status || '' },
  async load() {
    this.loading = true
    this.error = ''
    try {
      const resp = await fetchAdminFeedback({ page: this.page, page_size: this.pageSize, status: this.filters.status })
      this.items = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
      this.total = resp?.total ?? this.items.length
    } catch (err) {
      this.error = err.message || '反馈数据加载失败'
    } finally {
      this.loading = false
    }
  },
})

// 反馈处理对话框
const fbDialog = reactive({ visible: false, title: '', handleNote: '', submitting: false, item: null, targetStatus: '' })

function openFbReview(item, status) {
  const actionMap = { handling: '受理', resolved: '标记已解决', ignored: '忽略' }
  fbDialog.item = item
  fbDialog.targetStatus = status
  fbDialog.title = `${actionMap[status] || status}：反馈 #${item.id}`
  fbDialog.handleNote = ''
  fbDialog.visible = true
}

async function confirmFbReview() {
  fbDialog.submitting = true
  try {
    await updateFeedbackStatus(fbDialog.item.id, fbDialog.targetStatus, fbDialog.handleNote)
    ElMessage.success('操作成功')
    fbDialog.visible = false
    fb.load()
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  } finally {
    fbDialog.submitting = false
  }
}

// ---- 爬虫任务 Tab 状态 ----
const crawl = reactive({
  loading: false,
  error: '',
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  filters: { status: '', platform: '' },
  async load() {
    this.loading = true
    this.error = ''
    try {
      const resp = await fetchCrawlTasks({ page: this.page, page_size: this.pageSize, status: this.filters.status, platform: this.filters.platform })
      this.items = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
      this.total = resp?.total ?? this.items.length
    } catch (err) {
      this.error = err.message || '爬虫任务加载失败'
    } finally {
      this.loading = false
    }
  },
})

// ---- 系统日志 Tab 状态 ----
const syslog = reactive({
  loading: false,
  error: '',
  items: [],
  total: 0,
  page: 1,
  pageSize: 50,
  filters: { level: route.query.level || '', module: '' },
  async load() {
    this.loading = true
    this.error = ''
    try {
      const resp = await fetchSystemLogs({ page: this.page, page_size: this.pageSize, level: this.filters.level, module: this.filters.module })
      this.items = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
      this.total = resp?.total ?? this.items.length
    } catch (err) {
      this.error = err.message || '系统日志加载失败'
    } finally {
      this.loading = false
    }
  },
})

// ---- 操作日志 Tab 状态 ----
const oplog = reactive({
  loading: false,
  error: '',
  items: [],
  total: 0,
  page: 1,
  pageSize: 50,
  filters: { action: '', target_type: '' },
  async load() {
    this.loading = true
    this.error = ''
    try {
      const resp = await fetchOperationLogs({ page: this.page, page_size: this.pageSize, action: this.filters.action, target_type: this.filters.target_type })
      this.items = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
      this.total = resp?.total ?? this.items.length
    } catch (err) {
      this.error = err.message || '操作日志加载失败'
    } finally {
      this.loading = false
    }
  },
})

// Tab 切换时懒加载
const loaded = new Set()
function onTabChange(name) {
  if (!loaded.has(name)) {
    loaded.add(name)
    loadTab(name)
  }
}

function loadTab(name) {
  if (name === 'feedback') fb.load()
  else if (name === 'crawl') crawl.load()
  else if (name === 'system-logs') syslog.load()
  else if (name === 'oplog') oplog.load()
}

onMounted(() => {
  loaded.add(activeTab.value)
  loadTab(activeTab.value)
})

// ---- 工具函数 ----
function platformLabel(v) {
  const map = { weibo: '微博', wechat: '微信', tieba: '贴吧', zhihu: '知乎', xiaohongshu: '小红书' }
  return map[v] || v || '未知'
}

function fbTypeLabel(v) {
  const map = { error: '数据错误', suggestion: '建议', complaint: '投诉', other: '其他' }
  return map[v] || v || '—'
}

function fbStatusLabel(v) {
  const map = { pending: '待处理', handling: '处理中', resolved: '已解决', ignored: '已忽略' }
  return map[v] || v || '—'
}

function crawlStatusLabel(v) {
  const map = { pending: '等待中', running: '运行中', done: '已完成', failed: '失败' }
  return map[v] || v || '—'
}

function truncate(str, len) {
  if (!str) return '—'
  return str.length > len ? str.slice(0, len) + '…' : str
}

function formatTime(v) {
  return v ? String(v).slice(0, 16).replace('T', ' ') : '—'
}
</script>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 12px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0; }
.page-header h2 { margin: 0; font-size: 20px; color: var(--color-text); }

.ops-tabs { --el-tabs-header-height: 40px; }

.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 12px 16px; margin-bottom: 12px; }
.filter-select { width: 130px; }
.filter-input { flex: 1; min-width: 160px; }

.panel-card { background: var(--color-surface); border: 1px solid var(--color-border-light); border-radius: var(--radius); box-shadow: var(--shadow-card); }
.table-card { overflow: hidden; }

.admin-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.admin-table th { padding: 10px 12px; background: #f8fafd; color: var(--color-text-muted); font-weight: 600; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--color-border-light); }
.admin-table td { padding: 10px 12px; border-bottom: 1px solid var(--color-border-light); vertical-align: middle; }
.admin-table tbody tr:hover { background: #f9fafb; }
.admin-table tbody tr:last-child td { border-bottom: 0; }
.empty-cell { text-align: center; color: var(--color-text-muted); padding: 32px; }
.id-cell { color: var(--color-text-muted); font-family: monospace; font-size: 12px; }
.content-cell { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-text); }
.time-cell { white-space: nowrap; color: var(--color-text-muted); font-size: 12px; }
.module-cell { font-family: monospace; font-size: 12px; color: var(--color-text-secondary); }
.message-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #dc2626; font-size: 12px; }
.text-muted { color: var(--color-text-muted); font-size: 12px; }
.action-cell { white-space: nowrap; }
.action-code { font-family: monospace; font-size: 12px; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; color: #334155; }

.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-top: 1px solid var(--color-border-light); color: var(--color-text-secondary); font-size: 13px; }

/* 类型标签 */
.type-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.type-error { color: #dc2626; background: #fee2e2; }
.type-suggestion { color: #2563eb; background: #dbeafe; }
.type-complaint { color: #d97706; background: #fef3c7; }
.type-other { color: #6b7280; background: #f3f4f6; }

/* 反馈状态 */
.status-chip { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.fb-status-pending { color: #d97706; background: #fef3c7; }
.fb-status-handling { color: #2563eb; background: #dbeafe; }
.fb-status-resolved { color: #059669; background: #d1fae5; }
.fb-status-ignored { color: #9ca3af; background: #f3f4f6; }

/* 爬虫状态 */
.crawl-status-pending { color: #9ca3af; background: #f3f4f6; }
.crawl-status-running { color: #2563eb; background: #dbeafe; }
.crawl-status-done { color: #059669; background: #d1fae5; }
.crawl-status-failed { color: #dc2626; background: #fee2e2; }

/* 日志级别 */
.level-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; font-family: monospace; }
.level-info { color: #0284c7; background: #e0f2fe; }
.level-warning { color: #d97706; background: #fef3c7; }
.level-error { color: #dc2626; background: #fee2e2; }
.level-critical { color: #fff; background: #dc2626; }
</style>
