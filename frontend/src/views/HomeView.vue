<template>
  <div class="home-page">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div class="welcome-content">
        <div class="welcome-title">欢迎回来，林同学 👋</div>
        <div class="welcome-sub">
          今天是周{{ todayLabel }}，你有 <strong>{{ stats.courses }}</strong> 节课、
          <strong>{{ stats.pendingTasks }}</strong> 个待办、
          <strong>{{ stats.highRisk }}</strong> 条高风险校园预警。
        </div>
      </div>
      <div class="welcome-meta">
        <DataSourceBadge source="mock" style="margin-right:8px" />
        <el-tag type="danger" effect="dark" v-if="stats.highRisk > 0">
          ⚠️ {{ stats.highRisk }} 条高风险预警
        </el-tag>
        <el-tag type="success" effect="light" v-else>系统运行正常</el-tag>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <StatCard
        title="总帖子数"
        :value="stats.totalPosts"
        icon="📰"
        desc="来自爬虫 + 样本数据"
        color="primary"
      />
      <StatCard
        title="高风险事件"
        :value="stats.highRisk"
        icon="🚨"
        desc="需要优先关注"
        color="danger"
      />
      <StatCard
        title="今日新增线索"
        :value="stats.newToday"
        icon="💡"
        desc="过去 24 小时"
        color="warning"
      />
      <StatCard
        title="今日课程数"
        :value="stats.courses"
        icon="📚"
        desc="已加载课表数据"
        color="success"
      />
      <StatCard
        title="7天内 DDL"
        :value="stats.pendingTasks"
        icon="⏰"
        desc="作业与截止时间"
        color="purple"
      />
      <StatCard
        title="后端状态"
        :value="backendStatus"
        icon="🔗"
        :desc="backendDesc"
        :color="backendOk ? 'success' : 'muted'"
      />
    </div>

    <!-- 内容区：热点事件 + 趋势图 + 我的事务 -->
    <div class="content-grid">
      <!-- 舆情趋势 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">近7天校园舆情热度趋势</span>
        </div>
        <div class="section-body">
          <div class="mini-chart">
            <div
              v-for="item in trendData"
              :key="item.name"
              class="chart-bar-wrap"
            >
              <div
                class="chart-bar"
                :style="{ height: (item.value / maxTrend * 100) + '%' }"
                :title="item.name + ': ' + item.value"
              ></div>
              <div class="chart-label">{{ item.name }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 最新帖子列表 -->
      <div class="section-card span-2">
        <div class="section-header">
          <span class="section-title">最新校园帖子</span>
          <el-button size="small" type="primary" text @click="$router.push('/sentiment')">
            查看全部 →
          </el-button>
        </div>
        <div class="section-body">
          <div v-if="postsLoading" class="loading-state">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在加载数据…
          </div>
          <div v-else-if="posts.length === 0" class="empty-state">
            暂无帖子数据（后端未启动时将展示样本数据）
          </div>
          <table v-else class="data-table">
            <thead>
              <tr>
                <th>平台</th>
                <th>标题</th>
                <th>作者</th>
                <th>发布时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="post in posts.slice(0, 6)" :key="post.id">
                <td><el-tag size="small">{{ post.platform }}</el-tag></td>
                <td class="post-title">{{ post.title }}</td>
                <td class="text-muted">{{ post.author || '匿名' }}</td>
                <td class="text-muted">{{ formatTime(post.publish_time) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 我的今日事务 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">我的今日事务</span>
          <el-button size="small" type="primary" text @click="$router.push('/personal')">
            查看全部 →
          </el-button>
        </div>
        <div class="section-body">
          <div class="info-line" v-for="item in todayItems" :key="item.label">
            <span class="info-label">{{ item.label }}</span>
            <span class="info-value">{{ item.value }}</span>
          </div>
        </div>
      </div>

      <!-- 高风险预警快览 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">高风险预警快览</span>
        </div>
        <div class="section-body">
          <div
            v-for="event in highRiskEvents"
            :key="event.id"
            class="alert-card"
          >
            <div class="alert-title">{{ event.title }}</div>
            <div class="alert-desc">{{ event.riskReason }}</div>
            <span class="badge badge-high">高风险</span>
          </div>
          <div v-if="highRiskEvents.length === 0" class="empty-state">
            当前暂无高风险预警
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import DataSourceBadge from '@/components/DataSourceBadge.vue'
import { checkHealth, fetchPosts } from '@/api/posts'
import { mockPosts, mockEvents } from '@/mock/data'

// ——— 后端状态 ———
const backendOk = ref(false)
const backendDesc = ref('检测中…')
const backendStatus = computed(() => backendOk.value ? '正常' : '未连接')

onMounted(async () => {
  try {
    const data = await checkHealth()
    backendOk.value = data.pong === true
    backendDesc.value = backendOk.value ? '后端响应正常' : '响应异常'
  } catch {
    backendDesc.value = '后端未启动，展示 mock 数据'
  }
  loadPosts()
})

// ——— 帖子数据 ———
const posts = ref([])
const postsLoading = ref(true)

async function loadPosts() {
  try {
    const data = await fetchPosts(1, 10)
    posts.value = data.items
    postsLoading.value = false
  } catch {
    posts.value = mockPosts
    postsLoading.value = false
  }
}

// ——— mock 事件 ———
const highRiskEvents = computed(() => mockEvents.filter(e => e.riskLevel === 'high'))

// ——— 统计数据 ———
const stats = computed(() => ({
  totalPosts: posts.value.length > 0 ? posts.value.length + 50 : mockPosts.length,
  highRisk: highRiskEvents.value.length,
  newToday: 8,
  courses: 2,
  pendingTasks: 4,
}))

const todayLabel = '三'

const todayItems = [
  { label: '今日课程', value: 'Web 前端开发 14:00' },
  { label: '今日 DDL', value: '软工需求文档 04-17' },
  { label: '待办事项', value: '4 条待处理' },
  { label: '推荐活动', value: 'AI 产品经理公开课' },
]

// ——— 趋势图 ———
const trendData = [
  { name: '4/9', value: 18 },
  { name: '4/10', value: 22 },
  { name: '4/11', value: 19 },
  { name: '4/12', value: 33 },
  { name: '4/13', value: 28 },
  { name: '4/14', value: 39 },
  { name: '4/15', value: 46 },
]

const maxTrend = computed(() => Math.max(...trendData.map(d => d.value)))

// ——— 工具函数 ———
function formatTime(ts) {
  if (!ts) return '未知'
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 欢迎横幅 */
.welcome-banner {
  background: linear-gradient(135deg, #f0f8ff 0%, #fff 100%);
  border: 1px solid #d9ecff;
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.welcome-title {
  font-size: 18px;
  font-weight: 700;
}

.welcome-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

/* 统计卡片网格 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 14px;
}

@media (max-width: 1400px) {
  .stat-grid { grid-template-columns: repeat(3, 1fr); }
}

/* 内容区 */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 16px;
}

@media (max-width: 1300px) {
  .content-grid { grid-template-columns: 1fr 1fr; }
}

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.span-2 { grid-column: span 2; }

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--color-border-light);
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.section-body {
  padding: 16px 20px;
}

/* 迷你柱状图 */
.mini-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 100px;
}

.chart-bar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  justify-content: flex-end;
}

.chart-bar {
  width: 100%;
  background: var(--color-primary);
  border-radius: 2px 2px 0 0;
  min-height: 4px;
  transition: height 0.3s ease;
  cursor: pointer;
}

.chart-bar:hover { opacity: 0.75; }

.chart-label {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 4px;
}

/* 数据表格 */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th {
  padding: 8px 12px;
  text-align: left;
  background: #fafafa;
  color: var(--color-text-muted);
  font-weight: 500;
  font-size: 12px;
}

.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border-light);
  color: var(--color-text);
}

.post-title {
  max-width: 320px;
  font-weight: 500;
}

.text-muted { color: var(--color-text-muted); }

/* 信息列表 */
.info-line {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
  font-size: 13px;
}

.info-label {
  width: 72px;
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.info-value {
  font-weight: 500;
  color: var(--color-text);
}

/* 预警卡片 */
.alert-card {
  background: #fff1f0;
  border: 1px solid #ffa39e;
  border-radius: var(--radius-sm);
  padding: 12px;
  margin-bottom: 10px;
}

.alert-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}

.alert-desc {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  line-height: 1.5;
}

/* loading / empty */
.loading-state,
.empty-state {
  padding: 32px 0;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
</style>
