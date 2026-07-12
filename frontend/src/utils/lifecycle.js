/**
 * 事件状态（生命周期）的展示口径：**这件事完了没有**。
 *
 * 后端 GET /api/events 现在带 `lifecycle`（resolved / ongoing / escalating，由 LLM 读成员帖判出）
 * 和 `lifecycle_reason`（一句人话理由）。它是排序键的第四个因子：
 *
 *     priority = 严重性 × 时效性 × 生命周期({resolved: 0.5, ongoing: 2, escalating: 4, 未研判: 1})
 *
 * **为什么必须显示出来**：一个 3.5 个月前的火情排在第 4，和一个 2 个月前的实名举报排在第 1，
 * 光看"年龄"解释不了这个顺序——管理员有权一眼看到"凭什么"。理由就是那个"凭什么"
 * （「火势已控且校方通报无伤亡并启动调查」/「举报仍在追加，质疑范围继续扩大」）。
 *
 * `lifecycle` 为空 = 未研判（LLM 关掉/失败/老数据）：**不显示徽标**，也不显示"已了结"——
 * "不知道结没结" ≠ "已经结了"，界面上不许凭空替学校宣布一件事结束了。
 */

const LABELS = {
  resolved: '已了结',
  ongoing: '悬而未决',
  escalating: '持续发酵',
}

export function lifecycleLabel(lifecycle) {
  return LABELS[String(lifecycle || '').trim()] || ''
}

/** 有可展示的状态徽标吗（未研判 -> 没有）。 */
export function hasLifecycle(lifecycle) {
  return Boolean(lifecycleLabel(lifecycle))
}

/** 徽标的标题（hover 提示）：状态 + 模型给的理由 + 它对排序做了什么。 */
export function lifecycleTitle(lifecycle, reason) {
  const label = lifecycleLabel(lifecycle)
  if (!label) return ''
  const effect = {
    resolved: '已了结的事件在看板上加速沉底（优先级 ×0.5，相当于多老一个半衰期）',
    ongoing: '悬而未决的事件抗衰减（优先级 ×2，相当于年轻一个半衰期）',
    escalating: '持续发酵的事件抗衰减（优先级 ×4，相当于年轻两个半衰期）',
  }[lifecycle]
  const because = String(reason || '').trim()
  return because ? `${label}：${because}\n${effect}` : `${label}\n${effect}`
}
