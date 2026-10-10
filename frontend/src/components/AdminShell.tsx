// 管理端的外壳：和用户端同一套——背景（点阵 + 跟着鼠标的光晕）、同一条导航（logo 旁边标「管理端」，两个页面，头像菜单），
// 只是没有求职用的三个链接。里面的内容是数字、图和表格，类名带 adm- 前缀。样稿：docs/design/管理端用量预览.html
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { Backdrop } from './effects'
import { Nav } from './Nav'
import { UserMenu } from './UserMenu'

export function AdminShell({ children }: { children: ReactNode }) {
  return (
    <>
      <Backdrop />
      <Nav
        keepLinks
        palette={false}
        badge="管理端"
        links={
          <>
            <NavLink to="/admin" end className={({ isActive }) => (isActive ? 'on' : '')}>模型用量</NavLink>
            <NavLink to="/admin/settings" className={({ isActive }) => (isActive ? 'on' : '')}>模型设置</NavLink>
          </>
        }
        actions={<UserMenu />}
      />
      <main className="wrap adm">{children}</main>
    </>
  )
}
