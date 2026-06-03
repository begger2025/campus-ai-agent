<template>
  <span v-if="source !== 'real'" :class="['ds-badge', `ds-badge--${source}`]">
    <span class="ds-dot"></span>
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 'real' | 'mock' | 'demo' */
  source: {
    type: String,
    default: 'mock',
    validator: (v) => ['real', 'mock', 'demo'].includes(v),
  },
})

const label = computed(() => {
  if (props.source === 'mock') return 'Mock 数据'
  if (props.source === 'demo') return '离线 Demo'
  return ''
})
</script>

<style scoped>
.ds-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.ds-badge--mock {
  color: #9ca3af;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
}

.ds-badge--demo {
  color: #d97706;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.ds-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.ds-badge--mock .ds-dot {
  background: #d1d5db;
}

.ds-badge--demo .ds-dot {
  background: #f59e0b;
}
</style>
