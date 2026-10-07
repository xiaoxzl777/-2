// 面试报告：/app/interview/:id/report。左边结论 + 综合分 + 每个话题的分；右边「总结」「逐题回顾」两个页签。
// 「和简历问题的关联」点过去是初筛结果页，并直接展开对应的那一条（?open=finding:12 / requirement:4）。
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { interviewApi, SOURCE_LABEL, type InterviewReport as Data, type Turn } from '../api/interview'
import { AppShell } from '../components/AppShell'
import { MagneticButton, TiltCard, useCountUp } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { NotFound, notFoundText } from '../components/NotFound'
import { useDomain } from '../store/domains'
import { Tabs } from '../components/Tabs'
import { placeholders, underline } from '../components/InterviewText'

const RING = 314.2
const SHORT = 8 // 分数条上的话题名最多几个字

export default function InterviewReport() {
  const { id } = useParams()
  const sid = Number(id)
  const navigate = useNavigate()
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    interviewApi.report(sid).then((d) => { if (!cancelled) setData(d) }).catch((err) => {
      if (cancelled) return
      if (err instanceof ApiError && err.code === 40901) navigate(`/app/interview/${sid}`, { replace: true })  // 还没结束
      else setError(notFoundText(err, '这场面试不存在，可能已经被删除。'))
    })
    return () => { cancelled = true }
  }, [sid, navigate])

  return (
    <AppShell progress={100}>
      {error ? (
        <NotFound badge="面试报告" what="这份报告" message={error} />
      ) : data ? <Report data={data} /> : <section className="screen"><p className="hint">加载中…</p></section>}
    </AppShell>
  )
}

function Report({ data }: { data: Data }) {
  const label = useDomain(data.domain)?.interview_label ?? '面试'
  const navigate = useNavigate()
  const r = data.report
  const [tab, setTab] = useState<'sum' | 'turns'>('sum')
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setShown(true), 500)
    return () => window.clearTimeout(t)
  }, [])
  const count = useCountUp(shown ? r.overall : 0)
  const practice = r.verdict === 'practice'
  const noVerdict = practice || r.verdict === 'incomplete'
  const reached = r.topics.filter((t) => t.score !== null).length
  const nothing = r.answered === 0

  const lines: [ReactNode, ReactNode] = nothing ? ['这场面试', <>还没<Mark>开始</Mark>答。</>]
    : r.verdict === 'pass' ? [`${label}，`, <><Mark>通过</Mark>了。</>]
    : r.verdict === 'fail' ? [`这次${label}`, <><Mark>没过</Mark>。</>]
    : r.verdict === 'incomplete' ? ['这场面试', <>没有<Mark>做完</Mark>。</>]
    : ['这一场', <>练<Mark>完</Mark>了。</>]
  const sub = nothing ? '一道题都还没答就结束了，没有可以打分的内容。再面一次吧。'
    : r.verdict === 'pass' ? `综合 ${r.overall} 分，过了 ${r.threshold} 分的线。下面是这场的总结和每题回顾，薄弱的地方面试前值得再准备一下。`
    : r.verdict === 'fail' ? `综合 ${r.overall} 分，离 ${r.threshold} 分的线还差 ${Math.max(0, Math.ceil(r.threshold - r.overall))} 分。先看「需要加强」和每题的参考答法，改完可以再面一次。`
    : r.verdict === 'incomplete' ? `${r.topics.length} 个话题只聊了 ${reached} 个，不下通过与否的结论。综合 ${r.overall} 分只算了聊到的部分，完整面一次才有结论。`
    : `练习模式不下结论。综合 ${r.overall} 分，下面是这场的总结和每题回顾，练完可以再来一场。`

  const back = data.apply_id ? `/app/apply/${data.apply_id}` : '/app'
  return (
    <section className="screen">
      <div>
        <Headline badge={practice ? '练习模式' : '面试报告'} label={data.job_title ?? '岗位'} lines={lines} />
        <p className="sub result-sub fade d2">{sub}</p>
        {r.early && !nothing && r.verdict !== 'incomplete' && <p className="iv-early fade d2">提前结束：{r.topics.length} 个话题聊了 {reached} 个，没聊到的不计分。</p>}
        <div className="score-hero fade d2">
          <div className="score-ring" role="img" aria-label={`综合分 ${r.overall}`}>
            <svg width="120" height="120" viewBox="0 0 120 120" aria-hidden="true">
              <circle className="arc-track" cx="60" cy="60" r="50" />
              <circle className="arc-bar" cx="60" cy="60" r="50" style={{ strokeDashoffset: RING * (1 - (shown ? r.overall : 0) / 100) }} />
            </svg>
            <div className="num" aria-hidden="true">{count}</div>
          </div>
          <div className="iv-bars">
            {r.topics.map((t) => (
              <div key={t.idx} className="iv-bar">
                <div className="l"><span>{t.label.length > SHORT ? `${t.label.slice(0, SHORT)}…` : t.label}</span>
                  {t.score === null ? <b className="na">没聊到</b> : <b>{t.score}</b>}</div>
                <div className="tk"><i style={{ width: shown && t.score !== null ? `${t.score}%` : 0 }} /></div>
              </div>
            ))}
          </div>
        </div>
        <div className="cta fade d3">
          {data.apply_id && (
            <MagneticButton className="accent lg" onClick={() => navigate(`/app/apply/${data.apply_id}/interview`)}>再面一次 <span className="arrow">→</span></MagneticButton>
          )}
          <MagneticButton className="outline lg" onClick={() => navigate(back)}>回到初筛结果</MagneticButton>
        </div>
      </div>
      <div className="stage fade d4">
        <div className="floaty tl show"><b>{r.overall}{noVerdict ? '' : ` / ${r.threshold}`}</b><span>{noVerdict ? '综合分' : '综合分 / 通过线'}</span></div>
        <TiltCard>
          <div className="card-head">
            <Tabs value={tab} onChange={setTab} tabs={[{ key: 'sum', label: '总结' }, { key: 'turns', label: `逐题回顾 · ${data.turns.filter((t) => t.answer !== null).length}` }]} />
            <span className="hint">分数由每题评分算出，不让模型直接打总分</span>
          </div>
          <div className="issues">
            {tab === 'sum' ? <Summary data={data} /> : <Turns data={data} />}
          </div>
        </TiltCard>
      </div>
    </section>
  )
}

function Summary({ data }: { data: Data }) {
  const navigate = useNavigate()
  const r = data.report
  if (r.answered === 0) return <p className="empty">还没有答过题。</p>
  return (
    <div className="iv-sum">
      {!r.summary_ok && <p className="empty">这次的文字总结没能生成出来，分数不受影响，可以看「逐题回顾」里每题的点评。</p>}
      {r.strengths.length > 0 && (
        <>
          <h4 className="good">表现好的</h4>
          <ul>{r.strengths.map((p, i) => <li key={i} style={{ animationDelay: `${0.1 + i * 0.08}s` }}>{p.title}<small>{p.detail}</small></li>)}</ul>
        </>
      )}
      {r.weaknesses.length > 0 && (
        <>
          <h4 className="bad">需要加强</h4>
          <ul>{r.weaknesses.map((p, i) => <li key={i} style={{ animationDelay: `${0.3 + i * 0.08}s` }}>{p.title}<small>{p.detail}</small></li>)}</ul>
        </>
      )}
      {r.links.map((l) => (
        <div key={`${l.kind}:${l.ref_id}`} className="iv-linked">
          <div className="h">和{l.kind === 'finding' ? '简历问题' : '岗位要求'}的关联</div>
          <div className="q">{l.kind === 'finding' ? `简历里的「${l.label}」` : `岗位要求「${l.label}」`}</div>
          {l.text}
          {data.apply_id && (
            <button type="button" className="link" onClick={() => navigate(`/app/apply/${data.apply_id}?open=${l.kind}:${l.ref_id}`)}>
              去看这条的修改建议 →
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

function Turns({ data }: { data: Data }) {
  const labels = new Map(data.report.topics.map((t) => [t.idx, t]))
  const turns = data.turns.filter((t) => t.answer !== null)
  if (turns.length === 0) return <p className="empty">还没有答过题。</p>
  return <>{turns.map((t, i) => <TurnItem key={t.id} turn={t} index={i} topic={labels.get(t.topic_idx)} />)}</>
}

function TurnItem({ turn, index, topic }: { turn: Turn; index: number; topic?: { label: string; source: keyof typeof SOURCE_LABEL } }) {
  const [open, setOpen] = useState(false)
  const ev = turn.evaluation
  const score = turn.skipped ? null : ev?.score ?? null
  const cls = turn.skipped ? 'skip' : score === null ? 'skip' : score >= 80 ? 'hi' : score >= 60 ? 'mid' : 'lo'
  return (
    <div className={`issue ${open ? 'open' : ''}`} style={{ animationDelay: `${(0.05 + index * 0.06).toFixed(2)}s` }}>
      <button type="button" className="issue-row" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className={`tagx iv-score ${cls}`}>{turn.skipped ? '跳过' : score ?? '—'}</span>
        <span className="issue-text">
          <span className="main">{turn.question.replace(/^你好，[^\n]*\n/, '')}</span>
          <span className="why">话题 {turn.topic_idx + 1}{topic ? ` · ${topic.label}` : ''}{turn.depth > 0 ? ' · 追问' : ''}</span>
        </span>
        <span className="issue-arrow" aria-hidden="true">›</span>
      </button>
      <div className="detail" aria-hidden={!open}>
        <div>
          <div className="detail-in">
            <p><span className="k">你的回答</span><span className="q">{turn.skipped ? '这题跳过了' : underline(turn.answer ?? '', ev?.evidence.map((x) => x.quote) ?? [])}</span></p>
            {ev && !ev.skipped && ev.scores && (
              <p><span className="k">评分</span><span>正确性 {ev.scores.correctness} · 深度 {ev.scores.depth} · 表达 {ev.scores.clarity}（各 5 分）{ev.low_evidence ? ' · 没引用到原话，按中间分计' : ''}</span></p>
            )}
            {ev?.good && ev.good !== '无' && <p><span className="k">好在</span><span>{ev.good}</span></p>}
            {ev?.bad && !ev.skipped && <p><span className="k">差在</span><span>{ev.bad}</span></p>}
            {ev?.better_answer && <p><span className="k">参考答法</span><span className="q">{placeholders(ev.better_answer)}</span></p>}
          </div>
        </div>
      </div>
    </div>
  )
}
