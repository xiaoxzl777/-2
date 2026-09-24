import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useScrolled } from './effects'

export function Nav({ links, actions }: { links?: ReactNode; actions: ReactNode }) {
  const scrolled = useScrolled()
  return (
    <nav className={`nav ${scrolled ? 'scrolled' : ''}`}>
      <div className="wrap">
        <Link to="/" className="logo"><span className="logo-mark">求</span>求职辅助</Link>
        {links && <div className="links">{links}</div>}
        <div className="actions">{actions}</div>
      </div>
    </nav>
  )
}
