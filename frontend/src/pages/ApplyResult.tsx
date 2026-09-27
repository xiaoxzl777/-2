// 初筛结果：/app/apply/:id。通过 / 未通过两种；还在分析就显示流程卡，跑完自动换成结果；分析失败给出重投入口。
// 每条问题可以点开看原文、依据、建议；在简历原文里高亮下一轮再做。
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { applyApi, isAbort, isRunning, type ApplyResult as Result, type Dimension, type Finding, type MatchItem } from '../api/apply'
import { ApiError } from '../api/client'
import { jobsApi, REQ_TYPE_LABEL } from '../api/jobs'
import { AppShell } from '../components/AppShell'
import { MagneticButton, TiltCard, useCountUp } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { IssueItem, type DetailRow } from '../components/IssueItem'
import { Pipeline, useApplyTracker, type PipeState } from '../components/Pipeline'
import { Tabs } from '../components/Tabs'

const DIMENSIONS: [Dimension, string][] = [['skill', '技能'], ['education', '学历'], ['experience', '经验'], ['other', '其他']]
const MATCHED_BY = { dict: '规则判定（技能词典）', profile: '规则判定（学历 / 年限）', fulltext: '大模型判定' }
const SEVERITY = { high: ['high', '严重'], medium: ['med', '中等'], low: ['low', '轻微'] } as const
const RING = 314.2 // 2π × r(50)

export default function ApplyResult() {
  const { id } = useParams()
  const applyId = Number(id)
  const [data, setData] = useState<Result | null>(null)
  const [jobTitle, setJobTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { pipe, track } = useApplyTracker()

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      let r = await applyApi.get(applyId)
      if (cancelled) return
      setData(r)
      jobsApi.get(r.job_id).then((j) => { if (!cancelled) setJobTitle(j.title) }).catch(() => { /* 岗位删了就不显示名字 */ })
      if (!isRunning(r)) return
      await track(applyId, { stage: r.stage === 'parsing' ? 'parsing' : 'analyzing' })
      r = await applyApi.get(applyId)
      if (!cancelled) setData(r)
    }
    load().catch((err) => {
      if (cancelled || isAbort(err)) return
      setError(err instanceof ApiError && err.code !== 40401 ? err.message : '这条投递记录不存在，可能已经被删除。')
    })
    return () => { cancelled = true }
  }, [applyId, track])

  let body
  if (error) body = <Missing message={error} />
  else if (!data) body = <section className="screen"><p className="hint">加载中…</p></section>
  else if (isRunning(data)) body = <Analyzing pipe={pipe} jobTitle={jobTitle} />
  else if (data.status === 'failed' || !data.gate) body = <Failed data={data} jobTitle={jobTitle} />
  else body = <Outcome key={data.id} data={data} gate={data.gate} jobTitle={jobTitle} />
  return <AppShell progress={100}>{body}</AppShell>
}

// ───────────── 结果 ─────────────

function Outcome({ data, gate, jobTitle }: { data: Result; gate: NonNullable<Result['gate']>; jobTitle: string }) {
  const navigate = useNavigate()
  const [tab, setTab] = useState<'gap' | 'self'>('gap')
  const [shown, setShown] = useState(false) // 进场后再让圆环、分数条动起来
  useEffect(() => {
    const t = window.setTimeout(() => setShown(true), 500)
    return () => window.clearTimeout(t)
  }, [])

  const passed = gate.passed
  const overall = gate.overall_match === null ? null : Math.round(gate.overall_match)
  const count = useCountUp(shown ? overall ?? 0 : 0)
  const dims = DIMENSIONS.flatMap(([key, label]) => {
    const v = data.dimension_scores?.[key]
    return v === null || v === undefined ? [] : [{ key, label, value: Math.round(v) }]
  })
  const hasHardGap = data.gaps.some((g) => g.req_type === 'hard')
  const anythingToFix = data.gaps.length > 0 || data.resume_issues.length > 0
  const sub = passed
    ? `匹配度 ${overall}，过了 ${gate.threshold} 分的初筛线。` +
      (anythingToFix ? '下面还有几处可以写得更好，面试前值得先改。' : '岗位要求都满足了，简历本身也没发现明显问题。')
    : `匹配度 ${overall ?? '—'}，初筛线是 ${gate.threshold}。` +
      (hasHardGap ? '先看「对照岗位」里的必须项，补上它们分数涨得最快；简历本身的问题也顺手改掉。' : '先看「对照岗位」里没满足的要求，简历本身的问题也顺手改掉。')

  return (
    <section className="screen">
      <div>
        <Headline badge="初筛结果" label={jobTitle || '岗位'}
          lines={passed ? ['通过初筛，', <>可以去<Mark>面试</Mark>了。</>] : ['差一点，', <>这次没过<Mark>初筛</Mark>。</>]} />
        <p className="sub result-sub fade d2">{sub}</p>
        <div className="score-hero fade d2">
          <div className="score-ring" role="img" aria-label={`匹配度 ${overall ?? '无'}`}>
            <svg width="120" height="120" viewBox="0 0 120 120" aria-hidden="true">
              <circle className="arc-track" cx="60" cy="60" r="50" />
              <circle className="arc-bar" cx="60" cy="60" r="50" style={{ strokeDashoffset: RING * (1 - (shown ? overall ?? 0 : 0) / 100) }} />
            </svg>
            <div className="num" aria-hidden="true">{overall === null ? '—' : count}</div>
          </div>
          <div className="dims">
            {dims.map((d) => (
              <div key={d.key} className="dim">
                <div className="l">{d.label}<b>{d.value}</b></div>
                <div className="tk"><i style={{ width: shown ? `${d.value}%` : 0 }} /></div>
              </div>
            ))}
          </div>
        </div>
        <div className="cta fade d3">
          {passed ? (
            <>
              <button type="button" className="btn soon lg" disabled>进入模拟面试 <small>即将开放</small></button>
              <MagneticButton className="outline lg" onClick={() => navigate('/app')}>再投一个</MagneticButton>
            </>
          ) : (
            <>
              <MagneticButton className="accent lg" onClick={() => navigate(`/app?job=${data.job_id}`)}>改完简历，再投这个岗位 <span className="arrow">→</span></MagneticButton>
              <button type="button" className="btn soon lg" disabled>以练习模式面试 <small>即将开放</small></button>
            </>
          )}
        </div>
      </div>
      <div className="stage fade d4">
        <div className="floaty tl show"><b>{overall ?? '—'} / {gate.threshold}</b><span>匹配度 / 初筛线</span></div>
        <TiltCard>
          <div className="card-head">
            <Tabs value={tab} onChange={setTab} tabs={[
              { key: 'gap', label: `对照岗位 · ${data.gaps.length}` },
              { key: 'self', label: `简历本身 · ${data.resume_issues.length}` },
            ]} />
            <span className="hint">点一条看详情</span>
          </div>
          <div className="issues">
            {tab === 'gap' ? <GapList gaps={data.gaps} /> : <FindingList findings={data.resume_issues} />}
          </div>
        </TiltCard>
      </div>
    </section>
  )
}

function matchedByText(g: MatchItem): string {
  if (!g.matched_by) return '规则无法判定'
  const verified = g.matched_by === 'fulltext' && g.evidence_quote ? ' · 引用已在原文中核实' : ''
  return MATCHED_BY[g.matched_by] + verified
}

function GapList({ gaps }: { gaps: MatchItem[] }) {
  if (gaps.length === 0) return <p className="empty">岗位要求都满足了。</p>
  return (
    <>
      {gaps.map((g, i) => (
        <IssueItem key={g.requirement_id} index={i}
          tag={g.status === 'miss' ? '缺失' : '部分'} tagClass={g.status === 'miss' ? 'miss' : 'part'}
          text={g.content} why={`${REQ_TYPE_LABEL[g.req_type]} · ${g.reason}`}
          rows={[
            g.evidence_quote ? { label: '简历原文', value: `「${g.evidence_quote}」`, quote: true } : { label: '简历原文', value: '没有找到相关的内容' },
            { label: '判定方式', value: matchedByText(g) },
          ]} />
      ))}
    </>
  )
}

function FindingList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return <p className="empty">简历本身没发现明显问题。</p>
  return (
    <>
      {findings.map((f, i) => {
        const [cls, label] = SEVERITY[f.severity]
        const rows: DetailRow[] = []
        if (f.description) rows.push({ label: '问题', value: f.description })
        if (f.suggestion) rows.push({ label: '怎么改', value: f.suggestion })
        rows.push({ label: '来源', value: f.source === 'rule' ? '规则检查' : '大模型审阅 · 引用已在原文中核实' })
        // 页数、图片这类问题针对整份简历，没有具体的原文
        return (
          <IssueItem key={f.id} index={i} tag={label} tagClass={cls}
            text={f.evidence_quote ? `「${f.evidence_quote}」` : f.title} why={f.evidence_quote ? f.title : '针对整份简历'} rows={rows} />
        )
      })}
    </>
  )
}

// ───────────── 其他状态 ─────────────

function Analyzing({ pipe, jobTitle }: { pipe: PipeState; jobTitle: string }) {
  return (
    <section className="screen">
      <div>
        <Headline badge="分析中" label={jobTitle || '岗位'} lines={['还在分析，', <>稍等<Mark>一下</Mark>。</>]} />
        <p className="sub fade d2">诊断简历和对照岗位同时进行，大约 20–40 秒。跑完这里会自动换成结果。</p>
      </div>
      <div className="stage fade d4">
        <TiltCard>
          <div className="card-head">
            <div className="dots" aria-hidden="true"><i /><i /><i /></div>
            <span className="hint">{pipe.done ? '分析完成' : '分析中…'}</span>
          </div>
          <Pipeline pipe={pipe} />
        </TiltCard>
      </div>
    </section>
  )
}

function Failed({ data, jobTitle }: { data: Result; jobTitle: string }) {
  const navigate = useNavigate()
  // 简历解析失败（如扫描件）时重投同一份没用，要换简历
  const badResume = (data.error_msg ?? '').includes('简历解析失败')
  return (
    <section className="screen">
      <div>
        <Headline badge="分析失败" label={jobTitle || '岗位'} lines={['这次分析', <>没能<Mark>完成</Mark>。</>]} />
        <p className="sub fade d2">
          {badResume
            ? '这份简历没能解析出来（比如是扫描件）。换一份文本版 PDF 再投这个岗位吧。'
            : '多半是大模型服务一时没响应。岗位和简历都还在，重新投一次就好。'}
        </p>
        <div className="cta fade d3">
          {badResume ? (
            <MagneticButton className="accent lg" onClick={() => navigate(`/app?job=${data.job_id}`)}>换一份简历再投 <span className="arrow">→</span></MagneticButton>
          ) : (
            <MagneticButton className="accent lg" onClick={() => navigate(`/app?job=${data.job_id}&resume=${data.resume_id}`)}>重新投递 <span className="arrow">→</span></MagneticButton>
          )}
          <MagneticButton className="outline lg" onClick={() => navigate('/app')}>换个岗位</MagneticButton>
        </div>
      </div>
      {data.error_msg && (
        <div className="stage fade d4">
          <TiltCard>
            <div className="card-head"><span className="hint">技术信息（排查用）</span></div>
            <p className="tech-msg">{data.error_msg}</p>
          </TiltCard>
        </div>
      )}
    </section>
  )
}

function Missing({ message }: { message: string }) {
  const navigate = useNavigate()
  return (
    <section className="screen">
      <div>
        <Headline badge="初筛结果" label="—" lines={['这次投递', <>找<Mark>不到</Mark>了。</>]} />
        <p className="sub fade d2">{message}</p>
        <div className="cta fade d3">
          <MagneticButton className="accent lg" onClick={() => navigate('/app')}>回到工作台 <span className="arrow">→</span></MagneticButton>
        </div>
      </div>
    </section>
  )
}
