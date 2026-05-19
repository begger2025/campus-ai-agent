<template>
  <div class="personal-page">
    <!-- 统计 -->
    <div class="stat-row">
      <StatCard title="今日课程" :value="todayCourses.length" icon="📚" color="success" />
      <StatCard title="待完成作业" :value="pendingTasks.length" icon="📝" color="primary" />
      <StatCard title="7天内 DDL" :value="urgentTasks.length" icon="⏰" color="warning" />
      <StatCard title="今日提醒" :value="reminders.length" icon="🔔" color="purple" />
      <StatCard title="推荐活动" :value="activities.length" icon="✨" color="teal" />
    </div>

    <!-- 今日日程 + AI 建议 -->
    <div class="top-grid">
      <!-- 今日日程 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">今日日程</span>
        </div>
        <div class="section-body">
          <div class="schedule-list">
            <div v-for="item in todaySchedule" :key="item.time + item.title" class="schedule-row">
              <div class="schedule-time">{{ item.time }}</div>
              <div class="schedule-content">
                <div class="schedule-title">{{ item.title }}</div>
                <div v-if="item.meta" class="schedule-meta">{{ item.meta }}</div>
              </div>
              <el-tag v-if="item.type" size="small" :type="scheduleTagType(item.type)">
                {{ item.type }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- AI 今日建议 -->
      <div class="section-card ai-card">
        <div class="section-header">
          <span class="section-title">🤖 AI 今日建议</span>
        </div>
        <div class="section-body">
          <div class="ai-bubble" v-for="tip in aiTips" :key="tip">
            {{ tip }}
          </div>
          <el-button
            type="primary"
            class="ai-btn"
            :loading="aiLoading"
            @click="refreshAI"
          >
            重新生成建议
          </el-button>
        </div>
      </div>
    </div>

    <!-- 课表缩略 -->
    <div class="section-card">
      <div class="section-header">
        <span class="section-title">本周课表</span>
        <el-tag type="info" size="small">第8周</el-tag>
      </div>
      <div class="section-body">
        <div class="schedule-grid">
          <div class="schedule-col" v-for="day in weekDays" :key="day.name">
            <div class="day-header" :class="{ 'day-header--today': day.isToday }">
              {{ day.name }}
            </div>
            <div v-for="course in day.courses" :key="course.name" class="course-chip">
              <div class="course-name">{{ course.name }}</div>
              <div class="course-time">{{ course.time }}</div>
              <div class="course-loc">{{ course.location }}</div>
            </div>
            <div v-if="day.courses.length === 0" class="day-empty">无课</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 作业 DDL + 活动推荐 -->
    <div class="bottom-grid">
      <!-- 作业 DDL -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">作业与 DDL</span>
        </div>
        <div class="section-body">
          <div v-for="task in tasks" :key="task.id" class="task-row">
            <div class="task-info">
              <div class="task-title">{{ task.title }}</div>
              <div class="task-meta">{{ task.course }} · {{ task.source }}</div>
            </div>
            <div class="task-right">
              <div class="task-deadline">{{ task.deadline.slice(5) }}</div>
              <span :class="['badge', priorityBadge(task.priority)]">{{ task.priority }}</span>
              <el-tag
                size="small"
                :type="statusTagType(task.status)"
                effect="light"
              >
                {{ task.status }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 活动推荐 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">活动与宣讲会推荐</span>
        </div>
        <div class="section-body">
          <div v-for="act in activities" :key="act.id" class="activity-card">
            <div class="activity-top">
              <span class="activity-title">{{ act.title }}</span>
              <el-tag size="small" :type="act.kind === '招聘宣讲' ? 'warning' : 'primary'">
                {{ act.kind }}
              </el-tag>
            </div>
            <div class="activity-meta">{{ act.time }} · {{ act.location }}</div>
            <div class="activity-reason">💡 {{ act.reason }}</div>
            <div class="activity-actions">
              <el-button size="small" @click="handleJoin(act)">
                {{ joinedIds.includes(act.id) ? '✅ 已加入' : '加入日程' }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 提醒中心 -->
      <div class="section-card">
        <div class="section-header">
          <span class="section-title">提醒中心</span>
          <el-badge :value="reminders.length" type="danger" />
        </div>
        <div class="section-body">
          <div v-for="item in reminders" :key="item.title" class="reminder-row">
            <span class="reminder-time">{{ item.time }}</span>
            <span class="reminder-title">{{ item.title }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import StatCard from '@/components/StatCard.vue'

// ——— 课程数据 ———
const allCourses = [
  { name: '软件工程', day: '周一', time: '08:30-10:05', location: '信工楼B203' },
  { name: '数据库系统', day: '周一', time: '14:00-15:35', location: '主楼A302' },
  { name: '人工智能导论', day: '周二', time: '10:20-11:55', location: '信工楼C101' },
  { name: 'Web前端开发', day: '周三', time: '14:00-16:30', location: '实验楼404' },
  { name: '操作系统', day: '周五', time: '08:30-10:05', location: '主楼B201' },
  { name: '创新创业实践', day: '周五', time: '19:00-20:35', location: '双创中心2F' },
]

const weekDayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const weekDays = weekDayNames.map((name, index) => ({
  name,
  isToday: index === 2, // 假设今日为周三
  courses: allCourses.filter(c => c.day === name),
}))

const todayCourses = allCourses.filter(c => c.day === '周三')

// ——— 今日日程 ———
const todaySchedule = [
  { time: '08:30', title: '操作系统', meta: '主楼B201 · 赵老师', type: '课程' },
  { time: '14:00', title: 'Web前端开发', meta: '实验楼404 · 周老师', type: '课程' },
  { time: '19:00', title: '整理软件工程文档草稿', meta: '', type: '待办' },
  { time: '明天', title: 'AI产品经理公开课', meta: '图书馆报告厅 15:00', type: '活动' },
]

// ——— 任务 ———
const tasks = ref([
  { id: 'T-001', title: '软件工程需求分析文档', source: '课程平台', course: '软件工程', deadline: '2026-04-17', status: '进行中', priority: '高' },
  { id: 'T-002', title: '数据库ER图作业', source: '雨课堂', course: '数据库系统', deadline: '2026-04-18', status: '未完成', priority: '高' },
  { id: 'T-003', title: 'AI导论阅读报告', source: '学习通', course: '人工智能导论', deadline: '2026-04-21', status: '未完成', priority: '中' },
  { id: 'T-004', title: '前端页面原型优化', source: 'GitLab', course: 'Web前端开发', deadline: '2026-04-23', status: '进行中', priority: '中' },
  { id: 'T-005', title: '操作系统实验一', source: '课程平台', course: '操作系统', deadline: '2026-04-10', status: '已逾期', priority: '高' },
])

const pendingTasks = tasks.value.filter(t => t.status === '未完成' || t.status === '进行中')
const urgentTasks = tasks.value.filter(t => t.status !== '已完成')

// ——— 活动 ———
const activities = ref([
  { id: 'A-001', title: 'AI产品经理校园公开课', kind: '校园活动', time: '2026-04-16 15:00', location: '图书馆报告厅', reason: '与你的AI和软件工程兴趣匹配，且周四下午无课' },
  { id: 'A-002', title: '前端工程师校招宣讲会', kind: '招聘宣讲', time: '2026-04-17 19:00', location: '就业中心报告厅', reason: '与你最近关注的前端开发方向高度相关' },
  { id: 'A-003', title: '校园羽毛球友谊赛', kind: '校园活动', time: '2026-04-18 16:00', location: '体育馆3号场', reason: '与你的羽毛球兴趣匹配，不与课程冲突' },
])

const joinedIds = ref([])

function handleJoin(act) {
  if (joinedIds.value.includes(act.id)) return
  joinedIds.value.push(act.id)
  ElMessage.success(`已加入「${act.title}」到日程`)
}

// ——— 提醒 ———
const reminders = ref([
  { time: '今天 14:00', title: 'Web前端开发实验课' },
  { time: '今天 19:30', title: '整理软件工程文档草稿' },
  { time: '明天 15:00', title: 'AI产品经理公开课' },
  { time: '2天后', title: '数据库ER图作业截止' },
])

// ——— AI 建议 ———
const aiTips = ref([
  '📌 今天下午前半段无课，适合完成「数据库ER图作业」。',
  '📅 周四 15:00 的 AI 产品经理公开课与你的兴趣匹配。',
  '⚠️ 近期存在兼职押金诈骗预警，招聘信息请优先核验来源。',
  '✅ 软工需求文档 DDL 剩余 2 天，建议今晚推进主体框架。',
])

const aiLoading = ref(false)

function refreshAI() {
  aiLoading.value = true
  setTimeout(() => {
    aiTips.value = [
      '🎯 今日重点：先补操作系统实验，再处理数据库ER图。',
      '💡 周四下午 + 周五上午均有空，适合集中写软件工程文档。',
      '🚀 前端工程师宣讲会 (04-17 19:00) 与你方向匹配，请勿错过！',
    ]
    aiLoading.value = false
    ElMessage.success('AI 建议已更新')
  }, 800)
}

// ——— 样式辅助 ———
function scheduleTagType(type) {
  const map = { '课程': 'primary', '待办': 'warning', '活动': 'success', '提醒': 'danger' }
  return map[type] || 'info'
}

function statusTagType(status) {
  if (status === '已完成') return 'success'
  if (status === '已逾期') return 'danger'
  if (status === '进行中') return 'warning'
  return 'info'
}

function priorityBadge(p) {
  if (p === '高') return 'badge-high'
  if (p === '中') return 'badge-mid'
  return 'badge-low'
}
</script>

<style scoped>
.personal-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}

.top-grid,
.bottom-grid {
  display: grid;
  gap: 16px;
}

.top-grid { grid-template-columns: 1fr 1fr; }
.bottom-grid { grid-template-columns: 1fr 1fr 1fr; }

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

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
}

.section-body { padding: 14px 18px; }

/* 日程 */
.schedule-list { display: flex; flex-direction: column; gap: 8px; }

.schedule-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
}

.schedule-time {
  width: 56px;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
}

.schedule-content { flex: 1; }

.schedule-title { font-size: 13px; font-weight: 500; }

.schedule-meta {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

/* AI 建议 */
.ai-card { }

.ai-bubble {
  background: #f0f8ff;
  border-left: 3px solid var(--color-primary);
  padding: 10px 12px;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin-bottom: 8px;
}

.ai-btn { width: 100%; margin-top: 8px; }

/* 课表 */
.schedule-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
}

.day-header {
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  padding: 6px 0;
  border-radius: var(--radius-sm);
  background: #f8fafc;
  margin-bottom: 4px;
}

.day-header--today {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.course-chip {
  background: var(--color-primary-light);
  border-radius: var(--radius-sm);
  padding: 8px;
  margin-bottom: 4px;
}

.course-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
}

.course-time,
.course-loc {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.day-empty {
  font-size: 11px;
  color: #c0c7d0;
  text-align: center;
  padding: 12px 0;
}

/* 作业 */
.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
}

.task-title {
  font-size: 13px;
  font-weight: 500;
}

.task-meta {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.task-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.task-deadline {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 活动 */
.activity-card {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  padding: 12px;
  margin-bottom: 10px;
}

.activity-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.activity-title {
  font-size: 13px;
  font-weight: 600;
}

.activity-meta {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 4px;
}

.activity-reason {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  margin-bottom: 8px;
}

.activity-actions { display: flex; gap: 8px; }

/* 提醒 */
.reminder-row {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
  font-size: 13px;
}

.reminder-time {
  width: 68px;
  flex-shrink: 0;
  color: var(--color-primary);
  font-weight: 500;
}

.reminder-title { color: var(--color-text); }
</style>
