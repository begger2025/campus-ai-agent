<template>
  <PageStub title="页面不存在" description="当前路由没有匹配到页面。请通过左侧导航进入已定义的第二周页面。" package-name="FE-01">
    <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
  </PageStub>
</template>
<script setup>
import PageStub from '@/components/PageStub.vue'
</script>
