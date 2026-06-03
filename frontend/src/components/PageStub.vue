<template>
  <section class="page-stub">
    <div class="stub-header panel-card">
      <div>
        <div class="stub-eyebrow">{{ eyebrow }}</div>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
      <div class="stub-actions">
        <el-tag type="info" effect="light">{{ packageName }}</el-tag>
        <el-button size="small" @click="$router.back()">返回</el-button>
      </div>
    </div>

    <div class="page-toolbar">
      <el-input :model-value="toolbarKeyword" placeholder="搜索关键词、事件标题、来源平台" style="max-width: 320px" />
      <el-select model-value="all" style="width: 132px">
        <el-option label="全部来源" value="all" />
      </el-select>
      <el-button type="primary">查询</el-button>
      <el-button>刷新</el-button>
    </div>

    <div class="stub-kpi-grid kpi-grid">
      <div v-for="item in kpis" :key="item.label" class="kpi-card">
        <span class="kpi-label">{{ item.label }}</span>
        <span class="kpi-value">{{ item.value }}</span>
      </div>
    </div>

    <div class="stub-workbench">
      <slot>
        <div class="panel-card stub-main-panel">
          <div class="panel-header">
            <span class="panel-title">功能区占位</span>
            <el-tag size="small">后续工作包接入</el-tag>
          </div>
          <div class="panel-body">
            <p>本页当前为 FE-01 视觉基线页面壳，后续工作包会补充真实业务内容和接口联调。</p>
          </div>
        </div>
      </slot>
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, required: true },
  eyebrow: { type: String, default: 'Campus AI Agent' },
  packageName: { type: String, default: 'FE-01' },
  toolbarKeyword: { type: String, default: '' },
  kpis: {
    type: Array,
    default: () => [
      { label: '待接入数据', value: '—' },
      { label: '页面模块', value: '3' },
      { label: '接口状态', value: 'Mock' },
      { label: '联调阶段', value: 'FE-01' },
      { label: '待办事项', value: '4' },
      { label: '验收状态', value: '可启动' },
    ],
  },
})
</script>

<style scoped>
.page-stub {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.stub-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
}

.stub-eyebrow {
  font-size: 12px;
  color: var(--color-primary);
  font-weight: 600;
  margin-bottom: 6px;
}

.stub-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.25;
}

p {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.stub-workbench {
  display: block;
}

.stub-main-panel {
  min-height: 260px;
}
</style>
