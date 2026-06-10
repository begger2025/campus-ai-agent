<template>
  <section class="admin-page">
    <div class="page-header">
      <h2>事件审核</h2>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar panel-card">
      <el-select v-model="filters.status" class="filter-select" @change="loadData">
        <el-option label="全部状态" value="all" />
        <el-option label="草稿" value="draft" />
        <el-option label="已发布" value="published" />
        <el-option label="已驳回" value="rejected" />
        <el-option label="已归档" value="archived" />
      </el-select>
      <el-select v-model="filters.risk_level" class="filter-select" @change="loadData">
        <el-option label="全部风险" value="" />
        <el-option label="高风险" value="high" />
        <el-option label="中风险" value="medium" />
        <el-option label="低风险" value="low" />
      </el-select>
      <el-input v-model="filters.keyword" placeholder="搜索标题、关键词" clearable class="filter-input" @keyup.enter="loadData" />
      <el-button type="primary" @click="loadData">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <!-- 错误状态 -->
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <!-- 表格 -->
    <div class="panel-card table-card" v-loading="loading">
      <table class="admin-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>标题</th>
            <th>风险</th>
            <th>热度</th>
            <th>状态</th>
            <th>来源数</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!loading && !items.length">
            <td colspan="8" class="empty-cell">暂无数据</td>
          </tr>
          <tr v-for="item in items" :key="item.id">
            <td class="id-cell">{{ item.raw_id ?? item.id }}</td>
            <td class="title-cell">{{ item.title }}</td>
            <td><span :class="['risk-badge', riskClass(item.risk_level)]">{{ riskLabel(item.risk_level) }}</span></td>
            <td>{{ item.heat_score ?? item.heatScore ?? '—' }}</td>
            <td><span :class="['status-chip', `status-${item.status}`]">{{ statusLabel(item.status) }}</span></td>
            <td>{{ item.source_count ?? '—' }}</td>
            <td>{{ formatTime(item.updated_at ?? item.updatedAt) }}</td>
            <td class="action-cell">
              <template v-if="item.status === 'draft'">
                <el-button size="small" type="primary" @click="updateStatus(item, 'published')">发布</el-button>
                <el-button size="small" type="danger" plain @click="updateStatus(item, 'rejected')">驳回</el-button>
              </template>
              <template v-else-if="item.status === 'published'">
                <el-button size="small" @click="updateStatus(item, 'archived')">归档</el-button>
              </template>
              <template v-else-if="item.status !== 'archived'">
                <el-button size="small" @click="updateStatus(item, 'draft')">退回草稿</el-button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="table-footer" v-if="total > 0">
        <span>共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          background
          layout="prev, pager, next"
          :total="total"
          @current-change="loadData"
        />
      </div>
    </div>

    <!-- 审核确认对话框 -->
    <el-dialog v-model="reviewVisible" :title="reviewTitle" width="420px" :close-on-click-modal="false">
      <el-input
        v-model="reviewComment"
        type="textarea"
        :rows="3"
        placeholder="审核备注（可选）"
      />
      <template #footer>
        <el-button @click="reviewVisible = false">取消</el-button>
        <el-button type="primary" :loading="reviewing" @click="confirmReview">确认</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchAdminEvents, updateAdminEventStatus } from '@/api/adminEvents'

const route = useRoute()

const loading = ref(false)
const error = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  status: route.query.status || 'all',
  risk_level: '',
  keyword: '',
})

// 审核对话框
const reviewVisible = ref(false)
const reviewTitle = ref('')
const reviewComment = ref('')
const reviewing = ref(false)
let pendingReview = null

onMounted(loadData)

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchAdminEvents({
      status: filters.status,
      risk_level: filters.risk_level,
      keyword: filters.keyword,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    total.value = resp?.total ?? items.value.length
  } catch (err) {
    error.value = err.message || '事件列表加载失败'
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.status = 'all'
  filters.risk_level = ''
  filters.keyword = ''
  page.value = 1
  loadData()
}

function updateStatus(item, status) {
  const actionMap = { published: '发布', rejected: '驳回', archived: '归档', draft: '退回草稿' }
  reviewTitle.value = `确认${actionMap[status] || status}事件：${item.title}`
  reviewComment.value = ''
  pendingReview = { item, status }
  reviewVisible.value = true
}

async function confirmReview() {
  if (!pendingReview) return
  reviewing.value = true
  try {
    const { item, status } = pendingReview
    await updateAdminEventStatus(item.raw_id ?? item.id, status, reviewComment.value)
    ElMessage.success('操作成功')
    reviewVisible.value = false
    loadData()
  } catch (err) {
    ElMessage.error(err.message || '操作失败')
  } finally {
    reviewing.value = false
  }
}

function riskClass(v) { return v === 'high' ? 'risk-high' : v === 'medium' ? 'risk-mid' : 'risk-low' }
function riskLabel(v) { return v === 'high' ? '高风险' : v === 'medium' ? '中风险' : '低风险' }
function statusLabel(v) { return { draft: '草稿', published: '已发布', rejected: '已驳回', archived: '已归档' }[v] || v }
function formatTime(v) { return v ? String(v).slice(0, 16).replace('T', ' ') : '—' }
</script>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 12px; }
.page-header { display: flex; align-items: center; justify-content: space-between; }
.page-header h2 { margin: 0; font-size: 20px; color: var(--color-text); }

.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 12px 16px; }
.filter-select { width: 130px; }
.filter-input { flex: 1; min-width: 180px; }

.panel-card { background: var(--color-surface); border: 1px solid var(--color-border-light); border-radius: var(--radius); padding: 0; box-shadow: var(--shadow-card); }
.table-card { overflow: hidden; }

.admin-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.admin-table th { padding: 10px 12px; background: #f8fafd; color: var(--color-text-muted); font-weight: 600; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--color-border-light); }
.admin-table td { padding: 10px 12px; border-bottom: 1px solid var(--color-border-light); vertical-align: middle; }
.admin-table tbody tr:hover { background: #f9fafb; }
.admin-table tbody tr:last-child td { border-bottom: 0; }
.empty-cell { text-align: center; color: var(--color-text-muted); padding: 32px; }
.id-cell { color: var(--color-text-muted); font-family: monospace; font-size: 12px; }
.title-cell { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-text); font-weight: 500; }

.risk-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.risk-high { color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; }
.risk-mid { color: #d97706; background: #fffbeb; border: 1px solid #fde68a; }
.risk-low { color: #16a34a; background: #f0fdf4; border: 1px solid #bbf7d0; }

.status-chip { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.status-draft { color: #6b7280; background: #f3f4f6; }
.status-published { color: #059669; background: #d1fae5; }
.status-rejected { color: #dc2626; background: #fee2e2; }
.status-archived { color: #2563eb; background: #dbeafe; }

.action-cell { white-space: nowrap; }

.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-top: 1px solid var(--color-border-light); color: var(--color-text-secondary); font-size: 13px; }
</style>
