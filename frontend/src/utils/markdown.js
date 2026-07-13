/**
 * 轻量 Markdown 渲染器 —— 专为舆情助手的回答格式设计，零依赖。
 *
 * 支持：#~###### 标题、| 表格 |（含对齐语法）、- / 1. 列表、
 * **加粗**、`行内代码`、--- 分隔线、段落（单换行转 <br>）。
 * 输入先整体做 HTML 转义，再套结构标签，v-html 使用是安全的。
 */

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

const TABLE_SEPARATOR = /^\s*\|?[\s:|-]+\|?\s*$/

function isTableRow(line) {
  return line.trim().startsWith('|')
}

function splitTableRow(line) {
  const cells = line.trim().split('|')
  if (cells.length && cells[0].trim() === '') cells.shift()
  if (cells.length && cells[cells.length - 1].trim() === '') cells.pop()
  return cells.map((cell) => cell.trim())
}

function cellAlign(sep) {
  const left = sep.startsWith(':')
  const right = sep.endsWith(':')
  if (left && right) return 'center'
  if (right) return 'right'
  return ''
}

export function renderMarkdown(source) {
  if (!source) return ''
  const lines = escapeHtml(source).split(/\r?\n/)
  const out = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    // 标题（# 越少字号越大，聊天场景收敛到 h3~h6）
    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = Math.min(Math.max(heading[1].length + 1, 3), 6)
      out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`)
      i += 1
      continue
    }

    // 分隔线
    if (/^([-*_])\1{2,}$/.test(trimmed)) {
      out.push('<hr>')
      i += 1
      continue
    }

    // 表格：表头行 + 分隔行
    if (
      isTableRow(trimmed) &&
      i + 1 < lines.length &&
      TABLE_SEPARATOR.test(lines[i + 1]) &&
      lines[i + 1].includes('-')
    ) {
      const headers = splitTableRow(trimmed)
      const aligns = splitTableRow(lines[i + 1]).map(cellAlign)
      i += 2
      const rows = []
      while (i < lines.length && isTableRow(lines[i].trim())) {
        rows.push(splitTableRow(lines[i].trim()))
        i += 1
      }
      const th = headers
        .map((cell, c) => `<th${aligns[c] ? ` style="text-align:${aligns[c]}"` : ''}>${renderInline(cell)}</th>`)
        .join('')
      const body = rows
        .map((row) => `<tr>${headers
          .map((_, c) => `<td${aligns[c] ? ` style="text-align:${aligns[c]}"` : ''}>${renderInline(row[c] ?? '')}</td>`)
          .join('')}</tr>`)
        .join('')
      out.push(`<div class="md-table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`)
      continue
    }

    // 无序列表
    if (/^[-*]\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(`<li>${renderInline(lines[i].trim().replace(/^[-*]\s+/, ''))}</li>`)
        i += 1
      }
      out.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    // 有序列表。三件事必须一起做，缺一个编号就会全变成"1."：
    //   1. 吸收缩进的续行/子弹点——LLM 的编号项下面常挂缩进的"- 热度：…"，
    //      不吸收的话每个编号项都会被打断成独立的 <ol>；
    //   2. 跳过项与项之间的空行（后面还是编号项就算同一张列表）；
    //   3. 用 <li value> / <ol start> 保留原文编号——即使列表真被拆开，
    //      浏览器也按原编号渲染，而不是每张都从 1 数起。
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items = []
      let start = null
      while (i < lines.length) {
        const raw = lines[i]
        const t = raw.trim()
        if (!t) {
          // 空行：向后看第一个非空行，还是编号项则视为同一张列表继续
          let j = i + 1
          while (j < lines.length && !lines[j].trim()) j += 1
          if (j < lines.length && /^\d+[.)]\s+/.test(lines[j].trim())) {
            i = j
            continue
          }
          break
        }
        const numbered = t.match(/^(\d+)[.)]\s+(.*)$/)
        if (numbered && (!/^\s/.test(raw) || !items.length)) {
          if (start === null) start = Number(numbered[1])
          items.push({ value: Number(numbered[1]), html: renderInline(numbered[2]), subs: [] })
          i += 1
          continue
        }
        // 缩进行归属当前编号项：子弹点变嵌套列表，普通文字接 <br>
        if (items.length && /^\s/.test(raw)) {
          const item = items[items.length - 1]
          if (/^[-*]\s+/.test(t)) {
            item.subs.push(`<li>${renderInline(t.replace(/^[-*]\s+/, ''))}</li>`)
          } else {
            item.html += `<br>${renderInline(t)}`
          }
          i += 1
          continue
        }
        break
      }
      const body = items
        .map((item) => `<li value="${item.value}">${item.html}${item.subs.length ? `<ul>${item.subs.join('')}</ul>` : ''}</li>`)
        .join('')
      out.push(`<ol start="${start ?? 1}">${body}</ol>`)
      continue
    }

    // 段落：连续普通行合并，单换行转 <br>
    const paragraph = []
    while (i < lines.length) {
      const next = lines[i].trim()
      if (
        !next ||
        /^(#{1,6})\s+/.test(next) ||
        /^[-*]\s+/.test(next) ||
        /^\d+[.)]\s+/.test(next) ||
        isTableRow(next) ||
        /^([-*_])\1{2,}$/.test(next)
      ) {
        break
      }
      paragraph.push(renderInline(next))
      i += 1
    }
    if (paragraph.length) {
      out.push(`<p>${paragraph.join('<br>')}</p>`)
    } else {
      // 兜底：形似表格行但没有分隔行等无法归类的行，按普通段落输出，保证游标前进
      out.push(`<p>${renderInline(trimmed)}</p>`)
      i += 1
    }
  }

  return out.join('')
}
