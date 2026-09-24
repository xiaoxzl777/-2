// 首页右侧的演示卡：扫描 → 高亮问题句 → 逐条对照岗位要求 → 出匹配度。
// 用的是固定示例数据，只做动画，不调后端。
import { useEffect, useRef, useState } from 'react'

const REQS = [
  { text: '熟悉 Java / Spring Boot', status: 'hit', why: '项目经历' },
  { text: '有 Redis 使用经验', status: 'hit', why: '800ms → 120ms' },
  { text: '了解消息队列', status: 'miss', why: '简历未提及' },
  { text: '本科及以上学历', status: 'hit', why: '教育经历' },
] as const

const SCORE = 72
const CIRC = 251.3 // 2π × r(40)

// 每一步距上一步的毫秒数：扫描、问题句 1、批注 1、依据句、问题句 2、批注 2、四条要求（phase 7–10）
const TIMELINE = [0, 700, 250, 500, 450, 250, 600, 380, 380, 380]
const PHASE_SCORE = TIMELINE.length // 所有要求判完之后出分

const Check = () => (
  <svg viewBox="0 0 12 12" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2.5 6.5l2.2 2.2L9.5 3.8" /></svg>
)
const Cross = () => (
  <svg viewBox="0 0 12 12" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M3.5 3.5l5 5M8.5 3.5l-5 5" /></svg>
)

export function ResumeDemo({ playSignal }: { playSignal: number }) {
  const [phase, setPhase] = useState(0)     // 0 = 未开始
  const [run, setRun] = useState(0)         // 每次重播 +1，用来重启扫描动画
  const [score, setScore] = useState(0)
  const [drag, setDrag] = useState(false)
  const timers = useRef<number[]>([])
  const cardRef = useRef<HTMLDivElement>(null)
  const phaseRef = useRef(0)
  const doneRef = useRef(false)

  const play = () => {
    if (phaseRef.current > 0 && !doneRef.current) return
    timers.current.forEach(clearTimeout)
    timers.current = []
    setPhase(0)
    setScore(0)
    setRun((r) => r + 1)
    let at = 0
    TIMELINE.forEach((delay, i) => {
      at += delay
      timers.current.push(window.setTimeout(() => setPhase(i + 1), at))
    })
    timers.current.push(window.setTimeout(() => setPhase(PHASE_SCORE + 1), at + 380))
  }

  // 外部按钮（"先看演示"）触发
  useEffect(() => { if (playSignal > 0) play() }, [playSignal])
  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  // 分数从 0 数到目标值
  const scoring = phase >= PHASE_SCORE + 1
  useEffect(() => {
    if (!scoring) return
    const t0 = performance.now()
    let frame = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 1300)
      setScore(Math.round(SCORE * (1 - Math.pow(1 - k, 3))))
      if (k < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [scoring, run])

  const reqsShown = Math.max(0, Math.min(REQS.length, phase - 6))
  const done = scoring && score === SCORE
  const running = phase > 0 && !done
  phaseRef.current = phase
  doneRef.current = done

  return (
    <div className="demo fade d4">
      <div className="floaty a"><b>7 条</b><span>写作规则检查</span></div>
      <div className="floaty b"><b>≥ 60 分</b><span>即通过初筛</span></div>
      <div
        ref={cardRef}
        className={`demo-card ${drag ? 'drag' : ''}`}
        onMouseMove={(e) => {
          const c = cardRef.current
          if (!c) return
          const r = c.getBoundingClientRect()
          const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5
          c.style.transform = `rotateY(${px * 6}deg) rotateX(${-py * 6}deg)`
        }}
        onMouseLeave={() => { if (cardRef.current) cardRef.current.style.transform = '' }}
        onDragEnter={(e) => { e.preventDefault(); setDrag(true) }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={(e) => { e.preventDefault(); setDrag(false) }}
        onDrop={(e) => { e.preventDefault(); setDrag(false); play() }}
      >
        <div className="demo-head">
          <div className="dots" aria-hidden="true"><i /><i /><i /></div>
          <span className="demo-title"><b>示例数据</b><span className="demo-hint"> · 拖入任意文件或点右边按钮</span></span>
          <button type="button" className="btn dark run" onClick={play} disabled={running}>
            {running ? '分析中…' : done ? '↻ 再来一次' : '▶ 开始演示'}
          </button>
        </div>

        <div className="resume">
          <div key={run} className={`scan ${phase >= 1 ? 'go' : ''}`} />
          <h4>项目经历</h4>
          <div className="proj">校园二手交易平台 · 后端开发 <small>2023.09 – 2024.01</small></div>
          <ul>
            <li>
              <span className={`note ${phase >= 3 ? 'show' : ''}`}>缺少结果：做到了什么程度？</span>
              <span className={`hl ${phase >= 2 ? 'bad' : ''}`}>负责订单模块的开发</span>，完成下单、支付回调与退款流程
            </li>
            <li>使用 <span className={`hl ${phase >= 4 ? 'good' : ''}`}>Redis 缓存热门商品</span>，接口响应从 800ms 降到 120ms</li>
            <li>
              <span className={`note inline ${phase >= 6 ? 'show' : ''}`}>「参与」太弱，写清你具体做了什么</span>
              <span className={`hl ${phase >= 5 ? 'bad' : ''}`}>参与了数据库设计</span>
            </li>
          </ul>
          <h4>专业技能</h4>
          <div><span className={`hl ${phase >= 4 ? 'good' : ''}`}>Java、Spring Boot</span>、MySQL、Redis、Git</div>
          <div className="drop-hint">松手开始分析</div>
        </div>

        <div className="match">
          <div className="reqs">
            {REQS.map((r, i) => {
              const shown = i < reqsShown
              return (
                <div key={r.text} className={`req ${shown ? r.status : ''} ${shown && i === reqsShown - 1 && !scoring ? 'pop' : ''}`}>
                  <span className="st">{r.status === 'hit' ? <Check /> : <Cross />}</span>
                  {r.text}
                  <span className="why">{r.why}</span>
                </div>
              )
            })}
          </div>
          <div className="score" aria-live="polite">
            <svg viewBox="0 0 96 96" aria-hidden="true">
              <circle className="track" cx="48" cy="48" r="40" />
              <circle className="bar" cx="48" cy="48" r="40" style={{ strokeDashoffset: scoring ? CIRC * (1 - SCORE / 100) : CIRC }} />
            </svg>
            <span className="num">{score}</span>
            <span className="lbl">匹配度</span>
            <span className={`verdict ${done ? 'show' : ''}`}>通过初筛</span>
          </div>
        </div>
      </div>
    </div>
  )
}
