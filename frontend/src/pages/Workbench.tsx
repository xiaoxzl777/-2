// 工作台（新的投递）：一步一屏 —— ① 选岗位 → ② 选简历 → ③ 投递，流程卡实时显示进度，跑完跳到初筛结果页。
// 三步都常驻、只切换显示，来回切换时已填的 JD、已选的简历都还在。
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { applyApi, isAbort } from '../api/apply'
import { ApiError } from '../api/client'
import { jobsApi, type JobBrief } from '../api/jobs'
import { resumesApi, type Resume } from '../api/resumes'
import { AppShell } from '../components/AppShell'
import { MagneticButton, TiltCard } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { JobPicker } from '../components/JobPicker'
import { Pipeline, useApplyTracker } from '../components/Pipeline'
import { ResumePicker } from '../components/ResumePicker'

const STEP_PROGRESS = [18, 50, 82]
const DONE_PAUSE_MS = 900 // 进度走到 100% 之后停一下再跳结果页

function applyErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code === 40901) return '这份简历正在分析中（可能是刚才的另一次投递），等它结束再投。'
  return err instanceof ApiError ? err.message : '投递失败，请稍后重试'
}

export default function Workbench() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [step, setStep] = useState(0)
  const [job, setJob] = useState<JobBrief | null>(null)
  const [resume, setResume] = useState<Resume | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { pipe, track } = useApplyTracker()
  const leaveTimer = useRef(0)
  useEffect(() => () => window.clearTimeout(leaveTimer.current), [])

  // 从结果页回来：?job= 带着岗位直接到第 ② 步；再带 &resume= 就直接到第 ③ 步（重新投递）
  useEffect(() => {
    const jobId = Number(params.get('job'))
    const resumeId = Number(params.get('resume'))
    if (!jobId) return
    let cancelled = false
    void (async () => {
      try {
        const j = await jobsApi.get(jobId)
        const r = resumeId ? await resumesApi.get(resumeId).catch(() => null) : null
        if (cancelled) return
        setJob(j)
        if (r && r.parse_status !== 'failed') {
          setResume(r)
          setStep(2)
        } else {
          setStep(1)
        }
      } catch {
        /* 岗位已经删掉了：留在第 ① 步重新选 */
      }
    })()
    setParams({}, { replace: true })
    return () => { cancelled = true }
  }, []) // 只在进入页面时读一次

  const go = (i: number) => {
    setStep(i)
    setError(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const apply = async () => {
    if (!job || !resume || submitting) return
    setSubmitting(true)
    setError(null)
    let id: number
    try {
      id = (await applyApi.start(resume.id, job.id)).id
    } catch (err) {
      setError(applyErrorText(err))
      setSubmitting(false)
      return
    }
    try {
      const status = await track(id, { reused: resume.parse_status === 'success' })
      leaveTimer.current = window.setTimeout(() => navigate(`/app/apply/${id}`), status === 'success' ? DONE_PAUSE_MS : 0)
    } catch (err) {
      // 离开页面时中断属于正常；其他情况（进度拿不到）交给结果页继续跟
      if (!isAbort(err)) navigate(`/app/apply/${id}`)
    }
  }

  const started = pipe.started

  return (
    <AppShell progress={pipe.done ? 100 : STEP_PROGRESS[step]}>
      {/* ① 岗位 */}
      <section className="screen" hidden={step !== 0}>
        <div>
          <Headline badge="1 / 3" label="目标岗位" lines={['你想投', <>哪个<Mark>岗位</Mark>？</>]} />
          <p className="sub fade d2">把招聘信息里的「岗位要求」整段贴过来，我会拆成一条条，之后逐条对照你的简历。</p>
          <div className="cta fade d3">
            <MagneticButton className="accent lg" disabled={!job} onClick={() => go(1)}>下一步：选简历 <span className="arrow">→</span></MagneticButton>
          </div>
        </div>
        <div className="stage fade d4">
          <div className={`floaty tl ${job ? 'show' : ''}`}><b>{job?.requirement_count ?? 0} 条</b><span>要求已拆出</span></div>
          <div className={`floaty br ${job ? 'show' : ''}`}><b>{job?.title ?? '—'}</b><span>已选岗位</span></div>
          <JobPicker selected={job} onPick={setJob} />
        </div>
      </section>

      {/* ② 简历 */}
      <section className="screen" hidden={step !== 1}>
        <div>
          <button type="button" className="back fade d1" onClick={() => go(0)}>← 换个岗位</button>
          <Headline badge="2 / 3" label="简历" lines={['用哪份', <><Mark>简历</Mark>去投？</>]} />
          <p className="sub fade d2">目前只收 PDF，两栏排版也认得。同一份简历可以投很多个岗位，只需上传一次。</p>
          <div className="cta fade d3">
            <MagneticButton className="accent lg" disabled={!resume} onClick={() => go(2)}>下一步：确认 <span className="arrow">→</span></MagneticButton>
          </div>
        </div>
        <div className="stage fade d4">
          <div className="floaty tl show"><b>{job?.title ?? '—'}</b><span>目标岗位</span></div>
          <div className={`floaty br ${resume ? 'show' : ''}`}><b>{resume?.title ?? '—'}</b><span>已选简历</span></div>
          <ResumePicker selected={resume} onPick={setResume} />
        </div>
      </section>

      {/* ③ 投递 */}
      <section className="screen" hidden={step !== 2}>
        <div>
          <Headline badge="3 / 3" label="投递" lines={['准备好了，', <><Mark>投</Mark>吧。</>]} />
          <div className="pick-sum fade d2">
            <div><span>岗位</span><b>{job?.title ?? '—'}</b>{!started && <button type="button" className="link" onClick={() => go(0)}>换</button>}</div>
            <div><span>简历</span><b>{resume?.title ?? '—'}</b>{!started && <button type="button" className="link" onClick={() => go(1)}>换</button>}</div>
          </div>
          {!started && (
            <div className="cta fade d3">
              <MagneticButton className="accent lg" disabled={submitting || !job || !resume} onClick={() => void apply()}>
                {submitting ? '提交中…' : '投递'} <span className="arrow">→</span>
              </MagneticButton>
              <span className="cta-note">约 20–40 秒 · 大模型会逐条审阅你的经历</span>
            </div>
          )}
          {error && <p className="form-err" role="alert">{error}</p>}
        </div>
        <div className="stage fade d4">
          <div className={`floaty tr ${pipe.done ? 'show' : ''}`}><b>依据已核实</b><span>模型引用都能在原文找到</span></div>
          <TiltCard>
            <div className="card-head">
              <div className="dots" aria-hidden="true"><i /><i /><i /></div>
              <span className="hint">{pipe.done ? '分析完成' : started ? '分析中…' : '点「投递」后开始'}</span>
            </div>
            <Pipeline pipe={pipe} />
          </TiltCard>
        </div>
      </section>
    </AppShell>
  )
}
