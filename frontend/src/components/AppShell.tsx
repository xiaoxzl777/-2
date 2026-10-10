// 登录后页面的外壳：背景、导航（新的投递 / 我的投递 / 我的简历 + 头像菜单：配色、修改密码、退出登录）、导航下方的细进度线，
// 模型服务调不通时内容最上面一条横幅。手机上也保留这三个链接（首页的导航链接在窄屏收起）
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Backdrop } from './effects'
import { LlmBanner } from './LlmBanner'
import { Nav } from './Nav'
import { UserMenu } from './UserMenu'

export function AppShell({ progress = 0, children }: { progress?: number; children: ReactNode }) {
  return (
    <>
      <Backdrop />
      <Nav
        keepLinks
        palette={false}
        links={
          <>
            <NavLink to="/app" end className={({ isActive }) => (isActive ? 'on' : '')}>新的投递</NavLink>
            <NavLink to="/app/applies" className={({ isActive }) => (isActive ? 'on' : '')}>我的投递</NavLink>
            <NavLink to="/app/resumes" className={({ isActive }) => (isActive ? 'on' : '')}>我的简历</NavLink>
          </>
        }
        actions={<UserMenu />}
      />
      <div className="top-progress" aria-hidden="true"><i style={{ width: `${progress}%` }} /></div>
      <main className="wrap"><LlmBanner />{children}</main>
    </>
  )
}
