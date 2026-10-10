// 导航右上角的头像按钮：点开菜单，第一行是用户名，下面「配色」（三个色点，点了不收起，好直接看效果）、「修改密码」「退出登录」。
// 点外面或 Esc 收起。用户端和管理端共用。样稿：docs/design/修改密码预览.html、管理端用量预览.html（配色那一行）
import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { PALETTES, usePalette } from '../store/palette'
import { PasswordDialog } from './PasswordDialog'
import { useDismiss } from './useDismiss'

export function UserMenu() {
  const user = useAuth((s) => s.user)!
  const logout = useAuth((s) => s.logout)
  const palette = usePalette((s) => s.key)
  const setPalette = usePalette((s) => s.set)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [pwd, setPwd] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  // 弹窗是从菜单项打开的，菜单项这时已经收起来了：关掉后把焦点放回头像按钮
  const closePwd = useCallback(() => { setPwd(false); btn.current?.focus() }, [])

  useDismiss(box, open, () => setOpen(false))

  const signOut = () => {
    logout()
    navigate('/')
  }

  return (
    <div className={`um${open ? ' open' : ''}`} ref={box}>
      <button type="button" ref={btn} className="um-btn" aria-haspopup="menu" aria-expanded={open} aria-label={`账号 ${user.username}`} onClick={() => setOpen((o) => !o)}>
        <span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span>
        <span className="uname">{user.username}</span>
        <svg className="um-caret" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M2 4l3 3 3-3" /></svg>
      </button>
      <div className="um-menu" role="menu" aria-hidden={!open}>
        <div className="um-who"><b>{user.username}</b>{user.role === 'admin' ? <span>管理员</span> : user.email && <span>{user.email}</span>}</div>
        <div className="um-pal" role="group" aria-label="配色">
          <div>配色<small>{PALETTES.find((p) => p.key === palette)?.name}</small></div>
          <div className="um-sws">
            {PALETTES.map((p) => (
              <button key={p.key} type="button" role="menuitemradio" aria-checked={p.key === palette} aria-label={p.name} title={p.name}
                tabIndex={open ? 0 : -1} onClick={() => setPalette(p.key)}>
                <i style={{ background: p.accent }} />
              </button>
            ))}
          </div>
        </div>
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
