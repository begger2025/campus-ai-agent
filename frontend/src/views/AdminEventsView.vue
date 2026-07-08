<template>
  <section class="admin-page admin-events">
    <div class="panel-card filter-bar">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索标题、摘要、话题、关键词"
        class="filter-search"
        @keyup.enter="reload(1)"
      />
      <el-select v-model="filters.risk" class="filter-select" @change="reload(1)">
        <el-option label="风险等级：全部" value="" />
        <el-option label="风险等级：高" value="high" />
        <el-option label="风险等级：中" value="medium" />
        <el-option label="风险等级：低" value="low" />
      </el-select>
      <el-button type="primary" @click="reload(1)">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <div class="panel-card">
      <el-tabs v-model="filters.status" @tab-change="reload(1)">
        <el-tab-pane v-for="tab in statusTabs" :key="tab.value" :label="tab.label" :name="tab.value" />
      </el-tabs>

      <div class="table-shell" v-loading="loading">
        <table class="compact-table">
          <thead>
            <tr>
              <th style="width: 52px">ID</th>
              <th style="min-width: 220px">事件标题</th>
              <th>风险</th>
              <th>情绪</th>
              <th>热度</th>
              <th>来源数</th>
              <th>状态</th>
              <th style="width: 150px">更新时间</th>
              <th style="width: 210px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="event in events" :key="event.raw_id">
              <td>{{ event.raw_id }}</td>
              <td class="title-cell" :title="event.title">{{ event.title }}</td>
              <td><span :class="['badge', riskClass(event.riskLevel)]">{{ event.riskLabel || '低风险' }}</span></td>
              <td>{{ sentimentLabel(event.sentiment) }}</td>
              <td>{{ Math.round(event.heatScore || 0) }}</td>
              <td>{{ event.source_count ?? '—' }}</td>
              <td><span :class="['status-tag', `status-${event.status}`]">{{ statusLabel(event.status) }}</span></td>
              <td>{{ event.updatedAt || '—' }}</td>
              <td class="ops-cell">
                <el-button
                  v-if="event.status !== 'published'"
                  link
                  type="success"
                  @click="openReview(event, 'published')"
                >通过</el-button>
                <el-button
                  v-if="event.status !== 'rejected'"
                  link
                  type="danger"
                  @click="openReview(event, 'rejected')"
                >驳回</el-button>
                <el-button
                  v-if="event.status !== 'archived'"
                  link
                  @click="openReview(event, 'archived')"
                >归档</el-button>
                <el-button link type="primary" @click="openHistory(event)">历史</el-button>
              </td>
            </tr>
            <tr v-if="!events.length && !loading">
              <td colspan="9" class="empty-hint">当前筛选条件下没有事件</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="table-footer">
        <span>共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="page"
          background
          layout="prev, pager, next"
          :page-size="pageSize"
          :total="total"
          @current-change="reload"
        />
      </div>
    </div>

    <!-- 审核对话框 -->
    <el-dialog v-model="review.visible" :title="reviewTitle" width="480px">
      <p class="review-event-title">{{ review.event?.title }}</p>
      <el-input
        v-model="review.comment"
        type="textarea"
        :rows="3"
        maxlength="200"
        show-word-limit
        :placeholder="review.target === 'rejected' ? '请填写驳回原因（必填）' : '审核意见（选填）'"
      />
      <template #footer>
        <el-button @click="review.visible = false">取消</el-button>
        <el-button :type="reviewButtonType" :loading="review.submitting" @click="submitReview">
          确认{{ statusActionLabel(review.target) }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 审核历史抽屉 -->
    <el-drawer v-model="history.visible" :title="`审核历史 — ${history.event?.title || ''}`" size="420px">
      <div v-loading="history.loading">
        <el-timeline v-if="history.items.length">
          <el-timeline-item
            v-for="log in history.items"
            :key="log.id"
            :timestamp="log.created_at"
            :type="timelineType(log.to_status)"
          >
            <div class="history-line">
              <strong>{{ statusLabel(log.from_status) }} → {{ statusLabel(log.to_status) }}</strong>
              <span class="history-actor">操作人：{{ log.admin_user_id || '—' }}</span>
            </div>
            <p v-if="log.review_comment" class="history-comment">{{ log.review_comment }}</p>
          </el-timeline-item>
        </el-timeline>
        <div v-else-if="!history.loading" class="empty-hint">该事件暂无审核记录</div>
      </div>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchAdminEvents, fetchEventReviewLogs, updateEventStatus } from '@/api/admin'

const loading = ref(false)
const events = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 10

const filters = reactive({ status: 'all', keyword: '', risk: '' })

const statusTabs = [
  { value: 'all', label: '全部' },
  { value: 'draft', label: '待审核' },
  { value: 'published', label: '已发布' },
  { value: 'rejected', label: '已驳回' },
  { value: 'archived', label: '已归档' },
]

const STATUS_LABELS = { draft: '待审核', published: '已发布', rejected: '已驳回', archived: '已归档' }
const ACTION_LABELS = { published: '通过', rejected: '驳回', archived: '归档' }

const review = reactive({ visible: false, event: null, target: '', comment: '', submitting: false })
const history = reactive({ visible: false, event: null, items: [], loading: false })

const reviewTitle = computed(() => `${statusActionLabel(review.target)}事件 #${review.event?.raw_id ?? ''}`)
const reviewButtonType = computed(() => {
  if (review.target === 'published') return 'success'
  if (review.target === 'rejected') return 'danger'
  return 'primary'
})

function statusLabel(status) {
  return STATUS_LABELS[status] || status || '—'
}

const SENTIMENT_LABELS = { positive: '正向', negative: '负向', neutral: '中性', controversial: '争议' }

function sentimentLabel(sentiment) {
  return SENTIMENT_LABELS[sentiment] || sentiment || '—'
}

function statusActionLabel(target) {
  return ACTION_LABELS[target] || '更新'
}

function riskClass(level) {
  if (level === 'high') return 'badge-high'
  if (level === 'medium') return 'badge-mid'
  return 'badge-low'
}

function timelineType(status) {
  if (status === 'published') return 'success'
  if (status === 'rejected') return 'danger'
  return 'info'
}

async function reload(nextPage) {
  if (typeof nextPage === 'number') page.value = nextPage
  loading.value = true
  try {
    const data = await fetchAdminEvents({
      status: filters.status,
      keyword: filters.keyword || undefined,
      risk_level: filters.risk || undefined,
      page: page.value,
      page_size: pageSize,
    })
    events.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error(error.message || '加载事件列表失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.risk = ''
  filters.status = 'all'
  reload(1)
}

function openReview(event, target) {
  review.event = event
  review.target = target
  review.comment = ''
  review.visible = true
}

async function submitReview() {
  if (review.target === 'rejected' && !review.comment.trim()) {
    ElMessage.warning('驳回必须填写原因')
    return
  }
  review.submitting = true
  try {
    await updateEventStatus(review.event.raw_id, {
      status: review.target,
      review_comment: review.comment.trim(),
    })
    ElMessage.success(`已${statusActionLabel(review.target)}：${review.event.title}`)
    review.visible = false
    reload()
  } catch (error) {
    ElMessage.error(error.message || '审核操作失败')
  } finally {
    review.submitting = false
  }
}

async function openHistory(event) {
  history.event = event
  history.items = []
  history.visible = true
  history.loading = true
  try {
    const data = await fetchEventReviewLogs(event.raw_id, { page: 1, page_size: 50 })
    history.items = data.items || []
  } catch (error) {
    ElMessage.error(error.message || '加载审核历史失败')
  } finally {
    history.loading = false
  }
}

onMounted(() => reload(1))
</script>

<style scoped>
.title-cell {
  max-width: 320px;
}

.ops-cell .el-button {
  margin-left: 0;
  margin-right: 8px;
}

.review-event-title {
  margin: 0 0 12px;
  font-weight: 600;
}

.history-line {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
}

.history-actor {
  font-size: 12px;
  color: var(--color-text-muted);
}

.history-comment {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--color-text-secondary, #555);
  background: var(--color-bg);
  border-radius: 6px;
  padding: 6px 10px;
}
</style>
