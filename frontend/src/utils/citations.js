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

// 裸编号形态（「e1 的 risk_reasons」「p4 仅能支持」）。\b 保证 top1 / P2P
// 这类普通英文词不被误伤：p/e 前后必须是词边界（中文字符对 \b 是非词字符，
// 所以「但e1的」也能命中）。
const BARE_CITE_ID = /\b[pPeE][0-9]+\b/g

/**
 * 把文本里的内部编号翻译成人话——给「审校提示」这类**转述**引用的场合用。
 *
 * critic 的 issue 原文里既有完整标记 [来源:e1]，也有裸编号（"e1 的 risk_reasons
 * 仅写明…"）。编号是审计口径，issues 数据里保留；但直接展示给用户就是天书
 * （实测截图）。这里统一换成「事件“东校区宿舍搬迁”」「帖子“标题…”」。
 * 查不到的编号原样保留——宁可露出编号，不可吞掉内容。
 */
export function humanizeCiteIds(text, citations) {
  const source = String(text || '')
  if (!citations) return source
  const label = (raw) => {
    const entry = citations[normalizeCiteId(raw)]
    const title = String(entry?.title || '')
    if (!title) return null
    const kind = normalizeCiteId(raw).startsWith('e') ? '事件' : '帖子'
    return `${kind}“${title.length > 16 ? `${title.slice(0, 16)}…` : title}”`
  }
  return source
    .replace(CITE_MARK, (_match, group) => {
      const names = group.split(/[,，、]/).map((raw) => label(raw) || raw.trim())
      return `[来源:${names.join('、')}]`
    })
    .replace(BARE_CITE_ID, (raw) => label(raw) || raw)
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
