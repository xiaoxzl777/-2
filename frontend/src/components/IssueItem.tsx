// 结果页的一条问题：一行摘要，点开看简历原文、依据、建议。原文高亮下一轮再做
import { useState } from 'react'

export type DetailRow = { label: string; value: string; quote?: boolean }

export function IssueItem({ index, tag, tagClass, text, why, rows }: {
  index: number // 决定进场的先后
  tag: string
  tagClass: string // miss / part / high / med / low
  text: string
  why: string
  rows: DetailRow[]
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`issue ${open ? 'open' : ''}`} style={{ animationDelay: `${(0.1 + index * 0.08).toFixed(2)}s` }}>
      <button type="button" className="issue-row" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className={`tagx ${tagClass}`}>{tag}</span>
        <span className="issue-text"><span className="main">{text}</span><span className="why">{why}</span></span>
        <span className="issue-arrow" aria-hidden="true">›</span>
      </button>
      <div className="detail" aria-hidden={!open}>
        <div>
          <div className="detail-in">
            {rows.map((r) => (
              <p key={r.label} className={r.quote ? 'q' : undefined}><span className="k">{r.label}</span><span>{r.value}</span></p>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
