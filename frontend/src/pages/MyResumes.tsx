// 我的简历：/app/resumes。上面一条上传（点选或把文件拖上去），下面两列卡片：每份的解析状态、最近投的 3 个岗位，
// 「看原文」「用它投递 →」「删除」。删除和工作台里一样原地确认；「用它投递」回工作台、这份已经选好。
// 只用现有接口：简历列表（带投递次数）+ 我的投递（按简历分组）。样稿：docs/design/我的简历预览.html（方案 B）
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { applyApi, isRunning, type ApplyBrief } from '../api/apply'
import { ApiError } from '../api/client'
import { fileProblem, isParsing, MAX_UPLOAD_MB, parseErrorText, RESUME_LIST_MAX, resumesApi, uploadResume, type Resume } from '../api/resumes'
import { AppShell } from '../components/AppShell'
import { Headline, Mark } from '../components/Headline'
import { monthDay } from '../components/InterviewPill'
import { ResumeViewer } from '../components/ResumeViewer'
import { useParsingPoll } from '../components/useParsingPoll'

const NOT_FOUND = 40401
const RECENT = 3 // 卡片上列最近投的几个岗位


export default function MyResumes() {
  const [resumes, setResumes] = useState<Resume[] | null>(null)
  const [more, setMore] = useState(false) // 超过一次取的份数，更早的没列出来
  const [error, setError] = useState<string | null>(null)
  const [applies, setApplies] = useState<ApplyBrief[] | null>(null) // null = 还没取回来；取失败记成空列表
  const [upload, setUpload] = useState<{ name: string; error?: string } | null>(null)
  const [over, setOver] = useState(false)
  const [viewing, setViewing] = useState<Resume | null>(null)

  useEffect(() => {
    resumesApi.list().then((page) => {
      setResumes(page.items)
      setMore(page.total > page.items.length)
    }).catch((e) => setError(e instanceof ApiError ? e.message : '加载失败，请稍后刷新'))
    applyApi.list().then((page) => setApplies(page.items)).catch(() => setApplies([])) // 没取到只是少了「最近投递」，卡片照常显示
  }, [])

  useParsingPoll(resumes, (fresh) => setResumes((list) => list?.map((r) => (r.id === fresh.id ? { ...r, ...fresh } : r)) ?? null))

  const send = async (file: File | undefined) => {
    if (!file) return
    const problem = fileProblem(file)
    if (problem) return setUpload({ name: file.name, error: problem })
    setUpload({ name: file.name })
    try {
      const fresh = await uploadResume(file)
      setResumes((list) => {
        const prev = list?.find((r) => r.id === fresh.id) // 同一文件传过：沿用投递次数，挪到最上面
        return [{ ...prev, ...fresh }, ...(list ?? []).filter((r) => r.id !== fresh.id)]
      })
      setUpload(null)
    } catch (err) {
      setUpload({ name: file.name, error: err instanceof ApiError ? err.message : '上传失败，请稍后重试' })
    }
  }
  const dragOver = (e: DragEvent) => { e.preventDefault(); setOver(true) }
  const dragEnd = (e: DragEvent) => { e.preventDefault(); setOver(false) }

  const total = (resumes ?? []).reduce((n, r) => n + (r.apply_count ?? 0), 0)

  let list
  if (error) list = <div className="ap-note">{error}</div>
  else if (!resumes) list = <p className="hint">加载中…</p>
  else if (!resumes.length) list = <div className="ap-note">还没有上传过简历。用上面那一条传一份 PDF，之后投递时直接选。</div>
  else list = (
    <div className="mr-grid">
      {resumes.map((r, i) => (
        <ResumeCard key={r.id} r={r} index={i} applies={applies?.filter((a) => a.resume_id === r.id) ?? null}
          onView={() => setViewing(r)} onGone={() => setResumes((l) => l?.filter((x) => x.id !== r.id) ?? null)} />
      ))}
    </div>
  )

  return (
    <AppShell>
      <section className="screen ap-page">
        <header className="ap-head">
          <div>
            <Headline badge="简历" label="我的简历" lines={['传过的简历，', <>都在<Mark>这里</Mark>。</>]} />
            <p className="sub fade d2">一份简历传一次，就能投很多个岗位。点「看原文」核对系统读出来的内容，卡片上列着每份最近投了哪些岗位。</p>
          </div>
          {resumes && resumes.length > 0 && (
            <div className="ap-stats fade d3">
              <div><b>{resumes.length}</b><span>份简历</span></div>
              <div><b>{total}</b><span>次投递</span></div>
            </div>
          )}
        </header>

        <label className={`mr-up fade d3${over ? ' over' : ''}`} onDragEnter={dragOver} onDragOver={dragOver} onDragLeave={dragEnd}
          onDrop={(e) => { dragEnd(e); void send(e.dataTransfer.files[0]) }}>
          <input type="file" accept=".pdf,application/pdf" className="file-input" onChange={(e) => { void send(e.target.files?.[0]); e.target.value = '' }} />
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 15V3M7 8l5-5 5 5" /><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
          </svg>
          <span className="tx"><b>上传新简历</b>PDF · {MAX_UPLOAD_MB}MB 以内，可以直接把文件拖到这一条上；Word 请先另存为 PDF</span>
          <span className="btn accent">选择文件</span>
        </label>
        {upload && (
          <p className={`mr-upmsg${upload.error ? ' err' : ''}`} role={upload.error ? 'alert' : 'status'}>
            <b>{upload.name}</b>{upload.error ?? '上传中…'}
          </p>
        )}

        {list}
        {more && <p className="pick-list-foot">只列出最近 {RESUME_LIST_MAX} 份。</p>}
      </section>
      <ResumeViewer resume={viewing} onClose={() => setViewing(null)} />
    </AppShell>
  )
}

function ResumeCard({ r, index, applies, onView, onGone }: {
  r: Resume
  index: number
  applies: ApplyBrief[] | null // 用这份简历的投递，新的在前；null = 投递记录还没取回来
  onView: () => void
  onGone: () => void
}) {
  const navigate = useNavigate()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [delError, setDelError] = useState<string | null>(null)
  const delRef = useRef<HTMLButtonElement>(null)
  const failed = r.parse_status === 'failed'
  const parsing = isParsing(r)
  const count = r.apply_count ?? applies?.length ?? 0

  const cancel = () => {
    if (busy) return
    setAsking(false)
    setDelError(null)
    window.setTimeout(() => delRef.current?.focus()) // 确认框没了，焦点回到「删除」上
  }
  const remove = async () => {
    setBusy(true)
    setDelError(null)
    try {
      await resumesApi.remove(r.id)
    } catch (err) {
      if (!(err instanceof ApiError && err.code === NOT_FOUND)) { // 别的标签页删过：当作删掉了
        setBusy(false)
        setDelError(err instanceof ApiError ? err.message : '请稍后再试')
        return
      }
    }
    onGone()
  }

  let status
  if (failed) status = <span className="mr-st err">解析失败</span>
  else if (parsing) status = <span className="mr-st run">解析中</span>
  else status = <span className="mr-st ok">已解析</span>

  let body
  if (asking) body = (
    <div className="mr-confirm" role="alertdialog" aria-label={`删除「${r.title}」`} onKeyDown={(e) => { if (e.key === 'Escape') cancel() }}>
      <p>删除「<b>{r.title}</b>」？{count ? <>它的 <b>{count} 次投递</b>和面试报告也会从「我的投递」里隐藏。</> : '还没用它投过岗位。'}</p>
      {delError && <p className="form-err" role="alert">没删掉：{delError}</p>}
      <div className="btns">
        <button type="button" className="btn sm danger" disabled={busy} onClick={() => void remove()}>{busy ? '删除中…' : '删除'}</button>
        {/* 默认停在「取消」上：误按回车不会删 */}
        <button type="button" className="btn sm ghost" disabled={busy} autoFocus onClick={cancel}>取消</button>
      </div>
    </div>
  )
  else if (failed) body = <p className="mr-why">解析失败：{parseErrorText(r.parse_error)}。这份不能用来投递。</p>
  else body = (
    <>
      <div className="mr-hist">
        <div className="k"><span>最近投递</span>{count > RECENT && <Link className="more" to="/app/applies">全部 {count} 次 →</Link>}</div>
        {/* 「投过几次」来自简历列表，具体哪几条来自投递列表：后者还没回来、没取到、或者排在最近 100 条之外时，不能说成「还没投过」 */}
        {applies?.length ? applies.slice(0, RECENT).map((a) => <ApplyRow key={a.id} a={a} />)
          : !count ? <p className="none">还没用它投过岗位</p>
          : applies === null ? <p className="none">加载中…</p>
          : <p className="none">这 {count} 次投递在<Link className="more" to="/app/applies">「我的投递」</Link>里看</p>}
      </div>
      <div className="mr-acts">
        <button type="button" className="btn sm outline" disabled={parsing} title={parsing ? '解析完才能看' : undefined} onClick={onView}>看原文</button>
        <button type="button" className="btn sm accent" onClick={() => navigate(`/app?resume=${r.id}`)}>用它投递 <span className="arrow">→</span></button>
      </div>
    </>
  )

  return (
    <article className="mr-card" style={{ animationDelay: `${index * 60 + 150}ms` }}>
      <div className="mr-head">
        <span className="mr-ic">PDF</span>
        <div className="mr-text">
          <div className="mr-title">{r.title}</div>
          <div className="mr-meta">{status}<span>{r.page_count ? `${r.page_count} 页 · ` : ''}{monthDay(r.created_at)}上传{count ? ` · 投过 ${count} 次` : ''}</span></div>
        </div>
        {!asking && <button ref={delRef} type="button" className="mr-del" aria-label={`删除「${r.title}」`} onClick={() => setAsking(true)}>删除</button>}
      </div>
      {body}
    </article>
  )
}

function ApplyRow({ a }: { a: ApplyBrief }) {
  let result
  if (isRunning(a)) result = <span className="mid">分析中</span>
  else if (a.status === 'failed') result = <span className="err">分析失败</span>
  else result = <><b>{Math.round(a.overall_match ?? 0)}</b><span className={a.passed ? 'ok' : 'no'}>{a.passed ? '通过' : '未通过'}</span></>
  return (
    <Link className="mr-row" to={`/app/apply/${a.id}`}>
      <span className="t">{a.job_title}</span>{result}
    </Link>
  )
}
