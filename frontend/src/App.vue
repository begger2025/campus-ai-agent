<template>
  <div class="layout">
    <!-- 侧边导航 -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-icon">🤖</span>
        <div class="brand-text">
          <div class="brand-name">校声智枢</div>
          <div class="brand-sub">Campus AI Agent</div>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-group-title">{{ group.title }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            active-class="nav-item--active"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            {{ item.label }}
          </router-link>
        </div>
      </nav>
    </aside>

    <!-- 主内容区 -->
    <div class="main-wrapper">
      <header class="topbar">
        <div class="topbar-title">
          <div class="page-title">{{ currentTitle }}</div>
          <div class="page-sub">公共信息分析 + 个人事务智能助理</div>
        </div>
        <div class="topbar-right">
          <el-tag type="primary" effect="light">周一至周五 · 在校</el-tag>
          <div class="user-info">
            <span class="user-name">林同学</span>
            <span class="user-role">软件工程 · 2023级</span>
          </div>
        </div>
      </header>

      <main class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const navGroups = [
  {
    title: '公共分析',
    items: [
      { path: '/', label: '首页仪表盘', icon: '🏠' },
      { path: '/sentiment', label: '舆情分析', icon: '📊' },
    ],
  },
  {
    title: '个人事务',
    items: [
      { path: '/personal', label: '个人事项', icon: '📋' },
    ],
  },
]

const currentTitle = computed(() => route.meta?.title || '首页')
</script>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ——————— 侧边栏 ——————— */
.sidebar {
  width: 236px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  height: 64px;
  border-bottom: 1px solid var(--color-border-light);
}

.brand-icon {
  font-size: 24px;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-light);
  border-radius: var(--radius);
}

.brand-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-primary);
}

.brand-sub {
  font-size: 11px;
  color: var(--color-text-muted);
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 16px 12px;
}

.nav-group {
  margin-bottom: 20px;
}

.nav-group-title {
  font-size: 11px;
  font-weight: 600;
  color: #a0a8b5;
  padding: 0 12px;
  margin-bottom: 6px;
  letter-spacing: 0.5px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: 13px;
  color: var(--color-text-secondary);
  transition: background 0.15s, color 0.15s;
  text-decoration: none;
  margin-bottom: 2px;
}

.nav-item:hover {
  background: #f4f7fb;
}

.nav-item--active {
  background: var(--color-primary-light) !important;
  color: var(--color-primary) !important;
  font-weight: 600;
}

.nav-icon {
  width: 16px;
  text-align: center;
  font-size: 15px;
}

/* ——————— 主区域 ——————— */
.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  height: 64px;
  background: #fff;
  border-bottom: 1px solid var(--color-border);
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.page-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
}

.page-sub {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
}

.user-role {
  font-size: 12px;
  color: var(--color-text-muted);
}

.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

/* 路由切换过渡 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
