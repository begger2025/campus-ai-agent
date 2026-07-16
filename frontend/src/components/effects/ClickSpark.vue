<template>
  <div class="click-spark" @click="spawn">
    <canvas ref="canvasRef" class="click-spark__canvas" />
    <slot />
  </div>
</template>

<script setup>
// 移植自 ReactBits ClickSpark（MIT + Commons Clause）：点击迸发线条火花。
// 改进原版：rAF 循环只在有活跃火花时运行（原版常驻空转），空闲零开销。
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  sparkColor: { type: String, default: '#7188e5' },
  sparkSize: { type: Number, default: 10 },
  sparkRadius: { type: Number, default: 16 },
  sparkCount: { type: Number, default: 8 },
  duration: { type: Number, default: 400 },
})

const canvasRef = ref(null)
let sparks = []
let rafId = null
let resizeObserver = null
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

function resize() {
  const canvas = canvasRef.value
  const parent = canvas?.parentElement
  if (!canvas || !parent) return
  const { width, height } = parent.getBoundingClientRect()
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width
    canvas.height = height
  }
}

function draw(timestamp) {
  const canvas = canvasRef.value
  const ctx = canvas?.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  sparks = sparks.filter((spark) => {
    const elapsed = timestamp - spark.startTime
    if (elapsed >= props.duration) return false
    const t = elapsed / props.duration
    const eased = t * (2 - t) // ease-out
    const distance = eased * props.sparkRadius
    const lineLength = props.sparkSize * (1 - eased)
    ctx.strokeStyle = props.sparkColor
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(spark.x + distance * Math.cos(spark.angle), spark.y + distance * Math.sin(spark.angle))
    ctx.lineTo(
      spark.x + (distance + lineLength) * Math.cos(spark.angle),
      spark.y + (distance + lineLength) * Math.sin(spark.angle),
    )
    ctx.stroke()
    return true
  })

  rafId = sparks.length ? requestAnimationFrame(draw) : null
}

function spawn(event) {
  if (reduceMotion.matches) return
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  const now = performance.now()
  for (let i = 0; i < props.sparkCount; i += 1) {
    sparks.push({ x, y, angle: (2 * Math.PI * i) / props.sparkCount, startTime: now })
  }
  if (rafId === null) rafId = requestAnimationFrame(draw)
}

onMounted(() => {
  resize()
  resizeObserver = new ResizeObserver(resize)
  if (canvasRef.value?.parentElement) resizeObserver.observe(canvasRef.value.parentElement)
})

onBeforeUnmount(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.click-spark {
  position: relative;
  width: 100%;
  height: 100%;
}

.click-spark__canvas {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
</style>
