// 修改密码弹窗：头像菜单里点「修改密码」打开。当前密码、新密码（规则同注册）、再输一次；改好后显示「密码已修改」，这台设备照常登录。
// 面板、输入框、按钮沿用登录弹窗的样式（.panel / .field / .rule / .submit）。点遮罩、Esc、× 关闭，关掉再打开是空的。
// 样稿：docs/design/修改密码预览.html
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { authApi, PASSWORD_MAX, PASSWORD_MIN } from '../api/auth'
import { ApiError } from '../api/client'

type Field = 'old' | 'new' | 'again'
const RULE = `新密码 ${PASSWORD_MIN}–${PASSWORD_MAX} 位`

export function PasswordDialog({ open, username, onClose }: { open: boolean; username: string; onClose: () => void }) {
  const [old, setOld] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState<{ field: Field; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const oldRef = useRef<HTMLInputElement>(null)

  // 每次打开都是空的；打开后焦点放在第一个框（只跟着 open 变，别的重渲染不能清掉正在输的内容）
  useEffect(() => {
    if (!open) return
    setOld(''); setNext(''); setAgain(''); setError(null); setSaving(false); setDone(false)
    const t = window.setTimeout(() => oldRef.current?.focus(), 200)
    return () => window.clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (saving) return
    if (!old) return setError({ field: 'old', text: '请输入当前密码' })
    if (next.length < PASSWORD_MIN || next.length > PASSWORD_MAX) return setError({ field: 'new', text: `新密码要 ${PASSWORD_MIN}–${PASSWORD_MAX} 位` })
    if (next !== again) return setError({ field: 'again', text: '两次输入的新密码不一样' })
    setSaving(true)
    setError(null)
    try {
      await authApi.changePassword(old, next)
      setDone(true)
    } catch (err) {
      const text = err instanceof ApiError ? err.message : '没改成，请稍后重试'
      setError({ field: text.includes('当前密码') ? 'old' : 'new', text })
    } finally {
      setSaving(false)
    }
  }

  const fieldClass = (f: Field) => `field${error?.field === f ? ' shake' : ''}`
  const tab = open ? 0 : -1

  return createPortal(
    <div className={`pwd${open ? ' open' : ''}`} aria-hidden={!open}>
      <div className="pwd-bg" onClick={onClose} />
      <form className="panel" onSubmit={submit} noValidate role="dialog" aria-modal="true" aria-labelledby="pwd-title">
        <div className="panel-head">
          <h3 id="pwd-title">修改密码</h3>
          <button type="button" className="x" onClick={onClose} aria-label="关闭" tabIndex={tab}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" /></svg>
          </button>
        </div>
        {done ? (
          <div className="pwd-done">
            <span className="ok" aria-hidden="true">✓</span>
            <b>密码已修改</b>
            <p>下次登录用新密码。<br />这台设备不用重新登录。</p>
            <button type="button" className="btn dark submit" onClick={onClose} tabIndex={tab}>好的</button>
          </div>
        ) : (
          <>
            <p className="pwd-who">账号 {username}</p>
            <div className={fieldClass('old')}>
              <input id="pwd-old" ref={oldRef} type="password" value={old} onChange={(e) => setOld(e.target.value)} placeholder=" " autoComplete="current-password" tabIndex={tab} />
              <label htmlFor="pwd-old">当前密码</label>
            </div>
            <div className={fieldClass('new')}>
              <input id="pwd-new" type="password" value={next} onChange={(e) => setNext(e.target.value)} placeholder=" " autoComplete="new-password" tabIndex={tab} />
              <label htmlFor="pwd-new">新密码</label>
            </div>
            <div className={fieldClass('again')}>
              <input id="pwd-again" type="password" value={again} onChange={(e) => setAgain(e.target.value)} placeholder=" " autoComplete="new-password" tabIndex={tab} />
              <label htmlFor="pwd-again">再输一次新密码</label>
            </div>
            <p className={`rule${error ? ' err' : ''}`} role={error ? 'alert' : undefined}>{error?.text ?? RULE}</p>
            <button type="submit" className="btn dark submit" disabled={saving} tabIndex={tab}>
              {saving && <span className="spin" aria-hidden="true" />}{saving ? '保存中…' : '保存'}
            </button>
          </>
        )}
      </form>
    </div>,
    document.body,
  )
}
