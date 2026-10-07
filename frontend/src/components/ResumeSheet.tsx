// 简历原文抽屉：窄屏放不下两栏时从右侧滑出（宽屏原文常驻在结果页右边），纸面见 ResumePaper。
// 顶部卡片说明当前这一条；可以上一条 / 下一条（键盘 ← →）、点纸面上的高亮切换，Esc 关闭。样稿：docs/design/原文高亮预览.html
import { useEffect, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import { AdviceBlock } from './AdviceBlock'
import { located, ResumePaper, type SheetDoc, type SheetItem, type SheetList } from './ResumePaper'

const LIST_NAME: Record<SheetList, string> = { gap: '对照岗位', self: '简历本身', hit: '满足的要求' }

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
  const current = focusKey ? byKey.get(focusKey) ?? null : null

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

        <ResumePaper doc={doc} loadError={loadError} items={items} focusKey={focusKey} pulse={open ? 1 : 0} onFocus={onFocus} />
        <div className="legend">
          <span><i className="bad" />简历问题</span><span><i className="part" />部分满足的要求</span><span><i className="good" />满足的要求</span>
          <span className="keys">← → 切换 · Esc 关闭</span>
        </div>
      </aside>
    </>,
    document.body,
  )
}
