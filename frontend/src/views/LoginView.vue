<template>
  <main ref="pageEl" class="login-page">
    <header class="login-top">
      <router-link class="brand" to="/">
        <BrandLogo :size="40" />
        <span>
          <strong>校声智枢</strong>
          <small>Campus AI Agent</small>
        </span>
      </router-link>

      <button class="home-link" type="button" @click="$router.push('/')">
        <el-icon><House /></el-icon>
        返回首页
      </button>
    </header>

    <section class="login-shell">
      <section class="login-intro" aria-labelledby="login-title">
        <h1 id="login-title" aria-label="校园公共舆情分析平台">
          <span
            v-for="(char, index) in titleChars"
            :key="index"
            class="title-char"
            :style="{ animationDelay: `${index * 45}ms` }"
            aria-hidden="true"
          >{{ char }}</span>
        </h1>
        <p class="intro-subtitle">
          面向学生、教师与管理人员的公共舆情事件浏览、分析与反馈入口
        </p>

        <div class="feature-list">
          <div v-for="item in features" :key="item.title" class="feature-row">
            <span class="feature-icon">
              <el-icon><component :is="item.icon" /></el-icon>
            </span>
            <span>
              <strong>{{ item.title }}</strong>
              <small>{{ item.desc }}</small>
            </span>
          </div>
        </div>

        <div class="login-preview login-dashboard">
          <div class="preview-header">
            <strong>舆情工作台 · 概览</strong>
          </div>

          <div class="preview-kpis">
            <div v-for="item in dashboardKpis" :key="item.label" class="preview-kpi">
              <span class="preview-kpi-icon" :class="item.className">
                <el-icon><component :is="item.icon" /></el-icon>
              </span>
              <span>
                <small>{{ item.label }}</small>
                <strong>{{ item.value }}</strong>
              </span>
            </div>
          </div>

          <div class="preview-table-wrap">
            <div class="preview-table-head">
              <strong>热点事件（示例）</strong>
              <button type="button" @click="$router.push('/events')">查看更多 ›</button>
            </div>
            <table class="preview-table">
              <thead>
                <tr>
                  <th>事件标题</th>
                  <th>热度</th>
                  <th>来源平台</th>
                  <th>风险等级</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="event in previewEvents" :key="event.rank">
                  <td>
                    <span class="rank-badge">{{ event.rank }}</span>
                    {{ event.title }}
                  </td>
                  <td>{{ event.heat }}</td>
                  <td>{{ event.source }}</td>
                  <td><span :class="['risk-pill', event.riskClass]">{{ event.risk }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="login-card" aria-label="登录账号">
        <div class="login-card-header">
          <h2>登录账号</h2>
          <p>请选择身份后继续访问系统</p>
        </div>

        <div class="role-tabs" role="tablist" aria-label="身份选择">
          <button
            v-for="item in roleOptions"
            :key="item.value"
            type="button"
            :class="['role-tab', { 'role-tab--active': role === item.value }]"
            @click="role = item.value"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            {{ item.label }}
          </button>
        </div>

        <el-form class="login-form" label-position="top" @submit.prevent="handleLogin">
          <el-form-item label="账号 / 学号 / 工号">
            <el-input
              v-model="username"
              :prefix-icon="User"
              placeholder="请输入账号 / 学号 / 工号"
              size="large"
            />
          </el-form-item>

          <el-form-item label="密码">
            <el-input
              v-model="password"
              :prefix-icon="Lock"
              placeholder="请输入密码"
              show-password
              size="large"
              type="password"
            />
          </el-form-item>

          <div class="form-row">
            <el-checkbox v-model="remember">记住我</el-checkbox>
            <button class="text-link" type="button" @click="ElMessage.info('请联系管理员重置密码')">忘记密码</button>
          </div>

          <el-button class="login-btn" size="large" type="primary" :loading="loading" @click="handleLogin">
            <el-icon><Right /></el-icon>
            登录
          </el-button>

          <el-button class="guest-btn" size="large" @click="$router.push('/events')">
            <el-icon><Aim /></el-icon>
            游客浏览公开事件
          </el-button>

          <div class="apply-row">
            <span>没有账号？</span>
            <button class="text-link" type="button" @click="register.visible = true">注册账号</button>
          </div>

          <div class="login-info-box">
            <el-icon><InfoFilled /></el-icon>
            <span>管理员登录后可进入事件审核、数据管理、爬虫任务与系统日志。</span>
          </div>
        </el-form>
      </section>
    </section>

    <footer class="login-footer">
      登录即表示同意
      <button type="button" @click="ElMessage.info('《用户协议》全文将在正式环境提供')">用户协议</button>
      和
      <button type="button" @click="ElMessage.info('《隐私政策》全文将在正式环境提供')">隐私政策</button>
    </footer>

    <!-- 注册对话框 -->
    <el-dialog v-model="register.visible" title="注册账号" width="420px">
      <el-form label-position="top" @submit.prevent="handleRegister">
        <el-form-item label="用户名（3-32 位字母、数字、下划线或短横线）">
          <el-input v-model="register.username" placeholder="用于登录的账号名" />
        </el-form-item>
        <el-form-item label="昵称（选填）">
          <el-input v-model="register.displayName" maxlength="64" placeholder="展示用昵称" />
        </el-form-item>
        <el-form-item label="密码（至少 8 位）">
          <el-input v-model="register.password" show-password type="password" placeholder="设置登录密码" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="register.confirm" show-password type="password" placeholder="再输入一次密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="register.visible = false">取消</el-button>
        <el-button type="primary" :loading="register.submitting" @click="handleRegister">
          注册并登录
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { gsap } from 'gsap'
import { ElMessage } from 'element-plus'
import {
  Aim,
  Document,
  House,
  InfoFilled,
  Lock,
  Management,
  Promotion,
  Right,
  TrendCharts,
  User,
} from '@element-plus/icons-vue'
import { login, register as registerApi } from '@/api/auth'
import { getDefaultPathForRole, setSession } from '@/auth/session'
import BrandLogo from '@/components/BrandLogo.vue'

const router = useRouter()
const route = useRoute()

// 演示账号仅用于快速填充表单，认证一律走后端 /api/auth/login。
const DEMO_CREDENTIALS = {
  user: { username: 'user', password: 'user123456' },
  admin: { username: 'admin', password: 'admin123456' },
}

const titleChars = '校园公共舆情分析平台'.split('')

/* ---- 入场编排：一条 master timeline 协调整页节奏 ---- */
const pageEl = ref(null)
let gsapCtx = null

onMounted(() => {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  gsapCtx = gsap.context(() => {
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from('.login-top', { y: -10, autoAlpha: 0, duration: 0.4 })
      .from('.title-char', { y: 14, autoAlpha: 0, filter: 'blur(6px)', duration: 0.45, stagger: 0.035 }, 0.08)
      // 副标题带静态 translateY 偏移，用相对值从"当前位置 +12px"滑回
      .from('.intro-subtitle', { y: '+=12', autoAlpha: 0, duration: 0.4 }, '-=0.3')
      .from('.feature-row', { y: 14, autoAlpha: 0, duration: 0.4, stagger: 0.09 }, '-=0.15')
      .from('.login-preview', { y: 18, autoAlpha: 0, duration: 0.45 }, '-=0.2')
      .from('.login-card', { y: 18, autoAlpha: 0, duration: 0.5 }, 0.22)
      .from('.login-footer', { autoAlpha: 0, duration: 0.4 }, '-=0.2')
  }, pageEl.value)
})

onUnmounted(() => gsapCtx?.revert())

const role = ref('user')
const username = ref(DEMO_CREDENTIALS.user.username)
const password = ref(DEMO_CREDENTIALS.user.password)
const remember = ref(false)
const loading = ref(false)

const register = reactive({
  visible: false,
  username: '',
  displayName: '',
  password: '',
  confirm: '',
  submitting: false,
})

const roleOptions = [
  { label: '普通用户', value: 'user', icon: User },
  { label: '管理员', value: 'admin', icon: Lock },
]

const features = [
  {
    title: '公开事件浏览',
    desc: '浏览已发布的舆情事件，了解校园热点动态与风险提示。',
    icon: Document,
  },
  {
    title: '舆情工作台',
    desc: '关键词分析、趋势洞察、智能问答，辅助舆情分析与研判。',
    icon: TrendCharts,
  },
  {
    title: '后台审核管理',
    desc: '管理员可进行事件审核、数据管理、任务调度与系统配置。',
    icon: Management,
  },
]

const dashboardKpis = [
  { label: '今日新增', value: '63', icon: TrendCharts, className: 'kpi-blue' },
  { label: '中高风险', value: '7', icon: Management, className: 'kpi-red' },
  { label: '已发布', value: '18', icon: Promotion, className: 'kpi-green' },
]

const previewEvents = [
  { rank: 1, title: '校园餐饮排队与价格争议升温', heat: 86, source: 3, risk: '中风险', riskClass: 'risk-mid' },
  { rank: 2, title: '宿舍热水供应不足问题集中反馈', heat: 58, source: 2, risk: '低风险', riskClass: 'risk-low' },
  { rank: 3, title: '二教新开轻食窗口价格偏高争议', heat: 54, source: 2, risk: '中风险', riskClass: 'risk-mid' },
]

watch(role, (nextRole) => {
  const demo = DEMO_CREDENTIALS[nextRole] || DEMO_CREDENTIALS.user
  username.value = demo.username
  password.value = demo.password
})

async function handleLogin() {
  if (loading.value) return
  loading.value = true
  try {
    const data = await login(username.value.trim(), password.value)
    // 角色以后端返回为准，登录页的角色切换只是演示账号快速填充。
    const session = setSession({
      token: data.access_token,
      user: {
        id: data.user.id,
        username: data.user.username,
        displayName: data.user.display_name || data.user.username,
        role: data.user.role,
      },
    })
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' ? redirect : getDefaultPathForRole(session.user.role))
  } catch (error) {
    const status = error.response?.status
    if (status === 401) {
      ElMessage.error('用户名或密码错误')
    } else if (status === 403) {
      ElMessage.error('该账号已被禁用，请联系管理员')
    } else {
      ElMessage.error(error.message || '登录失败，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  const name = register.username.trim()
  if (!/^[a-zA-Z0-9_-]{3,32}$/.test(name)) {
    ElMessage.warning('用户名需为 3-32 位字母、数字、下划线或短横线')
    return
  }
  if (register.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  if (register.password !== register.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  register.submitting = true
  try {
    const data = await registerApi({
      username: name,
      password: register.password,
      display_name: register.displayName.trim(),
    })
    setSession({
      token: data.access_token,
      user: {
        id: data.user.id,
        username: data.user.username,
        displayName: data.user.display_name || data.user.username,
        role: data.user.role,
      },
    })
    ElMessage.success('注册成功，已自动登录')
    register.visible = false
    router.push(getDefaultPathForRole(data.user.role))
  } catch (error) {
    if (error.response?.status === 409) {
      ElMessage.error('用户名已被占用，换一个试试')
    } else {
      ElMessage.error(error.message || '注册失败，请稍后重试')
    }
  } finally {
    register.submitting = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  min-height: 100dvh;
  position: relative;
  overflow: hidden;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(circle at 8% 12%, rgba(59, 91, 219, 0.07), transparent 30%),
    radial-gradient(circle at 92% 88%, rgba(59, 91, 219, 0.05), transparent 32%),
    linear-gradient(180deg, #fbfcfe 0%, #f2f4f9 100%);
  padding: 22px 46px 24px;
  color: var(--color-text);
}

.login-page *,
.login-page *::before,
.login-page *::after {
  box-sizing: border-box;
}

.login-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  max-width: 1190px;
  width: 100%;
  margin: 0 auto;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  color: var(--color-text);
}

.brand strong,
.brand small {
  display: block;
}

.brand strong {
  font-size: 18px;
  line-height: 1.1;
}

.brand small {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.home-link {
  height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-weight: 600;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.home-link:hover {
  background: rgba(59, 91, 219, 0.06);
  color: var(--color-text);
}

.login-shell {
  max-width: 1076px;
  width: 100%;
  height: clamp(660px, calc(100dvh - 142px), 980px);
  margin: clamp(18px, 2.3vh, 28px) auto 0;
  display: grid;
  grid-template-columns: 496px 482px;
  gap: 88px;
  align-items: stretch;
  flex: 0 1 auto;
}

.login-intro {
  --intro-copy-offset: clamp(36px, 5.8vh, 72px);
  display: flex;
  flex-direction: column;
  padding-top: 0;
  min-height: 0;
}

.login-intro h1,
.intro-subtitle,
.feature-list {
  transform: translateY(var(--intro-copy-offset));
}

.login-intro h1 {
  margin: 0 0 14px;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.25;
  color: var(--color-text);
}

.intro-subtitle {
  margin: 0;
  font-size: 15px;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 60px;
  margin-top: 30px;
  margin-bottom: 28px;
}

.feature-row {
  display: grid;
  grid-template-columns: 52px 1fr;
  gap: 14px;
  align-items: center;
}

.feature-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--radius);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  color: var(--color-primary);
  font-size: 26px;
}

.feature-row strong {
  display: block;
  color: var(--color-text);
  font-size: 17px;
  margin-bottom: 7px;
}

.feature-row small {
  display: block;
  color: var(--color-text-secondary);
  line-height: 1.5;
  font-size: 14px;
}

.login-preview {
  margin-top: auto;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: 0 10px 28px rgba(23, 32, 63, 0.08);
  padding: 14px;
}

.preview-header {
  min-height: 30px;
  display: flex;
  align-items: center;
  font-size: 14px;
  color: var(--color-text);
}

.preview-kpis {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 10px;
}

.preview-kpi {
  min-height: 56px;
  display: grid;
  grid-template-columns: 42px 1fr;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  background: #fff;
}

.preview-kpi-icon {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 20px;
}

.kpi-blue {
  background: var(--brand-50);
  color: var(--brand-600);
}

.kpi-red {
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

.kpi-green {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.preview-kpi small,
.preview-kpi strong {
  display: block;
}

.preview-kpi small {
  color: var(--color-text-muted);
  font-size: 12px;
}

.preview-kpi strong {
  margin-top: 4px;
  color: var(--color-text);
  font-size: 20px;
}

.preview-table-wrap {
  margin-top: 10px;
}

.preview-table-head {
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--color-text);
  font-size: 13px;
}

.preview-table-head button {
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  transition: color var(--dur-fast) var(--ease-out);
}

.preview-table-head button:hover {
  color: var(--color-primary);
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius);
  font-size: 12px;
}

.preview-table th {
  padding: 8px 10px;
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  text-align: left;
  font-weight: 600;
}

.preview-table td {
  padding: 8px 10px;
  border-top: 1px solid var(--color-border-light);
  color: var(--color-text-secondary);
}

.preview-table td:first-child {
  max-width: 226px;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rank-badge {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 8px;
  border-radius: 4px;
  background: var(--color-danger);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}

.preview-table tr:nth-child(2) .rank-badge {
  background: #c8830f;
}

.preview-table tr:nth-child(3) .rank-badge {
  background: #d3a04b;
}

.risk-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 600;
}

.risk-mid {
  color: var(--color-warning-text);
  background: var(--color-warning-bg);
  border: 1px solid #ecd9ae;
}

.risk-low {
  color: var(--color-success-text);
  background: var(--color-success-bg);
  border: 1px solid #c8e5d0;
}

.login-card {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: 0 18px 38px rgba(23, 32, 63, 0.1);
  padding: 34px 38px;
}

/* 入场编排由 GSAP timeline 驱动（见 script 中的 onMounted），此处只保留结构样式 */
.title-char {
  display: inline-block;
}

.login-card-header h2 {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.2;
  color: var(--color-text);
}

.login-card-header p {
  margin: 10px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.role-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin-top: 24px;
  padding: 4px;
  background: var(--color-bg);
  border-radius: var(--radius);
}

.role-tab {
  height: 38px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-weight: 600;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.role-tab:hover {
  color: var(--color-text);
}

.role-tab--active {
  color: var(--brand-700);
  background: #fff;
  box-shadow: var(--shadow-xs);
}

.login-form {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  margin-top: 20px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 17px;
}

.login-form :deep(.el-form-item__label) {
  color: var(--color-text-secondary);
  font-weight: 600;
  line-height: 1;
  margin-bottom: 8px;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: var(--radius-sm);
  box-shadow: 0 0 0 1px var(--color-border) inset;
  transition: box-shadow var(--dur-fast) var(--ease-out);
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #b6c2d9 inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 3px rgba(59, 91, 219, 0.14);
}

.form-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 18px;
}

.text-link {
  border: 0;
  background: transparent;
  color: var(--color-primary);
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}

.login-btn,
.guest-btn {
  width: 100%;
  margin: 0;
  border-radius: var(--radius-sm);
  font-weight: 600;
  transition: transform var(--dur-fast) var(--ease-out), background-color var(--dur-fast), border-color var(--dur-fast), box-shadow var(--dur-fast);
}

.login-btn:active,
.guest-btn:active {
  transform: scale(0.985);
}

.login-btn {
  margin-bottom: 10px;
  box-shadow: 0 2px 8px rgba(59, 91, 219, 0.28);
}

.login-btn:hover {
  box-shadow: 0 4px 12px rgba(59, 91, 219, 0.32);
}

.guest-btn {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.apply-row {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin: 18px 0 20px;
  color: var(--color-text-muted);
}

.login-info-box {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  min-height: 50px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--brand-100);
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: 13px;
  line-height: 1.55;
}

.login-info-box .el-icon {
  flex-shrink: 0;
  font-size: 17px;
}

.login-footer {
  flex: 0 0 auto;
  margin-top: 14px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
}

.login-footer button {
  border: 0;
  background: transparent;
  color: var(--color-primary);
  font-weight: 700;
  cursor: pointer;
  padding: 0 3px;
}

@media (max-width: 1080px) {
  .login-shell {
    grid-template-columns: 1fr;
    height: auto;
    max-width: 620px;
    gap: 24px;
  }

  .login-intro {
    padding-top: 24px;
  }

  .login-card {
    min-height: auto;
  }
}

@media (max-height: 860px) and (min-width: 1081px) {
  .login-page {
    padding-top: 18px;
    padding-bottom: 18px;
  }

  .login-shell {
    height: clamp(596px, calc(100dvh - 119px), 720px);
    margin-top: 14px;
    gap: 72px;
  }

  .login-intro {
    --intro-copy-offset: 12px;
  }

  .login-intro h1 {
    margin-bottom: 10px;
    font-size: 26px;
  }

  .intro-subtitle {
    line-height: 1.5;
  }

  .feature-list {
    gap: 40px;
    margin-top: 22px;
    margin-bottom: 20px;
  }

  .feature-row {
    grid-template-columns: 46px 1fr;
  }

  .feature-icon {
    width: 46px;
    height: 46px;
    font-size: 23px;
  }

  .feature-row strong {
    margin-bottom: 4px;
    font-size: 16px;
  }

  .login-preview {
    padding: 12px;
  }

  .preview-header {
    min-height: 26px;
  }

  .preview-kpis {
    gap: 10px;
    margin-top: 8px;
  }

  .preview-kpi {
    min-height: 50px;
    grid-template-columns: 36px 1fr;
    gap: 8px;
    padding: 7px 10px;
  }

  .preview-kpi-icon {
    width: 32px;
    height: 32px;
    font-size: 18px;
  }

  .preview-kpi strong {
    font-size: 18px;
  }

  .preview-table-head {
    height: 28px;
  }

  .preview-table th,
  .preview-table td {
    padding: 6px 10px;
  }

  .login-card {
    padding: 28px 36px;
  }

  .login-card-header h2 {
    font-size: 26px;
  }

  .login-card-header p {
    margin-top: 8px;
  }

  .role-tabs {
    margin-top: 18px;
  }

  .login-form {
    margin-top: 16px;
  }

  .login-form :deep(.el-form-item) {
    margin-bottom: 14px;
  }

  .form-row {
    margin-bottom: 14px;
  }

  .apply-row {
    margin: 14px 0 16px;
  }

  .login-info-box {
    min-height: 44px;
    padding: 10px 12px;
  }

  .login-footer {
    margin-top: 12px;
  }
}
</style>
