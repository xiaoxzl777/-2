// 导航栏右上角的「配色」：点开选三套之一，只影响这台设备。样稿：docs/design/结果页排版预览.html
import { useEffect, useRef, useState } from 'react'
import { PALETTES, usePalette } from '../store/palette'

export function PalettePicker() {
  const key = usePalette((s) => s.key)
  const setPalette = usePalette((s) => s.set)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 点菜单外面、按 Esc 收起
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} className={`pal${open ? ' open' : ''}`}>
      <button type="button" className="pal-btn" aria-haspopup="menu" aria-expanded={open} title="换配色" onClick={() => setOpen((o) => !o)}>
        <span className="pal-dot" aria-hidden="true" /><span className="pal-label">配色</span>
      </button>
      <div className="pal-menu" role="menu" aria-label="配色">
        <p>选一套你喜欢的颜色，只影响这台设备</p>
        {PALETTES.map((p) => (
          <button key={p.key} type="button" role="menuitemradio" aria-checked={p.key === key} tabIndex={open ? 0 : -1}
            className={`pal-opt${p.key === key ? ' on' : ''}`} onClick={() => { setPalette(p.key); setOpen(false) }}>
            <span className="pal-sw" style={{ background: p.bg }} aria-hidden="true"><i style={{ background: p.accent }} /></span>
            <span className="pal-name">{p.name}<small>{p.desc}</small></span>
            <span className="pal-ok" aria-hidden="true">✓</span>
          </button>
        ))}
      </div>
    </div>
  )
}
