/**
 * 事件状态（生命周期）的展示口径：**这件事完了没有**。
 *
 * 后端 GET /api/events 带 `lifecycle`、`lifecycle_reason` 和 `growth`。它是排序键的第四个因子：
 *
 *     priority = 严重性 × 时效性
 *              × 生命周期({escalating: 4, ongoing: 2, resolved: 0.5, not_applicable: 0.5, 未研判: 1})
 *
 * **四个状态里有三个是 LLM 判的，一个是算出来的**：
 *
 *     resolved / ongoing / not_applicable   LLM 读帖子判的——「有没有一件悬而未决的事」（判断）
 *     escalating                            **算术**合成的——ongoing ∧「新帖还在来」（测量）
 *
 * 「持续发酵」曾经也是模型判的，结果它在 28 个事件上一次都没触发：模型读的是一份冻结的快照，
 * 看不见"新帖还在不在增加"，只能从**语气**里嗅发酵感。而每条帖子的发布时间就摆在那里——
 * **「还在不在长」是一个测量，不是一个判断**。现在它由后端按发帖速率算出来
 * （近 21 天的到帖速率 >= 该事件此前的速率，且窗口内至少 2 条新帖）。
 *
 * **所以「持续发酵」的徽标背后必须挂着证据**：`growth`（近 N 天新增几条 / 一共几条）。
 * 一个说不出依据的徽标只是一句主张；管理员点开就能看到"凭什么"，而且这个数字他能自己复核。
 *
 * `lifecycle` 为空 = 未研判（LLM 关掉/失败/老数据）：**不显示徽标**，也不显示"已了结"或"非事件"——
 * "不知道结没结" ≠ "已经结了"，"不知道是不是事件" ≠ "它不是事件"。界面上不许凭空替学校下结论。
 */

const LABELS = {
  resolved: '已了结',
  ongoing: '悬而未决',
  escalating: '持续发酵',
  not_applicable: '非事件',
}

export function lifecycleLabel(lifecycle) {
  return LABELS[String(lifecycle || '').trim()] || ''
}

/** 有可展示的状态徽标吗（未研判 -> 没有）。 */
export function hasLifecycle(lifecycle) {
  return Boolean(lifecycleLabel(lifecycle))
}

/**
 * 「还在发酵」的**算术证据**，一句人话。
 *
 * 这是「持续发酵」徽标的依据，也是它和其他三个状态的根本区别：另外三个是模型的判断（理由是
 * 一句话），这一个是**测量**（依据是一组可复核的数字）。没有数字就不该挂这个徽标。
 */
export function growthEvidence(growth) {
  if (!growth || !growth.growing) return ''
  const days = Math.round(Number(growth.window_days) || 0)
  const recent = Number(growth.recent_notes) || 0
  const total = Number(growth.total_notes) || 0
  return `近 ${days} 天新增 ${recent} 帖（共 ${total} 帖），发帖速率高于此前`
}

/** 徽标的标题（hover 提示）：状态 + 依据（模型的理由 / 算术的证据）+ 它对排序做了什么。 */
export function lifecycleTitle(lifecycle, reason, growth) {
  const label = lifecycleLabel(lifecycle)
  if (!label) return ''
  const effect = {
    resolved: '已了结的事件在看板上加速沉底（优先级 ×0.5，相当于多老一个半衰期）',
    ongoing: '悬而未决的事件抗衰减（优先级 ×2，相当于年轻一个半衰期）',
    escalating: '持续发酵的事件抗衰减（优先级 ×4，相当于年轻两个半衰期）',
    not_applicable:
      '咨询/攻略/分享类内容，没有需要学校处置的事（优先级 ×0.5，不与真实事件争版面）',
  }[lifecycle]
  const lines = [String(reason || '').trim() ? `${label}：${String(reason).trim()}` : label]
  // 「持续发酵」= 悬而未决（模型判的）+ 还在长（算术测的）。两半都要交代：
  // 上一行是模型"凭什么说它还没结"，这一行是算术"凭什么说它还在长"。
  const evidence = lifecycle === 'escalating' ? growthEvidence(growth) : ''
  if (evidence) lines.push(`发酵依据（算术）：${evidence}`)
  lines.push(effect)
  return lines.join('\n')
}
