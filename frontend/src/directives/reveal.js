/**
 * v-reveal — 子元素进入视口时级联浮现（IntersectionObserver + CSS transition）
 *
 * 用法：挂在**列表容器**上 <div v-reveal>，动画作用于它的直接子元素。
 * 特意不用 scroll 监听（taste-skill 硬禁项）也不引 GSAP——纯 CSS transition，
 * 全局的 prefers-reduced-motion 降级自动生效。异步数据渲染出的新子元素由
 * updated 钩子补挂观察。
 */
const states = new WeakMap()

function observeChildren(el) {
  const state = states.get(el)
  if (!state) return
  Array.from(el.children).forEach((child) => {
    if (state.seen.has(child)) return
    state.seen.add(child)
    child.classList.add('reveal-item')
    // 级联延迟：同屏一批内按序错开，8 个一轮避免长列表尾部等太久
    child.style.transitionDelay = `${(state.count % 8) * 45}ms`
    state.count += 1
    state.io.observe(child)
  })
}

export default {
  mounted(el) {
    if (
      !('IntersectionObserver' in window) ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return // 不支持/用户要求减少动效：子元素保持默认可见，什么都不做
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return
          entry.target.classList.add('reveal-item--in')
          io.unobserve(entry.target)
        })
      },
      { threshold: 0.1 },
    )
    states.set(el, { io, seen: new WeakSet(), count: 0 })
    observeChildren(el)
  },
  updated(el) {
    observeChildren(el)
  },
  unmounted(el) {
    states.get(el)?.io.disconnect()
    states.delete(el)
  },
}
