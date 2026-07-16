import http from './http'

export async function fetchPosts(page = 1, pageSize = 20) {
  const data = await http.get('/posts', {
    params: { page, page_size: pageSize },
  })

  if (Array.isArray(data?.items)) {
    return data
  }

  throw new Error('Invalid posts API response')
}

/**
 * 舆情分析页的帖子：GET /api/sentiment/posts —— 查 processed_posts（已清洗、已打分）。
 *
 * 和 fetchPosts 的区别不是"换了个表"，是**这些帖子经过了分析**：带 sentiment /
 * risk_level / heat_score。fetchPosts 查的 raw_posts 没有这三样，所以舆情分析页
 * 原本的风险徽章永远显示「—」、风险筛选器对帖子完全失效。
 *
 * 检索和筛选都在服务端做：前端过滤只能覆盖"已经加载进来的那一页"，而库里有 397 条
 * ——用户搜「食堂」，第 101 条之后的食堂帖一条都搜不到，页面却看起来像搜了全库。
 *
 * 返回 { items, total, page, page_size }，total 是**筛选后的全库条数**。
 *
 * 筛选轴是**情绪**而不是风险：帖子级 risk_level 的真实分布是 low 385 / medium 12 /
 * high 0（帖子级风险是规则算的，LLM 研判在事件级），筛了等于没筛；而情绪的分布是
 * positive 155 / neutral 128 / negative 84 / controversial 30——那才是有信息量的轴。
 * 接口仍支持 risk 参数（帖子级风险模型改进后立刻可用），当前 UI 不传。
 */
export async function fetchSentimentPosts({
  page = 1,
  pageSize = 8,
  keyword = '',
  sentiment = '',
  risk = '',
} = {}) {
  const data = await http.get('/sentiment/posts', {
    params: { page, page_size: pageSize, keyword, sentiment, risk },
  })

  if (Array.isArray(data?.items)) {
    return data
  }

  throw new Error('Invalid sentiment posts API response')
}

/**
 * 舆情分析页的帖子层统计：GET /api/sentiment/stats
 *
 * 返回 { total, sentiment{4档}, platforms[], daily_trend[], top_posts[], trend_days }。
 * 聚合在服务端做——前端只看得见"已经加载进来的那一页"（8 条），算不出全库 395 条的分布。
 */
export async function fetchSentimentStats() {
  const data = await http.get('/sentiment/stats')
  if (data && typeof data.total === 'number') {
    return data
  }
  throw new Error('Invalid sentiment stats API response')
}
