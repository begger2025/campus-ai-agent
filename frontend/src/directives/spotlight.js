/**
 * v-spotlight — 鼠标跟随光效（移植自 ReactBits SpotlightCard，MIT + Commons Clause）
 *
 * 用法：<div v-spotlight> 或 <div v-spotlight="'rgba(59,91,219,0.12)'">
 * 只写两个 CSS 变量，视觉全在 style.css 的 .spotlight-surface（radial-gradient ::before）。
 * 触屏设备没有 hover，::before 永不显示，mousemove 也不会触发——无需特判。
 */
const handlers = new WeakMap()

export default {
  mounted(el, binding) {
    el.classList.add('spotlight-surface')
    if (typeof binding.value === 'string' && binding.value) {
      el.style.setProperty('--spotlight-color', binding.value)
    }
    const onMove = (event) => {
      const rect = el.getBoundingClientRect()
      el.style.setProperty('--mouse-x', `${event.clientX - rect.left}px`)
      el.style.setProperty('--mouse-y', `${event.clientY - rect.top}px`)
    }
    el.addEventListener('mousemove', onMove, { passive: true })
    handlers.set(el, onMove)
  },
  unmounted(el) {
    const onMove = handlers.get(el)
    if (onMove) el.removeEventListener('mousemove', onMove)
    handlers.delete(el)
  },
}
