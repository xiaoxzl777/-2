// 结果页的一条问题：一行摘要，点开看依据和针对这一句的具体建议。
// 展开与否由页面管（点右边原文里的高亮，要能把左边对应的这条展开）；窄屏多一个「在原文中查看」，宽屏原文常驻在右边
import { useState, type ReactNode } from 'react'

export type DetailRow = { label: string; value: string; quote?: boolean }

export function IssueItem({ itemKey, index, tag, tagClass, text, why, rows, children, locate, open, active = false, onToggle, onHover }: {
  itemKey: string // 写在 data-key 上：点了原文里的高亮，页面按它找到这一条、滚过来
  index: number // 决定进场的先后
  tag: string
  tagClass: string // miss / part / high / med / low
  text: string
  why: string
  rows: DetailRow[]
  children?: ReactNode // 点开之后才挂载（具体建议在挂载时才开始生成，不能一进页面就全生成）
  locate?: { label: string; onClick: () => void }
  open: boolean
  active?: boolean // 右边原文正指着这一条
  onToggle: () => void
  onHover?: (on: boolean) => void
}) {
  // 点开过一次就一直挂着，收起再展开不会重新生成
  const [opened, setOpened] = useState(open)
  if (open && !opened) setOpened(true)
  return (
    <div className={`issue${open ? ' open' : ''}${active ? ' active' : ''}`} data-key={itemKey} style={{ animationDelay: `${(0.1 + index * 0.05).toFixed(2)}s` }}
      onMouseEnter={onHover && (() => onHover(true))} onMouseLeave={onHover && (() => onHover(false))}>
      <button type="button" className="issue-row" aria-expanded={open} onClick={onToggle}>
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
