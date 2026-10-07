// 简历原文纸面：从右侧滑出，把三类标注按字符区间画在原文上 —— 红 = 简历问题，橙 = 部分满足的要求，绿 = 满足的要求。
// 一段文字可以同时属于好几条标注（切成小段，颜色取最严重的那条）。当前这一条描边闪一下、弹出批注并滚到可见处；
// 可以上一条 / 下一条（键盘 ← →）、点纸面上的高亮切换，Esc 关闭。样稿：docs/design/原文高亮预览.html
import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { ResumeBlocks } from '../api/resumes'
import { AdviceBlock, type AdviceSource } from './AdviceBlock'

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
  fix?: [string, string] // 顶部卡片里的一行说明，如 ['判定方式', '规则判定（技能词典）']
  start: number | null
  end: number | null
  advice?: AdviceSource
}

export type SheetDoc = ResumeBlocks & { entryBlocks: number[] } // entryBlocks：每条经历的第一块（标题行，加粗）

const LIST_NAME: Record<SheetList, string> = { gap: '对照岗位', self: '简历本身', hit: '满足的要求' }
const PRIORITY: Record<Color, number> = { bad: 3, part: 2, good: 1 }
const located = (x: SheetItem) => x.start !== null && x.end !== null
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

type Seg = { start: number; end: number; keys: string[]; color: Color | null }
type Para = { kind: 'h4' | 'name' | 'contact' | 'entry' | 'p'; segs: Seg[] }

/** 按块排版，每块在所有标注的起止处切开 */
function layout(doc: SheetDoc, marks: SheetItem[]): Para[] {
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

export function ResumeSheet({ open, title, doc, loadError, items, focusKey, onFocus, onClose }: {
  open: boolean
  title: string
  doc: SheetDoc | null
  loadError: string | null
  items: SheetItem[]
  focusKey: string | null // null = 看全部标注
  onFocus: (key: string | null) => void
  onClose: () => void
}) {
  const byKey = useMemo(() => new Map(items.map((x) => [x.key, x])), [items])
  const lists = useMemo(() => ({
    gap: items.filter((x) => x.list === 'gap'), self: items.filter((x) => x.list === 'self'), hit: items.filter((x) => x.list === 'hit'),
  }), [items])
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

  const step = (d: number) => {
    if (!current) return onFocus(lists.self[0]?.key ?? lists.gap[0]?.key ?? null)
    const list = lists[current.list]
    const next = list[list.indexOf(current) + d]
    if (next) onFocus(next.key)
  }
  const stepRef = useRef(step)
  stepRef.current = step

  // 打开时锁住页面滚动；Esc 关闭，← → 切换
  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') stepRef.current(1)
      else if (e.key === 'ArrowLeft') stepRef.current(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  // 批注别超出纸面右边
  useLayoutEffect(() => {
    const note = noteRef.current, wrap = wrapRef.current
    if (!note || !wrap) return
    note.style.left = ''
    const over = note.getBoundingClientRect().right - wrap.getBoundingClientRect().right + 12
    if (over > 0) note.style.left = `${-over}px`
  }, [focusKey, paras, open])

  // 切到一条就把它滚到纸面中间；看全部标注时回到顶部
  useEffect(() => {
    if (!open || !wrapRef.current) return
    const first = wrapRef.current.querySelector('[data-first]')
    if (first) first.scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' })
    else wrapRef.current.scrollTop = 0
  }, [focusKey, open, paras])

  /** 点纸面上的高亮：一段属于好几条时，优先当前列表里的，其次问题 > 部分满足 > 满足 */
  const pick = (keys: string[]) => {
    const cands = keys.map((k) => byKey.get(k)).filter((x): x is SheetItem => !!x)
    const next = cands.find((x) => current && x.list === current.list && x !== current)
      ?? [...cands].sort((a, b) => PRIORITY[b.color!] - PRIORITY[a.color!]).find((x) => x !== current)
      ?? cands[0]
    if (next) onFocus(next.key)
  }

  const renderSegs = (segs: Seg[], text: string, para: number): ReactNode[] => {
    return segs.map((s) => {
      const piece = text.slice(s.start, s.end)
      if (!s.color) return piece
      const focused = !!focusKey && s.keys.includes(focusKey)
      const first = focused && firstFocus === `${para}:${s.start}`
      const notes = s.keys.map((k) => byKey.get(k)?.note).filter(Boolean).join('\n')
      return (
        // 聚焦时换 key，让闪一下的动画重新播放
        <span key={`${s.start}-${focused ? focusKey : ''}`} className={`hl ${s.color}${focused ? ' focus' : ''}`}
          data-first={first || undefined} title={notes} onClick={() => pick(s.keys)}>
          {piece}
          {first && current && <span ref={noteRef} className="paper-note">{current.note}</span>}
        </span>
      )
    })
  }

  const count = (list: SheetList) => lists[list].filter(located).length
  const idx = current ? lists[current.list].indexOf(current) : -1

  // 挂到 body 下：页面内容区 .wrap 自成层叠上下文（z-index: 1），放在里面盖不住导航栏
  return createPortal(
    <>
      <div className={`veil ${open ? 'open' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sheet ${open ? 'open' : ''}`} role="dialog" aria-modal="true" aria-labelledby="sheet-title" aria-hidden={!open}>
        <div className="sheet-head">
          <div className="sheet-title" id="sheet-title">简历原文<span>{title}</span></div>
          <button type="button" className="x" onClick={onClose} aria-label="关闭">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" /></svg>
          </button>
        </div>

        <div className="focus-card">
          {current ? (
            <div className="fc-in" key={current.key}>
              <div className="fc-top">
                <span className={`tagx ${current.tag[0]}`}>{current.tag[1]}</span>
                <span>{current.text}<span className="why">{current.why}</span></span>
              </div>
              {current.fix && <p className="fc-fix"><b>{current.fix[0]}</b>{current.fix[1]}</p>}
              {!located(current) && (
                <p className="fc-missing">
                  {current.list === 'gap' ? '简历里没有找到能证明这条要求的内容 —— 这正是需要补上的地方。' : '这条针对整份简历，没有具体的某一句。'}
                </p>
              )}
              {current.advice && <AdviceBlock source={current.advice} />}
              <div className="fc-nav">
                <button type="button" onClick={() => step(-1)} disabled={idx <= 0}>‹ 上一条</button>
                <span>{LIST_NAME[current.list]} · {idx + 1} / {lists[current.list].length}</span>
                <button type="button" onClick={() => step(1)} disabled={idx >= lists[current.list].length - 1}>下一条 ›</button>
              </div>
            </div>
          ) : (
            <div className="fc-in">
              <div className="fc-top"><span>全部标注</span></div>
              <p className="fc-fix">
                原文里标出了简历本身的问题（{count('self')} 处）、部分满足的岗位要求（{count('gap')} 处）和已经满足的要求（{count('hit')} 条），
                各自的颜色见最下面的图例（配色可以换，所以这里不写颜色名）。点任意一处看说明。
              </p>
              <div className="fc-nav"><span>{title}</span><button type="button" onClick={() => step(1)}>从第一条问题开始 →</button></div>
            </div>
          )}
        </div>

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
        <div className="legend">
          <span><i className="bad" />简历问题</span><span><i className="part" />部分满足的要求</span><span><i className="good" />满足的要求</span>
          <span className="keys">← → 切换 · Esc 关闭</span>
        </div>
      </aside>
    </>,
    document.body,
  )
}
