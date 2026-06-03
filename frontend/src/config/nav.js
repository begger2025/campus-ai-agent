const publicOpinionItems = [
  { path: '/', label: '首页', icon: '⌂', roles: ['guest', 'user', 'admin'] },
  { path: '/opinion', label: '舆情工作台', icon: '▣', roles: ['user', 'admin'] },
  { path: '/events', label: '事件列表', icon: '☰', roles: ['guest', 'user', 'admin'] },
]

const adminItems = [
  { path: '/admin', label: '后台概览', icon: '◇', roles: ['admin'] },
  { path: '/admin/events', label: '事件审核', icon: '✓', roles: ['admin'] },
  { path: '/admin/raw-posts', label: '数据管理', icon: '◎', roles: ['admin'] },
  { path: '/admin/ops', label: '运维反馈', icon: '!', roles: ['admin'] },
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
