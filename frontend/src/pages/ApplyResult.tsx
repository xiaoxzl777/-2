// 初筛结果：/app/apply/:id。通过 / 未通过两种；还在分析就显示流程卡，跑完自动换成结果；分析失败给出重投入口。
// 每条问题点开看依据和针对这一句的具体建议（现场生成），也可以在简历原文纸面上定位。
import { useCallback, useMemo, useRef, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { applyApi, isAbort, isRunning, type ApplyResult as Result, type Dimension, type MatchItem } from '../api/apply'
import { adviceApi } from '../api/advice'
import { ApiError } from '../api/client'
import { jobsApi, REQ_TYPE_LABEL } from '../api/jobs'
import { resumesApi, type ResumeStructure } from '../api/resumes'
import { AdviceBlock } from '../components/AdviceBlock'
import { AppShell } from '../components/AppShell'
import { MagneticButton, TiltCard, useCountUp } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { IssueItem, type DetailRow } from '../components/IssueItem'
import { NotFound, notFoundText } from '../components/NotFound'
import { Pipeline, useApplyTracker, type PipeState } from '../components/Pipeline'
import { ResumeSheet, type SheetDoc, type SheetItem } from '../components/ResumeSheet'
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
      setError(notFoundText(err, '这条投递记录不存在，可能已经被删除。'))
    })
    return () => { cancelled = true }
  }, [applyId, track])

  let body
  if (error) body = <NotFound badge="初筛结果" what="这次投递" message={error} />
  else if (!data) body = <section className="screen"><p className="hint">加载中…</p></section>
  else if (isRunning(data)) body = <Analyzing pipe={pipe} jobTitle={jobTitle} />
  else if (data.status === 'failed' || !data.gate) body = <Failed data={data} jobTitle={jobTitle} />
  else body = <Outcome key={data.id} data={data} gate={data.gate} jobTitle={jobTitle} />
  return <AppShell progress={100}>{body}</AppShell>
}

// ───────────── 结果 ─────────────

function Outcome({ data, gate, jobTitle }: { data: Result; gate: NonNullable<Result['gate']>; jobTitle: string }) {
  const navigate = useNavigate()
  // ?open=finding:12 / requirement:4：从面试报告点过来，切到对应的页签并展开那一条
  const [search] = useSearchParams()
  const [openKind, openId] = (search.get('open') ?? '').split(':')
  const openKey = openKind === 'finding' ? `finding:${openId}` : openKind === 'requirement' ? `gap:${data.id}:${openId}` : null
  const [tab, setTab] = useState<'gap' | 'self'>(openKind === 'finding' ? 'self' : 'gap')
  const [shown, setShown] = useState(false) // 进场后再让圆环、分数条动起来
  useEffect(() => {
    const t = window.setTimeout(() => setShown(true), 500)
    return () => window.clearTimeout(t)
  }, [])

  // 原文纸面：第一次打开时才去取原文、结构和完整匹配明细（「满足」的标注要用）
  const [sheet, setSheet] = useState<{ open: boolean; focus: string | null }>({ open: false, focus: null })
  const [doc, setDoc] = useState<SheetDoc | null>(null)
  const [docError, setDocError] = useState<string | null>(null)
  const [resumeTitle, setResumeTitle] = useState('')
  const [hits, setHits] = useState<MatchItem[]>([])
  const loading = useRef(false)
  const openSheet = (focus: string | null) => {
    setSheet({ open: true, focus })
    if (loading.current) return
    loading.current = true
    setDocError(null)
    Promise.all([
      resumesApi.blocks(data.resume_id),
      resumesApi.structure(data.resume_id).catch((): ResumeStructure => ({})),
      resumesApi.get(data.resume_id).then((r) => r.title).catch(() => ''),
      applyApi.match(data.id).then((m) => m.items).catch((): MatchItem[] => []),
    ]).then(([blocks, structure, title, items]) => {
      setDoc({ ...blocks, entryBlocks: entryBlocksOf(structure) })
      setResumeTitle(title)
      setHits(items.filter((i) => i.status === 'hit'))
    }).catch((err) => {
      loading.current = false
      setDocError(err instanceof ApiError ? err.message : '请稍后重试')
    })
  }
  const closeSheet = useCallback(() => setSheet((s) => ({ ...s, open: false })), [])
  const focusOn = useCallback((key: string | null) => setSheet((s) => ({ ...s, focus: key })), [])
  const items = useMemo(() => sheetItems(data, hits), [data, hits])

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
    <>
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
              <MagneticButton className="accent lg" onClick={() => navigate(`/app/apply/${data.id}/interview`)}>进入模拟面试 <span className="arrow">→</span></MagneticButton>
              <MagneticButton className="outline lg" onClick={() => navigate('/app')}>再投一个</MagneticButton>
            </>
          ) : (
            <>
              <MagneticButton className="accent lg" onClick={() => navigate(`/app?job=${data.job_id}`)}>改完简历，再投这个岗位 <span className="arrow">→</span></MagneticButton>
              <MagneticButton className="outline lg" onClick={() => navigate(`/app/apply/${data.id}/interview`)}>以练习模式面试</MagneticButton>
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
            <button type="button" className="link" onClick={() => openSheet(null)}>查看简历原文 →</button>
          </div>
          <div className="issues">
            <ItemList key={tab} items={items.filter((x) => x.list === tab)} onLocate={openSheet} openKey={openKey}
              empty={tab === 'gap' ? '岗位要求都满足了。' : '简历本身没发现明显问题。'} />
          </div>
        </TiltCard>
      </div>
    </section>
    <ResumeSheet open={sheet.open} title={resumeTitle} doc={doc} loadError={docError} items={items}
      focusKey={sheet.focus} onFocus={focusOn} onClose={closeSheet} />
    </>
  )
}

function matchedByText(g: MatchItem): string {
  if (!g.matched_by) return '规则无法判定'
  const verified = g.matched_by === 'fulltext' && g.evidence_quote ? ' · 引用已在原文中核实' : ''
  return MATCHED_BY[g.matched_by] + verified
}

function entryBlocksOf(structure: ResumeStructure): number[] {
  return (['education', 'work', 'projects', 'awards'] as const)
    .flatMap((k) => structure[k] ?? []).map((e) => e.block_ids?.[0]).filter((i): i is number => i !== undefined)
}

type ListItem = SheetItem & { rows: DetailRow[] }

/** 三类条目：对照岗位的差距、简历本身的问题、满足的要求（只在原文纸面上用）。列表与纸面共用同一份，具体建议也共享 */
function sheetItems(data: Result, hits: MatchItem[]): ListItem[] {
  const gap = data.gaps.map((g): ListItem => {
    const key = `gap:${data.id}:${g.requirement_id}`
    return {
      key, list: 'gap', color: g.status !== 'miss' && g.char_start !== null ? 'part' : null,
      tag: g.status === 'miss' ? ['miss', '缺失'] : ['part', '部分'], text: g.content,
      why: `${REQ_TYPE_LABEL[g.req_type]} · ${g.reason}`, note: `部分满足：${g.content}`,
      fix: ['判定方式', matchedByText(g)], start: g.char_start, end: g.char_end,
      advice: { key, path: adviceApi.gapPath(data.id, g.requirement_id), cached: g.advice ?? null, kind: 'gap' },
      rows: [
        g.evidence_quote ? { label: '简历原文', value: `「${g.evidence_quote}」`, quote: true } : { label: '简历原文', value: '没有找到相关的内容' },
        { label: '判定方式', value: matchedByText(g) },
      ],
    }
  })
  // 页数、图片这类问题针对整份简历，没有具体的原文。规则的"问题 / 怎么改"是固定模板，太泛，换成针对这一句现场生成的建议
  const self = data.resume_issues.map((f): ListItem => {
    const key = `finding:${f.id}`
    const [cls, label] = SEVERITY[f.severity]
    return {
      key, list: 'self', color: f.char_start !== null ? 'bad' : null, tag: [cls, label],
      text: f.evidence_quote ? `「${f.evidence_quote}」` : f.title, why: f.evidence_quote ? f.title : '针对整份简历',
      note: f.title, start: f.char_start, end: f.char_end,
      advice: { key, path: adviceApi.findingPath(f.id), cached: f.rewrite, kind: 'finding', fallback: f.suggestion },
      rows: [{ label: '来源', value: f.source === 'rule' ? '规则检查' : '大模型审阅 · 引用已在原文中核实' }],
    }
  })
  const hit = hits.map((h): ListItem => ({
    key: `hit:${data.id}:${h.requirement_id}`, list: 'hit', color: h.char_start !== null ? 'good' : null,
    tag: ['hit', '满足'], text: h.content, why: `${REQ_TYPE_LABEL[h.req_type]} · ${h.reason}`, note: `满足：${h.content}`,
    fix: ['判定方式', matchedByText(h)], start: h.char_start, end: h.char_end, rows: [],
  }))
  return [...gap, ...self, ...hit]
}

function ItemList({ items, empty, onLocate, openKey }: { items: ListItem[]; empty: string; onLocate: (key: string) => void; openKey: string | null }) {
  if (items.length === 0) return <p className="empty">{empty}</p>
  return (
    <>
      {items.map((x, i) => (
        <IssueItem key={x.key} index={i} tag={x.tag[1]} tagClass={x.tag[0]} text={x.text} why={x.why} rows={x.rows} defaultOpen={x.key === openKey}
          locate={{
            label: x.color ? '在原文中查看 →' : x.list === 'gap' ? '打开原文，看看缺在哪 →' : '打开简历原文 →',
            onClick: () => onLocate(x.key),
          }}>
          {x.advice && <AdviceBlock source={x.advice} />}
        </IssueItem>
      ))}
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
