<template>
  <div class="stat-card" :class="`stat-card--${color}`">
    <div class="stat-top">
      <span class="stat-title">{{ title }}</span>
      <span class="stat-icon">{{ icon }}</span>
    </div>
    <div class="stat-value">{{ value }}</div>
    <div v-if="desc" class="stat-desc">{{ desc }}</div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  icon: { type: String, default: '📊' },
  desc: { type: String, default: '' },
  color: {
    type: String,
    default: 'primary',
    validator: v => ['primary', 'danger', 'warning', 'success', 'purple', 'teal', 'muted'].includes(v),
  },
})
</script>

<style scoped>
.stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  padding: 18px 20px;
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.15s;
}

.stat-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.stat-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stat-title {
  font-size: 12px;
  color: var(--color-text-muted);
}

.stat-icon {
  font-size: 18px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 6px;
}

.stat-desc {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 颜色变体 */
.stat-card--primary .stat-value { color: var(--color-primary); }
.stat-card--danger  .stat-value { color: var(--color-danger); }
.stat-card--warning .stat-value { color: var(--color-warning); }
.stat-card--success .stat-value { color: var(--color-success); }
.stat-card--purple  .stat-value { color: #722ed1; }
.stat-card--teal    .stat-value { color: #13c2c2; }
.stat-card--muted   .stat-value { color: var(--color-text-muted); }
</style>
