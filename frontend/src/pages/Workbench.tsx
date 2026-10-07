// 工作台（新的投递）：一步一屏 —— ① 选方向 → ② 选岗位 → ③ 选简历 → ④ 投递，流程卡实时显示进度，跑完跳到初筛结果页。
// 四步都常驻、只切换显示，来回切换时已填的 JD、已选的简历都还在；顶上的步骤条写着每步选了什么。方向决定岗位模板、诊断标准和面试官（app/domains）。
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { applyApi, isAbort } from '../api/apply'
import { ApiError } from '../api/client'
import { jobsApi, type JobBrief } from '../api/jobs'
import { resumesApi, type Resume } from '../api/resumes'
import { AppShell } from '../components/AppShell'
import { DirectionPicker } from '../components/DirectionPicker'
import { MagneticButton, TiltCard } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { JobPicker } from '../components/JobPicker'
import { Pipeline, useApplyTracker } from '../components/Pipeline'
import { ResumePicker } from '../components/ResumePicker'
import { useDomains } from '../store/domains'

const STEP_PROGRESS = [14, 38, 62, 86]
const DONE_PAUSE_MS = 900 // 进度走到 100% 之后停一下再跳结果页

function applyErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code === 40901) return '这份简历正在分析中（可能是刚才的另一次投递），等它结束再投。'
  return err instanceof ApiError ? err.message : '投递失败，请稍后重试'
}

export default function Workbench() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [step, setStep] = useState(0)
  const domains = useDomains()
  const [domainKey, setDomainKey] = useState<string | null>(null)
  const [job, setJob] = useState<JobBrief | null>(null)
  const [resume, setResume] = useState<Resume | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { pipe, track } = useApplyTracker()
  const leaveTimer = useRef(0)
  useEffect(() => () => window.clearTimeout(leaveTimer.current), [])
  const domain = domains?.find((d) => d.key === domainKey) ?? null

  // 从结果页回来：?job= 带着岗位（方向跟着岗位）直接到第 ③ 步；再带 &resume= 就直接到第 ④ 步（重新投递）
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
        setDomainKey(j.domain)
        setJob(j)
        if (r && r.parse_status !== 'failed') {
          setResume(r)
          setStep(3)
        } else {
          setStep(2)
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

  const pickDomain = (key: string) => {
    setDomainKey(key)
    if (job && job.domain !== key) setJob(null) // 换了方向，之前选的岗位不算数
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
      <Steps step={step} locked={started} onGo={go} items={[
        { name: '方向', value: domain?.name ?? null },
        { name: '岗位', value: job?.title ?? null, title: job ? `${job.title} · ${job.requirement_count} 条要求` : undefined },
        { name: '简历', value: resume?.title ?? null },
        { name: '投递', value: pipe.done ? '分析完成' : started ? '分析中…' : null },
      ]} />

      {/* ① 方向：单独一屏、上下排版，选完再去选岗位 */}
      <section className="screen stack" hidden={step !== 0}>
        <div>
          <Headline lines={['你想找', <><Mark>哪类</Mark>工作？</>]} />
          <p className="sub fade d2">先选方向。岗位模板、简历按什么标准诊断、模拟面试问哪一类问题，都会跟着换。</p>
          <div className="cta fade d3">
            <MagneticButton className="accent lg" disabled={!domain} onClick={() => go(1)}>下一步：选岗位 <span className="arrow">→</span></MagneticButton>
          </div>
        </div>
        <div className="stage fade d4">
          <DirectionPicker domains={domains} value={domainKey} onChange={pickDomain} />
        </div>
      </section>

      {/* ② 岗位 */}
      <section className="screen" hidden={step !== 1}>
        <div>
          <button type="button" className="back fade d1" onClick={() => go(0)}>← 上一步：选方向</button>
          <Headline lines={['你想投', <>哪个<Mark>岗位</Mark>？</>]} />
          <p className="sub fade d2">「<b>{domain?.name ?? '—'}</b>」方向。把招聘信息里的「岗位要求」整段贴过来，我会拆成一条条，之后逐条对照你的简历。</p>
          <div className="cta fade d3">
            <MagneticButton className="accent lg" disabled={!job} onClick={() => go(2)}>下一步：选简历 <span className="arrow">→</span></MagneticButton>
          </div>
        </div>
        <div className="stage fade d4">
          {domain && <JobPicker domain={domain} selected={job} onPick={setJob} onChangeDomain={() => go(0)} />}
        </div>
      </section>

      {/* ③ 简历 */}
      <section className="screen" hidden={step !== 2}>
        <div>
          <button type="button" className="back fade d1" onClick={() => go(1)}>← 上一步：选岗位</button>
          <Headline lines={['用哪份', <><Mark>简历</Mark>去投？</>]} />
          <p className="sub fade d2">目前只收 PDF，两栏排版也认得。同一份简历可以投很多个岗位，只需上传一次。</p>
          <div className="cta fade d3">
            <MagneticButton className="accent lg" disabled={!resume} onClick={() => go(3)}>下一步：确认 <span className="arrow">→</span></MagneticButton>
          </div>
        </div>
        <div className="stage fade d4">
          <ResumePicker selected={resume} onPick={setResume} />
        </div>
      </section>

      {/* ④ 投递 */}
      <section className="screen" hidden={step !== 3}>
        <div>
          <Headline lines={['准备好了，', <><Mark>投</Mark>吧。</>]} />
          <div className="pick-sum fade d2">
            <div><span>方向</span><b>{domain?.name ?? '—'}</b>{!started && <button type="button" className="link" onClick={() => go(0)}>换</button>}</div>
            <div><span>岗位</span><b>{job?.title ?? '—'}</b>{!started && <button type="button" className="link" onClick={() => go(1)}>换</button>}</div>
            <div><span>简历</span><b>{resume?.title ?? '—'}</b>{!started && <button type="button" className="link" onClick={() => go(2)}>换</button>}</div>
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

type StepItem = { name: string; value: string | null; title?: string }

/** 顶上的步骤条：四等分，圆点在上、步骤名和选了什么居中写在下面，连线从上一个圆点接过来（代替原来漂浮在卡片周围的小卡）；
 *  前面都选好了的步骤可以直接点过去，投递开始后就不能再换 */
function Steps({ step, items, locked, onGo }: { step: number; items: StepItem[]; locked: boolean; onGo: (i: number) => void }) {
  return (
    <nav className="wb-steps fade" aria-label="投递步骤">
      {items.map((s, i) => {
        const state = i === step ? 'now' : s.value ? 'done' : 'todo'
        const reachable = !locked && i !== step && items.slice(0, i).every((x) => x.value)
        return (
          <button key={s.name} type="button" className={`wb-step ${state}${i <= step ? ' reached' : ''}`} disabled={!reachable}
            aria-current={i === step ? 'step' : undefined} title={s.title ?? s.value ?? undefined} onClick={() => onGo(i)}>
            <span className="wb-mark" aria-hidden="true">{state === 'done' ? '✓' : i + 1}</span>
            <span className="wb-name">{s.name}</span>
            {s.value && <span className="wb-val">{s.value}</span>}
          </button>
        )
      })}
    </nav>
  )
}
