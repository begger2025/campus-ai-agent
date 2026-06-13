<template>
  <div class="app-layout">
    <aside class="app-sidebar">
      <router-link class="sidebar-brand" to="/">
        <span class="brand-mark">
          <span class="brand-eye"></span>
        </span>
        <span class="brand-copy">
          <span class="brand-name">校声智枢</span>
          <span class="brand-sub">Campus AI Agent</span>
        </span>
      </router-link>

      <nav class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-group-title">{{ group.title }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            exact-active-class="nav-item--active"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </nav>

      <button class="collapse-btn" type="button">‹ 收起</button>
    </aside>

    <div class="main-wrapper">
      <header class="topbar">
        <div class="topbar-title">
          <div class="page-title">{{ currentTitle }}</div>
          <div class="page-sub">{{ currentSubtitle }}</div>
        </div>
        <div class="topbar-right">
          <span class="topbar-chip topbar-chip--success">
            <span class="status-dot"></span>
            真实接口
          </span>
          <span class="topbar-chip">{{ roleLabel }}</span>
          <el-button size="small" class="icon-btn" @click="syncRole">刷新</el-button>
          <el-button size="small" class="icon-btn" @click="handleLogout">退出</el-button>
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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCurrentRole, getCurrentUser, logout } from '@/auth/session'
import { getNavGroups } from '@/config/nav'

const route = useRoute()
const router = useRouter()
const role = ref(getCurrentRole())
const user = ref(getCurrentUser())

function syncRole() {
  role.value = getCurrentRole()
  user.value = getCurrentUser()
}

onMounted(() => window.addEventListener('auth:changed', syncRole))
onBeforeUnmount(() => window.removeEventListener('auth:changed', syncRole))

const navGroups = computed(() => getNavGroups(role.value))
const currentTitle = computed(() => route.meta?.title || '首页')
const currentSubtitle = computed(() => route.meta?.subtitle || '公共舆情分析 Agent')

const roleLabel = computed(() => {
  if (role.value === 'admin') return `管理员 ${user.value?.displayName ? '· ' + user.value.displayName : ''}`
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
  overflow: hidden;
  background: var(--color-page);
}

.app-sidebar {
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
  height: 70px;
  border-bottom: 1px solid var(--color-border-light);
  color: inherit;
}

.brand-mark {
  width: 38px;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  background: var(--color-primary-light);
  border: 1px solid #cfe8ff;
  border-radius: 11px;
}

.brand-mark::before {
  content: '';
  width: 23px;
  height: 16px;
  border: 2px solid #172033;
  border-radius: 8px;
  background: #fff;
}

.brand-mark::after {
  content: '';
  position: absolute;
  top: 5px;
  width: 12px;
  height: 7px;
  border-top: 2px solid #172033;
}

.brand-eye {
  position: absolute;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 10px 0 0 var(--color-primary);
}

.brand-copy {
  display: flex;
  flex-direction: column;
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.brand-sub {
  font-size: 11px;
  color: var(--color-text-muted);
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 22px 10px;
}

.nav-group {
  margin-bottom: 22px;
}

.nav-group-title {
  font-size: 12px;
  font-weight: 600;
  color: #8491a5;
  padding: 0 12px;
  margin-bottom: 10px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 12px;
  border-radius: var(--radius);
  font-size: 14px;
  color: var(--color-text-secondary);
  transition: background 0.15s, color 0.15s;
  text-decoration: none;
  margin-bottom: 4px;
}

.nav-item:hover {
  background: #f4f7fb;
}

.nav-item--active {
  background: #0f63ff !important;
  color: #fff !important;
  font-weight: 600;
}

.nav-icon {
  width: 20px;
  text-align: center;
  font-size: 16px;
}

.collapse-btn {
  margin: 0 16px 18px;
  padding: 8px 10px;
  border-radius: var(--radius);
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  text-align: left;
  cursor: pointer;
}

.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  height: 70px;
  background: #fff;
  border-bottom: 1px solid var(--color-border);
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
}

.page-sub {
  font-size: 13px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.topbar-chip {
  height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 13px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  background: #fff;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.topbar-chip--success {
  color: #167a3d;
  background: #f4fbf6;
  border-color: #d8efdf;
}

.icon-btn {
  min-width: 48px;
}

.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
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
