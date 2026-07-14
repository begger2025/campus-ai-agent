<template>
  <section class="admin-page admin-raw-posts">
    <div class="panel-card filter-bar">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索标题、正文、关键词、作者"
        class="filter-search"
        @keyup.enter="reload(1)"
      />
      <el-select v-model="filters.platform" class="filter-select" @change="reload(1)">
        <el-option label="平台：全部" value="" />
        <el-option label="平台：小红书" value="xhs" />
        <el-option label="平台：微博" value="weibo" />
        <el-option label="平台：贴吧" value="tieba" />
        <el-option label="平台：知乎" value="zhihu" />
        <el-option label="平台：快手" value="ks" />
        <el-option label="平台：网页证据" value="web" />
      </el-select>
      <el-date-picker
        v-model="filters.dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        class="filter-date"
        @change="reload(1)"
      />
      <!-- 数据质量管控：剔除的帖子不进舆情分析页/事件聚类/agent 检索。
           「已剔除」页签让管理员能复核自己剔了什么（也才谈得上恢复）。 -->
      <el-select v-model="filters.excluded" class="filter-select" @change="reload(1)">
        <el-option label="状态：全部" value="" />
        <el-option label="状态：生效中" value="false" />
        <el-option label="状态：已剔除" value="true" />
      </el-select>
      <el-button type="primary" @click="reload(1)">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <div class="panel-card">
      <div class="table-shell" v-loading="loading">
        <table class="compact-table">
          <thead>
            <tr>
              <th style="width: 56px">ID</th>
              <th style="width: 76px">平台</th>
              <th style="min-width: 260px">标题 / 内容</th>
              <th>采集关键词</th>
              <th>作者</th>
              <th>互动</th>
              <th style="width: 150px">发布时间</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="post in posts" :key="post.id" :class="{ 'row-excluded': post.excluded }">
              <td>{{ post.id }}</td>
              <td><span :class="['source-pill', `source-${post.platform}`]">{{ platformLabel(post.platform) }}</span></td>
              <td class="title-cell" :title="post.excluded ? `已剔除：${post.excluded_reason}` : (post.title || post.content)">
                <span :class="{ 'title-struck': post.excluded }">{{ post.title || post.content || '—' }}</span>
                <span v-if="post.excluded" class="excluded-tag" :title="post.excluded_reason">已剔除</span>
              </td>
              <td>{{ post.source_keyword || '—' }}</td>
              <td>{{ post.author || '—' }}</td>
              <td class="metrics-cell">赞 {{ post.like_count ?? 0 }} · 评 {{ post.comment_count ?? 0 }}</td>
              <td>{{ post.publish_time || '—' }}</td>
              <td>
                <el-button link type="primary" @click="openDetail(post)">详情</el-button>
                <el-button
                  v-if="!post.excluded"
                  link
                  type="danger"
                  :disabled="!post.processed_post_id"
                  :title="post.processed_post_id ? '' : '该帖尚未进入清洗流水线，下游还没有它'"
                  @click="openExclude(post)"
                >剔除</el-button>
                <el-button v-else link type="success" @click="restore(post)">恢复</el-button>
              </td>
            </tr>
            <tr v-if="!posts.length && !loading">
              <td colspan="8" class="empty-hint">当前筛选条件下没有帖子</td>
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

    <el-drawer v-model="detail.visible" :title="`帖子 #${detail.post?.id ?? ''}`" size="480px">
      <div v-if="detail.post" class="post-detail">
        <h3 class="post-title">{{ detail.post.title || '（无标题）' }}</h3>
        <div class="post-meta">
          <span :class="['source-pill', `source-${detail.post.platform}`]">{{ platformLabel(detail.post.platform) }}</span>
          <span>作者：{{ detail.post.author || '—' }}</span>
          <span>发布：{{ detail.post.publish_time || '—' }}</span>
        </div>
        <div class="post-metrics">
          <span>点赞 {{ detail.post.like_count ?? 0 }}</span>
          <span>收藏 {{ detail.post.collect_count ?? 0 }}</span>
          <span>评论 {{ detail.post.comment_count ?? 0 }}</span>
          <span>分享 {{ detail.post.share_count ?? 0 }}</span>
        </div>
        <p class="post-content">{{ detail.post.content || '（无正文）' }}</p>
        <div class="post-links">
          <el-link
            v-if="detailSearchUrl"
            :href="detailSearchUrl"
            target="_blank"
            type="primary"
          >
            去{{ platformLabelText }}搜索该帖 ↗
          </el-link>
          <el-tooltip v-if="detail.post.url" :content="LINK_EXPIRY_TIP" placement="top" :show-after="150">
            <el-link :href="detail.post.url" target="_blank" type="info">
              原帖直链（可能已失效）
            </el-link>
          </el-tooltip>
          <span class="post-external">external_id: {{ detail.post.external_id || '—' }}</span>
        </div>
        <p class="post-link-note">原帖直链依赖采集时的访问凭证（xsec_token），会随时间自然过期；站内搜索入口长期有效。</p>
      </div>
    </el-drawer>

    <!-- 剔除确认：**理由必填**。一个说不出理由的剔除只是一次任性，
         而它会静默地改变 AI 的结论（那条帖子不再进聚类、不再被检索到）。 -->
    <el-dialog v-model="exclude.visible" title="剔除这条帖子" width="480px">
      <p class="exclude-title">{{ exclude.post?.title || exclude.post?.content }}</p>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="剔除后它不再进入舆情分析页、事件聚类和舆情助手的检索。数据保留，可随时恢复。"
        style="margin-bottom: 12px"
      />
      <el-input
        v-model="exclude.reason"
        type="textarea"
        :rows="2"
        maxlength="200"
        show-word-limit
        placeholder="剔除理由（必填，如：同名的台湾国立中山大学，与本校无关 / 蹭校名的商业广告）"
      />
      <template #footer>
        <el-button @click="exclude.visible = false">取消</el-button>
        <el-button type="danger" :loading="exclude.submitting" @click="submitExclude">确认剔除</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { excludeProcessedPost, fetchRawPosts } from '@/api/admin'
import { LINK_EXPIRY_TIP, platformSearchUrl } from '@/utils/postLink'

const route = useRoute()

const loading = ref(false)
const posts = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15

const filters = reactive({ keyword: '', platform: '', dateRange: null, excluded: '' })
const detail = reactive({ visible: false, post: null })

// —— 数据质量管控：剔除无关帖 ——
//
// 这一页的动词是**质量管控**，不是审核。帖子是从公开平台爬来的客观事实，审核别人已经
// 公开发布的话语义上说不通；需要人工定夺的是 **AI 的主张**（事件的聚类和研判），
// 那道闸门在事件审核页。这里要做的是：发现噪声（同名的台湾国立中山大学、蹭校名的地产
// 广告、早期乱填关键词爬回的 Python 教程帖），剔掉它。
//
// 剔除会切断**所有**下游：舆情分析页、事件聚类、舆情助手的检索。软删除，可恢复。
const exclude = reactive({ visible: false, post: null, reason: '', submitting: false })

function openExclude(post) {
  exclude.post = post
  exclude.reason = ''
  exclude.visible = true
}

async function submitExclude() {
  const reason = exclude.reason.trim()
  if (!reason) {
    // 理由必填：一个说不出理由的剔除只是一次任性，而它会静默地改变 AI 的结论。
    ElMessage.warning('请填写剔除理由')
    return
  }
  exclude.submitting = true
  try {
    await excludeProcessedPost(exclude.post.processed_post_id, { excluded: true, reason })
    ElMessage.success('已剔除：该帖不再进入舆情分析、事件聚类和舆情助手检索')
    exclude.visible = false
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '剔除失败')
  } finally {
    exclude.submitting = false
  }
}

async function restore(post) {
  try {
    await excludeProcessedPost(post.processed_post_id, { excluded: false })
    ElMessage.success('已恢复：该帖重新进入下游')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '恢复失败')
  }
}

const PLATFORM_LABELS = { xhs: '小红书', weibo: '微博', tieba: '贴吧', zhihu: '知乎', ks: '快手', web: '网页证据' }

function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || '—'
}

// 直链凭证可能过期，提供平台站内搜索备用入口
const detailSearchUrl = computed(() => {
  const post = detail.post
  if (!post) return ''
  return platformSearchUrl(post.platform, post.title || post.content)
})

const platformLabelText = computed(() => platformLabel(detail.post?.platform))

async function reload(nextPage) {
  if (typeof nextPage === 'number') page.value = nextPage
  loading.value = true
  try {
    const [start, end] = filters.dateRange || []
    const data = await fetchRawPosts({
      keyword: filters.keyword || undefined,
      platform: filters.platform || undefined,
      excluded: filters.excluded || undefined,
      start_date: start || undefined,
      end_date: end || undefined,
      page: page.value,
      page_size: pageSize,
    })
    posts.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error(error.message || '加载帖子失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.platform = ''
  filters.dateRange = null
  filters.excluded = ''
  reload(1)
}

function openDetail(post) {
  detail.post = post
  detail.visible = true
}

// 事件审核的「站内溯源」会带着帖子标题跳过来（?keyword=…）——预填搜索框并直接查，
// 审核员才能一步看到这条代表帖的原始采集记录（采集关键词、互动量、原始链接）。
onMounted(() => {
  const keyword = String(route.query.keyword || '').trim()
  if (keyword) filters.keyword = keyword
  reload(1)
})
</script>

<style scoped>
/* —— 已剔除的行：看得出来，但不刺眼（它还在，只是不进下游了） —— */
.row-excluded { background: var(--color-surface-2); }
.title-struck { text-decoration: line-through; color: var(--color-text-muted); }

.excluded-tag {
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--color-danger-bg);
  color: var(--color-danger-text);
  font-size: 11px;
  font-weight: 600;
  cursor: help;
}

.exclude-title {
  margin: 0 0 12px;
  font-weight: 600;
  line-height: 1.6;
}

.filter-date {
  width: 260px;
}

.title-cell {
  max-width: 360px;
}

.metrics-cell {
  font-size: 12px;
  color: var(--color-text-muted);
}

.source-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  /* 未知平台兜底：中性灰，平台专属类覆盖 */
  background: var(--color-surface-2, #f5f7fa);
  color: var(--color-text-secondary);
}

.source-xhs { background: #fff1f2; color: #be123c; }
.source-weibo { background: #fff7ed; color: #c2410c; }
.source-tieba { background: #eff6ff; color: #1d4ed8; }
.source-zhihu { background: #f0f9ff; color: #0369a1; }
.source-ks { background: #fefce8; color: #a16207; }
.source-web { background: #ecfdf5; color: #047857; }

.post-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.post-title {
  margin: 0;
  font-size: 16px;
}

.post-meta,
.post-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 12px;
  color: var(--color-text-muted);
  align-items: center;
}

.post-content {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  background: var(--color-bg);
  border-radius: var(--radius);
  padding: 12px 14px;
}

.post-links {
  display: flex;
  align-items: center;
  gap: 14px;
}

.post-external {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-muted);
}

.post-link-note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-faint);
}
</style>
