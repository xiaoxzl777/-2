// 选岗位、选简历列表里的一条：选它的按钮 + 右边的「删除」（按钮里不能套按钮，所以并排放）。
// 点了删除不马上删，这一条原地变成确认框；删掉后收起来，再从列表里去掉。样稿：docs/design/删除简历和岗位预览.html
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'

const NOT_FOUND = 40401
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export type PickRowDelete = {
  note: ReactNode // 确认框第二行：删了会怎样
  run: () => Promise<unknown>
  onGone: () => void // 删掉、收起来之后：从列表里去掉
}

export function PickRow({ name, selected, disabled, onPick, del, children }: {
  name: string // 确认框里「删除「…」？」
  selected: boolean
  disabled?: boolean // 不能选（解析失败的简历），但照样能删
  onPick: () => void
  del?: PickRowDelete // 不给就没有删除（模板岗位）
  children: ReactNode // 按钮里的图标和文字
}) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [gone, setGone] = useState(false)
  const rowRef = useRef<HTMLDivElement>(null)
  const delRef = useRef<HTMLButtonElement>(null)
  const refocus = useRef(false)

  // 取消后焦点回到「删除」上（确认框没了，焦点不能丢到页面最上面）
  useEffect(() => {
    if (!asking && refocus.current) {
      refocus.current = false
      delRef.current?.focus()
    }
  }, [asking])

  const cancel = () => {
    if (busy) return
    refocus.current = true
    setAsking(false)
    setError(null)
  }

  const run = async () => {
    if (!del) return
    setBusy(true)
    setError(null)
    try {
      await del.run()
    } catch (err) {
      // 已经不在了（别的标签页删过）：当作删掉了
      if (!(err instanceof ApiError && err.code === NOT_FOUND)) {
        setBusy(false)
        setError(err instanceof ApiError ? err.message : '请稍后再试')
        return
      }
    }
    const el = rowRef.current
    if (!el || reducedMotion()) return del.onGone()
    el.style.height = `${el.offsetHeight}px`
    el.getBoundingClientRect() // 先让固定高度生效，收起才有过渡
    setGone(true)
    window.setTimeout(del.onGone, 360)
  }

  return (
    <div ref={rowRef} className={`pick-row${del ? ' has-del' : ''}${gone ? ' gone' : ''}`}>
      {asking && del ? (
        <div className="pick-confirm" role="alertdialog" aria-label={`删除「${name}」`}
          onKeyDown={(e) => { if (e.key === 'Escape') cancel() }}>
          <p><b>删除「{name}」？</b><br />{del.note}</p>
          {error && <p className="form-err" role="alert">没删掉：{error}</p>}
          <div className="pick-confirm-btns">
            <button type="button" className="btn sm danger" disabled={busy} onClick={() => void run()}>{busy ? '删除中…' : '删除'}</button>
            {/* 默认停在「取消」上：误按回车不会删 */}
            <button type="button" className="btn sm ghost" disabled={busy} autoFocus onClick={cancel}>取消</button>
          </div>
        </div>
      ) : (
        <>
          <button type="button" className={`pick-item ${selected ? 'sel' : ''}`} disabled={disabled} onClick={onPick}>
            {children}
            <span className="radio" aria-hidden="true" />
          </button>
          {del && <button ref={delRef} type="button" className="pick-del" aria-label={`删除「${name}」`} onClick={() => setAsking(true)}>删除</button>}
        </>
      )}
    </div>
  )
}
