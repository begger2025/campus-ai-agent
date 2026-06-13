import { createRouter, createWebHistory } from 'vue-router'
import { getCurrentRole, isAuthenticated } from '@/auth/session'

import MainLayout from '@/layouts/MainLayout.vue'
import HomeView from '@/views/HomeView.vue'
import SentimentView from '@/views/SentimentView.vue'
import PersonalView from '@/views/PersonalView.vue'
import EventListView from '@/views/EventListView.vue'
import EventDetailView from '@/views/EventDetailView.vue'
import OpinionView from '@/views/OpinionView.vue'
import LoginView from '@/views/LoginView.vue'
import ForbiddenView from '@/views/ForbiddenView.vue'
import NotFoundView from '@/views/NotFoundView.vue'

// 管理后台视图（懒加载，仅 admin 角色可访问）
const AdminOverviewView = () => import('@/views/admin/AdminOverviewView.vue')
const AdminEventsView = () => import('@/views/admin/AdminEventsView.vue')
const AdminRawPostsView = () => import('@/views/admin/AdminRawPostsView.vue')
const AdminOpsView = () => import('@/views/admin/AdminOpsView.vue')

const routes = [
  // 登录页 — 独立布局，无侧边栏
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { title: '登录', guest: true },
  },

  // 主布局 — 所有需认证页面
  {
    path: '/',
    component: MainLayout,
    children: [
      {
        path: '',
        name: 'Home',
        component: HomeView,
        meta: { title: '首页', subtitle: '校园舆情仪表盘' },
      },
      {
        path: 'sentiment',
        name: 'Sentiment',
        component: SentimentView,
        meta: { title: '舆情分析', subtitle: '公共舆情数据分析' },
      },
      {
        path: 'events',
        name: 'EventList',
        component: EventListView,
        meta: { title: '事件列表', subtitle: '公开舆情事件浏览' },
      },
      {
        path: 'events/:id',
        name: 'EventDetail',
        component: EventDetailView,
        meta: { title: '事件详情' },
      },
      {
        path: 'opinion',
        name: 'Opinion',
        component: OpinionView,
        meta: { title: '舆情工作台', subtitle: 'Agent 辅助分析', roles: ['user', 'admin'] },
      },
      {
        path: 'personal',
        name: 'Personal',
        component: PersonalView,
        meta: { title: '个人事项', subtitle: '日程与待办管理', roles: ['user', 'admin'] },
      },

      // ── 管理后台（仅 admin）──
      {
        path: 'admin',
        name: 'AdminOverview',
        component: AdminOverviewView,
        meta: { title: '后台概览', subtitle: '管理员仪表盘', roles: ['admin'] },
      },
      {
        path: 'admin/events',
        name: 'AdminEvents',
        component: AdminEventsView,
        meta: { title: '事件审核', subtitle: '管理员事件管理', roles: ['admin'] },
      },
      {
        path: 'admin/raw-posts',
        name: 'AdminRawPosts',
        component: AdminRawPostsView,
        meta: { title: '原始数据', subtitle: '采集数据浏览', roles: ['admin'] },
      },
      {
        path: 'admin/ops',
        name: 'AdminOps',
        component: AdminOpsView,
        meta: { title: '运营管理', subtitle: '反馈 · 爬虫 · 日志', roles: ['admin'] },
      },

      {
        path: 'forbidden',
        name: 'Forbidden',
        component: ForbiddenView,
        meta: { title: '无权限访问', subtitle: '403 Forbidden' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'NotFound',
        component: NotFoundView,
        meta: { title: '页面未找到', subtitle: '404 Not Found' },
      },
    ],
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

router.beforeEach((to, from, next) => {
  // 登录页始终可访问
  if (to.meta.guest) return next()

  // 未登录 → 跳转登录页
  if (!isAuthenticated()) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  // 角色权限检查
  const requiredRoles = to.meta.roles
  if (requiredRoles && requiredRoles.length) {
    const role = getCurrentRole()
    if (!requiredRoles.includes(role)) {
      return next({ name: 'Forbidden' })
    }
  }

  next()
})

export default router
