<template>
  <main class="login-page">
    <header class="login-top">
      <router-link class="brand" to="/">
        <span class="brand-mark">
          <span class="brand-eye"></span>
        </span>
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
        <h1 id="login-title">校园公共舆情分析平台</h1>
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
          <p>请输入账号和密码登录系统</p>
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
            <button class="text-link" type="button">忘记密码</button>
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
            <button class="text-link" type="button">申请开通</button>
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
      <button type="button">用户协议</button>
      和
      <button type="button">隐私政策</button>
    </footer>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
import { getDefaultPathForRole, logout, saveSessionFromLoginResponse } from '@/auth/session'
import { login } from '@/api/auth'

const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const remember = ref(false)
const loading = ref(false)

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

async function handleLogin() {
  const u = username.value.trim()
  const p = password.value
  if (!u || !p) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    // 先清旧 session，防止上一个登录用户的角色残留
    logout()
    const data = await login(u, p)
    const session = saveSessionFromLoginResponse(data)
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' ? redirect : getDefaultPathForRole(session.user.role))
  } catch (error) {
    // 401 → 用户名或密码错误，其他错误直接展示 message
    const msg = error?.response?.status === 401
      ? '用户名或密码错误'
      : (error.message || '登录失败，请稍后再试')
    ElMessage.error(msg)
  } finally {
    loading.value = false
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
    radial-gradient(circle at 8% 12%, rgba(15, 99, 255, 0.07), transparent 28%),
    linear-gradient(180deg, #fbfdff 0%, #f5f8fc 100%);
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

.brand-mark {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  background: #eef6ff;
  border: 1px solid #cfe2ff;
  border-radius: 12px;
}

.brand-mark::before {
  content: '';
  width: 24px;
  height: 17px;
  border: 2px solid #101828;
  border-radius: 8px;
  background: #fff;
}

.brand-mark::after {
  content: '';
  position: absolute;
  top: 6px;
  width: 13px;
  height: 7px;
  border-top: 2px solid #101828;
}

.brand-eye {
  position: absolute;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 10px 0 0 var(--color-primary);
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
  border: 0;
  background: transparent;
  color: #1d2939;
  font-weight: 600;
  cursor: pointer;
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
  font-size: 28px;
  line-height: 1.25;
  color: #0f1f3d;
}

.intro-subtitle {
  margin: 0;
  font-size: 15px;
  color: #51627a;
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
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f1f6ff;
  border: 1px solid #dce8f7;
  color: var(--color-primary);
  font-size: 26px;
}

.feature-row strong {
  display: block;
  color: #14213d;
  font-size: 17px;
  margin-bottom: 7px;
}

.feature-row small {
  display: block;
  color: #51627a;
  line-height: 1.5;
  font-size: 14px;
}

.login-preview {
  margin-top: auto;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #dfe7f2;
  border-radius: 10px;
  box-shadow: 0 10px 28px rgba(15, 35, 66, 0.08);
  padding: 14px;
}

.preview-header {
  min-height: 30px;
  display: flex;
  align-items: center;
  font-size: 14px;
  color: #0f1f3d;
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
  border: 1px solid #e4ebf5;
  border-radius: 8px;
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
  background: #edf5ff;
  color: #0f63ff;
}

.kpi-red {
  background: #fff1f0;
  color: #e03137;
}

.kpi-green {
  background: #eefaf3;
  color: #19a765;
}

.preview-kpi small,
.preview-kpi strong {
  display: block;
}

.preview-kpi small {
  color: #66758a;
  font-size: 12px;
}

.preview-kpi strong {
  margin-top: 4px;
  color: #0f1f3d;
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
  color: #0f1f3d;
  font-size: 13px;
}

.preview-table-head button {
  border: 0;
  background: transparent;
  color: #4f5f76;
  cursor: pointer;
  font-size: 12px;
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  border: 1px solid #e4ebf5;
  border-radius: 8px;
  font-size: 12px;
}

.preview-table th {
  padding: 8px 10px;
  background: #f7f9fc;
  color: #66758a;
  text-align: left;
  font-weight: 600;
}

.preview-table td {
  padding: 8px 10px;
  border-top: 1px solid #e9eef6;
  color: #344054;
}

.preview-table td:first-child {
  max-width: 226px;
  color: #172033;
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
  background: #f04438;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}

.preview-table tr:nth-child(2) .rank-badge {
  background: #f79009;
}

.preview-table tr:nth-child(3) .rank-badge {
  background: #fdb022;
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
  color: #d46b08;
  background: #fff7e6;
  border: 1px solid #ffd591;
}

.risk-low {
  color: #099250;
  background: #ecfdf3;
  border: 1px solid #abefc6;
}

.login-card {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid #dfe7f2;
  border-radius: 10px;
  box-shadow: 0 18px 38px rgba(15, 35, 66, 0.1);
  padding: 34px 38px;
}

.login-card-header h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  color: #0f1f3d;
}

.login-card-header p {
  margin: 10px 0 0;
  color: #51627a;
  font-size: 14px;
}

.login-form {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  margin-top: 24px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 17px;
}

.login-form :deep(.el-form-item__label) {
  color: #344054;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 8px;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: 6px;
  box-shadow: 0 0 0 1px #d5deea inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 3px rgba(15, 99, 255, 0.12);
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
  border-radius: 6px;
  font-weight: 700;
}

.login-btn {
  margin-bottom: 10px;
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
  color: #66758a;
}

.login-info-box {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  min-height: 50px;
  padding: 12px 14px;
  border-radius: 7px;
  border: 1px solid #bad8ff;
  background: #eef6ff;
  color: #1f5fbf;
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
  color: #66758a;
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

  .login-form {
    margin-top: 18px;
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
