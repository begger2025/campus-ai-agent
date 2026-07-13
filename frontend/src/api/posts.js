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
 */
export async function fetchSentimentPosts({ page = 1, pageSize = 8, keyword = '', risk = '' } = {}) {
  const data = await http.get('/sentiment/posts', {
    params: { page, page_size: pageSize, keyword, risk },
  })

  if (Array.isArray(data?.items)) {
    return data
  }

  throw new Error('Invalid sentiment posts API response')
}

export async function checkHealth() {
  return http.get('/ping')
}
