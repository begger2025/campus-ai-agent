<template>
  <section class="admin-page">
    <div class="page-header">
      <h2>原始采集数据</h2>
      <el-button size="small" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar panel-card">
      <el-select v-model="filters.platform" class="filter-select" @change="loadData">
        <el-option label="全部平台" value="" />
        <el-option label="微博" value="weibo" />
        <el-option label="微信" value="wechat" />
        <el-option label="贴吧" value="tieba" />
        <el-option label="知乎" value="zhihu" />
        <el-option label="小红书" value="xiaohongshu" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        size="default"
        style="width:240px"
        @change="loadData"
      />
      <el-input
        v-model="filters.keyword"
        placeholder="搜索内容关键词"
        clearable
        class="filter-input"
        @keyup.enter="loadData"
      />
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
            <th>平台</th>
            <th>内容摘要</th>
            <th>作者</th>
            <th>情感倾向</th>
            <th>采集时间</th>
            <th>来源链接</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!loading && !items.length">
            <td colspan="7" class="empty-cell">暂无数据</td>
          </tr>
          <tr v-for="item in items" :key="item.id">
            <td class="id-cell">{{ item.id }}</td>
            <td>
              <span :class="['platform-tag', `platform-${item.platform}`]">
                {{ platformLabel(item.platform) }}
              </span>
            </td>
            <td class="content-cell" :title="item.content">
              {{ truncate(item.content, 60) }}
            </td>
            <td class="author-cell">{{ item.author ?? '—' }}</td>
            <td>
              <span v-if="item.sentiment" :class="['sentiment-tag', `sentiment-${item.sentiment}`]">
                {{ sentimentLabel(item.sentiment) }}
              </span>
              <span v-else class="text-muted">—</span>
            </td>
            <td class="time-cell">{{ formatTime(item.crawled_at ?? item.created_at) }}</td>
            <td>
              <a v-if="item.url" :href="item.url" target="_blank" class="source-link">查看</a>
              <span v-else class="text-muted">—</span>
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

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" title="原始数据详情" size="480px" direction="rtl">
      <div v-if="selectedItem" class="detail-body">
        <div class="detail-row">
          <span class="detail-label">平台</span>
          <span>{{ platformLabel(selectedItem.platform) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">作者</span>
          <span>{{ selectedItem.author ?? '—' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">情感倾向</span>
          <span>{{ sentimentLabel(selectedItem.sentiment) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">采集时间</span>
          <span>{{ formatTime(selectedItem.crawled_at ?? selectedItem.created_at) }}</span>
        </div>
        <div class="detail-row align-start">
          <span class="detail-label">内容</span>
          <p class="detail-content">{{ selectedItem.content }}</p>
        </div>
        <div class="detail-row" v-if="selectedItem.url">
          <span class="detail-label">来源链接</span>
          <a :href="selectedItem.url" target="_blank" class="source-link">{{ selectedItem.url }}</a>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchAdminRawPosts } from '@/api/admin'

const route = useRoute()

const loading = ref(false)
const error = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dateRange = ref(null)

const filters = reactive({
  platform: route.query.platform || '',
  keyword: route.query.keyword || '',
  start_date: '',
  end_date: '',
})

const drawerVisible = ref(false)
const selectedItem = ref(null)

// 同步日期范围到 filters
watch(dateRange, (val) => {
  filters.start_date = val?.[0] || ''
  filters.end_date = val?.[1] || ''
})

onMounted(loadData)

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchAdminRawPosts({
      page: page.value,
      page_size: pageSize.value,
      platform: filters.platform,
      keyword: filters.keyword,
      start_date: filters.start_date,
      end_date: filters.end_date,
    })
    items.value = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : [])
    total.value = resp?.total ?? items.value.length
  } catch (err) {
    error.value = err.message || '原始数据加载失败'
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.platform = ''
  filters.keyword = ''
  filters.start_date = ''
  filters.end_date = ''
  dateRange.value = null
  page.value = 1
  loadData()
}

function openDetail(item) {
  selectedItem.value = item
  drawerVisible.value = true
}

function platformLabel(v) {
  const map = { weibo: '微博', wechat: '微信', tieba: '贴吧', zhihu: '知乎', xiaohongshu: '小红书' }
  return map[v] || v || '未知'
}

function sentimentLabel(v) {
  const map = { positive: '正面', negative: '负面', neutral: '中性' }
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
.page-header { display: flex; align-items: center; justify-content: space-between; }
.page-header h2 { margin: 0; font-size: 20px; color: var(--color-text); }

.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 12px 16px; }
.filter-select { width: 130px; }
.filter-input { flex: 1; min-width: 180px; }

.panel-card { background: var(--color-surface); border: 1px solid var(--color-border-light); border-radius: var(--radius); box-shadow: var(--shadow-card); }
.table-card { overflow: hidden; }

.admin-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.admin-table th { padding: 10px 12px; background: #f8fafd; color: var(--color-text-muted); font-weight: 600; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--color-border-light); }
.admin-table td { padding: 10px 12px; border-bottom: 1px solid var(--color-border-light); vertical-align: middle; }
.admin-table tbody tr:hover { background: #f9fafb; cursor: pointer; }
.admin-table tbody tr:last-child td { border-bottom: 0; }
.empty-cell { text-align: center; color: var(--color-text-muted); padding: 32px; }
.id-cell { color: var(--color-text-muted); font-family: monospace; font-size: 12px; }
.content-cell { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-text); }
.author-cell { white-space: nowrap; color: var(--color-text-secondary); }
.time-cell { white-space: nowrap; color: var(--color-text-muted); font-size: 12px; }
.text-muted { color: var(--color-text-muted); }

.platform-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.platform-weibo { color: #e6162d; background: #fff0f1; }
.platform-wechat { color: #07c160; background: #f0fff5; }
.platform-tieba { color: #2468f2; background: #eef3ff; }
.platform-zhihu { color: #0066ff; background: #e8f0ff; }
.platform-xiaohongshu { color: #ff2442; background: #fff0f2; }

.sentiment-tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.sentiment-positive { color: #059669; background: #d1fae5; }
.sentiment-negative { color: #dc2626; background: #fee2e2; }
.sentiment-neutral { color: #6b7280; background: #f3f4f6; }

.source-link { color: var(--color-primary); text-decoration: none; font-size: 13px; }
.source-link:hover { text-decoration: underline; }

.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-top: 1px solid var(--color-border-light); color: var(--color-text-secondary); font-size: 13px; }

/* 详情抽屉 */
.detail-body { display: flex; flex-direction: column; gap: 14px; }
.detail-row { display: flex; gap: 12px; font-size: 14px; align-items: center; }
.detail-row.align-start { align-items: flex-start; }
.detail-label { min-width: 72px; color: var(--color-text-muted); font-size: 13px; flex-shrink: 0; }
.detail-content { margin: 0; line-height: 1.6; color: var(--color-text); white-space: pre-wrap; word-break: break-all; }
</style>
