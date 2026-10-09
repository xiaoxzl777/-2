// 登录后页面的外壳：背景、导航（新的投递 / 我的投递 / 我的简历 + 用户 + 退出）、导航下方的细进度线，模型服务调不通时内容最上面一条横幅。
// 手机上也保留这两个链接（首页的导航链接在窄屏收起）
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { Backdrop, MagneticButton } from './effects'
import { LlmBanner } from './LlmBanner'
import { Nav } from './Nav'

export function AppShell({ progress = 0, children }: { progress?: number; children: ReactNode }) {
  const user = useAuth((s) => s.user)!
  const logout = useAuth((s) => s.logout)
  const navigate = useNavigate()

  const signOut = () => {
    logout()
    navigate('/')
  }

  return (
    <>
      <Backdrop />
      <Nav
        keepLinks
        links={
          <>
            <NavLink to="/app" end className={({ isActive }) => (isActive ? 'on' : '')}>新的投递</NavLink>
            <NavLink to="/app/applies" className={({ isActive }) => (isActive ? 'on' : '')}>我的投递</NavLink>
            <NavLink to="/app/resumes" className={({ isActive }) => (isActive ? 'on' : '')}>我的简历</NavLink>
          </>
        }
        actions={
          <>
            <span className="user-chip"><span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span><span className="uname">{user.username}</span></span>
            <MagneticButton className="ghost sm" onClick={signOut}>退出</MagneticButton>
          </>
        }
      />
      <div className="top-progress" aria-hidden="true"><i style={{ width: `${progress}%` }} /></div>
      <main className="wrap"><LlmBanner />{children}</main>
    </>
  )
}
