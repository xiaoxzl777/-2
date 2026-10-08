// 简历原文纸面：按块排版，把三类标注按字符区间画在原文上 —— 简历问题、部分满足的要求、满足的要求（颜色见图例，随配色变）。
// 一段文字可以同时属于好几条（切成小段，颜色取最严重的那条）。当前这一条描边闪一下、弹出批注，并在纸面里滚到中间。
// 结果页右边常驻的原文、窄屏从右侧滑出的原文（ResumeSheet）共用它。样稿：docs/design/结果页面试场次预览.html
import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from 'react'
import type { ResumeBlocks } from '../api/resumes'
import type { AdviceSource } from './AdviceBlock'

export type SheetList = 'gap' | 'self' | 'hit'
type Color = 'bad' | 'part' | 'good'

export type SheetItem = {
  key: string
  list: SheetList
  color: Color | null // null = 原文里没有位置（缺失的要求、针对整份简历的问题）
  tag: [string, string] // [样式, 文字]
  text: string
  why: string
  note: string // 纸面上的批注
  fix?: [string, string] // 抽屉顶部卡片里的一行说明，如 ['判定方式', '规则判定（技能词典）']
  start: number | null
  end: number | null
  advice?: AdviceSource
}

export type SheetDoc = ResumeBlocks & { entryBlocks: number[] } // entryBlocks：每条经历的第一块（标题行，加粗）

const PRIORITY: Record<Color, number> = { bad: 3, part: 2, good: 1 }
export const located = (x: SheetItem) => x.start !== null && x.end !== null
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export type Seg = { start: number; end: number; keys: string[]; color: Color | null }
export type Para = { kind: 'h4' | 'name' | 'contact' | 'entry' | 'p'; segs: Seg[] }

/** 按块排版，每块在所有标注的起止处切开（诊断报告 ApplyReport 也用它排原文） */
export function layout(doc: SheetDoc, marks: SheetItem[]): Para[] {
  const headings = new Set(doc.sections.filter((s) => s.matched_by !== 'implicit').map((s) => s.block_start))
  const basics = doc.sections.find((s) => s.type === 'basics')
  const entries = new Set(doc.entryBlocks)
  return doc.blocks.map((b) => {
    const inBlock = marks.filter((m) => m.start! < b.char_end && m.end! > b.char_start)
    const cuts = new Set([b.char_start, b.char_end])
    inBlock.forEach((m) => { cuts.add(Math.max(m.start!, b.char_start)); cuts.add(Math.min(m.end!, b.char_end)) })
    const points = [...cuts].sort((x, y) => x - y)
    const segs: Seg[] = []
    for (let i = 0; i < points.length - 1; i++) {
      const [start, end] = [points[i], points[i + 1]]
      const cover = inBlock.filter((m) => m.start! < end && m.end! > start)
      const top = cover.reduce<SheetItem | null>((p, m) => (!p || PRIORITY[m.color!] > PRIORITY[p.color!] ? m : p), null)
      segs.push({ start, end, keys: cover.map((m) => m.key), color: top?.color ?? null })
    }
    const kind = headings.has(b.block_index) ? 'h4'
      : basics && b.block_index === basics.block_start ? 'name'
      : basics && b.block_index <= basics.block_end ? 'contact'
      : entries.has(b.block_index) ? 'entry' : 'p'
    return { kind, segs }
  })
}

export function ResumePaper({ doc, loadError, items, focusKey, pulse = 0, peekKey = null, onFocus }: {
  doc: SheetDoc | null
  loadError: string | null
  items: SheetItem[]
  focusKey: string | null // null = 不指着哪一条，回到顶部
  pulse?: number // 变了就重新闪一下、重新滚过去（同一条又点了一次、抽屉重新打开）
  peekKey?: string | null // 鼠标停在列表里的某一条上：原文里对应的句子先亮一下
  onFocus: (key: string) => void // 点了纸面上的高亮
}) {
  const byKey = useMemo(() => new Map(items.map((x) => [x.key, x])), [items])
  const paras = useMemo(() => (doc ? layout(doc, items.filter((x) => x.color && located(x))) : []), [doc, items])
  const current = focusKey ? byKey.get(focusKey) ?? null : null
  // 批注只挂在当前这条的第一段上（一条可能跨好几块）
  const firstFocus = useMemo(() => {
    if (!focusKey) return null
    for (let i = 0; i < paras.length; i++) {
      const seg = paras[i].segs.find((s) => s.keys.includes(focusKey))
      if (seg) return `${i}:${seg.start}`
    }
    return null
  }, [paras, focusKey])
  const wrapRef = useRef<HTMLDivElement>(null)
  const noteRef = useRef<HTMLSpanElement>(null)

  // 批注别超出纸面右边
  useLayoutEffect(() => {
    const note = noteRef.current, wrap = wrapRef.current
    if (!note || !wrap) return
    note.style.left = ''
    const over = note.getBoundingClientRect().right - wrap.getBoundingClientRect().right + 12
    if (over > 0) note.style.left = `${-over}px`
  }, [focusKey, paras, pulse])

  // 把当前这条滚到纸面中间，没指着哪条就回到顶部。只滚纸面自己：scrollIntoView 会带着整页一起滚
  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const first = wrap.querySelector('[data-first]')
    const top = first ? first.getBoundingClientRect().top - wrap.getBoundingClientRect().top + wrap.scrollTop - wrap.clientHeight / 2 : 0
    wrap.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? 'instant' : 'smooth' })
  }, [focusKey, paras, pulse])

  /** 点纸面上的高亮：先给看得见颜色的那条（问题 > 部分满足 > 满足）；一段属于好几条时，同一处再点一次换下一条。
   *  原来是「优先当前列表里的」：刚看完一条满足的，再点标成问题的那段，弹出来的却是另一条满足的，对不上颜色 */
  const pick = (keys: string[]) => {
    const cands = keys.map((k) => byKey.get(k)).filter((x): x is SheetItem => !!x)
      .sort((a, b) => PRIORITY[b.color!] - PRIORITY[a.color!])
    const i = current ? cands.indexOf(current) : -1 // 当前这条不在这一段里：-1，下面正好取第一条
    const next = cands[(i + 1) % cands.length]
    if (next) onFocus(next.key)
  }

  const renderSegs = (segs: Seg[], text: string, para: number): ReactNode[] => {
    return segs.map((s) => {
      const piece = text.slice(s.start, s.end)
      if (!s.color) return piece
      const focused = !!focusKey && s.keys.includes(focusKey)
      const first = focused && firstFocus === `${para}:${s.start}`
      const peek = !!peekKey && s.keys.includes(peekKey)
      const notes = s.keys.map((k) => byKey.get(k)?.note).filter(Boolean).join('\n')
      return (
        // 聚焦时换 key，让闪一下的动画重新播放
        <span key={`${s.start}-${focused ? `${focusKey}-${pulse}` : ''}`} className={`hl ${s.color}${focused ? ' focus' : ''}${peek ? ' peek' : ''}`}
          data-first={first || undefined} title={notes} onClick={() => pick(s.keys)}>
          {piece}
          {first && current && <span ref={noteRef} className="paper-note">{current.note}</span>}
        </span>
      )
    })
  }

  return (
    <div className="paper-wrap" ref={wrapRef}>
      {loadError ? <p className="form-err">原文没能载入：{loadError}</p>
        : !doc ? <p className="hint">正在载入简历原文…</p>
        : (
          <div className="paper">
            {paras.map((p, i) => {
              const segs = renderSegs(p.segs, doc.full_text, i)
              if (p.kind === 'h4') return <h4 key={i}>{segs}</h4>
              return <p key={i} className={p.kind === 'p' ? undefined : p.kind}>{segs}</p>
            })}
          </div>
        )}
    </div>
  )
}
