<template>
  <svg
    class="brand-logo"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    aria-label="校声智枢"
  >
    <rect width="48" height="48" rx="12" fill="var(--brand-600, #3b5bdb)" />
    <rect width="48" height="48" rx="12" fill="url(#brand-sheen)" />
    <!-- 声波从两侧汇聚于中心枢纽 -->
    <circle cx="24" cy="24" r="3.4" fill="#fff" />
    <path d="M30.1 16.7 A9.5 9.5 0 0 1 30.1 31.3" stroke="#fff" stroke-width="2.6" stroke-linecap="round" />
    <path d="M17.9 16.7 A9.5 9.5 0 0 0 17.9 31.3" stroke="#fff" stroke-width="2.6" stroke-linecap="round" />
    <path d="M35.2 14 A15 15 0 0 1 35.2 34" stroke="#fff" stroke-opacity="0.55" stroke-width="2.6" stroke-linecap="round" />
    <path d="M12.8 14 A15 15 0 0 0 12.8 34" stroke="#fff" stroke-opacity="0.55" stroke-width="2.6" stroke-linecap="round" />
    <defs>
      <linearGradient id="brand-sheen" x1="24" y1="0" x2="24" y2="48" gradientUnits="userSpaceOnUse">
        <stop stop-color="#fff" stop-opacity="0.12" />
        <stop offset="1" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
    </defs>
  </svg>
</template>

<script setup>
defineProps({
  size: {
    type: [Number, String],
    default: 38,
  },
})
</script>

<style scoped>
.brand-logo {
  display: block;
  flex-shrink: 0;
}
</style>
