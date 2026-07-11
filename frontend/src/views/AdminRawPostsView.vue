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
              <th style="width: 76px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="post in posts" :key="post.id">
              <td>{{ post.id }}</td>
              <td><span :class="['source-pill', `source-${post.platform}`]">{{ platformLabel(post.platform) }}</span></td>
              <td class="title-cell" :title="post.title || post.content">{{ post.title || post.content || '—' }}</td>
              <td>{{ post.source_keyword || '—' }}</td>
              <td>{{ post.author || '—' }}</td>
              <td class="metrics-cell">赞 {{ post.like_count ?? 0 }} · 评 {{ post.comment_count ?? 0 }}</td>
              <td>{{ post.publish_time || '—' }}</td>
              <td>
                <el-button link type="primary" @click="openDetail(post)">详情</el-button>
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
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchRawPosts } from '@/api/admin'
import { LINK_EXPIRY_TIP, platformSearchUrl } from '@/utils/postLink'

const loading = ref(false)
const posts = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15

const filters = reactive({ keyword: '', platform: '', dateRange: null })
const detail = reactive({ visible: false, post: null })

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
  reload(1)
}

function openDetail(post) {
  detail.post = post
  detail.visible = true
}

onMounted(() => reload(1))
</script>

<style scoped>
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
  background: var(--brand-50);
  color: var(--brand-700);
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
