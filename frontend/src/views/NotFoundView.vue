<template>
  <section class="error-page">
    <BrandLogo :size="48" />
    <div class="error-code">404</div>
    <h1>页面不存在</h1>
    <p>当前地址没有匹配到页面，可能链接已失效或输入有误。</p>
    <div class="error-actions">
      <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
      <el-button @click="$router.push('/events')">浏览公开事件</el-button>
    </div>
  </section>
</template>

<script setup>
import BrandLogo from '@/components/BrandLogo.vue'
</script>

<style scoped>
.error-page {
  min-height: 60vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
}

.error-code {
  margin-top: 20px;
  font-size: 64px;
  font-weight: 700;
  line-height: 1;
  color: var(--brand-200);
  letter-spacing: 0.04em;
}

h1 {
  margin: 12px 0 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
}

p {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--color-text-muted);
  max-width: 42ch;
  line-height: 1.7;
}

.error-actions {
  margin-top: 24px;
  display: flex;
  gap: 10px;
}
</style>
