// 模拟面试：/app/interview/:id。左边是话题进度（问到哪个才显示哪个），右边是对话。
// 题目流式出来；练习模式每题答完先给点评，正常模式只显示「已记录」。刷新后从 GET /interviews/{id} 恢复，
// 中途出错给「重试」，重试就是调 start 从原处继续（后端的检查点停在失败的那一步）。样稿：docs/design/模拟面试预览.html
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  ANSWER_MAX, interviewApi, interviewStream, RejectedError, SOURCE_LABEL,
  type Evaluation, type Interview as Session, type Topic,
} from '../api/interview'
import { AppShell } from '../components/AppShell'
import { MagneticButton } from '../components/effects'
import { placeholders, underline } from '../components/InterviewText'
import { NotFound, notFoundText } from '../components/NotFound'
import { useAuth } from '../store/auth'

type Entry =
  | { kind: 'q'; key: string; topicIdx: number; depth: number; text: string; streaming: boolean }
  | { kind: 'a'; key: string; topicIdx: number; text: string; skipped: boolean; quotes: string[] }
  | { kind: 'eval'; key: string; ev: Evaluation; next: string | null }
  | { kind: 'noted'; key: string }
  | { kind: 'end'; key: string }

type Phase = 'loading' | 'asking' | 'waiting' | 'thinking' | 'finished' | 'error'

const DIMENSIONS = [['correctness', '正确性'], ['depth', '深度'], ['clarity', '表达']] as const
let seq = 0
const newKey = (p: string) => `${p}-${++seq}`

export default function Interview() {
  const { id } = useParams()
  const sid = Number(id)
  const navigate = useNavigate()
  const username = useAuth((s) => s.user?.username ?? '我')
  const [session, setSession] = useState<Session | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [topics, setTopics] = useState<Topic[]>([])
  const [current, setCurrent] = useState(-1)
  const [phase, setPhase] = useState<Phase>('loading')
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [hint, setHint] = useState<string | null>(null)
  const [shake, setShake] = useState(0)
  const [confirming, setConfirming] = useState(false)
  const [ending, setEnding] = useState(false)
  const started = useRef(false) // 开发环境 StrictMode 会把 effect 跑两遍，不能因此连开两次
  const msgsRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const practice = session?.mode === 'practice'

  const patch = (key: string, change: (e: Entry) => Entry) => setEntries((es) => es.map((e) => (e.key === key ? change(e) : e)))

  /** 开始 / 继续（answer 不传）或答题，把事件翻译成对话里的一条条 */
  const run = async (mode: Session['mode'], answer?: { text: string; skip: boolean }, answerKey?: string) => {
    setError(null)
    setPhase(answer ? 'thinking' : 'asking')
    let qKey: string | null = null
    let evalKey: string | null = null
    let noted = !answer || answer.skip || mode === 'practice' // 跳过的题什么都不显示，直接出下一题
    const note = () => {
      if (noted) return
      noted = true
      setEntries((es) => [...es, { kind: 'noted', key: newKey('noted') }])
    }
    const nextIs = (text: string) => {
      if (!evalKey) return
      const key = evalKey
      evalKey = null
      patch(key, (e) => (e.kind === 'eval' ? { ...e, next: text } : e))
    }
    let ended = false
    let lastTopic = current
    const addQuestion = (topicIdx: number, depth: number) => {
      const key = newKey('q')
      setEntries((es) => [...es, { kind: 'q', key, topicIdx, depth, text: '', streaming: true }])
      return key
    }
    try {
      for await (const ev of interviewStream(sid, answer)) {
        if (ev.name === 'evaluation') {
          const quotes = ev.data.evidence.map((x) => x.quote)
          const key = newKey('eval')
          evalKey = key
          setEntries((es) => {
            const out = [...es]
            const i = out.map((e) => e.kind).lastIndexOf('a')
            if (i >= 0 && out[i].kind === 'a') out[i] = { ...out[i], quotes } as Entry
            return [...out, { kind: 'eval', key, ev: ev.data, next: null }]
          })
        } else if (ev.name === 'topic') {
          note()
          nextIs(`→ 进入下一个话题：${ev.data.label}`)
          const topic = { idx: ev.data.idx, label: ev.data.label, source: ev.data.source }
          setTopics((ts) => (ts.some((t) => t.idx === topic.idx) ? ts : [...ts, topic]))
          setCurrent(ev.data.idx)
          lastTopic = ev.data.idx
        } else if (ev.name === 'asking') {
          note()
          if (ev.data.depth > 0) nextIs('→ 面试官会就这一点追问一次')
          qKey = addQuestion(ev.data.topic_idx, ev.data.depth)
          setPhase('asking')
        } else if (ev.name === 'question') {
          const delta = ev.data.delta
          const key = qKey ?? (qKey = addQuestion(lastTopic, 0))    // 没收到 asking 也照样显示
          patch(key, (e) => (e.kind === 'q' ? { ...e, text: e.text + delta } : e))
        } else if (ev.name === 'asked') {
          const { text, topic_idx: topicIdx, depth } = ev.data
          const key = qKey ?? (qKey = addQuestion(topicIdx, depth))   // 刷新后重新开始：只会收到这一个事件
          patch(key, (e) => (e.kind === 'q' ? { ...e, text, topicIdx, depth, streaming: false } : e))
          ended = true
          setPhase('waiting')
          window.setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 50)
        } else if (ev.name === 'finished') {
          note()
          nextIs('→ 这是最后一题')
          ended = true
          setEntries((es) => [...es, { kind: 'end', key: newKey('end') }])
          setPhase('finished')
        }
      }
      if (!ended) throw new ApiError(0, '连接中断了')
    } catch (err) {
      if (err instanceof RejectedError && answer && answerKey) {
        // 回答被拒（空的、太长、已经答过）：撤回刚放上去的那条，内容还给输入框
        setEntries((es) => es.filter((e) => e.key !== answerKey))
        setDraft(answer.text)
        setPhase('waiting')
        setHint(err.message)
        return
      }
      if (err instanceof RejectedError && err.code === 40901 && !answer) {
        const fresh = await interviewApi.get(sid).catch(() => null)
        if (fresh && (fresh.status === 'completed' || fresh.status === 'abandoned')) {
          navigate(`/app/interview/${sid}/report`, { replace: true })
          return
        }
      }
      if (qKey) patch(qKey, (e) => (e.kind === 'q' ? { ...e, streaming: false } : e))
      setError(err instanceof ApiError && err.message ? err.message : '面试官这边出了点问题，请重试')
      setPhase('error')
    }
  }

  useEffect(() => {
    if (started.current) return
    started.current = true
    interviewApi.get(sid).then((data) => {
      if (data.status === 'completed' || data.status === 'abandoned') {
        navigate(`/app/interview/${sid}/report`, { replace: true })
        return
      }
      setSession(data)
      setTopics(data.topics)
      setEntries(fromTurns(data))
      setCurrent(data.turns.at(-1)?.topic_idx ?? -1)
      if (data.waiting) setPhase('waiting')
      else void run(data.mode)
    }).catch((err) => {
      setLoadError(notFoundText(err, '这场面试不存在，可能已经被删除。'))
    })
    // run 每次渲染都是新的函数，只在第一次挂载时调用
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid])

  useEffect(() => {
    const box = msgsRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [entries])

  const submit = (skip = false) => {
    if (phase !== 'waiting' || !session) return
    const text = draft.trim()
    if (!skip && !text) {
      setHint('先写点什么，或者点「跳过」')
      setShake((n) => n + 1)
      return
    }
    if (text.length > ANSWER_MAX) {
      setHint(`回答太长了，请控制在 ${ANSWER_MAX} 字以内`)
      setShake((n) => n + 1)
      return
    }
    const key = newKey('a')
    setEntries((es) => [...es, { kind: 'a', key, topicIdx: current, text: skip ? '' : text, skipped: skip, quotes: [] }])
    setDraft('')
    setHint(null)
    void run(session.mode, { text: skip ? '' : text, skip }, key)
  }

  const finishEarly = async () => {
    setEnding(true)
    try {
      await interviewApi.finish(sid)
      navigate(`/app/interview/${sid}/report`)
    } catch (err) {
      setEnding(false)
      setConfirming(false)
      setError(err instanceof ApiError ? err.message : '结束失败，请稍后重试')
    }
  }

  if (loadError) {
    return (
      <AppShell progress={0}>
        <NotFound badge="模拟面试" what="这场面试" message={loadError} />
      </AppShell>
    )
  }

  const count = session?.topic_count ?? 0
  const finished = phase === 'finished'
  const busy = phase === 'asking' || phase === 'thinking' || phase === 'loading'
  const answered = (idx: number) => entries.filter((e): e is Extract<Entry, { kind: 'a' }> => e.kind === 'a' && e.topicIdx === idx)
  const topicState = (idx: number) => {
    const done = finished || idx < current
    if (done && answered(idx).length > 0 && answered(idx).every((a) => a.skipped)) return 'skipped'
    return done ? 'done' : idx === current ? 'cur' : ''
  }
  const doneCount = finished ? count : Math.max(0, current)
  const status = {
    loading: ['准备中', ''], asking: ['正在出题…', 'busy'], waiting: ['等你回答', 'wait'],
    thinking: [practice ? '正在看你的回答…' : '面试官在听…', 'busy'], finished: ['面试结束', ''], error: ['出了点问题', 'err'],
  }[phase]
  const left = count - doneCount

  return (
    <AppShell progress={count ? (doneCount / count) * 100 : 0}>
      <section className="iv-screen">
        <aside className="iv-rail">
          <span className="tag fade d1">{practice ? <b className="pr">练习模式</b> : <b>技术面</b>}{practice ? '技术面' : '模拟面试'}</span>
          <div className="iv-job fade d1">{session?.job_title ?? '…'}</div>
          <div className="iv-mode fade d1">{practice ? '每题答完马上有点评' : '答题时不打分，结束后看报告'}</div>
          <div className="iv-count fade d2">
            {topics.length ? <>第 <b>{Math.min(current + 1, count) || topics.length}</b> / {count} 个话题</> : `共 ${count || '…'} 个话题`}
          </div>
          <ol className="iv-topics">
            {[...topics].sort((a, b) => a.idx - b.idx).map((t) => (
              <li key={t.idx} className={`iv-topic ${topicState(t.idx)}`}>
                <span className="no">{t.idx + 1}</span>
                <div><div className="lb">{t.label}</div><span className={`iv-src ${t.source}`}>{SOURCE_LABEL[t.source]}</span></div>
              </li>
            ))}
          </ol>
          <div className="iv-rail-foot">
            {finished ? (
              <MagneticButton className="accent sm" onClick={() => navigate(`/app/interview/${sid}/report`)}>看面试报告 <span className="arrow">→</span></MagneticButton>
            ) : (
              <button type="button" className="btn outline sm" disabled={busy || ending} onClick={() => setConfirming(true)}>提前结束，看报告</button>
            )}
            {confirming && !finished && (
              <div className="iv-confirm" role="alertdialog" aria-label="提前结束面试">
                {left > 0 ? `还有 ${left} 个话题没聊完。` : ''}现在结束，报告只按已经答过的题算。
                <div className="cta">
                  <button type="button" className="btn dark sm" disabled={ending} onClick={() => void finishEarly()}>{ending ? '正在出报告…' : '结束'}</button>
                  <button type="button" className="btn ghost sm" disabled={ending} onClick={() => setConfirming(false)}>继续面</button>
                </div>
              </div>
            )}
          </div>
        </aside>

        <div className="card iv-chat">
          <div className="iv-head">
            <span className="dots" aria-hidden="true"><i /><i /><i /></span>
            <span className="iv-who">{session?.company_name ? `${session.company_name} · 技术面试官` : '技术面试官'}</span>
            <span className={`iv-status ${status[1]}`}><i />{status[0]}</span>
          </div>
          <div className="iv-msgs" ref={msgsRef} aria-live="polite">
            {entries.map((e) => (
              <Fragment key={e.key}>{renderEntry(e, username, () => navigate(`/app/interview/${sid}/report`))}</Fragment>
            ))}
            {phase === 'thinking' && !practice && entries.at(-1)?.kind === 'a' && <div className="iv-noted">面试官在听…</div>}
            {phase === 'error' && (
              <div className="iv-error" role="alert">
                <span>{error}</span>
                <button type="button" className="btn dark sm" onClick={() => session && void run(session.mode)}>重试</button>
              </div>
            )}
          </div>
          <div className="iv-composer">
            <textarea key={shake} ref={inputRef} className={shake ? 'shake' : undefined} value={draft} disabled={phase !== 'waiting'}
              placeholder={finished ? '面试结束了' : '输入你的回答……（Ctrl + Enter 发送）'} maxLength={ANSWER_MAX + 200}
              onChange={(e) => { setDraft(e.target.value); setHint(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit() } }} />
            <div className="iv-comp-foot">
              <button type="button" className="link mute" disabled={phase !== 'waiting'} onClick={() => submit(true)}>这题不会，跳过</button>
              <span className={`hint ${hint || draft.length > ANSWER_MAX ? 'warn' : ''}`}>
                {hint ?? (draft.length ? `${draft.length} / ${ANSWER_MAX} 字` : '')}
              </span>
              <button type="button" className="btn dark sm iv-send" disabled={phase !== 'waiting'} onClick={() => submit()}>
                发送 <span className="arrow">↑</span>
              </button>
            </div>
          </div>
        </div>
      </section>
    </AppShell>
  )
}

/** 从已有的问答恢复对话（刷新页面、从别处回来） */
function fromTurns(data: Session): Entry[] {
  const out: Entry[] = []
  const labels = new Map(data.topics.map((t) => [t.idx, t.label]))
  data.turns.forEach((t, i) => {
    out.push({ kind: 'q', key: `q-${t.id}`, topicIdx: t.topic_idx, depth: t.depth, text: t.question, streaming: false })
    if (t.answer === null) return
    out.push({ kind: 'a', key: `a-${t.id}`, topicIdx: t.topic_idx, text: t.answer, skipped: t.skipped,
      quotes: t.evaluation?.evidence.map((x) => x.quote) ?? [] })
    if (t.evaluation && !t.evaluation.skipped) {
      const next = data.turns[i + 1]
      const text = !next ? null : next.depth > 0 ? '→ 面试官会就这一点追问一次'
        : `→ 进入下一个话题${labels.has(next.topic_idx) ? `：${labels.get(next.topic_idx)}` : ''}`
      out.push({ kind: 'eval', key: `e-${t.id}`, ev: t.evaluation, next: text })
    }
  })
  return out
}

function renderEntry(e: Entry, username: string, toReport: () => void): ReactNode {
  if (e.kind === 'q') {
    return (
      <div className="iv-msg">
        <span className="iv-av">面</span>
        <div className="iv-bubble">
          <div className="iv-qtag"><span>话题 {e.topicIdx + 1}</span>{e.depth > 0 && <span className="follow">追问</span>}</div>
          {e.text ? e.text : <span className="iv-typing" aria-label="正在出题"><i /><i /><i /></span>}
          {e.streaming && e.text && <span className="caret" aria-hidden="true" />}
        </div>
      </div>
    )
  }
  if (e.kind === 'a') {
    return (
      <div className={`iv-msg me ${e.skipped ? 'skip' : ''}`}>
        <span className="iv-av">{username.slice(0, 1).toUpperCase()}</span>
        <div className="iv-bubble">{e.skipped ? '（这题跳过了）' : underline(e.text, e.quotes)}</div>
      </div>
    )
  }
  if (e.kind === 'eval') return <EvalCard ev={e.ev} next={e.next} />
  if (e.kind === 'noted') return <div className="iv-noted">已记录</div>
  return (
    <>
      <div className="iv-msg">
        <span className="iv-av">面</span>
        <div className="iv-bubble">好的，今天的面试就到这里，辛苦了。报告已经生成好了。</div>
      </div>
      <div className="iv-end"><MagneticButton className="accent" onClick={toReport}>看面试报告 <span className="arrow">→</span></MagneticButton></div>
    </>
  )
}

/** 练习模式的点评：三项评分、好在哪、差在哪、依据（回答里被引用的原话）、参考答法（点开才显示） */
function EvalCard({ ev, next }: { ev: Evaluation; next: string | null }) {
  const [open, setOpen] = useState(false)
  if (ev.skipped) return null           // 跳过的题不给点评（练习模式也一样）
  return (
    <div className="iv-eval">
      <div className="iv-eval-top"><b>点评</b><span className="pts">{ev.score}<small> / 100</small></span></div>
      {ev.scores && (
        <div className="iv-scores">
          {DIMENSIONS.map(([k, label]) => (
            <div key={k} className="sc">
              <div className="l">{label}<b>{ev.scores![k]}</b></div>
              <span className="pips" aria-label={`${label} ${ev.scores![k]} / 5`}>
                {[1, 2, 3, 4, 5].map((n) => <i key={n} className={n <= ev.scores![k] ? 'on' : ''} />)}
              </span>
            </div>
          ))}
        </div>
      )}
      {ev.good && ev.good !== '无' && <p className="good"><span className="k">好在</span><span>{ev.good}</span></p>}
      {ev.bad && <p className="bad"><span className="k">差在</span><span>{ev.bad}</span></p>}
      {ev.evidence.length > 0 && (
        <p className="src"><span className="k">依据</span><span>{ev.evidence.map((x) => `你说的「${x.quote}」`).join('；')}</span></p>
      )}
      {ev.low_evidence && <p className="src"><span className="k">说明</span><span>评分员没能引用到你的原话，这题按中间分计、权重减半。</span></p>}
      {ev.better_answer && (
        <div className={`iv-better ${open ? 'open' : ''}`}>
          <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? '收起参考答法 ‹' : '看参考答法 ›'}</button>
          <div className="body"><div><p>{placeholders(ev.better_answer)}</p></div></div>
        </div>
      )}
      {next && <div className="iv-next">{next}</div>}
    </div>
  )
}
