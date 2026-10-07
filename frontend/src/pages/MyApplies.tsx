// 我的投递：/app/applies。新的在前，点一条进初筛结果页；这次投递下面的面试挂在卡片底部，没面完的能接着面。
// 默认只显示最近 10 条（先按「全部 / 通过 / 未通过」筛，再取 10 条），更早的点「显示更早的」再展开，不删任何记录。
// 有还在分析的投递时每 3 秒刷新一次列表。样稿：docs/design/我的投递预览.html
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { applyApi, isRunning, type ApplyBrief } from '../api/apply'
import { ApiError } from '../api/client'
import { AppShell } from '../components/AppShell'
import { MagneticButton } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { InterviewPill, when } from '../components/InterviewPill'
import { Tabs } from '../components/Tabs'
import { useDomains } from '../store/domains'

const POLL_MS = 3000
const RING = 138.2 // 2π × r(22)
const LIMIT = 10 // 默认显示几条

type Filter = 'all' | 'pass' | 'fail'
const FILTERS: [Filter, string, (a: ApplyBrief) => boolean][] = [
  ['all', '全部', () => true],
  ['pass', '通过', (a) => a.status === 'success' && a.passed === true],
  ['fail', '未通过', (a) => a.status === 'success' && a.passed === false],
]

const icOf = (t: string) => t.replace(/\s/g, '').slice(0, 2) // 同工作台：图标取标题前两个字

export default function MyApplies() {
  const [data, setData] = useState<{ items: ApplyBrief[]; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [expanded, setExpanded] = useState(false)
  const barRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const pick = (f: Filter) => { setFilter(f); setExpanded(false) } // 换个筛选就收回到最近 10 条
  const toggle = () => {
    setExpanded(!expanded)
    if (!expanded) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    barRef.current?.scrollIntoView({ behavior: reduce ? 'instant' : 'smooth' }) // 收起后回到列表顶上，不停在一片空白里
  }

  useEffect(() => {
    let cancelled = false
    applyApi.list()
      .then((r) => { if (!cancelled) { setData(r); setError(null) } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : '加载失败，请稍后刷新') })
    return () => { cancelled = true }
  }, [])

  // 还有在分析的：过一会儿再取一次，直到都出结果
  const running = data?.items.some(isRunning) ?? false
  useEffect(() => {
    if (!running) return
    const t = setTimeout(() => { applyApi.list().then(setData).catch(() => { /* 下次再试 */ }) }, POLL_MS)
    return () => clearTimeout(t)
  }, [data, running])

  const items = data?.items ?? []
  const shown = items.filter(FILTERS.find((f) => f[0] === filter)![2])
  const visible = expanded ? shown : shown.slice(0, LIMIT)
  const passed = items.filter(FILTERS[1][2]).length
  const interviews = items.reduce((n, a) => n + a.interviews.length, 0)

  let list
  if (error) list = <div className="ap-note">{error}</div>
  else if (!data) list = <p className="hint">加载中…</p>
  else if (!items.length) list = (
    <div className="ap-empty fade d2">
      <b>还没有投递记录</b>
      <p>选一个方向和岗位，传一份简历，<br />投出去之后结果会出现在这里。</p>
      <MagneticButton className="btn accent" onClick={() => navigate('/app')}>去投第一份 <span className="arrow">→</span></MagneticButton>
    </div>
  )
  else list = shown.length ? (
    <>
      {/* 展开时新出来的那些，进场动画从头排（不然第 11 条要等 0.75 秒） */}
      {visible.map((a, i) => <ApplyCard key={a.id} a={a} index={i < LIMIT ? i : Math.min(i - LIMIT, LIMIT)} />)}
      {shown.length > LIMIT && (
        <button type="button" className={`ap-more${expanded ? ' up' : ''}`} onClick={toggle}>
          {expanded ? `收起，只看最近 ${LIMIT} 条` : `显示更早的 ${shown.length - LIMIT} 条`} <span className="ar" aria-hidden="true">{expanded ? '↑' : '↓'}</span>
        </button>
      )}
    </>
  ) : <div className="ap-note">没有{filter === 'pass' ? '通过' : '未通过'}的投递。</div>

  return (
    <AppShell>
      <section className="screen ap-page">
        <header className="ap-head">
          <div>
            <Headline badge="记录" label="我的投递" lines={['投过的岗位，', <>都在<Mark>这里</Mark>。</>]} />
            <p className="sub fade d2">点一条看初筛结果和修改建议。这次投递面过的模拟面试也挂在下面，没面完的可以接着面。</p>
          </div>
          {items.length > 0 && (
            <div className="ap-stats fade d3">
              <div><b>{data!.total}</b><span>次投递</span></div>
              <div><b>{passed}</b><span>初筛通过</span></div>
              <div><b>{interviews}</b><span>场面试</span></div>
            </div>
          )}
        </header>

        {items.length > 0 && (
          <div className="ap-bar fade d3" ref={barRef}>
            <Tabs tabs={FILTERS.map(([key, label, f]) => ({ key, label: <>{label}<i>{items.filter(f).length}</i></> }))}
              value={filter} onChange={pick} />
            <MagneticButton className="btn accent" onClick={() => navigate('/app')}>新的投递 <span className="arrow">→</span></MagneticButton>
          </div>
        )}
        <div className="ap-list">{list}</div>
      </section>
    </AppShell>
  )
}

function ApplyCard({ a, index }: { a: ApplyBrief; index: number }) {
  const domains = useDomains()
  const pass = a.status === 'success' && a.passed === true

  let result
  if (isRunning(a)) result = <><span className="ap-spin" /><span className="ap-badge run">分析中</span></>
  else if (a.status === 'failed') result = <><span className="why">{a.failure}</span><span className="ap-badge err">分析失败</span></>
  else {
    const score = Math.round(a.overall_match ?? 0)
    result = (
      <>
        <span className="ap-ring">
          <svg width="52" height="52" aria-hidden="true">
            <circle className="tr" cx="26" cy="26" r="22" />
            <circle className="br" cx="26" cy="26" r="22" style={{ strokeDashoffset: RING * (1 - score / 100) }} />
          </svg>
          <b>{score}</b>
        </span>
        <span className={`ap-badge ${pass ? 'ok' : 'no'}`}>{pass ? '初筛通过' : '未通过'}</span>
      </>
    )
  }

  // 卡片底部：面过的场次；一场都没有时给下一步
  let foot = null
  if (a.interviews.length) foot = <><span className="k">面试</span>{a.interviews.map((v) => <InterviewPill key={v.id} v={v} />)}</>
  else if (a.status === 'success') foot = (
    <><span className="none">还没面试</span>
      <Link className="ap-next" to={`/app/apply/${a.id}/interview`}>{pass ? '进入模拟面试' : '以练习模式面试'} →</Link></>
  )
  else if (a.status === 'failed') foot = <Link className="ap-next" to={`/app?job=${a.job_id}`}>重新投递 →</Link>

  return (
    <article className={`ap${pass ? ' pass' : ''}`} style={{ animationDelay: `${index * 60 + 150}ms` }}>
      <Link className="ap-main" to={`/app/apply/${a.id}`}>
        <span className="ap-ic">{icOf(a.job_title)}</span>
        <div className="ap-text">
          <div className="ap-title">
            {a.job_title}
            {a.company && <span className="co">{a.company}</span>}
            <span className="ap-dir">{domains?.find((d) => d.key === a.domain)?.name ?? ''}</span>
          </div>
          <div className="ap-meta"><b>{a.resume_title}</b> · {when(a.created_at)}</div>
        </div>
        <div className="ap-res">{result}</div>
        <span className="ap-go" aria-hidden="true">›</span>
      </Link>
      {foot && <div className="ap-iv">{foot}</div>}
    </article>
  )
}
