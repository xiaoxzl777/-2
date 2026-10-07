// 模拟面试的准备页：/app/apply/:id/interview，从初筛结果页的「进入模拟面试 / 以练习模式面试」进来。
// 右边列出面试官会参考的材料，公司名、面经选填；点开始后卡片换成准备流程（真正耗时的是"定下话题"那一步的模型调用），
// 定好了就进面试页。话题内容这里不列出来，问到哪个才显示哪个。样稿：docs/design/模拟面试预览.html
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { applyApi, type ApplyResult } from '../api/apply'
import { ApiError } from '../api/client'
import { CONTEXT_MAX, interviewApi } from '../api/interview'
import { jobsApi, type Job } from '../api/jobs'
import { resumesApi } from '../api/resumes'
import { AppShell } from '../components/AppShell'
import { MagneticButton, TiltCard } from '../components/effects'
import { Headline, Mark } from '../components/Headline'
import { NotFound, notFoundText } from '../components/NotFound'

const SAMPLE = `【后端一面 · 约 40 分钟】
1. 自我介绍，挑一个最有挑战的项目讲。
2. Redis 缓存和数据库怎么保证一致？删缓存失败怎么办？
3. 订单超时取消怎么做？定时任务和延时队列各有什么问题？
4. MySQL 联合索引的最左前缀，举个例子。
面试官很喜欢追问"你怎么验证效果"，最好准备好数据。`
const CONTEXT_FULL_MAX = 3000 // 同后端 INTERVIEW_CONTEXT_FULL_MAX：不超过就整段给面试官，更长才切段检索

type Step = 'idle' | 'run' | 'ok' | 'skip'

export default function InterviewSetup() {
  const { id } = useParams()
  const applyId = Number(id)
  const navigate = useNavigate()
  const [apply, setApply] = useState<ApplyResult | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [resumeTitle, setResumeTitle] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [company, setCompany] = useState('')
  const [context, setContext] = useState('')
  const [steps, setSteps] = useState<Step[] | null>(null) // 不为 null = 正在准备
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    applyApi.get(applyId).then(async (a) => {
      if (cancelled) return
      setApply(a)
      const [j, r] = await Promise.all([jobsApi.get(a.job_id), resumesApi.get(a.resume_id).catch(() => null)])
      if (cancelled) return
      setJob(j)
      setCompany((c) => c || j.company || '')
      setResumeTitle(r?.title ?? '')
    }).catch((err) => {
      if (!cancelled) setLoadError(notFoundText(err, '这条投递记录不存在，可能已经被删除。'))
    })
    return () => { cancelled = true }
  }, [applyId])

  const practice = apply?.gate ? !apply.gate.passed : false
  const ready = apply?.status === 'success' && !!apply.gate && !!job
  const length = context.trim().length

  const start = async (e?: FormEvent) => {
    e?.preventDefault()
    if (!ready || steps) return
    setError(null)
    const third: Step = length === 0 ? 'skip' : 'run'
    setSteps(['run', 'idle', 'idle', 'idle'])
    const created = interviewApi.create({ apply_id: applyId, company_name: company.trim() || undefined, extra_context: context.trim() || undefined })
    created.catch(() => { /* 下面 await 时再处理；先挂上，免得动画还没播完它就失败了、被当成没人处理的 rejection */ })
    // 前两步是整理数据，几乎不花时间；真正要等的是面经向量化（很长时）和定话题的模型调用
    const pause = (ms: number) => new Promise((r) => window.setTimeout(r, ms))
    try {
      await pause(350)
      setSteps(['ok', 'run', 'idle', 'idle'])
      await pause(350)
      setSteps(['ok', 'ok', third, third === 'skip' ? 'run' : 'idle'])
      if (third === 'run') {
        await pause(length > CONTEXT_FULL_MAX ? 900 : 400)
        setSteps(['ok', 'ok', 'ok', 'run'])
      }
      const session = await created
      setSteps(['ok', 'ok', third === 'skip' ? 'skip' : 'ok', 'ok'])
      await pause(500)
      navigate(`/app/interview/${session.id}`)
    } catch (err) {
      setSteps(null)
      setError(err instanceof ApiError ? err.message : '准备失败，请稍后重试')
    }
  }

  if (loadError) {
    return (
      <AppShell progress={0}>
        <NotFound badge="模拟面试" what="这次投递" message={loadError} />
      </AppShell>
    )
  }

  return (
    <AppShell progress={0}>
      <section className="screen">
        <div>
          <button type="button" className="back fade d1" onClick={() => navigate(`/app/apply/${applyId}`)}>← 回到初筛结果</button>
          <Headline badge={!apply?.gate ? '模拟面试' : practice ? '练习模式' : '初筛已通过'}
            label={!apply?.gate ? job?.title ?? '…' : practice ? '初筛没过也能练' : job?.title ?? '岗位'}
            lines={['来一场', <><Mark>技术面</Mark>。</>]} />
          <p className="sub fade d2">
            {/* 话题个数要等定完才知道（偶尔少一个），这里不写死 */}
            围绕几个话题来问，每个最多追问一次，大约 10–15 分钟。
            {!apply?.gate ? '' : practice
              ? '每题答完马上告诉你好在哪、差在哪，练完同样有完整报告。'
              : '和真实面试一样，答题时不打分，结束后看完整报告。'}
          </p>
          <div className="cta fade d3">
            <MagneticButton className="accent lg" onClick={() => void start()} disabled={!ready || !!steps}>
              {steps ? '准备中…' : practice ? '开始练习' : '开始面试'} <span className="arrow">→</span>
            </MagneticButton>
            <span className="cta-note">全程打字作答 · 中途离开，回来能接着答</span>
          </div>
          {apply && apply.status !== 'success' && <p className="form-err">这次投递还没分析完，完成后才能面试。</p>}
          {error && <p className="form-err" role="alert">{error}</p>}
        </div>
        <div className="stage fade d4">
          <TiltCard>
            {steps ? (
              <>
                <div className="card-head">
                  <div className="dots" aria-hidden="true"><i /><i /><i /></div>
                  <span className="hint">{steps[3] === 'ok' ? '准备好了' : '正在准备题目…'}</span>
                </div>
                <div className="pipe">
                  <PrepNode step={steps[0]} name="看简历问题" desc={`初筛发现的 ${apply?.resume_issues.length ?? 0} 处，挑值得追问的`} />
                  <PrepNode step={steps[1]} name="对照岗位要求" desc="重点问必须项，尤其是简历里没体现的" />
                  <PrepNode step={steps[2]} name={length === 0 ? '检索面经' : length > CONTEXT_FULL_MAX ? '检索你贴的面经' : '读你贴的面经'}
                    desc={length === 0 ? '没贴面经，跳过这一步'
                      : length > CONTEXT_FULL_MAX ? `比较长（${length} 字），切段后每个话题取最相关的几段`
                      : `不长（${length} 字），整段交给面试官参考`} />
                  <PrepNode step={steps[3]} name="定下话题" desc="按岗位要求和你的经历选几个话题" />
                </div>
              </>
            ) : (
              <form onSubmit={start} noValidate>
                <div className="card-head">
                  <div className="dots" aria-hidden="true"><i /><i /><i /></div>
                  <span className="hint">面试官会参考</span>
                </div>
                <div className="iv-refs">
                  <div className="iv-ref"><span className="ok" aria-hidden="true">✓</span><div>
                    <div className="t">岗位要求</div>
                    <div className="s">{job ? `${job.title} · ${job.requirement_count} 条` : '加载中…'}</div>
                  </div></div>
                  <div className="iv-ref"><span className="ok" aria-hidden="true">✓</span><div>
                    <div className="t">你的简历</div>
                    <div className="s">{apply ? `${resumeTitle || '简历'} · 初筛时发现 ${apply.resume_issues.length} 处可改进` : '加载中…'}</div>
                  </div></div>
                </div>
                <div className="iv-opt">这家公司怎么面<span>选填</span></div>
                <div className="field">
                  <input id="iv-company" value={company} onChange={(e) => setCompany(e.target.value)} placeholder=" " maxLength={200} />
                  <label htmlFor="iv-company">公司名称</label>
                </div>
                <div className="field">
                  <textarea id="iv-context" value={context} onChange={(e) => setContext(e.target.value)} placeholder=" " maxLength={CONTEXT_MAX} />
                  <label htmlFor="iv-context">面经 / 公司或部门介绍</label>
                </div>
                <div className="card-foot">
                  <button type="button" className="link" onClick={() => setContext(SAMPLE)}>填一段示例面经</button>
                  <span className="hint">{context.length} / {CONTEXT_MAX}</span>
                </div>
                <p className="iv-note">贴了的话面试官会参考它，出题更像这家公司；很长的面经会按话题只挑最相关的几段。不贴就只按岗位要求和简历出题。</p>
              </form>
            )}
          </TiltCard>
        </div>
      </section>
    </AppShell>
  )
}

function PrepNode({ step, name, desc }: { step: Step; name: string; desc: string }) {
  const cls = { idle: '', run: 'is-run', ok: 'is-ok', skip: 'is-skip' }[step]
  return (
    <div className={`node ${cls}`}>
      <span className="node-mark" aria-hidden="true" />
      <div><div className="n">{name}</div><div className="d">{desc}</div></div>
    </div>
  )
}
