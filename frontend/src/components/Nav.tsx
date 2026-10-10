import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useScrolled } from './effects'
import { PalettePicker } from './PalettePicker'

/** keepLinks：窄屏也显示链接（登录后的导航）；首页的锚点链接在窄屏收起。
 *  palette：右上角带不带「配色」。登录后它收在头像菜单里（UserMenu），导航栏上就不放了。
 *  badge：logo 旁边的小标（管理端用） */
export function Nav({ links, actions, keepLinks = false, palette = true, badge }: {
  links?: ReactNode; actions: ReactNode; keepLinks?: boolean; palette?: boolean; badge?: string
}) {
  const scrolled = useScrolled()
  return (
    <nav className={`nav ${scrolled ? 'scrolled' : ''}`}>
      <div className="wrap">
        <div className="nav-brand">
          <Link to="/" className="logo"><span className="logo-mark">求</span>求职辅助</Link>
          {badge && <span className="adm-badge">{badge}</span>}
        </div>
        {links && <div className={`links${keepLinks ? ' keep' : ''}`}>{links}</div>}
        <div className="actions">{palette && <PalettePicker />}{actions}</div>
      </div>
    </nav>
  )
}
