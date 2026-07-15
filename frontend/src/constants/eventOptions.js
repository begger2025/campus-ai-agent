/**
 * constants/eventOptions.js — 事件筛选下拉的选项表
 *
 * 原先住在 mock/events.js 里，但它们是真实的界面配置（风险等级、平台清单），
 * 不是演示数据。mock 目录已随「静默降级假数据」一起删除，选项表搬到这里。
 */

/** 风险等级筛选选项 */
export const riskOptions = [
  { value: 'high', label: '高风险' },
  { value: 'medium', label: '中风险' },
  { value: 'low', label: '低风险' },
]

/** 来源平台筛选选项 */
export const sourceOptions = [
  { value: 'weibo', label: '微博' },
  { value: 'xhs', label: '小红书' },
  { value: 'tieba', label: '贴吧' },
  { value: 'zhihu', label: '知乎' },
  { value: 'ks', label: '快手' },
  { value: 'web', label: '网页证据' },
]
