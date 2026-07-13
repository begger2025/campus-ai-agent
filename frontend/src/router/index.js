import { createRouter, createWebHistory } from 'vue-router'
import { getCurrentRole, isAuthenticated } from '@/auth/session'

import MainLayout from '@/layouts/MainLayout.vue'
import HomeView from '@/views/HomeView.vue'
import SentimentView from '@/views/SentimentView.vue'
import PersonalView from '@/views/PersonalView.vue'
import EventListView from '@/views/EventListView.vue'
import EventDetailView from '@/views/EventDetailView.vue'
import OpinionView from '@/views/OpinionView.vue'
import AgentChatView from '@/views/AgentChatView.vue'
import LoginView from '@/views/LoginView.vue'
import ForbiddenView from '@/views/ForbiddenView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import AdminOverviewView from '@/views/AdminOverviewView.vue'
import AdminEventsView from '@/views/AdminEventsView.vue'
import AdminRawPostsView from '@/views/AdminRawPostsView.vue'
import AdminKeywordsView from '@/views/AdminKeywordsView.vue'
import AdminEvidenceView from '@/views/AdminEvidenceView.vue'
import AdminOpsView from '@/views/AdminOpsView.vue'

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
        // 首页展示采集帖子数与最新帖子列表（原始数据）——那需要登录（见后端 /api/posts）。
        // 真正对游客公开的是**事件**：它们是人工审核发布过的对外结论。
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
        meta: { title: '事件列表', subtitle: '公开舆情事件浏览', public: true },
      },
      {
        path: 'events/:id',
        name: 'EventDetail',
        component: EventDetailView,
        meta: { title: '事件详情', public: true },
      },
      {
        path: 'opinion',
        name: 'Opinion',
        component: OpinionView,
        meta: { title: '舆情工作台', subtitle: 'Agent 辅助分析', roles: ['user', 'admin'] },
      },
      {
        path: 'agent-chat',
        name: 'AgentChat',
        component: AgentChatView,
        meta: { title: '舆情助手', subtitle: '对话式舆情问答（支持多步推理）', roles: ['user', 'admin'] },
      },
      {
        path: 'personal',
        name: 'Personal',
        component: PersonalView,
        meta: { title: '舆情关注', subtitle: '中高风险事件关注与影响评估', roles: ['user', 'admin'] },
      },
      {
        path: 'admin',
        name: 'AdminOverview',
        component: AdminOverviewView,
        meta: { title: '后台概览', subtitle: '数据与事件运营总览', roles: ['admin'] },
      },
      {
        path: 'admin/events',
        name: 'AdminEvents',
        component: AdminEventsView,
        meta: { title: '事件审核', subtitle: '舆情事件审核与发布', roles: ['admin'] },
      },
      {
        path: 'admin/raw-posts',
        name: 'AdminRawPosts',
        component: AdminRawPostsView,
        meta: { title: '数据管理', subtitle: '采集帖子浏览与筛选', roles: ['admin'] },
      },
      {
        path: 'admin/keywords',
        name: 'AdminKeywords',
        component: AdminKeywordsView,
        meta: { title: '智能选题', subtitle: '客观数据驱动的爬取关键词推荐', roles: ['admin'] },
      },
      {
        path: 'admin/evidence',
        name: 'AdminEvidence',
        component: AdminEvidenceView,
        meta: { title: '证据采集', subtitle: 'AI 联网检索证据采集与人工审核', roles: ['admin'] },
      },
      {
        path: 'admin/ops',
        name: 'AdminOps',
        component: AdminOpsView,
        meta: { title: '运维中心', subtitle: '反馈处理 · 采集任务 · 日志审计', roles: ['admin'] },
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

  // 公开页面（事件列表/事件详情）游客可浏览：已发布事件是**人工审核过的对外结论**。
  // 原始帖子不在此列——它是平台的内部数据，后端也加了登录门（见 routers/api.py）。
  if (to.meta.public) return next()

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
