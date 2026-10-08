// 初筛结果：/app/apply/:id。通过 / 未通过两种；还在分析就显示流程卡，跑完自动换成结果；分析失败给出重投入口。
// 每条问题点开看依据和针对这一句的具体建议（现场生成），同时在简历原文上定位。
import { useCallback, useMemo, useRef, useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { applyApi, isAbort, isRunning, type ApplyResult as Result, type MatchItem } from '../api/apply'
import { ApiError } from '../api/client'
import { jobsApi } from '../api/jobs'
import { resumesApi, type ResumeStructure } from '../api/resumes'
import { AdviceBlock } from '../components/AdviceBlock'
import { AppShell } from '../components/AppShell'
import { MagneticButton, useCountUp, useMedia } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { InterviewPill, isLive } from '../components/InterviewPill'
import { IssueItem } from '../components/IssueItem'
import { NotFound, notFoundText } from '../components/NotFound'
import { Pipeline, useApplyTracker, type PipeState } from '../components/Pipeline'
import { located, ResumePaper, type SheetDoc } from '../components/ResumePaper'
import { ResumeSheet } from '../components/ResumeSheet'
import { DIMENSIONS, entryBlocksOf, sheetItems, verdictSub, type ListItem } from './applyItems'

const RING = 314.2 // 2π × r(50)
const IV_SHOWN = 2

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
  else if (!data) body = <section className="rv"><p className="hint">加载中…</p></section>
  else if (isRunning(data)) body = <Analyzing pipe={pipe} jobTitle={jobTitle} />
  else if (data.status === 'failed' || !data.gate) body = <Failed data={data} jobTitle={jobTitle} />
  else body = <Outcome key={data.id} data={data} gate={data.gate} jobTitle={jobTitle} />
  return <AppShell progress={100}>{body}</AppShell>
}

// ───────────── 结果 ─────────────

// 顶部成绩单，下面左边问题清单、右边常驻原文（整页一套两列网格，各边对齐）。样稿：docs/design/结果页面试场次预览.html（「改后」）
// 宽屏：点开一条，右边原文就定位到它；点原文里的高亮，左边展开对应的那条。窄屏放不下两栏：原文照旧从右侧滑出
function Outcome({ data, gate, jobTitle }: { data: Result; gate: NonNullable<Result['gate']>; jobTitle: string }) {
  const navigate = useNavigate()
  const wide = useMedia('(min-width: 1001px)') // 和 index.css 里 .rv 的断点一致
  // ?open=finding:12 / requirement:4：从面试报告点过来，展开那一条并滚过去
  const [search] = useSearchParams()
  const [openKind, openId] = (search.get('open') ?? '').split(':')
  const openKey = openKind === 'finding' ? `finding:${openId}` : openKind === 'requirement' ? `gap:${data.id}:${openId}` : null
  const [shown, setShown] = useState(false) // 进场后再让圆环、分数条动起来
  useEffect(() => {
    const t = window.setTimeout(() => setShown(true), 500)
    return () => window.clearTimeout(t)
  }, [])

  // 原文：进页面就取（宽屏常驻在右边）—— 原文、结构、简历名和完整匹配明细（「满足」的标注要用）
  const [doc, setDoc] = useState<SheetDoc | null>(null)
  const [docError, setDocError] = useState<string | null>(null)
  const [resumeTitle, setResumeTitle] = useState('')
  const [hits, setHits] = useState<MatchItem[]>([])
  const loading = useRef(false)
  const loadDoc = useCallback(() => {
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
      loading.current = false // 失败了，下次打开抽屉再取
      setDocError(err instanceof ApiError ? err.message : '请稍后重试')
    })
  }, [data.id, data.resume_id])
  useEffect(loadDoc, [loadDoc])
  const items = useMemo(() => sheetItems(data, hits), [data, hits])
  const byKey = useMemo(() => new Map(items.map((x) => [x.key, x])), [items])

  // 窄屏的原文抽屉
  const [sheet, setSheet] = useState<{ open: boolean; focus: string | null }>({ open: false, focus: null })
  const openSheet = (focus: string | null) => {
    setSheet({ open: true, focus })
    loadDoc()
  }
  const closeSheet = useCallback(() => setSheet((s) => ({ ...s, open: false })), [])
  const focusOn = useCallback((key: string | null) => setSheet((s) => ({ ...s, focus: key })), [])

  // 左边清单：展开了哪些、右边原文正指着哪条（active）、鼠标停在哪条上（peek，原文里先亮一下）
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set(openKey ? [openKey] : []))
  const [active, setActive] = useState<string | null>(openKey)
  const [paper, setPaper] = useState({ key: openKey, pulse: 0 }) // 同一条再点一次也要重新闪、重新滚过去
  const [peek, setPeek] = useState<string | null>(null)
  const point = (key: string) => setPaper((p) => ({ key, pulse: p.pulse + 1 }))
  const toggle = (key: string) => {
    setExpanded((s) => {
      const next = new Set(s)
      if (!next.delete(key)) next.add(key)
      return next
    })
    setActive(key)
    point(key)
  }
  // 点了原文里的高亮：在左边展开那一条、滚到可见处；满足的要求左边没有，只在原文里指一下
  const fromPaper = (key: string) => {
    point(key)
    if (byKey.get(key)?.list === 'hit') return setActive(null)
    setExpanded((s) => new Set(s).add(key))
    setActive(key)
    scrollToItem(key)
  }
  // 从面试报告点过来的那一条，进页面时滚过去
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (openKey) scrollToItem(openKey) }, [])
  const pointed = paper.key ? byKey.get(paper.key) : undefined
  const paperMsg = !paper.key ? { hint: true, text: '点左边任意一条，这里会定位到简历里对应的那一句。' }
    : pointed && !located(pointed) ? {
      hint: false,
      text: pointed.list === 'gap' ? `简历里没有找到能证明「${pointed.text}」的内容 —— 这正是需要补上的地方。` : '这条针对整份简历，没有具体的某一句。',
    }
    : null

  const passed = gate.passed
  const overall = gate.overall_match === null ? null : Math.round(gate.overall_match)
  const count = useCountUp(shown ? overall ?? 0 : 0)
  const dims = DIMENSIONS.flatMap(([key, label]) => {
    const v = data.dimension_scores?.[key]
    return v === null || v === undefined ? [] : [{ key, label, value: Math.round(v) }]
  })
  const sub = verdictSub(data, gate)

  // 有一场没做完：按钮直接接着面，不再进准备页开新的一场
  const live = data.interviews.find(isLive)
  const toInterview = live ? `/app/interview/${live.id}` : `/app/apply/${data.id}/interview`
  // 成绩单里最多放两场（没做完的在前）：面过五场就是五行，成绩单撑高会把左边的标题挤下去；全部的在「我的投递」里
  const shownInterviews = [...data.interviews.filter(isLive), ...data.interviews.filter((v) => !isLive(v))].slice(0, IV_SHOWN)

  const listProps = {
    wide, expanded, active, onToggle: toggle, onHover: setPeek,
    onLocate: openSheet,
  }
  const gapItems = items.filter((x) => x.list === 'gap')
  const selfItems = items.filter((x) => x.list === 'self')

  return (
    <>
    <section className="rv">
      <div className="rv-band">
        <div>
          <Headline badge="初筛结果" label={jobTitle || '岗位'}
            lines={passed ? ['通过初筛，', <>可以去<Mark>面试</Mark>了。</>] : ['差一点，', <>这次没过<Mark>初筛</Mark>。</>]} />
          <p className="rv-sub fade d2">{sub[0]}<br />{sub[1]}</p>
          <div className="cta fade d3">
            {passed ? (
              <>
                <MagneticButton className="accent lg" onClick={() => navigate(toInterview)}>{live ? '继续面试' : '进入模拟面试'} <span className="arrow">→</span></MagneticButton>
                <MagneticButton className="outline lg" onClick={() => navigate('/app')}>再投一个</MagneticButton>
              </>
            ) : (
              <>
                <MagneticButton className="accent lg" onClick={() => navigate(`/app?job=${data.job_id}`)}>改完简历，再投这个岗位 <span className="arrow">→</span></MagneticButton>
                <MagneticButton className="outline lg" onClick={() => navigate(toInterview)}>{live ? '继续练习' : '以练习模式面试'}</MagneticButton>
              </>
            )}
            {/* 诊断报告：排成 A4、可以下载成 PDF 对照着改（样稿：docs/design/诊断报告导出预览.html） */}
            <Link className="rv-report" to={`/app/apply/${data.id}/report`}>预览报告</Link>
          </div>
        </div>
        <div className={`rv-score fade d2${data.interviews.length ? ' has-iv' : ''}`}>
          <div className="score-ring" role="img" aria-label={`匹配度 ${overall ?? '无'}，初筛线 ${gate.threshold}`}>
            <svg viewBox="0 0 120 120" aria-hidden="true">
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
          {data.interviews.length > 0 && (
            // 这次投递面过的场次，和分数放在一起（样稿：docs/design/结果页面试场次预览.html）
            <div className="rv-iv">
              <div className="k">
                <span>面试记录</span>
                {data.interviews.length > IV_SHOWN && <Link className="more" to="/app/applies">全部 {data.interviews.length} 场 →</Link>}
              </div>
              <div className="pills">{shownInterviews.map((v) => <InterviewPill key={v.id} v={v} />)}</div>
            </div>
          )}
        </div>
      </div>

      <div className="rv-body">
        <div className="rv-list">
          <div className="rv-sec">
            <div className="rv-h">
              <h3>对照岗位<span>{gapItems.length ? `${gapItems.length} 条没满足或只满足一部分 · 重要的在前` : '没有要补的'}</span></h3>
              {!wide && <button type="button" className="link" onClick={() => openSheet(null)}>查看简历原文 →</button>}
            </div>
            <ItemList items={gapItems} from={0} empty="岗位要求都满足了。" {...listProps} />
          </div>
          <div className="rv-sec">
            <div className="rv-h"><h3>简历本身<span>{selfItems.length ? `${selfItems.length} 处可以写得更好 · 严重的在前` : '没有要改的'}</span></h3></div>
            <ItemList items={selfItems} from={gapItems.length} empty="简历本身没发现明显问题。" {...listProps} />
          </div>
        </div>
        {wide && (
          // 右列不参与定行高（见 index.css 的 .rv-col），原文卡吸在导航栏下面，底边和清单平齐
          <div className="rv-col">
            <div className="rv-side fade d3">
              <div className="rv-h">
                <h3>简历原文<span>{resumeTitle}</span></h3>
                <div className="legend"><span><i className="bad" />简历问题</span><span><i className="part" />部分满足</span><span><i className="good" />满足</span></div>
              </div>
              <div className="rv-paper">
                {paperMsg && <p key={paperMsg.text} className={`rv-msg${paperMsg.hint ? ' hint' : ''}`}>{paperMsg.text}</p>}
                <ResumePaper doc={doc} loadError={docError} items={items} focusKey={paper.key} pulse={paper.pulse} peekKey={peek} onFocus={fromPaper} />
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
    {!wide && (
      <ResumeSheet open={sheet.open} title={resumeTitle} doc={doc} loadError={docError} items={items}
        focusKey={sheet.focus} onFocus={focusOn} onClose={closeSheet} />
    )}
    </>
  )
}

/** 把左边清单里的某一条滚到屏幕中间（右边原文是吸顶的，跟着整页走） */
function scrollToItem(key: string) {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  document.querySelector(`.rv-list [data-key="${key}"]`)?.scrollIntoView({ block: 'center', behavior: reduce ? 'instant' : 'smooth' })
}

function ItemList({ items, from, empty, wide, expanded, active, onToggle, onHover, onLocate }: {
  items: ListItem[]
  from: number // 前面已经有几条（进场动画接着排）
  empty: string
  wide: boolean // 宽屏原文常驻在右边：不要「在原文中查看」，鼠标停在一条上原文先亮一下
  expanded: ReadonlySet<string>
  active: string | null
  onToggle: (key: string) => void
  onHover: (key: string | null) => void
  onLocate: (key: string) => void
}) {
  if (items.length === 0) return <p className="empty">{empty}</p>
  return (
    <>
      {items.map((x, i) => (
        <IssueItem key={x.key} itemKey={x.key} index={from + i} tag={x.tag[1]} tagClass={x.tag[0]} text={x.text} why={x.why} rows={x.rows}
          open={expanded.has(x.key)} active={wide && x.key === active} onToggle={() => onToggle(x.key)}
          onHover={wide ? (on) => onHover(on ? x.key : null) : undefined}
          locate={wide ? undefined : {
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

// 分析中、失败两种状态和结果用同一个顶部排版（.rv-band），跑完换成结果时标题不跳
function Analyzing({ pipe, jobTitle }: { pipe: PipeState; jobTitle: string }) {
  return (
    <section className="rv">
      <div className="rv-band top">
        <div>
          <Headline badge="分析中" label={jobTitle || '岗位'} lines={['还在分析，', <>稍等<Mark>一下</Mark>。</>]} />
          <p className="rv-sub fade d2">诊断简历和对照岗位同时进行，大约 20–40 秒。<br />跑完这里会自动换成结果。</p>
        </div>
        <div className="rv-card fade d3">
          <div className="card-head">
            <div className="dots" aria-hidden="true"><i /><i /><i /></div>
            <span className="hint">{pipe.done ? '分析完成' : '分析中…'}</span>
          </div>
          <Pipeline pipe={pipe} />
        </div>
      </div>
    </section>
  )
}

function Failed({ data, jobTitle }: { data: Result; jobTitle: string }) {
  const navigate = useNavigate()
  // 简历解析失败（如扫描件）时重投同一份没用，要换简历
  const badResume = (data.error_msg ?? '').includes('简历解析失败')
  return (
    <section className="rv">
      <div className="rv-band top">
        <div>
          <Headline badge="分析失败" label={jobTitle || '岗位'} lines={['这次分析', <>没能<Mark>完成</Mark>。</>]} />
          <p className="rv-sub fade d2">
            {badResume
              ? <>这份简历没能解析出来（比如是扫描件）。<br />换一份文本版 PDF 再投这个岗位吧。</>
              : <>多半是大模型服务一时没响应。<br />岗位和简历都还在，重新投一次就好。</>}
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
          <div className="rv-card fade d3">
            <div className="card-head"><span className="hint">技术信息（排查用）</span></div>
            <p className="tech-msg">{data.error_msg}</p>
          </div>
        )}
      </div>
    </section>
  )
}
