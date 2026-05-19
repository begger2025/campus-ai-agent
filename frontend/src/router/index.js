import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import SentimentView from '@/views/SentimentView.vue'
import PersonalView from '@/views/PersonalView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: HomeView,
    meta: { title: '首页' },
  },
  {
    path: '/sentiment',
    name: 'Sentiment',
    component: SentimentView,
    meta: { title: '舆情分析' },
  },
  {
    path: '/personal',
    name: 'Personal',
    component: PersonalView,
    meta: { title: '个人事项' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} — Campus AI Agent`
    : 'Campus AI Agent'
})

export default router
