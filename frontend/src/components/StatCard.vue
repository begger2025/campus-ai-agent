<template>
  <div class="stat-card" :class="`stat-card--${color}`">
    <span class="stat-chip">
      <el-icon v-if="isComponentIcon" :size="18"><component :is="icon" /></el-icon>
      <span v-else class="stat-emoji">{{ icon }}</span>
    </span>
    <div class="stat-body">
      <div class="stat-title">{{ title }}</div>
      <div v-if="loading" class="stat-skeleton" aria-label="加载中" />
      <div v-else class="stat-value">{{ displayValue }}</div>
      <div v-if="desc" class="stat-desc">{{ desc }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  /* 字符串（emoji，兼容旧用法）或图标组件 */
  icon: { type: [String, Object, Function], default: '📊' },
  desc: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  color: {
    type: String,
    default: 'primary',
    validator: v => ['primary', 'danger', 'warning', 'success', 'purple', 'teal', 'muted'].includes(v),
  },
})

const isComponentIcon = computed(() => typeof props.icon !== 'string')

/* ---- 数字滚动（CountUp）：仅对纯数字值生效，其余原样展示 ---- */
const numericValue = computed(() => {
  if (typeof props.value === 'number' && Number.isFinite(props.value)) return props.value
  const s = String(props.value).trim()
  return /^-?\d+(\.\d+)?$/.test(s) ? parseFloat(s) : null
})

const displayValue = ref(props.value)
let rafId = null
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

function animateTo(target, from) {
  cancelAnimationFrame(rafId)
  if (reduceMotion.matches || target === from) {
    displayValue.value = target
    return
  }
  const start = performance.now()
  const duration = 700
  const decimals = Number.isInteger(target) ? 0 : 1
  const step = (now) => {
    const t = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - t, 3)
    const v = from + (target - from) * eased
    displayValue.value = decimals ? v.toFixed(decimals) : Math.round(v)
    if (t < 1) rafId = requestAnimationFrame(step)
  }
  rafId = requestAnimationFrame(step)
}

watch(
  () => [numericValue.value, props.value],
  ([num], old) => {
    if (num === null) {
      cancelAnimationFrame(rafId)
      displayValue.value = props.value
      return
    }
    const prev = old && Number.isFinite(old[0]) ? old[0] : 0
    animateTo(num, prev)
  },
  { immediate: true },
)

onBeforeUnmount(() => cancelAnimationFrame(rafId))
</script>

<style scoped>
.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  padding: 16px 18px;
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.stat-card:hover {
  box-shadow: var(--shadow-card);
  transform: translateY(-1px);
}

.stat-chip {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  margin-top: 2px;
}

.stat-emoji {
  font-size: 17px;
  line-height: 1;
}

.stat-body {
  min-width: 0;
}

.stat-title {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 4px;
  white-space: nowrap;
}

/* 数值统一墨色，语义色由图标块承载（避免满屏彩色数字）。
   柔化：字重 600（不再是硬邦邦的 700）、冷调软墨（比纯黑 #262626 更柔）、
   等宽数字对齐、微负字距，让 KPI 更精致耐看。 */
.stat-value {
  font-size: 23px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: var(--color-ink-num);
  font-family: var(--font-numeric);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-skeleton {
  width: 56px;
  height: 22px;
  margin: 2px 0;
  border-radius: 4px;
  background: linear-gradient(90deg, #eef1f7 25%, #f6f8fb 50%, #eef1f7 75%);
  background-size: 200% 100%;
  animation: stat-shimmer 1.4s ease-in-out infinite;
}

@keyframes stat-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

.stat-desc {
  font-size: 12px;
  color: var(--color-text-faint);
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 图标块的语义色变体 */
.stat-card--primary .stat-chip { background: var(--brand-50); color: var(--brand-600); }
.stat-card--danger  .stat-chip { background: var(--color-danger-bg); color: var(--color-danger); }
.stat-card--warning .stat-chip { background: var(--color-warning-bg); color: var(--color-warning); }
.stat-card--success .stat-chip { background: var(--color-success-bg); color: var(--color-success); }
.stat-card--purple  .stat-chip { background: #f3effc; color: #7053c4; }
.stat-card--teal    .stat-chip { background: #e8f6f6; color: #17847e; }
.stat-card--muted   .stat-chip { background: #eef1f7; color: var(--color-text-muted); }
</style>
