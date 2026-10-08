// 第 ② 步右侧：粘贴 JD 当场解析成要求项，或从「我的岗位」「模板」里选一个。都只列上一步选的方向，
// 左上角的「X方向 换」回到上一步。「我的岗位」每条能删（模板不能）。
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { Domain } from '../api/domains'
import { JD_MAX, JD_MIN, jobsApi, REQ_TYPE_LABEL, type Job, type JobBrief } from '../api/jobs'
import { TiltCard } from './effects'
import { PickRow } from './PickRow'
import { Tabs } from './Tabs'

type Tab = 'paste' | 'mine' | 'tpl'

const REQ_ORDER = { hard: 0, plus: 1, soft: 2 }

export function JobPicker({ domain, selected, onPick, onChangeDomain }: {
  domain: Domain
  selected: JobBrief | null
  onPick: (job: JobBrief | null) => void
  onChangeDomain: () => void
}) {
  const [tab, setTab] = useState<Tab>('paste')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [jd, setJd] = useState('')
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [parsed, setParsed] = useState<Job | null>(null)
  const [jobs, setJobs] = useState<JobBrief[] | null>(null) // null = 还在加载

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]))
  }, [])

  // 换了方向：上一个方向解析出的要求不算数（贴进去的原文留着，免得白贴）
  useEffect(() => {
    setParsed(null)
    setError(null)
  }, [domain.key])

  const jdLength = jd.trim().length
  const canParse = title.trim() !== '' && jdLength >= JD_MIN && !parsing

  const parse = async (e: FormEvent) => {
    e.preventDefault()
    if (!canParse) return
    setParsing(true)
    setError(null)
    try {
      const job = await jobsApi.create(title.trim(), company.trim(), jd, domain.key)
      setParsed(job)
      setJobs((list) => [job, ...(list ?? [])])
      onPick(job)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '解析失败，请稍后重试')
    } finally {
      setParsing(false)
    }
  }

  const fillSample = () => {
    setTitle(domain.sample_jd.title)
    setCompany(domain.sample_jd.company)
    setJd(domain.sample_jd.text)
  }

  /** 删掉之后：从列表里去掉；正选着它就清空，「粘贴 JD」里刚解析出的就是它也收起来 */
  const removed = (id: number) => {
    setJobs((list) => list?.filter((j) => j.id !== id) ?? null)
    if (selected?.id === id) onPick(null)
    if (parsed?.id === id) setParsed(null)
  }

  const inDomain = jobs?.filter((j) => j.domain === domain.key) ?? null
  const mine = inDomain?.filter((j) => !j.is_template) ?? null
  const templates = inDomain?.filter((j) => j.is_template) ?? null

  return (
    <TiltCard>
      <div className="card-head">
        <button type="button" className="dir-chip" onClick={onChangeDomain} title="回到上一步换方向">
          <span>{domain.name}方向</span><span className="chg">换</span>
        </button>
        <Tabs value={tab} onChange={setTab} tabs={[
          { key: 'paste', label: '粘贴 JD' }, { key: 'mine', label: '我的岗位' }, { key: 'tpl', label: '模板' },
        ]} />
      </div>

      {tab === 'paste' && (
        <form onSubmit={parse} noValidate>
          <div className="row2">
            <div className="field">
              <input id="jd-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder=" " maxLength={200} />
              <label htmlFor="jd-title">岗位名称</label>
            </div>
            <div className="field">
              <input id="jd-company" value={company} onChange={(e) => setCompany(e.target.value)} placeholder=" " maxLength={200} />
              <label htmlFor="jd-company">公司（选填）</label>
            </div>
          </div>
          <div className="field">
            <textarea id="jd-text" value={jd} onChange={(e) => setJd(e.target.value)} placeholder=" " maxLength={JD_MAX} />
            <label htmlFor="jd-text">岗位要求原文</label>
          </div>
          <div className="card-foot">
            <button type="button" className="link" onClick={fillSample}>填一份示例 JD</button>
            <span className="foot-right">
              {jdLength > 0 && jdLength < JD_MIN && <span className="hint">还差 {JD_MIN - jdLength} 字</span>}
              <button type="submit" className="btn dark sm" disabled={!canParse}>
                {parsing ? '解析中…' : parsed ? '重新解析' : '解析要求'}
              </button>
            </span>
          </div>
          {error && <p className="form-err" role="alert">{error}</p>}
          {parsing ? (
            <div className="req-box" aria-label="正在解析">
              {[80, 60, 70].map((w) => <div key={w} className="skeleton" style={{ width: `${w}%` }} />)}
            </div>
          ) : parsed && (
            <div className="req-box">
              <div className="req-head">拆出 <b>{parsed.requirements.length}</b> 条要求 · 黑色为必须项，每条都能在原文找到出处</div>
              <div className="req-chips">
                {[...parsed.requirements].sort((a, b) => REQ_ORDER[a.req_type] - REQ_ORDER[b.req_type]).map((r, i) => (
                  <span key={r.id} className={`req-chip ${r.req_type}`} style={{ animationDelay: `${i * 45}ms` }}
                    title={`${REQ_TYPE_LABEL[r.req_type]} · JD 原文：${r.quote}`}>{r.content}</span>
                ))}
              </div>
            </div>
          )}
        </form>
      )}

      {tab === 'mine' && (
        <JobList jobs={mine} selected={selected} onPick={onPick} onRemoved={removed} empty={`「${domain.name}」方向下还没有岗位。在「粘贴 JD」里贴一份，解析后会保存在这里。`} />
      )}
      {tab === 'tpl' && (
        <JobList jobs={templates} selected={selected} onPick={onPick} empty="这个方向暂时没有内置模板，先用「粘贴 JD」吧。" />
      )}
    </TiltCard>
  )
}

function JobList({ jobs, selected, onPick, onRemoved, empty }: {
  jobs: JobBrief[] | null
  selected: JobBrief | null
  onPick: (job: JobBrief) => void
  onRemoved?: (id: number) => void // 不给就不能删（模板）
  empty: string
}) {
  if (jobs === null) return <div className="skeleton" />
  if (jobs.length === 0) return <p className="empty">{empty}</p>
  return (
    <div className="pick-list">
      {jobs.map((j) => (
        <PickRow key={j.id} name={j.title} selected={selected?.id === j.id} onPick={() => onPick(j)}
          del={onRemoved && { note: '之前用它的投递不受影响，在「我的投递」里照样能看。', run: () => jobsApi.remove(j.id), onGone: () => onRemoved(j.id) }}>
          <span className="ic">{j.is_template ? j.title.slice(0, 2) : 'JD'}</span>
          <span className="txt">
            <span className="t">{j.title}</span>
            <span className="s">{j.is_template ? '' : `${j.company ?? '未填公司'} · `}{j.requirement_count} 条要求</span>
          </span>
        </PickRow>
      ))}
    </div>
  )
}
