// 面试页和报告页共用的两种文字处理
import type { ReactNode } from 'react'

/** 回答里被评分引用的原话画下划线（引用都经后端核实过，逐字出自回答） */
export function underline(text: string, quotes: string[]): ReactNode {
  const ranges = quotes.flatMap((q) => {
    const at = q ? text.indexOf(q) : -1
    return at >= 0 ? [[at, at + q.length] as const] : []
  }).sort((a, b) => a[0] - b[0])
  const out: ReactNode[] = []
  let pos = 0
  for (const [s, e] of ranges) {
    if (s < pos) continue
    out.push(text.slice(pos, s), <span key={s} className="iv-ev">{text.slice(s, e)}</span>)
    pos = e
  }
  out.push(text.slice(pos))
  return out
}

/** 参考答法里的【】是留给用户按实际填的，标颜色 */
export function placeholders(text: string): ReactNode {
  return text.split(/(【[^【】]*】)/).map((part, i) => (part.startsWith('【') ? <span key={i} className="ph">{part}</span> : part))
}
