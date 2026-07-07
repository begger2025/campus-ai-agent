<template>
  <section class="admin-page admin-overview" v-loading="loading">
    <div class="stat-grid">
      <StatCard title="原始帖子" :value="overview.raw_posts_count" :icon="Coin" color="primary" desc="raw_posts 累计入库" />
      <StatCard title="清洗后帖子" :value="overview.processed_posts_count" :icon="Files" color="teal" desc="processed_posts" />
      <StatCard title="待审核事件" :value="overview.events?.draft" :icon="DocumentChecked" color="warning" desc="等待管理员审核发布" />
      <StatCard title="已发布事件" :value="overview.events?.published" :icon="Promotion" color="success" desc="用户可见的公开事件" />
      <StatCard title="待处理反馈" :value="overview.pending_feedback_count" :icon="Bell" color="danger" desc="用户反馈 pending" />
      <StatCard title="注册用户" :value="overview.users_count" :icon="User" color="purple" desc="users 表账号总数" />
    </div>

    <div class="overview-layout">
      <div class="panel-card overview-panel">
        <div class="panel-title-row">
          <span class="compact-panel-title">事件状态分布</span>
          <el-button link type="primary" @click="router.push('/admin/events')">去审核 →</el-button>
        </div>
        <div class="status-bars">
          <div v-for="item in eventStatusRows" :key="item.key" class="status-bar-row">
            <span class="status-name">{{ item.label }}</span>
            <div class="status-track">
              <div :class="['status-fill', `fill-${item.key}`]" :style="{ width: item.percent + '%' }"></div>
            </div>
            <span class="status-count">{{ item.count }}</span>
          </div>
        </div>

        <div class="panel-title-row crawl-title">
          <span class="compact-panel-title">最近采集任务</span>
          <el-button link type="primary" @click="router.push('/admin/ops')">运维中心 →</el-button>
        </div>
        <div v-if="overview.recent_crawl_task" class="crawl-card">
          <div class="crawl-main">
            <span class="crawl-name">{{ overview.recent_crawl_task.task_name || overview.recent_crawl_task.task_type }}</span>
            <span :class="['tag', taskStatusClass(overview.recent_crawl_task.status)]">{{ overview.recent_crawl_task.status }}</span>
          </div>
          <div class="crawl-meta">
            <span>平台：{{ overview.recent_crawl_task.platform || '—' }}</span>
            <span>成功 {{ overview.recent_crawl_task.success_count ?? 0 }} / 共 {{ overview.recent_crawl_task.total_count ?? 0 }}</span>
            <span>{{ overview.recent_crawl_task.created_at }}</span>
          </div>
        </div>
        <div v-else class="empty-hint">暂无采集任务记录</div>
      </div>

      <div class="panel-card overview-panel">
        <div class="panel-title-row">
          <span class="compact-panel-title">最近管理操作</span>
          <el-button link type="primary" @click="router.push('/admin/ops')">全部审计 →</el-button>
        </div>
        <div class="table-shell">
          <table class="compact-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作人</th>
                <th>动作</th>
                <th>对象</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in recentOps" :key="log.id">
                <td class="time-cell">{{ log.created_at }}</td>
                <td>{{ log.admin_user_id || '—' }}</td>
                <td>{{ actionLabel(log.action) }}</td>
                <td>{{ log.target_type }}#{{ log.target_id }}</td>
              </tr>
              <tr v-if="!recentOps.length && !loading">
                <td colspan="4" class="empty-hint">暂无操作记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Bell, Coin, DocumentChecked, Files, Promotion, User } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import { fetchOperationLogs, fetchOverview } from '@/api/admin'

const router = useRouter()
const loading = ref(false)
const overview = ref({ events: {} })
const recentOps = ref([])

const EVENT_STATUS_LABELS = {
  draft: '待审核',
  published: '已发布',
  rejected: '已驳回',
  archived: '已归档',
}

const ACTION_LABELS = {
  update_event_status: '事件审核',
  update_feedback_status: '反馈处理',
  update_user_status: '用户管理',
}

const eventStatusRows = computed(() => {
  const events = overview.value.events || {}
  const total = Object.values(events).reduce((sum, count) => sum + (count || 0), 0) || 1
  return Object.entries(EVENT_STATUS_LABELS).map(([key, label]) => ({
    key,
    label,
    count: events[key] || 0,
    percent: Math.round(((events[key] || 0) / total) * 100),
  }))
})

function taskStatusClass(status) {
  if (status === 'success' || status === 'finished') return 'tag-success'
  if (status === 'failed' || status === 'error') return 'tag-danger'
  return 'tag-info'
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action
}

onMounted(async () => {
  loading.value = true
  try {
    const [overviewData, opsData] = await Promise.all([
      fetchOverview(),
      fetchOperationLogs({ page: 1, page_size: 8 }),
    ])
    overview.value = overviewData
    recentOps.value = opsData.items || []
  } catch (error) {
    ElMessage.error(error.message || '加载后台概览失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px;
}

.overview-layout {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
  align-items: start;
}

.overview-panel {
  padding: 18px 20px;
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.status-bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 8px;
}

.status-bar-row {
  display: grid;
  grid-template-columns: 62px 1fr 40px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.status-name {
  color: var(--color-text-muted);
}

.status-track {
  height: 8px;
  border-radius: 4px;
  background: var(--color-bg);
  overflow: hidden;
}

.status-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
}

.fill-draft { background: var(--color-warning); }
.fill-published { background: var(--color-success); }
.fill-rejected { background: var(--color-danger); }
.fill-archived { background: var(--color-text-muted); }

.status-count {
  text-align: right;
  font-weight: 600;
}

.crawl-title {
  margin-top: 18px;
}

.crawl-card {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  padding: 12px 14px;
}

.crawl-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
}

.crawl-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.tag-success { background: rgba(82, 196, 26, 0.12); color: var(--color-success); }
.tag-danger { background: rgba(255, 77, 79, 0.12); color: var(--color-danger); }
.tag-info { background: rgba(24, 144, 255, 0.1); color: var(--color-primary); }

.time-cell {
  white-space: nowrap;
  font-size: 12px;
  color: var(--color-text-muted);
}

@media (max-width: 1100px) {
  .overview-layout {
    grid-template-columns: 1fr;
  }
}
</style>
