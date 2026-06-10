<template>
  <section class="admin-page">
    <div class="page-header">
      <h2>后台概览</h2>
      <el-button size="small" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <!-- 错误状态 -->
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" style="margin-bottom:14px" />

    <!-- KPI 卡片 -->
    <div class="kpi-grid" v-loading="loading">
      <div class="kpi-card" @click="router.push('/admin/raw-posts')">
        <div class="kpi-icon kpi-blue">📦</div>
        <div>
          <div class="kpi-value">{{ overview?.raw_posts_count ?? '—' }}</div>
          <div class="kpi-label">原始采集数据</div>
        </div>
      </div>
      <div class="kpi-card">
        <div class="kpi-icon kpi-purple">🔬</div>
        <div>
          <div class="kpi-value">{{ overview?.processed_posts_count ?? '—' }}</div>
          <div class="kpi-label">已清洗数据</div>
        </div>
      </div>
      <div class="kpi-card" @click="router.push('/admin/events?status=draft')">
        <div class="kpi-icon kpi-orange">📋</div>
        <div>
          <div class="kpi-value">{{ overview?.draft_events_count ?? overview?.events?.draft ?? '—' }}</div>
          <div class="kpi-label">待审核事件</div>
        </div>
      </div>
      <div class="kpi-card" @click="router.push('/admin/events?status=published')">
        <div class="kpi-icon kpi-green">✅</div>
        <div>
          <div class="kpi-value">{{ overview?.events?.published ?? '—' }}</div>
          <div class="kpi-label">已发布事件</div>
        </div>
      </div>
      <div class="kpi-card" @click="router.push('/admin/ops?tab=feedback&status=pending')">
        <div class="kpi-icon kpi-red">💬</div>
        <div>
          <div class="kpi-value">{{ overview?.pending_feedback_count ?? overview?.feedback?.pending ?? '—' }}</div>
          <div class="kpi-label">待处理反馈</div>
        </div>
      </div>
      <div class="kpi-card" @click="router.push('/admin/ops?tab=system-logs&level=error')">
        <div class="kpi-icon kpi-red">⚠️</div>
        <div>
          <div class="kpi-value">{{ overview?.recent_system_errors_count ?? '—' }}</div>
          <div class="kpi-label">近期系统异常</div>
        </div>
      </div>
    </div>

    <!-- 事件状态分布 -->
    <div class="section-card" v-if="overview?.events">
      <div class="section-title">事件状态分布</div>
      <div class="status-row">
        <div class="status-item" v-for="item in eventStatusItems" :key="item.label"
             @click="router.push(`/admin/events?status=${item.status}`)">
          <span :class="['status-dot', item.dotClass]"></span>
          <span class="status-label">{{ item.label }}</span>
          <strong class="status-count">{{ item.count }}</strong>
        </div>
      </div>
    </div>

    <!-- 最近爬虫任务 -->
    <div class="section-card" v-if="overview?.recent_crawl_task && Object.keys(overview.recent_crawl_task).length">
      <div class="section-title">最近爬虫任务</div>
      <div class="crawl-row">
        <span>任务状态：<strong>{{ overview.recent_crawl_task.status ?? '—' }}</strong></span>
        <span v-if="overview.recent_crawl_task.started_at">开始时间：{{ overview.recent_crawl_task.started_at }}</span>
        <span v-if="overview.recent_crawl_task.finished_at">完成时间：{{ overview.recent_crawl_task.finished_at }}</span>
        <el-button text size="small" @click="router.push('/admin/ops?tab=crawl')">查看详情</el-button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchAdminOverview } from '@/api/admin'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const overview = ref(null)

const eventStatusItems = computed(() => {
  const ev = overview.value?.events || {}
  return [
    { label: '草稿', status: 'draft', count: ev.draft ?? 0, dotClass: 'dot-gray' },
    { label: '已发布', status: 'published', count: ev.published ?? 0, dotClass: 'dot-green' },
    { label: '已驳回', status: 'rejected', count: ev.rejected ?? 0, dotClass: 'dot-red' },
    { label: '已归档', status: 'archived', count: ev.archived ?? 0, dotClass: 'dot-blue' },
  ]
})

onMounted(loadData)

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await fetchAdminOverview()
  } catch (err) {
    error.value = err.message || '后台概览加载失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; }
.page-header h2 { margin: 0; font-size: 20px; color: var(--color-text); }

.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }

.kpi-card {
  display: flex; align-items: center; gap: 16px;
  padding: 20px 20px; border-radius: var(--radius);
  background: var(--color-surface); border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-card); cursor: pointer; transition: box-shadow .15s;
}
.kpi-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.08); }

.kpi-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; }
.kpi-blue { background: #eef5ff; }
.kpi-purple { background: #f5f0ff; }
.kpi-orange { background: #fffbeb; }
.kpi-green { background: #f0fdf4; }
.kpi-red { background: #fef2f2; }

.kpi-value { font-size: 28px; font-weight: 700; color: var(--color-text); font-family: "Segoe UI", Arial, sans-serif; }
.kpi-label { font-size: 13px; color: var(--color-text-muted); margin-top: 2px; }

.section-card { background: var(--color-surface); border: 1px solid var(--color-border-light); border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow-card); }
.section-title { font-size: 15px; font-weight: 700; color: var(--color-text); margin-bottom: 14px; }

.status-row { display: flex; gap: 24px; flex-wrap: wrap; }
.status-item { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 6px 12px; border-radius: 6px; }
.status-item:hover { background: #f5f7fa; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-gray { background: #9ca3af; }
.dot-green { background: #13b26b; }
.dot-red { background: #e03137; }
.dot-blue { background: #2563eb; }
.status-label { font-size: 14px; color: var(--color-text-secondary); }
.status-count { font-size: 18px; font-weight: 700; color: var(--color-text); }

.crawl-row { display: flex; align-items: center; gap: 24px; font-size: 13px; color: var(--color-text-secondary); flex-wrap: wrap; }
.crawl-row strong { color: var(--color-text); }
</style>
