// 登录弹窗背后的装饰：散落的产品碎片（匹配结果、诊断批注、面试题），
// 缓缓漂浮，随鼠标按远近做视差；再加一团跟随鼠标的光晕。纯装饰，读屏跳过。
import { useEffect, useRef, type CSSProperties } from 'react'

type Kind = 'good' | 'bad' | 'score' | 'plain'
type Chip = { text: string; kind: Kind; x: number; y: number; d: number } // x/y 为百分比，d 为远近 0–1

// 位置避开正中间的登录卡
const CHIPS: Chip[] = [
  { text: 'Redis 使用经验', kind: 'good', x: 8, y: 14, d: 0.9 },
  { text: '匹配度', kind: 'score', x: 74, y: 11, d: 1 },
  { text: '缺少量化结果', kind: 'bad', x: 5, y: 44, d: 0.65 },
  { text: '技术面 · 第 2 题', kind: 'plain', x: 79, y: 40, d: 0.55 },
  { text: '了解消息队列', kind: 'bad', x: 13, y: 76, d: 0.85 },
  { text: '通过初筛 ≥ 60', kind: 'good', x: 71, y: 74, d: 0.9 },
  { text: '追问 · 第 2 层', kind: 'plain', x: 40, y: 6, d: 0.4 },
  { text: '本科及以上学历', kind: 'good', x: 47, y: 89, d: 0.45 },
  { text: '「参与」太弱', kind: 'bad', x: 20, y: 27, d: 0.35 },
  { text: '运营面 · 活动复盘', kind: 'plain', x: 85, y: 58, d: 0.35 },
  { text: 'Spring Boot', kind: 'plain', x: 27, y: 90, d: 0.3 },
  { text: '800ms → 120ms', kind: 'good', x: 88, y: 25, d: 0.4 },
  { text: '依据已定位回原文', kind: 'plain', x: 3, y: 62, d: 0.3 },
  { text: '岗位要求 12 条', kind: 'plain', x: 60, y: 3, d: 0.3 },
]

const ICON: Record<Kind, string> = { good: '✓', bad: '!', score: '', plain: '' }

export function AuthDeco({ open }: { open: boolean }) {
  const layer = useRef<HTMLDivElement>(null)
  const glow = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let tx = 0, ty = 0, cx = 0, cy = 0          // 视差：目标值与当前值（-1…1）
    let gx = window.innerWidth / 2, gy = window.innerHeight / 2, mx = gx, my = gy
    let frame = 0
    const onMove = (e: MouseEvent) => {
      mx = e.clientX; my = e.clientY
      tx = e.clientX / window.innerWidth * 2 - 1
      ty = e.clientY / window.innerHeight * 2 - 1
    }
    const loop = () => {
      cx += (tx - cx) * 0.06; cy += (ty - cy) * 0.06
      gx += (mx - gx) * 0.08; gy += (my - gy) * 0.08
      layer.current?.style.setProperty('--mx', cx.toFixed(4))
      layer.current?.style.setProperty('--my', cy.toFixed(4))
      if (glow.current) glow.current.style.transform = `translate(${gx}px, ${gy}px)`
      frame = requestAnimationFrame(loop)
    }
    window.addEventListener('mousemove', onMove)
    frame = requestAnimationFrame(loop)
    return () => { window.removeEventListener('mousemove', onMove); cancelAnimationFrame(frame) }
  }, [open])

  return (
    <div className="auth-deco" ref={layer} aria-hidden="true">
      <div className="auth-glow" ref={glow} />
      {CHIPS.map((c, i) => (
        <div
          key={c.text}
          className="chip-pos"
          style={{ left: `${c.x}%`, top: `${c.y}%`, '--d': c.d, '--i': i } as CSSProperties}
        >
          <div className={`chip ${c.kind} ${c.d < 0.45 ? 'far' : ''}`}>
            {c.kind === 'score' ? <><b>72</b>{c.text}</> : <>{ICON[c.kind] && <i>{ICON[c.kind]}</i>}{c.text}</>}
          </div>
        </div>
      ))}
    </div>
  )
}
