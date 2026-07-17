<template>
  <main ref="pageEl" class="login-page">
    <!-- 校园声音星座：动态背景，垫在所有内容下层 -->
    <LoginConstellation />

    <!-- 极光光晕层：两团缓慢漂移的模糊色斑（品牌靛 + 雾松绿），
         压在星座上、内容下，给纯深底加纵深。reduced-motion 时静止。 -->
    <div class="aurora" aria-hidden="true">
      <span class="aurora__blob aurora__blob--indigo"></span>
      <span class="aurora__blob aurora__blob--green"></span>
    </div>

    <header class="login-top">
      <router-link class="brand" to="/">
        <BrandLogo :size="40" />
        <span>
          <strong><GradientText :speed="9" :colors="BRAND_FLOW">校声智枢</GradientText></strong>
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

        <!-- 底部信任条：一句能力概述 + 数据口径，取代原先的假仪表盘预览 -->
        <div class="login-assurance">
          <span class="assurance-dot"></span>
          多平台聚合采集 · AI 事件聚类与风险研判 · 真实接口驱动
        </div>
      </section>

      <section v-spotlight="'rgba(160, 190, 250, 0.10)'" class="login-card" aria-label="登录账号">
        <!-- ClickSpark：卡内点击迸发雾松绿火花；canvas 覆层不拦截事件 -->
        <ClickSpark class="card-spark" spark-color="#8dbaab" :spark-radius="18">
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
        </ClickSpark>
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
  Right,
  TrendCharts,
  User,
} from '@element-plus/icons-vue'
import { login, register as registerApi } from '@/api/auth'
import { getDefaultPathForRole, setSession } from '@/auth/session'
import BrandLogo from '@/components/BrandLogo.vue'
import LoginConstellation from '@/components/LoginConstellation.vue'
import GradientText from '@/components/effects/GradientText.vue'
import ClickSpark from '@/components/effects/ClickSpark.vue'

// 品牌字的流动渐变：浅靛 → 雪白 → 雾松绿，呼应卡内主色
const BRAND_FLOW = ['#9db8f0', '#e8f0ff', '#8dbaab', '#e8f0ff', '#9db8f0']

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
    tl.from('.aurora', { autoAlpha: 0, duration: 1.4, ease: 'power1.out' }, 0)
      .from('.login-top', { y: -10, autoAlpha: 0, duration: 0.4 }, 0)
      .from('.title-char', { y: 14, autoAlpha: 0, filter: 'blur(6px)', duration: 0.45, stagger: 0.035 }, 0.08)
      .from('.intro-subtitle', { y: 12, autoAlpha: 0, duration: 0.4 }, '-=0.3')
      .from('.feature-row', { y: 14, autoAlpha: 0, duration: 0.4, stagger: 0.09 }, '-=0.15')
      .from('.login-assurance', { y: 12, autoAlpha: 0, duration: 0.4 }, '-=0.2')
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
  /* 深藏青兜底色（Canvas 星座会覆盖在上层提供渐变） */
  background: #081733;
  padding: 22px 46px 24px;
  color: #eaf0fb;
}

/* 所有直接内容层抬到星座（z-index:0）之上 */
.login-top,
.login-shell,
.login-footer {
  position: relative;
  z-index: 1;
}

/* ===== 极光光晕层：星座之上、内容之下 ===== */
.aurora {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.aurora__blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  will-change: transform;
  animation: aurora-drift 22s ease-in-out infinite alternate;
}

.aurora__blob--indigo {
  width: 48vw;
  height: 48vw;
  top: -18vw;
  left: -10vw;
  background: radial-gradient(circle, rgba(78, 108, 214, 0.34), transparent 65%);
}

.aurora__blob--green {
  width: 40vw;
  height: 40vw;
  right: -12vw;
  bottom: -16vw;
  background: radial-gradient(circle, rgba(76, 143, 116, 0.26), transparent 65%);
  animation-delay: -11s;
  animation-duration: 26s;
}

@keyframes aurora-drift {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(6vw, 4vh) scale(1.12); }
}

@media (prefers-reduced-motion: reduce) {
  .aurora__blob { animation: none; }
}

/* ClickSpark 包裹层要接管登录卡原本的纵向 flex 布局（login-form 依赖 flex:1） */
.card-spark {
  display: flex;
  flex-direction: column;
  height: 100%;
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
  /* 用真实 padding 下移内容（不用 transform，避免与 GSAP 的 y 动画互相覆盖导致重叠） */
  padding-top: var(--intro-copy-offset);
  min-height: 0;
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

/* 「假仪表盘预览」的整套样式已随功能删除（审计清扫）：login-preview、preview 系列、
   kpi 系列、preview-table 系列、rank-badge、risk-pill 家族约 180 行孤儿 CSS——
   模板早已用 .login-assurance 信任条取代该预览块 */

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

  /* 预览块的矮屏调优亦随功能删除（审计清扫） */

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

/* ================= 深色主题覆盖（星座背景之上） =================
   登录卡保持浅色浮层不动；仅把外围文字/图标改为深底可读的浅色。 */
.login-intro h1 { color: #f4f8ff; }
.intro-subtitle { color: rgba(210, 222, 245, 0.85); }
.feature-row strong { color: #eef3fc; }
.feature-row small { color: rgba(190, 205, 234, 0.78); }
.feature-icon {
  background: rgba(90, 130, 210, 0.14);
  border-color: rgba(120, 160, 235, 0.28);
  color: #9db8f0;
}

/* 顶栏 */
.brand strong { color: #f4f8ff; }
.brand small { color: rgba(190, 205, 234, 0.7); }
.home-link { color: rgba(210, 222, 245, 0.85); }
.home-link:hover { background: rgba(255, 255, 255, 0.08); color: #fff; }

/* 底部信任条（取代原假仪表盘预览） */
.login-assurance {
  margin-top: auto;
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 9px 15px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(140, 175, 240, 0.18);
  color: rgba(214, 226, 248, 0.9);
  font-size: 13px;
  font-weight: 500;
  backdrop-filter: blur(4px);
}
.assurance-dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #6ba58d;
  box-shadow: 0 0 0 4px rgba(107, 165, 141, 0.16);
}

/* 页脚 */
.login-footer { color: rgba(190, 205, 234, 0.7); }
.login-footer button { color: #86a7f5; }

/* 登录卡：深底上加深投影，浮层感更强（本体仍是浅色卡） */
.login-card {
  box-shadow: 0 24px 60px rgba(3, 10, 28, 0.5);
}

@media (prefers-reduced-motion: reduce) {
  .login-assurance { backdrop-filter: none; }
}

/* ================= 登录卡：深色玻璃浮层 + 中大绿强调 =================
   不再是白板压在深色上，而是从星野里"浮"出的半透明深色面板；
   卡内 Element Plus 控件的主色统一切成中大绿，彻底脱离 AI 蓝白。 */
.login-card {
  /* 一处改主色，卡内输入焦点/勾选/主按钮全部跟随。
     柔化：降饱和的雾松绿，不再是电光翡翠 */
  --el-color-primary: #4c8f74;
  --el-color-primary-light-3: #6ba590;
  --el-color-primary-light-5: #8dbaab;
  --el-color-primary-light-7: #b3d1c6;
  --el-color-primary-light-8: #cbe0d9;
  --el-color-primary-light-9: #e6f1ec;
  background: linear-gradient(158deg, rgba(30, 52, 96, 0.66), rgba(15, 30, 60, 0.6));
  border: 1px solid rgba(150, 180, 235, 0.16);
  box-shadow: 0 24px 60px rgba(3, 10, 28, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(16px) saturate(1.08);
}

.login-card-header h2 { color: #f2f6ff; }
.login-card-header p { color: rgba(200, 214, 240, 0.66); }

/* 角色切换：深槽 + 浅色激活块 */
.role-tabs { background: rgba(0, 0, 0, 0.22); }
.role-tab { color: rgba(200, 214, 240, 0.7); }
.role-tab:hover { color: #eef4ff; }
.role-tab--active {
  color: #eafaf3;
  background: rgba(255, 255, 255, 0.1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
}

/* 表单标签 */
.login-form :deep(.el-form-item__label) { color: rgba(200, 214, 240, 0.75); }

/* 输入框：深色浅描边字段（不再是白框） */
.login-form :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.045);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.13) inset;
}
.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.26) inset;
}
.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #4c8f74 inset, 0 0 0 3px rgba(76, 143, 116, 0.18);
}
.login-form :deep(.el-input__inner) { color: #eaf0fb; }
.login-form :deep(.el-input__inner::placeholder) { color: rgba(190, 205, 234, 0.5); }
.login-form :deep(.el-input__prefix),
.login-form :deep(.el-input__suffix) { color: rgba(190, 205, 234, 0.6); }

/* 记住我 */
.login-form :deep(.el-checkbox__label) { color: rgba(200, 214, 240, 0.8); }

/* 链接：柔和绿调 */
.text-link { color: #7bb49f; }

/* 主按钮（type=primary 自动取上面的雾松绿），阴影也压柔和 */
.login-btn { box-shadow: 0 2px 12px rgba(40, 100, 78, 0.22); }
.login-btn:hover { box-shadow: 0 6px 16px rgba(40, 100, 78, 0.28); }

/* 游客按钮：浅描边幽灵按钮（显式盖掉原来的蓝色 border-color） */
.guest-btn {
  color: rgba(220, 232, 250, 0.9);
  border-color: rgba(255, 255, 255, 0.22);
  background: transparent;
}
.guest-btn:hover {
  color: #ffffff;
  border-color: rgba(255, 255, 255, 0.36);
  background: rgba(255, 255, 255, 0.06);
}

/* 注册引导 */
.apply-row { color: rgba(190, 205, 234, 0.66); }

/* 信息条：柔和绿调深色 */
.login-info-box {
  border-color: rgba(110, 165, 140, 0.24);
  background: rgba(90, 150, 125, 0.08);
  color: rgba(210, 232, 222, 0.88);
}
.login-info-box .el-icon { color: #6ba58d; }
</style>
