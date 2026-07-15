<template>
  <section class="admin-page">
    <div class="panel-card">
      <el-tabs v-model="mode" @tab-change="load">
        <el-tab-pane label="被举报" name="reported" />
        <el-tab-pane label="已隐藏" name="hidden" />
        <el-tab-pane label="全部" name="all" />
      </el-tabs>
      <div v-loading="loading">
        <div v-if="!items.length && !loading" class="empty-hint">没有需要处理的评论</div>
        <article v-for="c in items" :key="c.id" class="c-item">
          <div class="c-head">
            <b>{{ c.username }}</b>
            <span class="c-meta">事件 #{{ c.event_id }} · {{ (c.created_at || '').slice(0, 16).replace('T', ' ') }}</span>
            <span v-if="c.report_count" class="c-report">举报 ×{{ c.report_count }}</span>
            <span :class="['c-status', `c-${c.status}`]">{{ c.status === 'hidden' ? '已隐藏' : '可见' }}</span>
          </div>
          <p class="c-body">{{ c.content }}</p>
          <p v-if="c.hidden_reason" class="c-reason">隐藏理由：{{ c.hidden_reason }}</p>
          <div class="c-ops">
            <el-button v-if="c.status === 'visible'" size="small" type="danger" plain @click="moderate(c, 'hidden')">隐藏</el-button>
            <el-button v-else size="small" type="success" plain @click="moderate(c, 'visible')">恢复</el-button>
            <el-button size="small" link @click="$router.push(`/events/${c.event_id}`)">查看事件 →</el-button>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'

const mode = ref('reported')
const items = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const params = mode.value === 'reported'
      ? { reported: true, page_size: 50 }
      : { status: mode.value, page_size: 50 }
    items.value = (await http.get('/admin/comments', { params })).items || []
  } catch (error) {
    ElMessage.error(error.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function moderate(comment, target) {
  let reason = ''
  if (target === 'hidden') {
    const r = await ElMessageBox.prompt('隐藏理由（投稿人不可见，供管理员复核）', '隐藏评论', {
      inputValidator: (v) => (v && v.trim() ? true : '必须填写理由'),
    }).catch(() => null)
    if (!r) return
    reason = r.value.trim()
  }
  try {
    await http.patch(`/admin/comments/${comment.id}`, { status: target, reason })
    ElMessage.success(target === 'hidden' ? '已隐藏' : '已恢复')
    load()
  } catch (error) {
    ElMessage.error(error.message || '操作失败')
  }
}

onMounted(load)
</script>

<style scoped>
.c-item { padding: 10px 0; border-top: 1px solid var(--color-border-light); }
.c-head { display: flex; align-items: center; gap: 10px; font-size: 13px; flex-wrap: wrap; }
.c-meta { color: var(--color-text-muted); font-size: 12px; }
.c-report { color: #b45309; background: #fffbeb; padding: 1px 8px; border-radius: 9px; font-size: 11px; font-weight: 600; }
.c-status { font-size: 11px; padding: 1px 8px; border-radius: 9px; }
.c-hidden { background: #fef2f2; color: #b91c1c; }
.c-visible { background: #f0fdf4; color: #15803d; }
.c-body { margin: 4px 0; font-size: 13.5px; }
.c-reason { font-size: 12px; color: #b91c1c; margin: 2px 0; }
.c-ops { margin-top: 4px; }
.empty-hint { color: var(--color-text-muted); font-size: 13px; padding: 12px 0; }
</style>
