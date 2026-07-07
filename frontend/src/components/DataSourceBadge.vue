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
  color: var(--color-text-muted);
  background: #eef1f7;
  border: 1px solid var(--color-border);
}

.ds-badge--demo {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  border: 1px solid #ecd9ae;
}

.ds-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.ds-badge--mock .ds-dot {
  background: #b3bccb;
}

.ds-badge--demo .ds-dot {
  background: var(--color-warning);
}
</style>
