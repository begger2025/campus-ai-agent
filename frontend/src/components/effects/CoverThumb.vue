<template>
  <span
    class="cover-thumb"
    :style="{ width: `${size}px`, height: `${size}px`, background: gradient, fontSize: `${Math.round(size * 0.42)}px`, borderRadius: `${Math.max(6, Math.round(size * 0.18))}px` }"
    aria-hidden="true"
  >
    <b>{{ glyph }}</b>
  </span>
</template>

<script setup>
/**
 * CoverThumb — 生成式封面：从 seed 确定性地取一款双色渐变 + 首字。
 *
 * 为什么是生成式而不是真图：库里 173 条带图帖子的小红书 CDN 链接全部
 * 带小时级签名（实测连爬取次日就 403，加 UA/Referer 也无效，见
 * 2026-07-16 探针），真图路线不可行。生成式封面确定性强（同一帖子
 * 永远同一张脸）、零外部请求、零版权风险。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 决定渐变与首字的种子（帖子/事件标题） */
  seed: { type: String, default: '' },
  size: { type: Number, default: 40 },
})

// 八款压深的企业感双色渐变：与全站品牌靛/雾松绿/琥珀同族，深色保证白字可读
const GRADIENTS = [
  'linear-gradient(135deg, #5a74dd, #37479d)', // 品牌靛
  'linear-gradient(135deg, #2f9d8f, #1e6b64)', // 青
  'linear-gradient(135deg, #8168d6, #533f9e)', // 紫
  'linear-gradient(135deg, #d9962e, #a05f14)', // 琥珀
  'linear-gradient(135deg, #d26383, #963a55)', // 玫红
  'linear-gradient(135deg, #5a80b8, #33517d)', // 石蓝
  'linear-gradient(135deg, #4c8f74, #2d604b)', // 雾松绿（呼应登录页）
  'linear-gradient(135deg, #3e9ac2, #226285)', // 湖蓝
]

function hash(text) {
  let h = 0
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) >>> 0
  return h
}

const gradient = computed(() => GRADIENTS[hash(props.seed) % GRADIENTS.length])

// 首个非标点字符做封面字（emoji/标点开头时向后找）
const glyph = computed(() => {
  const match = String(props.seed).match(/[一-龥a-zA-Z0-9]/)
  return match ? match[0].toUpperCase() : '声'
})
</script>

<style scoped>
.cover-thumb {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
  color: rgba(255, 255, 255, 0.92);
}

.cover-thumb b {
  font-weight: 600;
  line-height: 1;
}

/* 左上斜向高光，给纯渐变一点"材质" */
.cover-thumb::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.22), transparent 42%);
  pointer-events: none;
}
</style>
