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
            <!-- 行可点 -> 打开详情抽屉。审核员此前**只能看着标题盲审**：后端的
                 /admin/events/{id} 早就返回完整的 AI 研判和代表帖，前端从来没接线。
                 「AI 提议、人来定夺」——人看不到内容，这个闸门就是橡皮图章。 -->
            <tr
              v-for="event in events"
              :key="event.raw_id"
              class="clickable-row"
              @click="openDetail(event)"
            >
              <td>{{ event.raw_id }}</td>
              <td class="title-cell" :title="event.title">{{ event.title }}</td>
              <td><span :class="['badge', riskClass(event.riskLevel)]">{{ event.riskLabel || '低风险' }}</span></td>
              <td>{{ sentimentLabel(event.sentiment) }}</td>
              <td>{{ Math.round(event.heatScore || 0) }}</td>
              <td>{{ event.source_count ?? '—' }}</td>
              <td><span :class="['status-tag', `status-${event.status}`]">{{ statusLabel(event.status) }}</span></td>
              <td>{{ event.updatedAt || '—' }}</td>
              <td class="ops-cell" @click.stop>
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

    <!-- 事件详情抽屉：审核员定夺前要看的一切 -->
    <el-drawer v-model="detail.visible" size="640px" :title="`事件详情 — ${detail.event?.title || ''}`">
      <div v-loading="detail.loading" class="detail-body">
        <template v-if="detail.data">
          <div class="detail-head">
            <span :class="['badge', riskClass(detailRisk)]">{{ riskLabel(detailRisk) }}</span>
            <span :class="['status-tag', `status-${detail.data.status}`]">{{ statusLabel(detail.data.status) }}</span>
            <span class="detail-meta">
              {{ detail.data.source_count ?? 0 }} 条来源 · 热度 {{ Math.round(detail.data.heatScore || 0) }}
              <template v-if="detail.data.age_days != null"> · {{ formatAge(detail.data.age_days) }}</template>
            </span>
          </div>

          <p v-if="detail.data.summary" class="detail-summary">{{ detail.data.summary }}</p>

          <!-- 「凭什么这么判」：AI 的研判摆出来，审核员才有得核 -->
          <section v-if="detail.data.priority_breakdown" class="detail-block">
            <h4>展示优先级</h4>
            <p class="axis-line">
              <b>{{ (detail.data.priority_score ?? 0).toFixed(2) }}</b>
              = 严重性 {{ detail.data.priority_breakdown.severity }}
              × 时效 {{ detail.data.priority_breakdown.recency.toFixed(3) }}
              × 状态 {{ detail.data.priority_breakdown.lifecycle }}
            </p>
          </section>

          <section v-if="detailRiskReasons.length" class="detail-block">
            <h4>风险依据 <em>LLM 研判</em></h4>
            <ol class="detail-list">
              <li v-for="(reason, i) in detailRiskReasons" :key="i">{{ reason }}</li>
            </ol>
          </section>

          <section v-if="detail.data.lifecycle_reason" class="detail-block">
            <h4>事件状态 <em>{{ lifecycleLabel(detail.data.lifecycle) }}</em></h4>
            <p class="detail-text">{{ detail.data.lifecycle_reason }}</p>
          </section>

          <section v-if="detailConcerns.length" class="detail-block">
            <h4>关注点 <em>LLM 从成员帖提炼</em></h4>
            <div class="concern-tags">
              <span v-for="c in detailConcerns" :key="c" class="concern-tag">{{ c }}</span>
            </div>
          </section>

          <!-- 代表帖：**这是审核员真正要看的东西**。原帖可点，也可回站内数据管理页溯源。 -->
          <section class="detail-block">
            <h4>
              代表帖
              <em>{{ detailPosts.length }} 条 · 审核请核对内容是否与标题相符</em>
            </h4>
            <div v-if="!detailPosts.length" class="empty-hint">该事件没有关联的代表帖</div>
            <article v-for="post in detailPosts" :key="post.processed_post_id || post.raw_post_id" class="post-card">
              <div class="post-top">
                <span class="post-plat">{{ platformLabel(post.platform) }}</span>
                <span class="post-author">{{ post.author || '匿名' }}</span>
                <span class="post-time">{{ (post.publish_time || '').slice(0, 16).replace('T', ' ') }}</span>
                <span class="post-counts">
                  赞 {{ post.like_count ?? 0 }} · 评 {{ post.comment_count ?? 0 }}
                </span>
              </div>
              <div class="post-title">{{ post.title || '（无标题）' }}</div>
              <p v-if="post.content" class="post-content">{{ post.content }}</p>
              <div class="post-links">
                <a v-if="isSafeUrl(post.url)" :href="post.url" target="_blank" rel="noopener">查看原帖 →</a>
                <a v-else-if="isSafeUrl(post.raw_url)" :href="post.raw_url" target="_blank" rel="noopener">查看原帖 →</a>
                <span v-else class="post-nolink">原帖链接缺失</span>
                <button type="button" class="post-search" @click="searchInSite(post)">站内溯源 →</button>
              </div>
            </article>
          </section>
        </template>
      </div>

      <!-- 看完就能定夺：不用关掉抽屉再去点行尾的按钮 -->
      <template #footer>
        <div class="detail-footer">
          <el-button @click="detail.visible = false">关闭</el-button>
          <el-button
            v-if="detail.event && detail.event.status !== 'archived'"
            @click="reviewFromDetail('archived')"
          >归档</el-button>
          <el-button
            v-if="detail.event && detail.event.status !== 'rejected'"
            type="danger"
            @click="reviewFromDetail('rejected')"
          >驳回</el-button>
          <el-button
            v-if="detail.event && detail.event.status !== 'published'"
            type="success"
            @click="reviewFromDetail('published')"
          >通过并发布</el-button>
        </div>
      </template>
    </el-drawer>

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
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  fetchAdminEventDetail,
  fetchAdminEvents,
  fetchEventReviewLogs,
  updateEventStatus,
} from '@/api/admin'
import { formatAge } from '@/utils/age'
import { hasLifecycle, lifecycleLabel } from '@/utils/lifecycle'

const router = useRouter()
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

// —— 事件详情：审核员定夺前要看的一切 ——
//
// 后端 /admin/events/{id} 早就返回完整的 AI 研判（风险依据、关注点、四轴、生命周期理由）
// 和代表帖（标题/正文/作者/互动量/原帖链接），前端 fetchAdminEventDetail 也早就写好了——
// **就是没接线**。审核员只能看着标题盲审：105 条待审里全是「中大考研咨询」「校园风光展示」
// 这类该驳回的噪声，而他没有任何办法核对内容。
//
// 「AI 提议，人来定夺」是这个项目的核心闸门。人看不到内容，闸门就是橡皮图章。
const detail = reactive({ visible: false, event: null, data: null, loading: false })

const detailRisk = computed(() => detail.data?.riskLevel ?? detail.data?.risk_level ?? 'low')
const detailRiskReasons = computed(() => detail.data?.risk_reasons || [])
const detailConcerns = computed(() => detail.data?.concerns || [])
const detailPosts = computed(() => detail.data?.representative_posts || [])

async function openDetail(event) {
  detail.event = event
  detail.data = null
  detail.visible = true
  detail.loading = true
  const wanted = event.raw_id
  try {
    const data = await fetchAdminEventDetail(event.raw_id)
    // 用户可能在请求飞行途中点了别的事件——晚到的响应不许覆盖当前打开的那个
    if (detail.event?.raw_id === wanted) detail.data = data
  } catch (error) {
    ElMessage.error(error.message || '事件详情加载失败')
  } finally {
    if (detail.event?.raw_id === wanted) detail.loading = false
  }
}

// 看完直接定夺：关掉详情、开审核对话框（驳回仍然要求填原因）
function reviewFromDetail(target) {
  const event = detail.event
  detail.visible = false
  openReview(event, target)
}

// 站内溯源：带着标题跳数据管理页，管理员能看到这条帖子的原始采集记录
function searchInSite(post) {
  const keyword = String(post.title || '').slice(0, 12)
  router.push({ path: '/admin/raw-posts', query: { keyword } })
}

function isSafeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//.test(url)
}

const PLATFORM_LABELS = {
  xhs: '小红书', ks: '快手', zhihu: '知乎', weibo: '微博', tieba: '贴吧', web: '网页',
}

function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || '—'
}

function riskLabel(level) {
  if (level === 'high') return '高风险'
  if (level === 'medium') return '中风险'
  return '低风险'
}

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

/* —— 事件详情抽屉：审核员定夺前要看的一切 —— */
.clickable-row { cursor: pointer; }
.clickable-row:hover { background: var(--color-surface-2); }

.detail-body { font-size: 13px; }

.detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.detail-meta { font-size: 12px; color: var(--color-text-muted); }

.detail-summary {
  margin: 0 0 14px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.detail-block { margin-bottom: 16px; }

.detail-block h4 {
  margin: 0 0 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.detail-block h4 em {
  margin-left: 6px;
  font-style: normal;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted);
}

.axis-line {
  margin: 0;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
  font-size: 12px;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.axis-line b { color: var(--brand-700); font-size: 13px; }

.detail-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.75;
  color: var(--color-text-secondary);
}

.detail-list li::marker { color: var(--brand-500); }
.detail-text { margin: 0; line-height: 1.7; color: var(--color-text-secondary); }

.concern-tags { display: flex; flex-wrap: wrap; gap: 6px; }

.concern-tag {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--brand-50);
  color: var(--brand-700);
  border: 1px solid var(--brand-100);
  font-size: 12px;
}

/* 代表帖：审核员真正要核的东西 */
.post-card {
  padding: 10px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
}

.post-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 5px;
  font-size: 11.5px;
  color: var(--color-text-muted);
}

.post-plat {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border-light);
  font-weight: 600;
}

.post-counts { margin-left: auto; font-variant-numeric: tabular-nums; }

.post-title { font-size: 13px; font-weight: 600; line-height: 1.5; color: var(--color-text); }

.post-content {
  margin: 5px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 128px;
  overflow-y: auto;
}

.post-links {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 7px;
  font-size: 12px;
}

.post-links a { color: var(--brand-600); text-decoration: none; }
.post-links a:hover { text-decoration: underline; }
.post-nolink { color: var(--color-text-faint); }

.post-search {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--brand-600);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.post-search:hover { text-decoration: underline; }

.detail-footer { display: flex; justify-content: flex-end; gap: 8px; }

.empty-hint { padding: 14px 0; text-align: center; font-size: 12px; color: var(--color-text-muted); }
</style>
