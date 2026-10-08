// 诊断报告：/app/apply/:id/report。把结果页的内容排成一份 A4 报告，「下载 PDF」在浏览器里直接生成文件，方便对照着改简历。
// 结果页本身不变，只在成绩单那排按钮旁边多一个「预览报告」进来。样稿：docs/design/诊断报告导出预览.html
// 纸面用固定的黑白灰（不跟三套配色走）：问题 = 实线下划线、部分满足 = 虚线下划线，黑白打印也分得清。
// PDF 用 html2pdf.js 生成（把纸面按 A4 截成图拼起来），点了下载才加载，不拖慢别的页面。
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { applyApi, isAbort, isRunning, type ApplyResult as Result, type MatchItem } from '../api/apply'
import { jobsApi, REQ_TYPE_LABEL, type Job } from '../api/jobs'
import { resumesApi, type ResumeStructure } from '../api/resumes'
import { sections, withPlaceholders } from '../components/AdviceBlock'
import { AppShell } from '../components/AppShell'
import { MagneticButton } from '../components/effects'
import { NotFound, notFoundText } from '../components/NotFound'
import { layout, located, type Seg, type SheetDoc } from '../components/ResumePaper'
import { useAdviceStore } from '../store/advice'
import { useDomains } from '../store/domains'
import { DIMENSIONS, entryBlocksOf, sheetItems, verdictSub, type ListItem } from './applyItems'

type Loaded = { data: Result; gate: NonNullable<Result['gate']>; doc: SheetDoc; resumeTitle: string; hits: number; total: number; job: Job | null }

const SEVERITY_TAG = { high: ['bad', '高'], medium: ['part', '中'], low: ['gray', '低'] } as const
const pad = (n: number) => String(n).padStart(2, '0')
const day = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const minute = (d: Date) => `${day(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`

// Tailwind 的基础样式把 img 设成了 block。html2canvas 测文字基线时，往当前页面的 body 下面挂一个 div、里面放一个 img 来量，
// 基线就量错了：带边框的小标签、编号圆圈里的字会往下掉。生成 PDF 的那一两秒里临时改回行内（页面自己的 #root 里不受影响）
const baselineFix = Object.assign(document.createElement('style'), { textContent: 'body > div:not(#root) img { display: inline !important; }' })

export default function ApplyReport() {
  const { id } = useParams()
  const applyId = Number(id)
  const navigate = useNavigate()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notReady, setNotReady] = useState<string | null>(null) // 还在分析 / 分析失败：没有报告可看

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      const data = await applyApi.get(applyId)
      if (cancelled) return
      if (isRunning(data)) return setNotReady('这次投递还在分析，分析完才能看报告。')
      if (data.status === 'failed' || !data.gate) return setNotReady('这次分析没能完成，没有报告可看。')
      const [blocks, structure, resumeTitle, items, job] = await Promise.all([
        resumesApi.blocks(data.resume_id),
        resumesApi.structure(data.resume_id).catch((): ResumeStructure => ({})),
        resumesApi.get(data.resume_id).then((r) => r.title).catch(() => ''),
        applyApi.match(data.id).then((m) => m.items).catch((): MatchItem[] => []),
        jobsApi.get(data.job_id).catch(() => null),
      ])
      if (cancelled) return
      setLoaded({ data, gate: data.gate, doc: { ...blocks, entryBlocks: entryBlocksOf(structure) }, resumeTitle, job,
        hits: items.filter((i) => i.status === 'hit').length, total: items.length })
    }
    load().catch((err) => {
      if (!cancelled && !isAbort(err)) setError(notFoundText(err, '这条投递记录不存在，可能已经被删除。'))
    })
    return () => { cancelled = true }
  }, [applyId])

  const back = () => navigate(`/app/apply/${applyId}`)
  let body
  if (error) body = <NotFound badge="诊断报告" what="这次投递" message={error} />
  else if (notReady) body = (
    <section className="rpt"><div className="rpt-bar"><button type="button" className="back" onClick={back}>← 回到结果页</button></div>
      <p className="rpt-msg">{notReady}</p></section>
  )
  else if (!loaded) body = <section className="rpt"><p className="hint">正在整理报告…</p></section>
  else body = <Report {...loaded} onBack={back} />
  return <AppShell progress={100}>{body}</AppShell>
}

function Report({ data, gate, doc, resumeTitle, hits, total, job, onBack }: Loaded & { onBack: () => void }) {
  const domains = useDomains()
  const entries = useAdviceStore((s) => s.entries)
  const sheetRef = useRef<HTMLElement>(null)
  const [busy, setBusy] = useState(false)
  const [dlError, setDlError] = useState<string | null>(null)
  const [now] = useState(() => new Date())

  // 报告里只列没满足的要求和简历问题（满足的不画线，免得原文太花）；编号按清单顺序，原文里同一个编号标在那句话末尾
  const items = useMemo(() => sheetItems(data, []), [data])
  const gaps = items.filter((x) => x.list === 'gap')
  const issues = items.filter((x) => x.list === 'self')
  const numbers = useMemo(() => new Map(items.map((x, i) => [x.key, i + 1])), [items])
  const marks = useMemo(() => items.filter((x) => x.color && located(x)), [items])
  const paras = useMemo(() => layout(doc, marks), [doc, marks])
  const endsAt = useMemo(() => new Map(marks.map((x) => [x.key, x.end])), [marks])
  /** 网页上点开过的建议：这次会话里刚生成的在 store 里，以前生成的跟着接口带回来 */
  const adviceOf = (x: ListItem) => {
    const e = entries[x.key]
    return (e?.status === 'done' ? e.text : null) ?? x.advice?.cached?.text ?? null
  }

  const domainName = domains?.find((d) => d.key === job?.domain)?.name
  const overall = gate.overall_match === null ? null : Math.round(gate.overall_match)
  const dims = DIMENSIONS.flatMap(([key, label]) => {
    const v = data.dimension_scores?.[key]
    return v === null || v === undefined ? [] : [{ key, label, value: Math.round(v) }]
  })
  const sub = verdictSub(data, gate)

  const download = async () => {
    if (!sheetRef.current) return
    setBusy(true)
    setDlError(null)
    try {
      const { default: html2pdf } = await import('html2pdf.js')
      // 文件名里不能有 \ / : * ? " < > |
      const name = `简历诊断报告-${job?.title ?? '岗位'}-${day(now)}.pdf`.replace(/[\\/:*?"<>|]/g, '-')
      const options = {
        margin: [14, 14, 16, 14] as [number, number, number, number],
        filename: name,
        image: { type: 'jpeg' as const, quality: 0.95 },
        html2canvas: { scale: 2, backgroundColor: '#ffffff' },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' as const },
        // 一条问题、一个小标题和它下面的第一行都不拆到两页
        pagebreak: { mode: ['css'], avoid: ['.rpt-keep', '.rpt-item', '.rpt-verdict', '.rpt-howto', '.rpt-paper p'] },
      }
      document.head.appendChild(baselineFix)
      const worker = html2pdf().set(options).from(sheetRef.current).toPdf()
      const pdf = await worker.get('pdf')
      const pages = pdf.internal.getNumberOfPages()
      for (let i = 1; i <= pages; i++) {   // 页码只写数字：jsPDF 自带的字体写不了中文
        pdf.setPage(i)
        pdf.setFontSize(9)
        pdf.setTextColor(136)
        pdf.text(`${i} / ${pages}`, 105, 290, { align: 'center' })
      }
      await worker.save()
    } catch {
      setDlError('PDF 没能生成，请稍后再试。')
    } finally {
      baselineFix.remove()
      setBusy(false)
    }
  }

  /** 原文的一段：标注的句子画线，句子结束的地方标上编号 */
  const segs = (list: Seg[]): ReactNode[] => list.map((s) => {
    const piece = doc.full_text.slice(s.start, s.end)
    const ending = s.keys.filter((k) => endsAt.get(k) === s.end)
    return (
      <Fragment key={s.start}>
        {s.color ? <span className={`rpt-m ${s.color}`}>{piece}</span> : piece}
        {ending.map((k) => <span key={k} className="rpt-no">{numbers.get(k)}</span>)}
      </Fragment>
    )
  })
  const para = (p: (typeof paras)[number], i: number) =>
    p.kind === 'h4' ? <h4 key={i}>{segs(p.segs)}</h4> : <p key={i} className={p.kind === 'p' ? undefined : p.kind}>{segs(p.segs)}</p>
  const paper: ReactNode[] = []
  for (let i = 0; i < paras.length; i++) {
    // 小标题和它下面的第一行包在一起，生成 PDF 时不会在页底留下一个孤零零的标题
    if (paras[i].kind === 'h4' && i + 1 < paras.length) {
      paper.push(<div key={i} className="rpt-keep">{para(paras[i], i)}{para(paras[i + 1], i + 1)}</div>)
      i++
    } else paper.push(para(paras[i], i))
  }

  const gapRows = gaps.map((x, i) => {
    const g = data.gaps[i]
    const advice = adviceOf(x)
    return (
      <Item key={x.key} no={numbers.get(x.key)!}
        head={<><Tag cls={g.status === 'miss' ? 'bad' : 'part'}>{g.status === 'miss' ? '缺失' : '部分满足'}</Tag><Tag cls="gray">{REQ_TYPE_LABEL[g.req_type]}</Tag><b>{g.content}</b></>}>
        <Row k="简历原文">{g.evidence_quote ? <span className="rpt-q">{g.evidence_quote}</span> : <span className="rpt-none">没有找到相关内容</span>}</Row>
        {g.reason && <Row k="判断">{g.reason}</Row>}
        {advice && <AdviceBox title="针对这条要求的建议（DeepSeek 生成）" text={advice} />}
      </Item>
    )
  })
  const issueRows = issues.map((x, i) => {
    const f = data.resume_issues[i]
    const advice = adviceOf(x)
    const [cls, label] = SEVERITY_TAG[f.severity]
    return (
      <Item key={x.key} no={numbers.get(x.key)!} head={<><Tag cls={cls}>{label}</Tag><b>{f.title}</b></>}>
        <Row k="原文">{f.evidence_quote ? <span className="rpt-q">{f.evidence_quote}</span> : <span className="rpt-none">针对整份简历</span>}</Row>
        {advice ? <AdviceBox title="针对这一句的建议（DeepSeek 生成）" text={advice} /> : (
          <>
            {f.description && <Row k="问题">{f.description}</Row>}
            {f.suggestion && <Row k="通用建议">{f.suggestion}</Row>}
          </>
        )}
      </Item>
    )
  })

  return (
    <section className="rpt">
      <div className="rpt-bar">
        <button type="button" className="back" onClick={onBack}>← 回到结果页</button>
        <span className="rpt-tip">结果页上点开过的建议都会放进报告；下载的 PDF 可以对照着改简历。</span>
        <MagneticButton className="accent" disabled={busy} onClick={() => void download()}>{busy ? '正在生成…' : '下载 PDF'}</MagneticButton>
      </div>
      {dlError && <p className="form-err rpt-err" role="alert">{dlError}</p>}

      <article className="rpt-sheet" ref={sheetRef}>
        <header className="rpt-head">
          <h1>简历诊断报告</h1>
          <div className="by">智能求职辅助系统<br />导出于 {minute(now)}</div>
        </header>
        <dl className="rpt-meta">
          <dt>目标岗位</dt><dd>{job?.title ?? '（岗位已删除）'}{domainName ? ` · ${domainName}方向` : ''}</dd>
          <dt>使用简历</dt><dd>{resumeTitle || '—'}</dd>
          <dt>岗位要求</dt><dd>{total ? `${total} 条，满足 ${hits} 条` : '—'}</dd>
        </dl>

        <div className="rpt-verdict">
          <div className="v"><b>{gate.passed ? '通过初筛' : '差一点，这次没过初筛'}</b><span>{sub[0]}{sub[1]}</span></div>
          <div className="scores">
            <div><b>{overall ?? '—'}</b><span>匹配度</span></div>
            {dims.map((d) => <div key={d.key}><b>{d.value}</b><span>{d.label}</span></div>)}
          </div>
        </div>

        <div className="rpt-howto">
          怎么看：原文里标了编号的句子，对应后面同一个编号的条目。<span className="key bad">实线</span>是简历本身的问题，
          <span className="key part">虚线</span>是只满足了一部分的岗位要求；没有标在原文里的，是简历里找不到相关内容的要求。【】里的内容请按你的实际情况填写。<br />
          带「DeepSeek 生成」的是你在网页上点开过、针对那一句生成的建议；没有的，在结果页点开那一条就能生成。
        </div>

        <div className="rpt-keep"><h2>一、简历原文（带标注）</h2></div>
        <div className="rpt-paper">{paper}</div>

        <Section title="二、对照岗位的差距" note={gaps.length ? `${gaps.length} 条没满足或只满足一部分 · 重要的在前` : ''}
          rows={gapRows} empty="岗位要求都满足了。" />
        <Section title="三、简历本身的问题" note={issues.length ? `${issues.length} 条 · 严重的在前` : ''}
          rows={issueRows} empty="简历本身没发现明显问题。" />

        <p className="rpt-foot">本报告由系统根据简历原文和岗位要求自动生成，仅供修改简历时参考。「DeepSeek 生成」的建议只用了你简历里已有的事实，【】里的数字和做法需要你按实际填写。</p>
      </article>
    </section>
  )
}

/** 章节标题和第一条包在一起：生成 PDF 时标题不会落在页底、内容却在下一页 */
function Section({ title, note, rows, empty }: { title: string; note: string; rows: ReactNode[]; empty: string }) {
  const h = <h2>{title}{note && <small>{note}</small>}</h2>
  if (rows.length === 0) return <div className="rpt-keep">{h}<p className="rpt-none">{empty}</p></div>
  return <><div className="rpt-keep">{h}{rows[0]}</div>{rows.slice(1)}</>
}

function Item({ no, head, children }: { no: number; head: ReactNode; children: ReactNode }) {
  return (
    <div className="rpt-item">
      <span className="rpt-no">{no}</span>
      <div><div className="t">{head}</div>{children}</div>
    </div>
  )
}

const Tag = ({ cls, children }: { cls: string; children: ReactNode }) => <span className={`rpt-tag ${cls}`}>{children}</span>
const Row = ({ k, children }: { k: string; children: ReactNode }) => <div className="rpt-row"><span className="k">{k}</span><span>{children}</span></div>

function AdviceBox({ title, text }: { title: string; text: string }) {
  return (
    <div className="rpt-advice">
      <div className="h">{title}</div>
      {sections(text).map(([label, value], i) => (
        <Row key={label || i} k={label || '建议'}><span className={label === '改成' ? 'rw' : undefined}>{withPlaceholders(value)}</span></Row>
      ))}
    </div>
  )
}
