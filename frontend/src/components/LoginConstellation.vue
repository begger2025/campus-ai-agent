<template>
  <!-- 登录页动态背景：校园声音星座。纯装饰，屏读器忽略 -->
  <div class="constellation" aria-hidden="true">
    <canvas ref="canvasEl" class="constellation-canvas"></canvas>
    <!-- 顶部/底部渐隐，让内容区文字更透气 -->
    <div class="constellation-veil"></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 语义化动态背景：漂浮的"帖子"粒子彼此连线，时不时有一簇邻近节点被
 * 点亮成一个"事件"（中大绿脉冲）——映射舆情"聚合→聚类"的过程。
 * 部分节点携带校园话题关键词，点出"中山大学校园舆情"。
 *
 * 约束：Canvas 2D、零依赖、离线；prefers-reduced-motion 只画一帧静态星图；
 * 标签页不可见 / 组件离屏时暂停 rAF 省电；卸载时彻底清理。
 */

const canvasEl = ref(null)

// 校园话题关键词（真实校园事务口径，非杜撰品牌词）
const KEYWORDS = [
  '食堂排队', '宿舍热水', '教务系统', '选课', '图书馆', '奖学金',
  '迎新', '考研', '社团招新', '体育馆', '校车', '讲座', '宿舍搬迁', '食堂价格',
]

// 深藏青底上的配色（比 #00693E 中大绿提亮，深底上才看得清）
const COLOR = {
  node: '148, 176, 232',      // 柔和蓝：普通帖子
  nodeKw: '190, 208, 240',    // 关键词节点更亮些
  link: '96, 132, 205',       // 连线
  event: '104, 178, 148',     // 柔和雾松绿：事件点亮（降饱和，不刺眼）
}

let ctx = null
let raf = 0
let width = 0
let height = 0
let dpr = 1
let running = true
let visible = true
let nodes = []
let events = []
let lastEventAt = 0
let frame = 0
const pointer = { x: 0.5, y: 0.5, tx: 0.5, ty: 0.5 }

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
let io = null

const LINK_DIST = 132       // 连线距离阈值
const EVENT_EVERY = 2600    // 事件生成间隔（ms，用 frame 近似）

function rand(min, max) {
  return min + Math.random() * (max - min)
}

function seed() {
  // 面积自适应，桌面约 70~110 个节点
  const count = Math.max(46, Math.min(110, Math.round((width * height) / 15000)))
  const kwEvery = Math.max(4, Math.floor(count / KEYWORDS.length))
  nodes = []
  for (let i = 0; i < count; i++) {
    const withKw = i % kwEvery === 0
    nodes.push({
      x: rand(0, width),
      y: rand(0, height),
      vx: rand(-0.14, 0.14),
      vy: rand(-0.14, 0.14),
      r: withKw ? rand(2.4, 3.2) : rand(1, 2),
      kw: withKw ? KEYWORDS[(i / kwEvery) % KEYWORDS.length | 0] : null,
      glow: 0, // 被事件点亮的程度 0~1
    })
  }
}

function resize() {
  const el = canvasEl.value
  if (!el) return
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  const rect = el.getBoundingClientRect()
  width = rect.width
  height = rect.height
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  seed()
  if (reduceMotion.matches) drawStatic()
}

// 生成一个"事件"：以某节点为中心，点亮邻近节点
function spawnEvent() {
  if (!nodes.length) return
  const center = nodes[(Math.random() * nodes.length) | 0]
  const members = nodes.filter((n) => {
    const dx = n.x - center.x
    const dy = n.y - center.y
    return dx * dx + dy * dy < 150 * 150
  })
  if (members.length < 3) return
  events.push({ x: center.x, y: center.y, t: 0, life: 150, members })
}

function step() {
  frame++
  // 指针平滑跟随（整体轻微视差）
  pointer.x += (pointer.tx - pointer.x) * 0.05
  pointer.y += (pointer.ty - pointer.y) * 0.05
  const px = (pointer.x - 0.5) * 16
  const py = (pointer.y - 0.5) * 16

  for (const n of nodes) {
    n.x += n.vx
    n.y += n.vy
    if (n.x < -20) n.x = width + 20
    else if (n.x > width + 20) n.x = -20
    if (n.y < -20) n.y = height + 20
    else if (n.y > height + 20) n.y = -20
    n.glow *= 0.94 // 余晖衰减
  }

  // 事件节奏
  if (frame - lastEventAt > EVENT_EVERY / 16) {
    spawnEvent()
    lastEventAt = frame
  }
  for (const ev of events) {
    ev.t++
    const p = ev.t / ev.life
    const lit = Math.sin(Math.min(p, 1) * Math.PI) // 0→1→0
    for (const m of ev.members) m.glow = Math.max(m.glow, lit)
  }
  events = events.filter((ev) => ev.t < ev.life)

  draw(px, py)
}

function draw(px = 0, py = 0) {
  ctx.clearRect(0, 0, width, height)

  // 连线
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i]
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const d2 = dx * dx + dy * dy
      if (d2 > LINK_DIST * LINK_DIST) continue
      const d = Math.sqrt(d2)
      const t = 1 - d / LINK_DIST
      const lit = Math.max(a.glow, b.glow)
      const color = lit > 0.15 ? COLOR.event : COLOR.link
      ctx.strokeStyle = `rgba(${color}, ${(t * 0.22 + lit * 0.3).toFixed(3)})`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(a.x + px, a.y + py)
      ctx.lineTo(b.x + px, b.y + py)
      ctx.stroke()
    }
  }

  // 事件涟漪
  for (const ev of events) {
    const p = ev.t / ev.life
    const radius = 8 + p * 120
    const alpha = Math.max(0, 0.35 * (1 - p))
    ctx.strokeStyle = `rgba(${COLOR.event}, ${alpha.toFixed(3)})`
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(ev.x + px, ev.y + py, radius, 0, Math.PI * 2)
    ctx.stroke()
  }

  // 节点
  for (const n of nodes) {
    const base = n.kw ? COLOR.nodeKw : COLOR.node
    const color = n.glow > 0.15 ? COLOR.event : base
    const a = (n.kw ? 0.7 : 0.5) + n.glow * 0.5
    if (n.glow > 0.2) {
      ctx.shadowColor = `rgba(${COLOR.event}, ${(n.glow * 0.8).toFixed(3)})`
      ctx.shadowBlur = 10
    }
    ctx.fillStyle = `rgba(${color}, ${Math.min(a, 1).toFixed(3)})`
    ctx.beginPath()
    ctx.arc(n.x + px, n.y + py, n.r + n.glow * 1.5, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0

    // 关键词
    if (n.kw) {
      ctx.font = '11px "Helvetica Neue", Arial, "Microsoft YaHei", sans-serif'
      ctx.fillStyle = `rgba(${n.glow > 0.15 ? COLOR.event : COLOR.nodeKw}, ${(0.28 + n.glow * 0.5).toFixed(3)})`
      ctx.fillText(n.kw, n.x + px + 6, n.y + py + 3)
    }
  }
}

// reduced-motion：只画一帧静态星图（含少量已点亮的簇，避免死气沉沉）
function drawStatic() {
  for (let k = 0; k < 3; k++) spawnEvent()
  for (const ev of events) for (const m of ev.members) m.glow = 0.6
  draw()
  events = []
}

function tick() {
  if (running && visible) step()
  raf = requestAnimationFrame(tick)
}

function onPointerMove(e) {
  pointer.tx = e.clientX / window.innerWidth
  pointer.ty = e.clientY / window.innerHeight
}

function onVisibility() {
  visible = !document.hidden
}

onMounted(() => {
  const el = canvasEl.value
  ctx = el.getContext('2d')
  resize()

  if (reduceMotion.matches) {
    drawStatic()
    return // 不启动动画循环
  }

  window.addEventListener('resize', resize)
  window.addEventListener('pointermove', onPointerMove, { passive: true })
  document.addEventListener('visibilitychange', onVisibility)

  // 组件滚出视口就暂停（登录页一般不滚动，作为稳妥兜底）
  if ('IntersectionObserver' in window) {
    io = new IntersectionObserver((entries) => {
      running = entries[0]?.isIntersecting ?? true
    })
    io.observe(el)
  }

  raf = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', resize)
  window.removeEventListener('pointermove', onPointerMove)
  document.removeEventListener('visibilitychange', onVisibility)
  io?.disconnect()
})
</script>

<style scoped>
.constellation {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  /* 深藏青径向渐变底：中心稍亮，四周沉入近黑蓝 */
  background:
    radial-gradient(120% 90% at 30% 20%, #16305e 0%, #0e2249 38%, #081733 72%, #050f24 100%);
}

.constellation-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

/* 顶部与底部各压一层暗晕，让 logo 行与页脚文字更清楚 */
.constellation-veil {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(5, 15, 36, 0.55) 0%, rgba(5, 15, 36, 0) 22%,
      rgba(5, 15, 36, 0) 78%, rgba(5, 15, 36, 0.5) 100%);
}
</style>
