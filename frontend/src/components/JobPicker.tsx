// 第 ① 步右侧：粘贴 JD 当场解析成要求项，或从「我的岗位」「模板」里选一个
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { JD_MAX, JD_MIN, jobsApi, REQ_TYPE_LABEL, type Job, type JobBrief } from '../api/jobs'
import { TiltCard } from './effects'
import { Tabs } from './Tabs'

type Tab = 'paste' | 'mine' | 'tpl'

const SAMPLE_JD = `任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟悉 Java，熟悉 Spring Boot、MyBatis 等常用框架；
3. 熟悉 MySQL，有 SQL 调优经验者优先；
4. 有 Redis 使用经验，了解常见缓存问题；
5. 了解消息队列（Kafka / RocketMQ）；
6. 有高并发场景经验者优先；熟悉 Linux 常用命令；
7. 良好的沟通能力与团队协作意识。`

const REQ_ORDER = { hard: 0, plus: 1, soft: 2 }

export function JobPicker({ selected, onPick }: { selected: JobBrief | null; onPick: (job: JobBrief) => void }) {
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

  const jdLength = jd.trim().length
  const canParse = title.trim() !== '' && jdLength >= JD_MIN && !parsing

  const parse = async (e: FormEvent) => {
    e.preventDefault()
    if (!canParse) return
    setParsing(true)
    setError(null)
    try {
      const job = await jobsApi.create(title.trim(), company.trim(), jd)
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
    setTitle('后端开发实习生')
    setCompany('示例科技')
    setJd(SAMPLE_JD)
  }

  const mine = jobs?.filter((j) => !j.is_template) ?? null
  const templates = jobs?.filter((j) => j.is_template) ?? null

  return (
    <TiltCard>
      <div className="card-head">
        <div className="dots" aria-hidden="true"><i /><i /><i /></div>
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
        <JobList jobs={mine} selected={selected} onPick={onPick} empty="还没有岗位。在「粘贴 JD」里贴一份，解析后会保存在这里。" />
      )}
      {tab === 'tpl' && (
        <JobList jobs={templates} selected={selected} onPick={onPick} empty="内置岗位模板还在整理中，先用「粘贴 JD」吧。" />
      )}
    </TiltCard>
  )
}

function JobList({ jobs, selected, onPick, empty }: {
  jobs: JobBrief[] | null
  selected: JobBrief | null
  onPick: (job: JobBrief) => void
  empty: string
}) {
  if (jobs === null) return <div className="skeleton" />
  if (jobs.length === 0) return <p className="empty">{empty}</p>
  return (
    <div className="pick-list">
      {jobs.map((j) => (
        <button key={j.id} type="button" className={`pick-item ${selected?.id === j.id ? 'sel' : ''}`} onClick={() => onPick(j)}>
          <span className="ic">{j.is_template ? j.title.slice(0, 2) : 'JD'}</span>
          <span className="txt">
            <span className="t">{j.title}</span>
            <span className="s">{j.is_template ? '' : `${j.company ?? '未填公司'} · `}{j.requirement_count} 条要求</span>
          </span>
          <span className="radio" aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
