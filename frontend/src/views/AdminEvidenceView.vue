<template>
  <section class="admin-page admin-evidence">
    <!-- 发起采集 -->
    <div class="panel-card">
      <div class="card-head">
        <h3 class="card-title">发起证据采集</h3>
        <span class="card-hint">调用联网检索大模型抓取公开网页证据，耗时较长（通常 30s ~ 2min），请勿重复提交。</span>
      </div>
      <div class="run-form">
        <el-input
          v-model="form.topic"
          class="form-topic"
          maxlength="200"
          placeholder="采集主题，例如：某高校食堂食品安全争议"
        />
        <el-input
          v-model="form.queries"
          type="textarea"
          :rows="3"
          class="form-queries"
          placeholder="检索问题，每行一条（至少一条）"
        />
        <el-select
          v-model="form.providerIds"
          multiple
          collapse-tags
          class="form-providers"
          placeholder="检索模型：默认全部已启用"
        >
          <el-option v-for="p in PROVIDER_IDS" :key="p" :label="PROVIDER_LABELS[p]" :value="p" />
        </el-select>
        <el-button type="primary" :loading="form.submitting" @click="submitRun">
          {{ form.submitting ? '采集中…' : '开始采集' }}
        </el-button>
      </div>
      <p v-if="form.feedback" :class="['run-feedback', `run-feedback--${form.feedbackType}`]">
        {{ form.feedback }}
      </p>
    </div>

    <!-- 采集任务列表 -->
    <div class="panel-card">
      <div class="card-head">
        <h3 class="card-title">采集任务</h3>
        <el-button link type="primary" @click="loadRuns">刷新</el-button>
      </div>
      <div class="table-shell" v-loading="runs.loading">
        <table class="compact-table">
          <thead>
            <tr>
              <th style="width: 56px">ID</th>
              <th style="min-width: 200px">主题</th>
              <th style="width: 90px">状态</th>
              <th style="width: 76px">证据数</th>
              <th style="width: 76px">检索数</th>
              <th style="width: 90px">耗时</th>
              <th style="width: 160px">创建时间</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in runs.items"
              :key="run.id"
              :class="{ 'row-active': run.id === selectedRunId }"
            >
              <td>{{ run.id }}</td>
              <td class="title-cell" :title="run.topic">{{ run.topic }}</td>
              <td><span :class="['status-tag', `run-${run.status}`]">{{ runStatusLabel(run.status) }}</span></td>
              <td>{{ run.item_count ?? 0 }}</td>
              <td>{{ run.query_count ?? 0 }}</td>
              <td>{{ durationLabel(run.duration_ms) }}</td>
              <td>{{ formatTime(run.created_at) }}</td>
              <td class="ops-cell">
                <el-button link type="primary" @click="selectRun(run)">查看证据</el-button>
                <el-button link type="success" @click="openDeliver(run)">交付入库</el-button>
              </td>
            </tr>
            <tr v-if="!runs.items.length && !runs.loading">
              <td colspan="8" class="empty-hint">还没有采集任务，先在上方发起一次采集</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="table-footer">
        <span>共 {{ runs.total }} 条</span>
        <el-pagination
          v-model:current-page="runs.page"
          background
          layout="prev, pager, next"
          :page-size="RUN_PAGE_SIZE"
          :total="runs.total"
          @current-change="loadRuns"
        />
      </div>
    </div>

    <!-- 选中任务的逐条检索详情 -->
    <div v-if="runDetail.run" class="panel-card" v-loading="runDetail.loading">
      <div class="card-head">
        <h3 class="card-title">任务 #{{ runDetail.run.id }} 检索明细</h3>
        <span class="card-hint">{{ runDetail.run.topic }}</span>
      </div>
      <p v-if="runDetail.run.error" class="run-error">任务错误：{{ runDetail.run.error }}</p>
      <table class="compact-table">
        <thead>
          <tr>
            <th style="width: 90px">模型厂商</th>
            <th style="width: 150px">模型</th>
            <th style="width: 90px">状态</th>
            <th style="min-width: 200px">检索问题</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="q in runDetail.queries" :key="q.id">
            <td><span class="provider-badge">{{ PROVIDER_LABELS[q.provider] || q.provider }}</span></td>
            <td>{{ q.model || '—' }}</td>
            <td><span :class="['status-tag', `run-${q.status}`]">{{ runStatusLabel(q.status) }}</span></td>
            <td class="title-cell" :title="q.query_text">{{ q.query_text }}</td>
            <td class="error-cell">{{ q.error || '—' }}</td>
          </tr>
          <tr v-if="!runDetail.queries.length && !runDetail.loading">
            <td colspan="5" class="empty-hint">该任务没有检索记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 证据条目 -->
    <div class="panel-card">
      <div class="card-head">
        <h3 class="card-title">
          证据条目<span v-if="selectedRunId" class="card-hint">（任务 #{{ selectedRunId }}）</span>
        </h3>
        <el-button v-if="selectedRunId" link @click="clearRunFilter">查看全部任务的证据</el-button>
      </div>

      <div class="filter-bar filter-bar--inline">
        <el-select v-model="filters.scope_decision" class="filter-select" @change="loadItems(1)">
          <el-option label="范围判定：全部" value="" />
          <el-option v-for="v in SCOPE_DECISIONS" :key="v" :label="`范围判定：${SCOPE_LABELS[v]}`" :value="v" />
        </el-select>
        <el-select v-model="filters.verification_status" class="filter-select" @change="loadItems(1)">
          <el-option label="核验状态：全部" value="" />
          <el-option v-for="v in VERIFICATION_STATUSES" :key="v" :label="`核验状态：${VERIFICATION_LABELS[v]}`" :value="v" />
        </el-select>
        <el-select v-model="filters.review_status" class="filter-select" @change="loadItems(1)">
          <el-option label="人工审核：全部" value="" />
          <el-option v-for="v in REVIEW_STATUSES" :key="v" :label="`人工审核：${REVIEW_LABELS[v]}`" :value="v" />
        </el-select>
        <el-button @click="resetFilters">重置</el-button>
      </div>

      <p class="gate-hint">
        交付门槛：范围判定 = 校内相关 且 核验状态 = 已核验 且 人工审核 = 已通过，三者同时满足才会写入 raw_posts。
      </p>

      <div class="table-shell" v-loading="items.loading">
        <table class="compact-table">
          <thead>
            <tr>
              <th style="width: 52px">ID</th>
              <th style="width: 140px">来源域名</th>
              <th style="min-width: 220px">标题 / 证据原文</th>
              <th style="width: 110px">检索模型</th>
              <th style="width: 96px">范围判定</th>
              <th style="width: 90px">核验</th>
              <th style="width: 90px">审核</th>
              <th style="min-width: 150px">可交付性</th>
              <th style="width: 190px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items.rows" :key="item.id">
              <td>{{ item.id }}</td>
              <td>
                <el-link :href="item.source_url" target="_blank" type="primary">
                  {{ item.source_domain || '未知来源' }} ↗
                </el-link>
              </td>
              <td class="title-cell">
                <div class="item-title" :title="item.title || ''">{{ item.title || '（无标题）' }}</div>
                <div class="item-quote" :title="item.evidence_quote">{{ item.evidence_quote }}</div>
              </td>
              <td>
                <span class="provider-badge">{{ PROVIDER_LABELS[item.retrieval_provider] || item.retrieval_provider }}</span>
                <div class="model-name">{{ item.retrieval_model || '—' }}</div>
              </td>
              <td>
                <span :class="['scope-chip', `scope-${item.scope_decision}`]">{{ SCOPE_LABELS[item.scope_decision] || item.scope_decision }}</span>
              </td>
              <td><span :class="['status-tag', `verify-${item.verification_status}`]">{{ VERIFICATION_LABELS[item.verification_status] || item.verification_status }}</span></td>
              <td><span :class="['status-tag', `review-${item.review_status}`]">{{ REVIEW_LABELS[item.review_status] || item.review_status }}</span></td>
              <td>
                <span v-if="!blockers(item).length" class="deliverable-ok">可交付</span>
                <ul v-else class="blocker-list">
                  <li v-for="reason in blockers(item)" :key="reason">{{ reason }}</li>
                </ul>
              </td>
              <td class="ops-cell">
                <el-button link type="primary" @click="openVerify(item)">核验</el-button>
                <el-button link type="success" @click="openReview(item, 'approved')">通过</el-button>
                <el-button link type="danger" @click="openReview(item, 'rejected')">驳回</el-button>
                <el-button link @click="openDetail(item)">详情</el-button>
              </td>
            </tr>
            <tr v-if="!items.rows.length && !items.loading">
              <td colspan="9" class="empty-hint">当前筛选条件下没有证据条目</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="table-footer">
        <span>共 {{ items.total }} 条</span>
        <el-pagination
          v-model:current-page="items.page"
          background
          layout="prev, pager, next"
          :page-size="ITEM_PAGE_SIZE"
          :total="items.total"
          @current-change="loadItems"
        />
      </div>
    </div>

    <!-- 人工审核对话框 -->
    <el-dialog v-model="review.visible" :title="`${REVIEW_ACTION_LABELS[review.target] || '审核'}证据 #${review.item?.id ?? ''}`" width="480px">
      <p class="dialog-quote">{{ review.item?.evidence_quote }}</p>
      <el-alert
        v-if="review.target === 'approved' && review.item && blockers(review.item, { ignoreReview: true }).length"
        type="warning"
        :closable="false"
        show-icon
        class="dialog-alert"
        title="该证据尚不满足通过条件"
        :description="blockers(review.item, { ignoreReview: true }).join('；')"
      />
      <el-input
        v-model="review.note"
        type="textarea"
        :rows="3"
        maxlength="200"
        show-word-limit
        :placeholder="review.target === 'rejected' ? '请填写驳回原因（必填）' : '审核意见（选填）'"
      />
      <template #footer>
        <el-button @click="review.visible = false">取消</el-button>
        <el-button
          :type="review.target === 'rejected' ? 'danger' : 'success'"
          :loading="review.submitting"
          @click="submitReview"
        >
          确认{{ REVIEW_ACTION_LABELS[review.target] || '审核' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 核验对话框 -->
    <el-dialog v-model="verify.visible" :title="`核验证据 #${verify.item?.id ?? ''}`" width="480px">
      <p class="dialog-quote">{{ verify.item?.evidence_quote }}</p>
      <el-select v-model="verify.status" class="dialog-select">
        <el-option v-for="v in VERIFICATION_STATUSES" :key="v" :label="VERIFICATION_LABELS[v]" :value="v" />
      </el-select>
      <el-input
        v-model="verify.reason"
        type="textarea"
        :rows="3"
        maxlength="200"
        show-word-limit
        placeholder="核验依据（选填），例如：已在来源页核对原文"
      />
      <p class="dialog-note">核验方式记录为 manual_review（管理员人工核验）。</p>
      <template #footer>
        <el-button @click="verify.visible = false">取消</el-button>
        <el-button type="primary" :loading="verify.submitting" @click="submitVerify">确认核验</el-button>
      </template>
    </el-dialog>

    <!-- 交付确认对话框 -->
    <el-dialog v-model="deliver.visible" :title="`交付任务 #${deliver.run?.id ?? ''} 的证据`" width="500px">
      <p class="deliver-warn">审批通过的证据将写入 raw_posts，进入舆情处理流水线。</p>
      <p class="dialog-note">
        只有「范围判定 = 校内相关 且 核验状态 = 已核验 且 人工审核 = 已通过」的证据会被交付；
        重复交付不会产生重复数据，已存在的记录会被识别为「已存在」。
      </p>
      <template #footer>
        <el-button @click="deliver.visible = false">取消</el-button>
        <el-button type="success" :loading="deliver.submitting" @click="submitDeliver">确认交付</el-button>
      </template>
    </el-dialog>

    <!-- 证据详情 -->
    <el-drawer v-model="detail.visible" :title="`证据 #${detail.item?.id ?? ''}`" size="480px">
      <div v-if="detail.item" class="item-detail">
        <h3 class="detail-title">{{ detail.item.title || '（无标题）' }}</h3>
        <div class="detail-meta">
          <span :class="['scope-chip', `scope-${detail.item.scope_decision}`]">{{ SCOPE_LABELS[detail.item.scope_decision] }}</span>
          <span>核验：{{ VERIFICATION_LABELS[detail.item.verification_status] }}</span>
          <span>审核：{{ REVIEW_LABELS[detail.item.review_status] }}</span>
        </div>
        <div class="detail-meta">
          <span>来源类型：{{ detail.item.source_type || '—' }}</span>
          <span>发布方：{{ detail.item.publisher || '—' }}</span>
          <span>质量分：{{ detail.item.quality_score ?? '—' }}</span>
        </div>
        <div class="detail-meta">
          <span>发布时间：{{ formatTime(detail.item.published_at) }}</span>
          <span>抓取时间：{{ formatTime(detail.item.retrieved_at) }}</span>
        </div>
        <p class="detail-quote">{{ detail.item.evidence_quote }}</p>
        <p v-if="detail.item.scope_reasons" class="dialog-note">范围判定依据：{{ detail.item.scope_reasons }}</p>
        <p v-if="detail.item.review_note" class="dialog-note">
          审核备注（{{ detail.item.reviewed_by || '—' }}）：{{ detail.item.review_note }}
        </p>
        <div class="detail-links">
          <el-link :href="detail.item.source_url" target="_blank" type="primary">原始链接 ↗</el-link>
          <el-link
            v-if="detail.item.canonical_url && detail.item.canonical_url !== detail.item.source_url"
            :href="detail.item.canonical_url"
            target="_blank"
            type="info"
          >规范化链接 ↗</el-link>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createEvidenceRun,
  deliverEvidenceRun,
  fetchEvidenceItems,
  fetchEvidenceRunDetail,
  fetchEvidenceRuns,
  reviewEvidenceItem,
  verifyEvidenceItem,
} from '@/api/evidence'

const RUN_PAGE_SIZE = 10
const ITEM_PAGE_SIZE = 10

// 与 backend/services/evidence/config.py::SUPPORTED_PROVIDER_IDS 保持一致
const PROVIDER_IDS = ['deepseek', 'glm', 'kimi', 'doubao', 'qwen']
const PROVIDER_LABELS = {
  deepseek: 'DeepSeek',
  glm: '智谱 GLM',
  kimi: 'Kimi',
  doubao: '豆包',
  qwen: '通义千问',
}

// 与 backend/services/evidence/schemas.py 的状态枚举保持一致
const SCOPE_DECISIONS = ['in_scope', 'needs_review', 'out_of_scope']
const VERIFICATION_STATUSES = ['pending', 'verified', 'rejected', 'needs_review', 'failed']
const REVIEW_STATUSES = ['pending', 'approved', 'rejected', 'needs_review']

const SCOPE_LABELS = { in_scope: '校内相关', needs_review: '待人工判定', out_of_scope: '范围之外' }
const VERIFICATION_LABELS = {
  pending: '未核验',
  verified: '已核验',
  rejected: '核验驳回',
  needs_review: '需复核',
  failed: '核验失败',
}
const REVIEW_LABELS = { pending: '待审核', approved: '已通过', rejected: '已驳回', needs_review: '需复核' }
const REVIEW_ACTION_LABELS = { approved: '通过', rejected: '驳回' }
const RUN_STATUS_LABELS = {
  pending: '排队中',
  running: '采集中',
  completed: '已完成',
  partial: '部分成功',
  failed: '失败',
  cancelled: '已取消',
}

const form = reactive({
  topic: '',
  queries: '',
  providerIds: [],
  submitting: false,
  feedback: '',
  feedbackType: 'info',
})

const runs = reactive({ items: [], total: 0, page: 1, loading: false })
const runDetail = reactive({ run: null, queries: [], loading: false })
const items = reactive({ rows: [], total: 0, page: 1, loading: false })
const filters = reactive({ scope_decision: '', verification_status: '', review_status: '' })
const selectedRunId = ref(null)

const review = reactive({ visible: false, item: null, target: '', note: '', submitting: false })
const verify = reactive({ visible: false, item: null, status: 'verified', reason: '', submitting: false })
const deliver = reactive({ visible: false, run: null, submitting: false })
const detail = reactive({ visible: false, item: null })

function runStatusLabel(status) {
  return RUN_STATUS_LABELS[status] || status || '—'
}

function durationLabel(ms) {
  if (ms === null || ms === undefined) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function formatTime(value) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 19)
}

// 交付门槛：in_scope + verified + approved，三者缺一不可。
// 这里返回"为什么不可交付"，而不是静默禁用按钮。
function blockers(item, { ignoreReview = false } = {}) {
  const reasons = []
  if (item.scope_decision !== 'in_scope') {
    reasons.push(`范围判定为「${SCOPE_LABELS[item.scope_decision] || item.scope_decision}」`)
  }
  if (item.verification_status !== 'verified') {
    reasons.push(`核验状态为「${VERIFICATION_LABELS[item.verification_status] || item.verification_status}」`)
  }
  if (!ignoreReview && item.review_status !== 'approved') {
    reasons.push(`人工审核为「${REVIEW_LABELS[item.review_status] || item.review_status}」`)
  }
  return reasons
}

async function submitRun() {
  const topic = form.topic.trim()
  const queries = form.queries
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!topic) {
    ElMessage.warning('请填写采集主题')
    return
  }
  if (!queries.length) {
    ElMessage.warning('请至少填写一条检索问题')
    return
  }
  if (form.submitting) return

  form.submitting = true
  form.feedback = '正在并发调用联网检索模型，请勿关闭页面…'
  form.feedbackType = 'info'
  try {
    const run = await createEvidenceRun({
      topic,
      queries,
      provider_ids: form.providerIds.length ? form.providerIds : undefined,
    })
    form.feedback = `任务 #${run.id} ${runStatusLabel(run.status)}：抓到 ${run.item_count ?? 0} 条证据${run.error ? `（${run.error}）` : ''}`
    form.feedbackType = run.status === 'failed' ? 'error' : 'success'
    form.queries = ''
    await loadRuns(1)
    await selectRun(run)
  } catch (error) {
    form.feedback = error.message || '采集失败'
    form.feedbackType = 'error'
    ElMessage.error(form.feedback)
  } finally {
    form.submitting = false
  }
}

async function loadRuns(nextPage) {
  if (typeof nextPage === 'number') runs.page = nextPage
  runs.loading = true
  try {
    const data = await fetchEvidenceRuns({ page: runs.page, page_size: RUN_PAGE_SIZE })
    runs.items = data.items || []
    runs.total = data.total || 0
  } catch (error) {
    ElMessage.error(error.message || '加载采集任务失败')
  } finally {
    runs.loading = false
  }
}

async function selectRun(run) {
  selectedRunId.value = run.id
  runDetail.run = run
  runDetail.queries = []
  runDetail.loading = true
  try {
    const data = await fetchEvidenceRunDetail(run.id)
    runDetail.run = data
    runDetail.queries = data.queries || []
  } catch (error) {
    ElMessage.error(error.message || '加载任务详情失败')
  } finally {
    runDetail.loading = false
  }
  await loadItems(1)
}

function clearRunFilter() {
  selectedRunId.value = null
  runDetail.run = null
  runDetail.queries = []
  loadItems(1)
}

async function loadItems(nextPage) {
  if (typeof nextPage === 'number') items.page = nextPage
  items.loading = true
  try {
    const data = await fetchEvidenceItems({
      run_id: selectedRunId.value ?? undefined,
      scope_decision: filters.scope_decision || undefined,
      verification_status: filters.verification_status || undefined,
      review_status: filters.review_status || undefined,
      page: items.page,
      page_size: ITEM_PAGE_SIZE,
    })
    items.rows = data.items || []
    items.total = data.total || 0
  } catch (error) {
    ElMessage.error(error.message || '加载证据条目失败')
  } finally {
    items.loading = false
  }
}

function resetFilters() {
  filters.scope_decision = ''
  filters.verification_status = ''
  filters.review_status = ''
  loadItems(1)
}

// 局部替换单条，避免整页刷新丢失筛选与滚动位置
function replaceItem(updated) {
  const index = items.rows.findIndex((row) => row.id === updated.id)
  if (index !== -1) items.rows.splice(index, 1, updated)
  if (detail.item?.id === updated.id) detail.item = updated
}

function openReview(item, target) {
  review.item = item
  review.target = target
  review.note = ''
  review.visible = true
}

async function submitReview() {
  if (review.target === 'rejected' && !review.note.trim()) {
    ElMessage.warning('驳回必须填写原因')
    return
  }
  review.submitting = true
  try {
    const updated = await reviewEvidenceItem(review.item.id, {
      status: review.target,
      note: review.note.trim() || null,
    })
    replaceItem(updated)
    ElMessage.success(`已${REVIEW_ACTION_LABELS[review.target]}证据 #${updated.id}`)
    review.visible = false
  } catch (error) {
    ElMessage.error(error.message || '审核操作失败')
  } finally {
    review.submitting = false
  }
}

function openVerify(item) {
  verify.item = item
  verify.status = 'verified'
  verify.reason = ''
  verify.visible = true
}

async function submitVerify() {
  verify.submitting = true
  try {
    const reason = verify.reason.trim()
    const updated = await verifyEvidenceItem(verify.item.id, {
      method: 'manual_review',
      status: verify.status,
      reasons: reason ? [reason] : undefined,
    })
    replaceItem(updated)
    ElMessage.success(`证据 #${updated.id} 核验状态已更新为「${VERIFICATION_LABELS[updated.verification_status]}」`)
    verify.visible = false
  } catch (error) {
    ElMessage.error(error.message || '核验失败')
  } finally {
    verify.submitting = false
  }
}

function openDeliver(run) {
  deliver.run = run
  deliver.visible = true
}

async function submitDeliver() {
  deliver.submitting = true
  try {
    const result = await deliverEvidenceRun(deliver.run.id)
    ElMessage.success(
      `交付完成：新建 ${result.created} 条，已存在 ${result.existing} 条，合计 ${result.delivered} 条写入 raw_posts`,
    )
    deliver.visible = false
    await loadRuns()
  } catch (error) {
    ElMessage.error(error.message || '交付失败')
  } finally {
    deliver.submitting = false
  }
}

function openDetail(item) {
  detail.item = item
  detail.visible = true
}

onMounted(async () => {
  await loadRuns(1)
  await loadItems(1)
})
</script>

<style scoped>
.card-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 12px;
}

.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.card-hint {
  font-size: 12px;
  color: var(--color-text-faint);
}

.card-head .el-button {
  margin-left: auto;
}

.run-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-start;
}

.form-topic {
  width: 280px;
}

.form-queries {
  flex: 1;
  min-width: 280px;
}

.form-providers {
  width: 220px;
}

.run-feedback {
  margin: 12px 0 0;
  font-size: 13px;
}

.run-feedback--info { color: var(--color-text-muted); }
.run-feedback--success { color: var(--color-success-text, #2f7a45); }
.run-feedback--error { color: #b91c1c; }

.run-error {
  margin: 0 0 12px;
  font-size: 12px;
  color: #b91c1c;
}

.filter-bar--inline {
  padding: 0;
  margin-bottom: 10px;
  background: transparent;
  box-shadow: none;
}

.gate-hint {
  margin: 0 0 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-faint);
}

.row-active {
  background: var(--brand-50);
}

.title-cell {
  max-width: 340px;
}

.item-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-quote {
  margin-top: 2px;
  font-size: 12px;
  color: var(--color-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.error-cell {
  font-size: 12px;
  color: #b91c1c;
}

.provider-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--brand-50);
  color: var(--brand-700);
}

.model-name {
  margin-top: 2px;
  font-size: 11px;
  color: var(--color-text-faint);
}

.scope-chip {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
}

.scope-in_scope { background: #ecfdf5; color: #047857; }
.scope-needs_review { background: #fffbeb; color: #b45309; }
.scope-out_of_scope { background: #f3f4f6; color: #6b7280; }

.verify-verified,
.review-approved { color: #047857; }

.verify-rejected,
.verify-failed,
.review-rejected { color: #b91c1c; }

.verify-needs_review,
.review-needs_review { color: #b45309; }

.deliverable-ok {
  font-size: 12px;
  font-weight: 600;
  color: #047857;
}

.blocker-list {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.ops-cell .el-button {
  margin-left: 0;
  margin-right: 8px;
}

.dialog-quote {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.7;
  background: var(--color-bg);
  border-radius: var(--radius);
  padding: 10px 12px;
  max-height: 140px;
  overflow-y: auto;
}

.dialog-alert {
  margin-bottom: 12px;
}

.dialog-select {
  width: 100%;
  margin-bottom: 12px;
}

.dialog-note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-faint);
}

.deliver-warn {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.item-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-title {
  margin: 0;
  font-size: 16px;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  align-items: center;
  font-size: 12px;
  color: var(--color-text-muted);
}

.detail-quote {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  background: var(--color-bg);
  border-radius: var(--radius);
  padding: 12px 14px;
}

.detail-links {
  display: flex;
  gap: 14px;
}
</style>
