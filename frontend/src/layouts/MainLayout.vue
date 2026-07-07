<template>
  <div class="app-layout">
    <transition name="backdrop">
      <div v-if="isMobile && mobileOpen" class="sidebar-backdrop" @click="mobileOpen = false" />
    </transition>

    <aside
      class="app-sidebar"
      :class="{
        'app-sidebar--collapsed': collapsed && !isMobile,
        'app-sidebar--mobile': isMobile,
        'app-sidebar--open': isMobile && mobileOpen,
      }"
    >
      <router-link class="sidebar-brand" to="/">
        <BrandLogo :size="36" />
        <span v-show="!collapsed || isMobile" class="brand-copy">
          <span class="brand-name">校声智枢</span>
          <span class="brand-sub">Campus AI Agent</span>
        </span>
      </router-link>

      <nav class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.title" class="nav-group">
          <div v-if="!collapsed || isMobile" class="nav-group-title">{{ group.title }}</div>
          <div v-else class="nav-group-rule" />
          <el-tooltip
            v-for="item in group.items"
            :key="item.path"
            :content="item.label"
            :disabled="!collapsed || isMobile"
            placement="right"
          >
            <router-link
              :to="item.path"
              class="nav-item"
              exact-active-class="nav-item--active"
            >
              <el-icon class="nav-icon" :size="17"><component :is="item.icon" /></el-icon>
              <span v-show="!collapsed || isMobile" class="nav-label">{{ item.label }}</span>
            </router-link>
          </el-tooltip>
        </div>
      </nav>

      <button
        v-if="!isMobile"
        class="collapse-btn"
        type="button"
        :title="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="toggleCollapsed"
      >
        <el-icon :size="15">
          <Expand v-if="collapsed" />
          <Fold v-else />
        </el-icon>
        <span v-show="!collapsed">收起侧栏</span>
      </button>
    </aside>

    <div class="main-wrapper">
      <header class="topbar">
        <div class="topbar-left">
          <button v-if="isMobile" class="menu-btn" type="button" aria-label="打开导航" @click="mobileOpen = true">
            <el-icon :size="18"><Menu /></el-icon>
          </button>
          <div class="topbar-title">
            <div class="page-title">{{ currentTitle }}</div>
            <div class="page-sub">{{ currentSubtitle }}</div>
          </div>
        </div>
        <div class="topbar-right">
          <span class="topbar-chip topbar-chip--success">
            <span class="status-dot"></span>
            真实接口
          </span>
          <span class="topbar-chip topbar-chip--role">
            <el-icon :size="14"><UserFilled /></el-icon>
            {{ roleLabel }}
          </span>
          <el-button v-if="role === 'guest'" type="primary" @click="router.push('/login')">登录</el-button>
          <el-button v-else class="logout-btn" @click="handleLogout">退出</el-button>
        </div>
      </header>

      <main class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Expand, Fold, Menu, UserFilled } from '@element-plus/icons-vue'
import { getCurrentRole, getCurrentUser, logout } from '@/auth/session'
import { getNavGroups } from '@/config/nav'
import BrandLogo from '@/components/BrandLogo.vue'

const route = useRoute()
const router = useRouter()
const role = ref(getCurrentRole())

function syncRole() {
  role.value = getCurrentRole()
}

/* ---- 侧栏收起 / 响应式 ---- */
const COLLAPSE_KEY = 'ui:sidebar-collapsed'
const collapsed = ref(localStorage.getItem(COLLAPSE_KEY) === '1')
const isMobile = ref(false)
const mobileOpen = ref(false)

const mqTablet = window.matchMedia('(max-width: 1024px)')
const mqMobile = window.matchMedia('(max-width: 768px)')

function applyViewport() {
  isMobile.value = mqMobile.matches
  if (mqMobile.matches) {
    mobileOpen.value = false
  } else if (mqTablet.matches) {
    collapsed.value = true
  } else {
    collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1'
  }
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  if (!mqTablet.matches) {
    localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0')
  }
}

watch(() => route.path, () => {
  mobileOpen.value = false
})

onMounted(() => {
  window.addEventListener('auth:changed', syncRole)
  mqTablet.addEventListener('change', applyViewport)
  mqMobile.addEventListener('change', applyViewport)
  applyViewport()
})

onBeforeUnmount(() => {
  window.removeEventListener('auth:changed', syncRole)
  mqTablet.removeEventListener('change', applyViewport)
  mqMobile.removeEventListener('change', applyViewport)
})

const navGroups = computed(() => getNavGroups(role.value))
const currentTitle = computed(() => route.meta?.title || '首页')
const currentSubtitle = computed(() => route.meta?.subtitle || '公共舆情分析 Agent')
const user = computed(() => getCurrentUser())

const roleLabel = computed(() => {
  if (role.value === 'admin') return '管理员'
  if (role.value === 'user') return user.value?.displayName || '普通用户'
  return '游客'
})

function handleLogout() {
  logout()
  router.push('/login')
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--color-page);
}

/* ---- 侧栏 ---- */
.app-sidebar {
  width: 236px;
  flex-shrink: 0;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  transition: width var(--dur) var(--ease-out), transform var(--dur-slow) var(--ease-out);
  z-index: var(--z-sidebar);
}

.app-sidebar--collapsed {
  width: 68px;
}

.app-sidebar--mobile {
  position: fixed;
  inset: 0 auto 0 0;
  transform: translateX(-100%);
  box-shadow: none;
}

.app-sidebar--open {
  transform: translateX(0);
  box-shadow: var(--shadow-raised);
}

.sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(23, 32, 63, 0.4);
  z-index: calc(var(--z-sidebar) - 1);
}

.backdrop-enter-active,
.backdrop-leave-active {
  transition: opacity var(--dur) var(--ease-out);
}

.backdrop-enter-from,
.backdrop-leave-to {
  opacity: 0;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 0 16px;
  height: 64px;
  flex-shrink: 0;
  color: inherit;
  overflow: hidden;
}

.app-sidebar--collapsed .sidebar-brand {
  justify-content: center;
  padding: 0;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  white-space: nowrap;
}

.brand-name {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--color-text);
  line-height: 1.25;
}

.brand-sub {
  font-size: 11px;
  letter-spacing: 0.01em;
  color: var(--color-text-faint);
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 14px 12px;
}

.nav-group {
  margin-bottom: 20px;
}

.nav-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-faint);
  padding: 0 10px;
  margin-bottom: 8px;
  white-space: nowrap;
}

.nav-group-rule {
  height: 1px;
  background: var(--color-border-light);
  margin: 0 10px 10px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  color: var(--color-text-secondary);
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
  text-decoration: none;
  margin-bottom: 2px;
  white-space: nowrap;
}

.app-sidebar--collapsed .nav-item {
  justify-content: center;
  padding: 0;
}

.nav-item:hover {
  background: var(--color-surface-2);
  color: var(--color-text);
}

.nav-item:active {
  background: var(--brand-50);
}

.nav-item--active {
  background: var(--brand-50);
  color: var(--brand-700);
  font-weight: 600;
}

.nav-item--active .nav-icon {
  color: var(--brand-600);
}

.nav-icon {
  flex-shrink: 0;
  color: var(--color-text-muted);
  transition: color var(--dur-fast) var(--ease-out);
}

.nav-item:hover .nav-icon {
  color: var(--color-text-secondary);
}

.collapse-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 12px 14px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 0;
  background: transparent;
  color: var(--color-text-faint);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.app-sidebar--collapsed .collapse-btn {
  justify-content: center;
  padding: 8px 0;
}

.collapse-btn:hover {
  background: var(--color-surface-2);
  color: var(--color-text-secondary);
}

/* ---- 主区域 ---- */
.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  height: 64px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border-light);
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-shrink: 0;
  z-index: var(--z-topbar);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  flex-shrink: 0;
}

.topbar-title {
  min-width: 0;
}

.page-title {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--color-text);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.page-sub {
  font-size: 12px;
  color: var(--color-text-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.topbar-chip {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.topbar-chip--success {
  color: var(--color-success-text);
  background: var(--color-success-bg);
  border-color: #c8e5d0;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 0 3px rgba(52, 146, 75, 0.15);
}

.topbar-chip--role .el-icon {
  color: var(--color-text-faint);
}

.topbar-right :deep(.el-button) {
  transition: transform var(--dur-fast) var(--ease-out), background-color var(--dur-fast), border-color var(--dur-fast);
}

.topbar-right :deep(.el-button:active) {
  transform: scale(0.97);
}

.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 28px;
}

@media (max-width: 768px) {
  .topbar {
    padding: 0 14px;
  }

  .page-content {
    padding: 14px 14px 22px;
  }

  .page-sub {
    display: none;
  }

  .topbar-chip--success {
    display: none;
  }
}

/* 路由切换过渡：淡入 + 6px 上移 */
.page-enter-active {
  transition: opacity var(--dur) var(--ease-out), transform var(--dur) var(--ease-out);
}

.page-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out);
}

.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-leave-to {
  opacity: 0;
}
</style>
