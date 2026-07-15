<template>
  <div class="submission-page">
    <div class="panel-card">
      <h3>我要投稿</h3>
      <p class="page-hint">
        看到值得关注的校园情况？投稿给平台。审核通过后会进入数据管线，
        与采集数据一起参与 AI 聚类与研判。文字必填（AI 分析读文字），图片是给审核员看的证据附件（最多 3 张）。
      </p>
      <el-input v-model="form.title" maxlength="100" show-word-limit placeholder="一句话标题（必填）" />
      <el-input
        v-model="form.content"
        type="textarea"
        :rows="5"
        maxlength="2000"
        show-word-limit
        placeholder="发生了什么？时间、地点、经过……（必填）"
        class="form-gap"
      />
      <div class="form-gap upload-row">
        <input ref="fileEl" type="file" accept=".jpg,.jpeg,.png,.webp" hidden @change="onPick" />
        <el-button :disabled="form.images.length >= 3" :loading="uploading" @click="fileEl?.click()">
          上传图片（{{ form.images.length }}/3）
        </el-button>
        <span class="upload-hint">jpg / png / webp，单张 ≤5MB</span>
      </div>
      <div v-if="form.images.length" class="thumbs">
        <div v-for="(p, i) in form.images" :key="p" class="thumb">
          <img :src="'/' + p" alt="投稿图片" />
          <button type="button" @click="form.images.splice(i, 1)">✕</button>
        </div>
      </div>
      <div class="form-gap">
        <el-button type="primary" :loading="submitting" @click="submit">提交投稿（进入人工审核）</el-button>
      </div>
    </div>

    <div class="panel-card">
      <h3>我的投稿</h3>
      <div v-if="!mine.length" class="empty-hint">还没有投稿记录</div>
      <article v-for="s in mine" :key="s.id" class="mine-item">
        <div class="mine-head">
          <b>{{ s.title }}</b>
          <span :class="['status-pill', `st-${s.status}`]">{{ statusLabel(s.status) }}</span>
        </div>
        <p class="mine-content">{{ s.content }}</p>
        <p v-if="s.status === 'approved'" class="mine-note">✅ 已进入数据管线，将随下一轮分析参与事件聚合</p>
        <p v-if="s.status === 'rejected'" class="mine-note mine-reject">驳回理由：{{ s.review_comment }}</p>
      </article>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createSubmission, fetchMySubmissions, uploadSubmissionImage } from '@/api/submissions'

const form = reactive({ title: '', content: '', images: [] })
const mine = ref([])
const fileEl = ref(null)
const uploading = ref(false)
const submitting = ref(false)

const STATUS = { pending: '待审核', approved: '已通过', rejected: '已驳回' }
function statusLabel(s) {
  return STATUS[s] || s
}

async function onPick(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploading.value = true
  try {
    const data = await uploadSubmissionImage(file)
    form.images.push(data.path)
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function submit() {
  if (!form.title.trim()) return ElMessage.warning('标题必填')
  if (!form.content.trim()) return ElMessage.warning('正文必填——AI 分析读的是文字')
  submitting.value = true
  try {
    await createSubmission({ title: form.title.trim(), content: form.content.trim(), images: form.images })
    ElMessage.success('已提交，等待管理员审核')
    form.title = ''
    form.content = ''
    form.images = []
    await load()
  } catch (error) {
    ElMessage.error(error.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function load() {
  try {
    mine.value = (await fetchMySubmissions()).items || []
  } catch {
    /* 列表失败不阻塞表单 */
  }
}

onMounted(load)
</script>

<style scoped>
.submission-page { display: flex; flex-direction: column; gap: 14px; max-width: 760px; }
.panel-card { background: var(--color-surface); border: 1px solid var(--color-border-light); border-radius: var(--radius); padding: 18px; }
.page-hint { font-size: 13px; color: var(--color-text-muted); margin: 6px 0 14px; }
.form-gap { margin-top: 12px; }
.upload-row { display: flex; align-items: center; gap: 10px; }
.upload-hint { font-size: 12px; color: var(--color-text-faint, #c0c4cc); }
.thumbs { display: flex; gap: 10px; margin-top: 10px; }
.thumb { position: relative; width: 96px; height: 96px; border-radius: 8px; overflow: hidden; border: 1px solid var(--color-border-light); }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.thumb button { position: absolute; top: 2px; right: 2px; border: none; border-radius: 50%; width: 20px; height: 20px; background: rgba(0,0,0,.55); color: #fff; cursor: pointer; font-size: 11px; }
.mine-item { padding: 10px 0; border-top: 1px solid var(--color-border-light); }
.mine-head { display: flex; align-items: center; gap: 10px; }
.status-pill { padding: 1px 8px; border-radius: 9px; font-size: 11px; font-weight: 600; }
.st-pending { background: #fffbeb; color: #b45309; }
.st-approved { background: #f0fdf4; color: #15803d; }
.st-rejected { background: #fef2f2; color: #b91c1c; }
.mine-content { margin: 4px 0; font-size: 13px; color: var(--color-text-secondary); }
.mine-note { font-size: 12px; color: var(--color-text-muted); margin: 2px 0 0; }
.mine-reject { color: #b91c1c; }
.empty-hint { color: var(--color-text-muted); font-size: 13px; padding: 8px 0; }
</style>
