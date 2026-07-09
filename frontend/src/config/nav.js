import { markRaw } from 'vue'
import {
  ChatDotRound,
  Coin,
  DataAnalysis,
  DocumentChecked,
  House,
  List,
  MagicStick,
  Odometer,
  Operation,
  TrendCharts,
  View,
} from '@element-plus/icons-vue'

const publicOpinionItems = [
  { path: '/', label: '首页', icon: markRaw(House), roles: ['guest', 'user', 'admin'] },
  { path: '/opinion', label: '舆情工作台', icon: markRaw(DataAnalysis), roles: ['user', 'admin'] },
  { path: '/agent-chat', label: '舆情助手', icon: markRaw(ChatDotRound), roles: ['user', 'admin'] },
  { path: '/events', label: '事件列表', icon: markRaw(List), roles: ['guest', 'user', 'admin'] },
  { path: '/sentiment', label: '舆情分析', icon: markRaw(TrendCharts), roles: ['user', 'admin'] },
  { path: '/personal', label: '舆情关注', icon: markRaw(View), roles: ['user', 'admin'] },
]

const adminItems = [
  { path: '/admin', label: '后台概览', icon: markRaw(Odometer), roles: ['admin'] },
  { path: '/admin/events', label: '事件审核', icon: markRaw(DocumentChecked), roles: ['admin'] },
  { path: '/admin/raw-posts', label: '数据管理', icon: markRaw(Coin), roles: ['admin'] },
  { path: '/admin/keywords', label: '智能选题', icon: markRaw(MagicStick), roles: ['admin'] },
  { path: '/admin/ops', label: '运维反馈', icon: markRaw(Operation), roles: ['admin'] },
]

export function getNavGroups(role = 'guest') {
  const groups = [
    {
      title: '公共舆情',
      items: publicOpinionItems.filter((item) => item.roles.includes(role)),
    },
  ]

  const visibleAdminItems = adminItems.filter((item) => item.roles.includes(role))
  if (visibleAdminItems.length) {
    groups.push({
      title: '后台管理',
      items: visibleAdminItems,
    })
  }

  return groups
}
