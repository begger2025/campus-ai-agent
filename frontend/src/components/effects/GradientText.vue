<template>
  <span class="gradient-text" :style="styleVars"><slot /></span>
</template>

<script setup>
// 移植自 ReactBits GradientText（MIT + Commons Clause）：流动渐变文字。
// 用于标题/品牌字，正文禁用（可读性纪律）。
import { computed } from 'vue'

const props = defineProps({
  /** 渐变色列表，默认品牌靛蓝三阶 */
  colors: {
    type: Array,
    default: () => ['#7188e5', '#3b5bdb', '#9dadee', '#3b5bdb', '#7188e5'],
  },
  /** 一轮流动的秒数 */
  speed: { type: Number, default: 8 },
})

const styleVars = computed(() => ({
  '--gt-gradient': `linear-gradient(90deg, ${props.colors.join(', ')})`,
  '--gt-speed': `${props.speed}s`,
}))
</script>

<style scoped>
.gradient-text {
  background: var(--gt-gradient);
  background-size: 300% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: gt-flow var(--gt-speed) linear infinite;
}

@keyframes gt-flow {
  to { background-position: 300% 0; }
}
</style>
