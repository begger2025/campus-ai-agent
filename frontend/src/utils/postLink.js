/**
 * 原帖跳转辅助。
 *
 * 小红书等平台的站外直链依赖采集时的访问凭证（xsec_token），会随时间失效；
 * 平台站内搜索页不需要凭证，作为直链失效时的备用入口。
 */

export const LINK_EXPIRY_TIP =
  '直链带有采集时的访问凭证，可能随时间失效；打不开时可用"搜索"在平台内查找同款帖子'

const SEARCH_BUILDERS = {
  xhs: (kw) => `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(kw)}`,
  weibo: (kw) => `https://s.weibo.com/weibo?q=${encodeURIComponent(kw)}`,
  tieba: (kw) => `https://tieba.baidu.com/f/search/res?qw=${encodeURIComponent(kw)}`,
}

/** 生成平台站内搜索链接；平台未知或无关键词时返回空串（调用方隐藏入口） */
export function platformSearchUrl(platform, keyword) {
  const build = SEARCH_BUILDERS[platform]
  const kw = (keyword || '').trim().slice(0, 30)
  if (!build || !kw) return ''
  return build(kw)
}
