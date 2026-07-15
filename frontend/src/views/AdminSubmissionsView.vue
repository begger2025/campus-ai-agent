<template>
  <section class="admin-page">
    <div class="panel-card">
      <el-tabs v-model="status" @tab-change="load">
        <el-tab-pane label="待审核" name="pending" />
        <el-tab-pane label="已通过" name="approved" />
        <el-tab-pane label="已驳回" name="rejected" />
      </el-tabs>

      <div v-loading="loading">
        <div v-if="!items.length && !loading" class="empty-hint">该状态下没有投稿</div>
        <article v-for="s in items" :key="s.id" class="sub-item">
          <div class="sub-head">
            <b>#{{ s.id }} {{ s.title }}</b>
            <span class="sub-meta">{{ s.username }} · {{ (s.created_at || '').slice(0, 16).replace('T', ' ') }}</span>
          </div>
          <p class="sub-content">{{ s.content }}</p>
          <div v-if="s.images.length" class="sub-thumbs">
            <a v-for="p in s.images" :key="p" :href="'/' + p" target="_blank" rel="noopener">
              <img :src="'/' + p" alt="证据图片" />
            </a>
          </div>
          <p v-if="s.suggested_event_id" class="sub-note">投稿人认为相关事件：#{{ s.suggested_event_id }}（仅提示，不自动关联）</p>
          <p v-if="s.status === 'approved'" class="sub-note">已写入数据管线（raw_post #{{ s.raw_post_id }}），下轮分析自动参与聚合</p>
          <p v-if="s.status === 'rejected'" class="sub-note sub-reject">驳回理由：{{ s.review_comment }}</p>
          <div v-if="s.status === 'pending'" class="sub-ops">
            <el-button size="small" type="success" @click="review(s, 'approved')">通过（进数据管线）</el-button>
            <el-button size="small" type="danger" @click="review(s, 'rejected')">驳回</el-button>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchAdminSubmissions, reviewSubmission } from '@/api/submissions'

const status = ref('pending')
const items = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = (await fetchAdminSubmissions({ status: status.value, page_size: 50 })).items || []
  } catch (error) {
    ElMessage.error(error.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function review(submission, target) {
  let comment = ''
  if (target === 'rejected') {
    const r = await ElMessageBox.prompt('驳回理由（必填，投稿人可见）', '驳回投稿', {
      inputValidator: (v) => (v && v.trim() ? true : '必须填写理由'),
    }).catch(() => null)
    if (!r) return
    comment = r.value.trim()
  }
  try {
    await reviewSubmission(submission.id, { status: target, review_comment: comment })
    ElMessage.success(target === 'approved' ? '已通过并写入数据管线' : '已驳回')
    load()
  } catch (error) {
    ElMessage.error(error.message || '操作失败')
  }
}

onMounted(load)
</script>

<style scoped>
.sub-item { padding: 12px 0; border-top: 1px solid var(--color-border-light); }
.sub-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.sub-meta { font-size: 12px; color: var(--color-text-muted); }
.sub-content { margin: 6px 0; font-size: 13.5px; line-height: 1.65; white-space: pre-wrap; }
.sub-thumbs { display: flex; gap: 8px; margin: 6px 0; }
.sub-thumbs img { width: 110px; height: 110px; object-fit: cover; border-radius: 8px; border: 1px solid var(--color-border-light); }
.sub-note { font-size: 12px; color: var(--color-text-muted); margin: 4px 0 0; }
.sub-reject { color: #b91c1c; }
.sub-ops { margin-top: 8px; }
.empty-hint { color: var(--color-text-muted); font-size: 13px; padding: 12px 0; }
</style>
