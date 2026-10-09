// 导航右上角的头像按钮：点开菜单，第一行是用户名，下面「修改密码」「退出登录」（原来单独的「退出」收进来了）。
// 点外面或 Esc 收起。样稿：docs/design/修改密码预览.html
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { PasswordDialog } from './PasswordDialog'

export function UserMenu() {
  const user = useAuth((s) => s.user)!
  const logout = useAuth((s) => s.logout)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [pwd, setPwd] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const closePwd = useCallback(() => setPwd(false), [])

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

  const signOut = () => {
    logout()
    navigate('/')
  }

  return (
    <div className={`um${open ? ' open' : ''}`} ref={box}>
      <button type="button" className="um-btn" aria-haspopup="menu" aria-expanded={open} aria-label={`账号 ${user.username}`} onClick={() => setOpen((o) => !o)}>
        <span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span>
        <span className="uname">{user.username}</span>
        <svg className="caret" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M2 4l3 3 3-3" /></svg>
      </button>
      <div className="um-menu" role="menu" aria-hidden={!open}>
        <div className="um-who"><b>{user.username}</b>{user.email && <span>{user.email}</span>}</div>
        <button type="button" role="menuitem" tabIndex={open ? 0 : -1} onClick={() => { setOpen(false); setPwd(true) }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
          修改密码
        </button>
        <button type="button" role="menuitem" tabIndex={open ? 0 : -1} onClick={signOut}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
          退出登录
        </button>
      </div>
      <PasswordDialog open={pwd} username={user.username} onClose={closePwd} />
    </div>
  )
}
