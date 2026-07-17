/**
 * utils/citations.js — 简报引用标记（[来源:pN]/[来源:eN]）的前端解析与跳转解析。
 *
 * pN/eN 是后端「生成 → 确定性校验 → AI 审校」三方对口径用的内部编号
 * （见 backend/services/citations.py），直接漏给用户毫无意义（实测截图：
 * 正文里满是 e1、p3，读者不知道是什么）。前端把它们统一转成按首次出现
 * 编号的上标角标 [1][2]…，并用 done.citations（编号 → 标题/原帖 url/事件 id）
 * 解析出每个角标该跳去哪。
 *
 * 正则与后端 CITATION_PATTERN 同口径：全角括号/冒号、大写与全角 P/E、
 * 全角数字、[来源:p1,p2] 合并写法。两边不一致 = 后端校验放行的标记前端渲染不出来。
 */

export const CITE_MARK =
  /[[【［]\s*来源\s*[:：]\s*([pPeEｐＰｅＥ][0-9０-９]+(?:\s*[,，、]\s*[pPeEｐＰｅＥ][0-9０-９]+)*)\s*[\]】］]/g

const FULLWIDTH = {
  '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
  '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
  'ｐ': 'p', 'Ｐ': 'p', 'ｅ': 'e', 'Ｅ': 'e',
}

export function normalizeCiteId(raw) {
  return String(raw || '')
    .trim()
    .replace(/[０-９ｐＰｅＥ]/g, (ch) => FULLWIDTH[ch] || ch)
    .toLowerCase()
}

/** 文本中出现过的引用编号（归一化、按首次出现去重）——角标序号的唯一事实来源。
 *  流式期间正文只增不改，首次出现顺序不会变，所以边流边渲染序号也是稳定的。 */
export function extractCitations(text) {
  const seen = []
  for (const match of String(text || '').matchAll(CITE_MARK)) {
    for (const raw of match[1].split(/[,，、]/)) {
      const id = normalizeCiteId(raw)
      if (id && !seen.includes(id)) seen.push(id)
    }
  }
  return seen
}

// 帖子链接来自爬取数据，只放行 http(s)——与后端 _SAFE_URL_PREFIXES 同口径
export function isSafeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//.test(url)
}

/**
 * 一个引用编号 → 跳转目标。返回 null = 不可点（宁可不可点，不可点错）。
 *
 *   eN（事件级结论）→ 舆情工作台该事件（?event_id=，站内路由）
 *   pN 有原帖 url   → 原帖（新窗口）
 *   pN 无 url 有标题 → 舆情分析页站内搜索（?keyword=标题前缀）
 */
export function citeTarget(id, entry) {
  if (!entry) return null
  const title = String(entry.title || '')
  if (id.startsWith('e')) {
    if (!entry.event_id) return null
    return { href: `/opinion?event_id=${entry.event_id}`, external: false, kind: 'event', title }
  }
  if (isSafeUrl(entry.url)) {
    return { href: entry.url, external: true, kind: 'post', title }
  }
  if (title) {
    // LIKE 检索按标题前缀足够定位；整条长标题反而容易因清洗差异搜不到
    return { href: `/sentiment?keyword=${encodeURIComponent(title.slice(0, 24))}`, external: false, kind: 'post', title }
  }
  return null
}
