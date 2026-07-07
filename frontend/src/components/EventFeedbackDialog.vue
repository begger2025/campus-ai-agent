<template>
  <el-dialog
    :model-value="visible"
    title="事件反馈"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template v-if="event">
      <div class="feedback-event-title">{{ event.title }}</div>

      <el-form label-position="top">
        <el-form-item label="反馈类型" required>
          <el-select v-model="form.type" class="full-width">
            <el-option label="信息补充" value="supplement" />
            <el-option label="内容纠错" value="correction" />
            <el-option label="风险误判" value="risk_misjudge" />
            <el-option label="其他反馈" value="other" />
          </el-select>
        </el-form-item>

        <el-form-item label="反馈内容" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="4"
            placeholder="请描述您的反馈意见..."
          />
        </el-form-item>
      </el-form>
    </template>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="handleSubmit" :loading="submitting">
        提交反馈
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { getCurrentUser } from '@/auth/session'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  event: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue'])

const visible = ref(props.modelValue)
const submitting = ref(false)

const form = reactive({
  type: 'supplement',
  content: '',
})

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (!val) {
    form.type = 'supplement'
    form.content = ''
  }
})

async function handleSubmit() {
  if (!form.content.trim()) {
    ElMessage.warning('请输入反馈内容')
    return
  }

  submitting.value = true
  try {
    await http.post('/feedback', {
      feedback_type: form.type,
      content: form.content.trim(),
      user_id: getCurrentUser()?.username || 'anonymous',
      target_type: 'public_event',
      target_id: String(props.event?.raw_id ?? props.event?.id ?? ''),
    })
    ElMessage.success('反馈已提交，管理员会在运维中心处理')
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(error.message || '反馈提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.feedback-event-title {
  margin-bottom: 18px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
  border: 1px solid var(--color-border-light);
  color: var(--color-text);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
}

.full-width {
  width: 100%;
}
</style>
