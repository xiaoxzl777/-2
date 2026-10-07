import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useScrolled } from './effects'

/** keepLinks：窄屏也显示链接（登录后的导航）；首页的锚点链接在窄屏收起 */
export function Nav({ links, actions, keepLinks = false }: { links?: ReactNode; actions: ReactNode; keepLinks?: boolean }) {
  const scrolled = useScrolled()
  return (
    <nav className={`nav ${scrolled ? 'scrolled' : ''}`}>
      <div className="wrap">
        <Link to="/" className="logo"><span className="logo-mark">求</span>求职辅助</Link>
        {links && <div className={`links${keepLinks ? ' keep' : ''}`}>{links}</div>}
        <div className="actions">{actions}</div>
      </div>
    </nav>
  )
}
