<template>
  <section class="admin-page admin-keywords">
    <div class="panel-card">
      <div class="intro-card">
        <p class="intro-title">下一轮优先爬什么，由四路客观信号决定：</p>
        <p class="intro-line">
          <el-tag size="small">需求</el-tag> 用户最近在问什么（3天半衰期）
          <el-tag size="small" type="danger">缺口</el-tag> 问了但站内没数据（×2加权）
          <el-tag size="small" type="warning">热点</el-tag> 已爬话题在小红书仍在升温
          <el-tag size="small" type="success">新话题</el-tag> 笔记标签冒头、从未爬过
        </p>
        <p class="intro-meta" v-if="meta">
          基于近 {{ meta.query_window_days }} 天 {{ meta.query_count }} 条用户提问 与
          近 {{ meta.content_window_days }} 天 {{ meta.post_count }} 条已爬内容计算；
          14 天内爬过的关键词 ×0.3 降权。
        </p>
        <el-button size="small" :loading="loading" @click="load">刷新推荐</el-button>
      </div>

      <div class="table-shell" v-loading="loading">
        <table class="compact-table">
          <thead>
            <tr>
              <th style="width: 48px">#</th>
              <th style="min-width: 120px">关键词</th>
              <th style="width: 140px">分数</th>
              <th>信号</th>
              <th style="min-width: 260px">推荐理由</th>
              <th style="width: 130px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in suggestions" :key="item.keyword">
              <td>{{ index + 1 }}</td>
              <td class="kw-cell">{{ item.keyword }}</td>
              <td>
                <div class="score-bar">
                  <div class="score-fill" :style="{ width: scoreWidth(item.score) }" />
                  <span class="score-text">{{ item.score }}</span>
                </div>
              </td>
              <td>
                <el-tag
                  v-for="signal in item.signals"
                  :key="signal"
                  size="small"
                  :type="SIGNAL_TYPE[signal]"
                  class="signal-tag"
                >
                  {{ SIGNAL_LABEL[signal] }}
                </el-tag>
              </td>
              <td class="reason-cell" :title="item.reason">{{ item.reason }}</td>
              <td>
                <el-button link type="primary" @click="copyCommand(item.keyword)">复制爬取命令</el-button>
              </td>
            </tr>
            <tr v-if="!suggestions.length && !loading">
              <td colspan="6" class="empty-hint">
                暂无推荐。可先在「舆情助手」提问、或运行爬取流水线积累数据后刷新。
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchKeywordSuggestions } from '@/api/admin'

const SIGNAL_LABEL = { demand: '需求', gap: '缺口', heat: '热点', discovery: '新话题' }
const SIGNAL_TYPE = { demand: 'primary', gap: 'danger', heat: 'warning', discovery: 'success' }

const suggestions = ref([])
const meta = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await fetchKeywordSuggestions({ days: 30, top: 10 })
    suggestions.value = data.suggestions || []
    meta.value = data.meta || null
  } catch (error) {
    ElMessage.error(error.message || '加载推荐失败')
  } finally {
    loading.value = false
  }
}

function scoreWidth(score) {
  const max = suggestions.value.length ? suggestions.value[0].score : 10
  return `${Math.min(Math.round((score / (max || 1)) * 100), 100)}%`
}

async function copyCommand(keyword) {
  const command = `.\\.venv\\Scripts\\python.exe main.py --keywords "${keyword}" --get_comment yes`
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success(`已复制（在 MediaCrawler 目录下执行）：${command}`)
  } catch {
    ElMessage.warning(`复制失败，请手动执行：${command}`)
  }
}

onMounted(load)
</script>

<style scoped>
/*
 * .admin-page / .panel-card / .table-shell / .compact-table / .empty-hint
 * 已由全局 src/assets/admin.css 统一定义（其余管理后台页面均不重复声明），
 * 这里只补充本页特有的样式，避免与全局规则重复或打架。
 */

.intro-card {
  padding: 12px 14px;
  margin-bottom: 14px;
  border: 1px dashed var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.intro-title {
  font-weight: 600;
  margin: 0;
}

.intro-line {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  color: var(--color-text-secondary, #6b7280);
}

.intro-meta {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-secondary, #9ca3af);
}

.kw-cell {
  font-weight: 600;
}

/* 全局 admin.css 的 .admin-page .compact-table td（0,2,1）强制 nowrap+ellipsis，
   这里用更高特异性的复合选择器（0,4,1）覆盖，让推荐理由可换行完整展示。 */
.admin-page .compact-table td.reason-cell {
  color: var(--color-text-secondary, #6b7280);
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
}

.signal-tag {
  margin-right: 4px;
}

.score-bar {
  position: relative;
  height: 18px;
  background: var(--color-fill, #f3f4f6);
  border-radius: 9px;
  overflow: hidden;
  min-width: 110px;
}

.score-fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--el-color-primary, #409eff);
  opacity: 0.25;
  border-radius: 9px;
}

.score-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 12px;
}
</style>
