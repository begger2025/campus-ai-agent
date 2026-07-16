<template>
  <div class="empty-illust">
    <svg viewBox="0 0 120 88" :width="width" aria-hidden="true">
      <!-- 抽象场景：三张浮起的卡片 + 放大镜，全部走品牌色，空态不再是一个孤零零的图标 -->
      <rect x="14" y="20" width="52" height="12" rx="4" fill="var(--brand-100)" />
      <rect x="20" y="38" width="64" height="12" rx="4" fill="var(--brand-50)" stroke="var(--brand-100)" />
      <rect x="10" y="56" width="46" height="12" rx="4" fill="var(--brand-50)" />
      <circle cx="84" cy="52" r="17" fill="none" stroke="var(--brand-300)" stroke-width="4" />
      <line x1="96" y1="65" x2="108" y2="77" stroke="var(--brand-300)" stroke-width="5" stroke-linecap="round" />
      <circle cx="30" cy="14" r="3" fill="var(--brand-200, #b9c6f2)" />
      <circle cx="70" cy="10" r="2" fill="var(--brand-100)" />
    </svg>
    <p v-if="title">{{ title }}</p>
    <span v-if="hint">{{ hint }}</span>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  hint: { type: String, default: '' },
  width: { type: Number, default: 110 },
})
</script>

<style scoped>
.empty-illust {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 24px 12px;
  text-align: center;
}

.empty-illust p {
  margin: 4px 0 0;
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.empty-illust span {
  font-size: 12px;
  color: var(--color-text-faint, #a8abb2);
}

.empty-illust :deep(.el-button) {
  margin-top: 8px;
}
</style>
