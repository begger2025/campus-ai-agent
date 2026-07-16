<template>
  <component :is="as" class="star-border" :style="{ padding: `${thickness}px 0` }">
    <span class="star-border__strip star-border__strip--bottom" :style="stripStyle" />
    <span class="star-border__strip star-border__strip--top" :style="stripStyle" />
    <span class="star-border__inner"><slot /></span>
  </component>
</template>

<script setup>
// 移植自 ReactBits StarBorder（MIT + Commons Clause）：流光描边按钮。
// 只用于最高优先级 CTA（登录按钮级别），一页最多一个。
import { computed } from 'vue'

const props = defineProps({
  as: { type: String, default: 'button' },
  /** 流光颜色，默认品牌浅靛 */
  color: { type: String, default: '#9dadee' },
  /** 一轮流动秒数 */
  speed: { type: Number, default: 6 },
  thickness: { type: Number, default: 1 },
})

const stripStyle = computed(() => ({
  background: `radial-gradient(circle, ${props.color}, transparent 10%)`,
  animationDuration: `${props.speed}s`,
}))
</script>

<style scoped>
.star-border {
  display: inline-block;
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  border: 0;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
}

.star-border__strip {
  position: absolute;
  width: 300%;
  height: 50%;
  opacity: 0.7;
  border-radius: 50%;
  z-index: 0;
  pointer-events: none;
}

.star-border__strip--bottom {
  bottom: -11px;
  right: -250%;
  animation: star-move-bottom linear infinite alternate;
}

.star-border__strip--top {
  top: -10px;
  left: -250%;
  animation: star-move-top linear infinite alternate;
}

.star-border__inner {
  position: relative;
  z-index: 1;
  display: block;
  background: linear-gradient(to bottom, var(--brand-800), var(--brand-900));
  border: 1px solid rgba(157, 173, 238, 0.35);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  text-align: center;
  padding: 13px 26px;
  border-radius: 12px;
}

@keyframes star-move-bottom {
  0% { transform: translate(0, 0); opacity: 1; }
  100% { transform: translate(-100%, 0); opacity: 0; }
}

@keyframes star-move-top {
  0% { transform: translate(0, 0); opacity: 1; }
  100% { transform: translate(100%, 0); opacity: 0; }
}
</style>
