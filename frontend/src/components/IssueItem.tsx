// 结果页的一条问题：一行摘要，点开看依据、针对这一句的具体建议，以及「在原文中查看」
import { useState, type ReactNode } from 'react'

export type DetailRow = { label: string; value: string; quote?: boolean }

export function IssueItem({ index, tag, tagClass, text, why, rows, children, locate }: {
  index: number // 决定进场的先后
  tag: string
  tagClass: string // miss / part / high / med / low
  text: string
  why: string
  rows: DetailRow[]
  children?: ReactNode // 点开之后才挂载（具体建议在挂载时才开始生成，不能一进页面就全生成）
  locate?: { label: string; onClick: () => void }
}) {
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState(false)
  const toggle = () => {
    setOpen((o) => !o)
    setOpened(true)
  }
  return (
    <div className={`issue ${open ? 'open' : ''}`} style={{ animationDelay: `${(0.1 + index * 0.08).toFixed(2)}s` }}>
      <button type="button" className="issue-row" aria-expanded={open} onClick={toggle}>
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
            {opened && children}
            {locate && <button type="button" className="to-paper" onClick={locate.onClick} tabIndex={open ? 0 : -1}>{locate.label}</button>}
          </div>
        </div>
      </div>
    </div>
  )
}
