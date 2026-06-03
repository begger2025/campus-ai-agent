<template>
  <PageStub title="无权限访问" description="当前账号没有访问该页面的权限。请使用管理员账号登录，或返回公开页面。" package-name="FE-01">
    <el-button type="primary" @click="$router.push('/login')">重新登录</el-button>
    <el-button @click="$router.push('/')">返回首页</el-button>
  </PageStub>
</template>
<script setup>
import PageStub from '@/components/PageStub.vue'
</script>
