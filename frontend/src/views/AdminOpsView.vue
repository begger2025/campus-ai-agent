<template>
  <section class="admin-page admin-ops">
    <div class="panel-card">
      <el-tabs v-model="activeTab">
        <!-- 用户反馈 -->
        <el-tab-pane label="用户反馈" name="feedback">
          <div class="tab-toolbar">
            <el-select v-model="feedback.status" class="filter-select" @change="loadFeedback(1)">
              <el-option label="状态：全部" value="" />
              <el-option label="状态：待处理" value="pending" />
              <el-option label="状态：处理中" value="handling" />
              <el-option label="状态：已解决" value="resolved" />
              <el-option label="状态：已忽略" value="ignored" />
            </el-select>
          </div>
          <div class="table-shell" v-loading="feedback.loading">
            <table class="compact-table">
              <thead>
                <tr>
                  <th style="width: 52px">ID</th>
                  <th style="min-width: 240px">反馈内容</th>
                  <th>类型</th>
                  <th>对象</th>
                  <th>状态</th>
                  <th>处理人</th>
                  <th style="width: 150px">提交时间</th>
                  <th style="width: 140px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in feedback.items" :key="item.id">
                  <td>{{ item.id }}</td>
                  <td class="title-cell" :title="item.content">{{ item.content || '—' }}</td>
                  <td>{{ item.feedback_type || '—' }}</td>
                  <td>{{ item.target_type }}{{ item.target_id ? `#${item.target_id}` : '' }}</td>
                  <td><span :class="['status-tag', `status-${item.status}`]">{{ feedbackStatusLabel(item.status) }}</span></td>
                  <td>{{ item.handled_by || '—' }}</td>
                  <td>{{ item.created_at }}</td>
                  <td>
                    <el-button link type="primary" @click="openHandle(item)">处理</el-button>
                  </td>
                </tr>
                <tr v-if="!feedback.items.length && !feedback.loading">
                  <td colspan="8" class="empty-hint">暂无反馈</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-footer">
            <span>共 {{ feedback.total }} 条</span>
            <el-pagination
              v-model:current-page="feedback.page"
              background
              layout="prev, pager, next"
              :page-size="PAGE_SIZE"
              :total="feedback.total"
              @current-change="loadFeedback"
            />
          </div>
        </el-tab-pane>

        <!-- 爬虫任务 -->
        <el-tab-pane label="采集任务" name="tasks">
          <div class="table-shell" v-loading="tasks.loading">
            <table class="compact-table">
              <thead>
                <tr>
                  <th style="width: 52px">ID</th>
                  <th style="min-width: 180px">任务</th>
                  <th>类型</th>
                  <th>平台</th>
                  <th>关键词</th>
                  <th>状态</th>
                  <th>成功/总数</th>
                  <th style="width: 150px">创建时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="task in tasks.items" :key="task.id">
                  <td>{{ task.id }}</td>
                  <td class="title-cell" :title="task.task_name">{{ task.task_name || '—' }}</td>
                  <td>{{ task.task_type || '—' }}</td>
                  <td>{{ task.platform || '—' }}</td>
                  <td>{{ task.keyword || '—' }}</td>
                  <td><span :class="['status-tag', `status-${task.status}`]">{{ task.status }}</span></td>
                  <td>{{ task.success_count ?? 0 }} / {{ task.total_count ?? 0 }}</td>
                  <td>{{ task.created_at }}</td>
                </tr>
                <tr v-if="!tasks.items.length && !tasks.loading">
                  <td colspan="8" class="empty-hint">暂无采集任务</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-footer">
            <span>共 {{ tasks.total }} 条</span>
            <el-pagination
              v-model:current-page="tasks.page"
              background
              layout="prev, pager, next"
              :page-size="PAGE_SIZE"
              :total="tasks.total"
              @current-change="loadTasks"
            />
          </div>
        </el-tab-pane>

        <!-- 系统日志 -->
        <el-tab-pane label="系统日志" name="syslogs">
          <div class="tab-toolbar">
            <el-select v-model="syslogs.level" class="filter-select" @change="loadSyslogs(1)">
              <el-option label="级别：全部" value="" />
              <el-option label="级别：info" value="info" />
              <el-option label="级别：warning" value="warning" />
              <el-option label="级别：error" value="error" />
            </el-select>
          </div>
          <div class="table-shell" v-loading="syslogs.loading">
            <table class="compact-table">
              <thead>
                <tr>
                  <th style="width: 52px">ID</th>
                  <th>级别</th>
                  <th>模块</th>
                  <th style="min-width: 300px">消息</th>
                  <th style="width: 150px">时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in syslogs.items" :key="log.id">
                  <td>{{ log.id }}</td>
                  <td><span :class="['status-tag', levelClass(log.level)]">{{ log.level }}</span></td>
                  <td>{{ log.module || '—' }}</td>
                  <td class="title-cell" :title="log.message">{{ log.message }}</td>
                  <td>{{ log.created_at }}</td>
                </tr>
                <tr v-if="!syslogs.items.length && !syslogs.loading">
                  <td colspan="5" class="empty-hint">暂无系统日志</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-footer">
            <span>共 {{ syslogs.total }} 条</span>
            <el-pagination
              v-model:current-page="syslogs.page"
              background
              layout="prev, pager, next"
              :page-size="PAGE_SIZE"
              :total="syslogs.total"
              @current-change="loadSyslogs"
            />
          </div>
        </el-tab-pane>

        <!-- 用户管理 -->
        <el-tab-pane label="用户管理" name="users">
          <div class="tab-toolbar">
            <el-input
              v-model="users.keyword"
              clearable
              placeholder="搜索用户名 / 昵称"
              class="filter-search"
              @keyup.enter="loadUsers(1)"
            />
            <el-select v-model="users.role" class="filter-select" @change="loadUsers(1)">
              <el-option label="角色：全部" value="" />
              <el-option label="角色：管理员" value="admin" />
              <el-option label="角色：普通用户" value="user" />
            </el-select>
            <el-button type="primary" @click="loadUsers(1)">查询</el-button>
          </div>
          <div class="table-shell" v-loading="users.loading">
            <table class="compact-table">
              <thead>
                <tr>
                  <th style="width: 52px">ID</th>
                  <th>用户名</th>
                  <th>昵称</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th style="width: 150px">注册时间</th>
                  <th style="width: 150px">最近登录</th>
                  <th style="width: 100px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in users.items" :key="user.id">
                  <td>{{ user.id }}</td>
                  <td>{{ user.username }}</td>
                  <td>{{ user.display_name || '—' }}</td>
                  <td>{{ user.role === 'admin' ? '管理员' : '普通用户' }}</td>
                  <td><span :class="['status-tag', `status-${user.status}`]">{{ user.status === 'active' ? '正常' : '已禁用' }}</span></td>
                  <td>{{ user.created_at || '—' }}</td>
                  <td>{{ user.last_login_at || '—' }}</td>
                  <td>
                    <el-button
                      v-if="user.status === 'active'"
                      link
                      type="danger"
                      @click="toggleUser(user, 'disabled')"
                    >禁用</el-button>
                    <el-button v-else link type="success" @click="toggleUser(user, 'active')">启用</el-button>
                  </td>
                </tr>
                <tr v-if="!users.items.length && !users.loading">
                  <td colspan="8" class="empty-hint">没有匹配的用户</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-footer">
            <span>共 {{ users.total }} 个账号</span>
            <el-pagination
              v-model:current-page="users.page"
              background
              layout="prev, pager, next"
              :page-size="PAGE_SIZE"
              :total="users.total"
              @current-change="loadUsers"
            />
          </div>
        </el-tab-pane>

        <!-- 操作审计 -->
        <el-tab-pane label="操作审计" name="oplogs">
          <div class="table-shell" v-loading="oplogs.loading">
            <table class="compact-table">
              <thead>
                <tr>
                  <th style="width: 52px">ID</th>
                  <th>操作人</th>
                  <th>动作</th>
                  <th>对象</th>
                  <th style="min-width: 260px">变更详情</th>
                  <th style="width: 150px">时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in oplogs.items" :key="log.id">
                  <td>{{ log.id }}</td>
                  <td>{{ log.admin_user_id || '—' }}</td>
                  <td>{{ log.action }}</td>
                  <td>{{ log.target_type }}#{{ log.target_id }}</td>
                  <td class="title-cell" :title="log.detail">{{ log.detail || '—' }}</td>
                  <td>{{ log.created_at }}</td>
                </tr>
                <tr v-if="!oplogs.items.length && !oplogs.loading">
                  <td colspan="6" class="empty-hint">暂无操作记录</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-footer">
            <span>共 {{ oplogs.total }} 条</span>
            <el-pagination
              v-model:current-page="oplogs.page"
              background
              layout="prev, pager, next"
              :page-size="PAGE_SIZE"
              :total="oplogs.total"
              @current-change="loadOplogs"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 反馈处理对话框 -->
    <el-dialog v-model="handleDialog.visible" title="处理反馈" width="480px">
      <p class="handle-content">{{ handleDialog.item?.content }}</p>
      <el-form label-position="top">
        <el-form-item label="处理状态">
          <el-radio-group v-model="handleDialog.status">
            <el-radio value="handling">处理中</el-radio>
            <el-radio value="resolved">已解决</el-radio>
            <el-radio value="ignored">忽略</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="处理备注">
          <el-input v-model="handleDialog.note" type="textarea" :rows="3" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handleDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="handleDialog.submitting" @click="submitHandle">确认</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchCrawlTasks,
  fetchFeedbackList,
  fetchOperationLogs,
  fetchSystemLogs,
  fetchUsers,
  updateFeedbackStatus,
  updateUserStatus,
} from '@/api/admin'
import { getCurrentUser } from '@/auth/session'

const PAGE_SIZE = 15

const activeTab = ref('feedback')

const feedback = reactive({ items: [], total: 0, page: 1, status: '', loading: false, loaded: false })
const tasks = reactive({ items: [], total: 0, page: 1, loading: false, loaded: false })
const syslogs = reactive({ items: [], total: 0, page: 1, level: '', loading: false, loaded: false })
const oplogs = reactive({ items: [], total: 0, page: 1, loading: false, loaded: false })
const users = reactive({ items: [], total: 0, page: 1, keyword: '', role: '', loading: false, loaded: false })

const handleDialog = reactive({ visible: false, item: null, status: 'resolved', note: '', submitting: false })

const FEEDBACK_STATUS_LABELS = {
  pending: '待处理',
  handling: '处理中',
  resolved: '已解决',
  handled: '已处理',
  ignored: '已忽略',
}

function feedbackStatusLabel(status) {
  return FEEDBACK_STATUS_LABELS[status] || status
}

function levelClass(level) {
  if (level === 'error' || level === 'critical') return 'status-failed'
  if (level === 'warning') return 'status-pending'
  return 'status-handling'
}

async function runLoad(state, fetcher, errorText, nextPage) {
  if (typeof nextPage === 'number') state.page = nextPage
  state.loading = true
  try {
    const data = await fetcher()
    state.items = data.items || []
    state.total = data.total || 0
    state.loaded = true
  } catch (error) {
    ElMessage.error(error.message || errorText)
  } finally {
    state.loading = false
  }
}

const loadFeedback = (nextPage) =>
  runLoad(
    feedback,
    () => fetchFeedbackList({ status: feedback.status || undefined, page: feedback.page, page_size: PAGE_SIZE }),
    '加载反馈失败',
    nextPage,
  )

const loadTasks = (nextPage) =>
  runLoad(tasks, () => fetchCrawlTasks({ page: tasks.page, page_size: PAGE_SIZE }), '加载采集任务失败', nextPage)

const loadSyslogs = (nextPage) =>
  runLoad(
    syslogs,
    () => fetchSystemLogs({ level: syslogs.level || undefined, page: syslogs.page, page_size: PAGE_SIZE }),
    '加载系统日志失败',
    nextPage,
  )

const loadOplogs = (nextPage) =>
  runLoad(oplogs, () => fetchOperationLogs({ page: oplogs.page, page_size: PAGE_SIZE }), '加载操作审计失败', nextPage)

const loadUsers = (nextPage) =>
  runLoad(
    users,
    () =>
      fetchUsers({
        keyword: users.keyword || undefined,
        role: users.role || undefined,
        page: users.page,
        page_size: PAGE_SIZE,
      }),
    '加载用户失败',
    nextPage,
  )

async function toggleUser(user, targetStatus) {
  if (targetStatus === 'disabled' && user.id === getCurrentUser()?.id) {
    ElMessage.warning('不能禁用自己的账号')
    return
  }
  if (targetStatus === 'disabled') {
    try {
      await ElMessageBox.confirm(`确认禁用账号「${user.username}」？禁用后该账号无法登录。`, '禁用账号', {
        type: 'warning',
        confirmButtonText: '禁用',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  try {
    await updateUserStatus(user.id, targetStatus)
    ElMessage.success(targetStatus === 'disabled' ? '账号已禁用' : '账号已启用')
    loadUsers()
  } catch (error) {
    ElMessage.error(error.message || '更新账号状态失败')
  }
}

// 页签懒加载：切到哪个页签才拉哪个列表
watch(activeTab, (tab) => {
  if (tab === 'tasks' && !tasks.loaded) loadTasks(1)
  if (tab === 'syslogs' && !syslogs.loaded) loadSyslogs(1)
  if (tab === 'oplogs' && !oplogs.loaded) loadOplogs(1)
  if (tab === 'users' && !users.loaded) loadUsers(1)
})

function openHandle(item) {
  handleDialog.item = item
  handleDialog.status = item.status === 'pending' ? 'resolved' : item.status
  handleDialog.note = item.handle_note || ''
  handleDialog.visible = true
}

async function submitHandle() {
  handleDialog.submitting = true
  try {
    await updateFeedbackStatus(handleDialog.item.id, {
      status: handleDialog.status,
      handle_note: handleDialog.note.trim(),
    })
    ElMessage.success('反馈状态已更新')
    handleDialog.visible = false
    loadFeedback()
  } catch (error) {
    ElMessage.error(error.message || '更新反馈失败')
  } finally {
    handleDialog.submitting = false
  }
}

onMounted(() => loadFeedback(1))
</script>

<style scoped>
.tab-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.filter-select {
  width: 160px;
}

.title-cell {
  max-width: 340px;
}

.handle-content {
  margin: 0 0 14px;
  background: var(--color-bg);
  border-radius: var(--radius);
  padding: 10px 12px;
  font-size: 13px;
}
</style>
