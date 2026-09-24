// 页面的几种交互效果：鼠标跟随光晕、磁吸按钮、滚动出现
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** 跟着鼠标缓慢移动的暖色光晕 */
export function Glow() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (reducedMotion()) return
    let mx = window.innerWidth / 2, my = window.innerHeight / 3
    let gx = mx, gy = my
    let frame = 0
    const onMove = (e: MouseEvent) => { mx = e.clientX; my = e.clientY }
    const loop = () => {
      gx += (mx - gx) * 0.08
      gy += (my - gy) * 0.08
      if (ref.current) ref.current.style.transform = `translate(${gx}px, ${gy}px)`
      frame = requestAnimationFrame(loop)
    }
    window.addEventListener('mousemove', onMove)
    frame = requestAnimationFrame(loop)
    return () => { window.removeEventListener('mousemove', onMove); cancelAnimationFrame(frame) }
  }, [])
  return <div className="glow" ref={ref} aria-hidden="true" />
}

export function Backdrop() {
  return (
    <>
      <div className="grain" aria-hidden="true" />
      <Glow />
    </>
  )
}

/** 鼠标靠近时被"吸"过去一点的按钮 */
export function MagneticButton({ className = '', children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const ref = useRef<HTMLButtonElement>(null)
  return (
    <button
      {...rest}
      ref={ref}
      className={`btn ${className}`}
      onMouseMove={(e) => {
        const b = ref.current
        if (!b || reducedMotion()) return
        const r = b.getBoundingClientRect()
        const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2)
        b.style.transform = `translate(${dx * 0.22}px, ${dy * 0.3}px)`
      }}
      onMouseLeave={() => { if (ref.current) ref.current.style.transform = '' }}
    >
      {children}
    </button>
  )
}

/** 第一次滚动进视口时浮现；onReveal 用来触发里面的动画 */
export function Reveal({ className = '', onReveal, children, id }: {
  className?: string
  onReveal?: () => void
  children: ReactNode
  id?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(false)
  const onRevealRef = useRef(onReveal)
  onRevealRef.current = onReveal

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      setShown(true)
      onRevealRef.current?.()
      io.disconnect()
    }, { threshold: 0.2 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return <div ref={ref} id={id} className={`reveal ${shown ? 'in' : ''} ${className}`}>{children}</div>
}

/** 导航栏滚动后加底色 */
export function useScrolled(offset = 10) {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > offset)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [offset])
  return scrolled
}
