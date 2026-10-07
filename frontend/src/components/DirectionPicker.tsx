// 工作台第一步：选求职方向。下拉框单独一屏、做大；选中后下面说明这个方向有什么不同。
// 以后方向多了，下拉菜单里只是多几行（太长会滚动）。样稿：docs/design/岗位方向预览.html
import { useEffect, useRef, useState } from 'react'
import type { Domain } from '../api/domains'
import { TiltCard } from './effects'

export function DirectionPicker({ domains, value, onChange }: {
  domains: Domain[] | null
  value: string | null
  onChange: (key: string) => void
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const current = domains?.find((d) => d.key === value) ?? null

  useEffect(() => {
    if (!open) return
    const outside = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <TiltCard>
      <span className="dsel-label" id="dsel-label">求职方向</span>
      <div className={`dsel ${open ? 'open' : ''}`} ref={box}>
        <button type="button" className={`dsel-btn ${current ? 'has' : ''}`} disabled={!domains}
          aria-haspopup="listbox" aria-expanded={open} aria-labelledby="dsel-label" onClick={() => setOpen((o) => !o)}>
          <span className="ic">{current?.icon ?? '?'}</span>
          {current ? (
            <span className="txt"><span className="t">{current.name}</span><span className="s">{current.desc}</span></span>
          ) : (
            <span className="dsel-ph">{domains ? '点这里选择方向' : '加载中…'}</span>
          )}
          <svg className="dsel-caret" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 7l5 5 5-5" />
          </svg>
        </button>
        <div className="dsel-menu" role="listbox" aria-labelledby="dsel-label">
          {domains?.map((d) => (
            <button key={d.key} type="button" role="option" aria-selected={d.key === value} tabIndex={open ? 0 : -1}
              className={`dsel-opt ${d.key === value ? 'on' : ''}`} onClick={() => { onChange(d.key); setOpen(false) }}>
              <span className="ic">{d.icon}</span>
              <span className="txt"><span className="t">{d.name}</span><span className="s">{d.desc}</span></span>
              <span className="ok" aria-hidden="true">✓</span>
            </button>
          ))}
        </div>
      </div>
      <div className="dir-info">
        {current ? (
          <>
            选了「<b>{current.name}</b>」之后：
            <ul>
              <li>常见岗位：{current.desc.split(' · ').join('、')}</li>
              <li>简历按{current.rule_hint}诊断</li>
              <li>模拟{current.interview_hint}</li>
            </ul>
          </>
        ) : '不同方向的岗位模板、简历诊断标准、模拟面试问的问题都不一样，先选一个。'}
      </div>
      <p className="dirs-note">选错了也没关系，下一步点「← 上一步」就能回来换。</p>
    </TiltCard>
  )
}
