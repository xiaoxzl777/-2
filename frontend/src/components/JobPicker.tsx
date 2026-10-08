// 第 ② 步右侧：两个页签「我的岗位」「模板」，都只列上一步选的方向；左上角的「X方向 换」回到上一步。
// 「我的岗位」最上面一条「＋ 粘贴新的招聘 JD」，点开就地展开表单，解析完收起、新岗位排第一条并选中；
// 下面是贴过的岗位，每条能删（模板不能）。原来「粘贴 JD」是单独的页签，贴好的却跑到「我的岗位」里，2026-10-08 并成一个。
// 样稿：docs/design/选岗位合并预览.html
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { Domain } from '../api/domains'
import { JD_MAX, JD_MIN, jobsApi, REQ_TYPE_LABEL, type Job, type JobBrief } from '../api/jobs'
import { TiltCard } from './effects'
import { PickRow } from './PickRow'
import { Tabs } from './Tabs'

type Tab = 'mine' | 'tpl'

const REQ_ORDER = { hard: 0, plus: 1, soft: 2 }

export function JobPicker({ domain, selected, onPick, onChangeDomain }: {
  domain: Domain
  selected: JobBrief | null
  onPick: (job: JobBrief | null) => void
  onChangeDomain: () => void
}) {
  const [tab, setTab] = useState<Tab>('mine')
  const [open, setOpen] = useState(false) // 「粘贴新的招聘 JD」展开了没有
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [jd, setJd] = useState('')
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [parsed, setParsed] = useState<Job | null>(null) // 刚解析出来的：上面显示拆出的要求，列表里标「新」
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
      // 收起表单、清空，下次再贴就是一份新的
      setOpen(false)
      setTitle('')
      setCompany('')
      setJd('')
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

  /** 删掉之后：从列表里去掉；正选着它就清空，刚解析出的就是它，上面的要求也收起来 */
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
        <Tabs value={tab} onChange={setTab} tabs={[{ key: 'mine', label: '我的岗位' }, { key: 'tpl', label: '模板' }]} />
      </div>

      {tab === 'mine' && (
        <>
          <p className="jp-guide">贴过的岗位都存在下面，下次直接选；没有具体岗位，可以去「模板」里挑一个。</p>
          <button type="button" className={`jp-add${open ? ' open' : ''}`} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <span className="plus" aria-hidden="true">+</span>粘贴新的招聘 JD
            <span className="hint">{open ? '收起' : '贴进来自动拆成一条条要求'}</span>
          </button>
          {open && (
            <form className="jp-form" onSubmit={parse} noValidate>
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
                  <button type="submit" className="btn dark sm" disabled={!canParse}>{parsing ? '解析中…' : '解析要求'}</button>
                </span>
              </div>
              {error && <p className="form-err" role="alert">{error}</p>}
              {parsing && (
                <div className="jp-parsing" aria-label="正在解析">
                  {[80, 60].map((w) => <div key={w} className="skeleton" style={{ width: `${w}%` }} />)}
                </div>
              )}
            </form>
          )}
          {parsed && (
            <div className="req-box jp-parsed">
              <div className="req-head">已解析「<b>{parsed.title}</b>」：拆出 <b>{parsed.requirements.length}</b> 条要求 · 黑色为必须项，每条都能在原文找到出处</div>
              <div className="req-chips">
                {[...parsed.requirements].sort((a, b) => REQ_ORDER[a.req_type] - REQ_ORDER[b.req_type]).map((r, i) => (
                  <span key={r.id} className={`req-chip ${r.req_type}`} style={{ animationDelay: `${i * 45}ms` }}
                    title={`${REQ_TYPE_LABEL[r.req_type]} · JD 原文：${r.quote}`}>{r.content}</span>
                ))}
              </div>
            </div>
          )}
          {mine === null ? <div className="skeleton jp-list-gap" /> : mine.length > 0 ? (
            <>
              <p className="small-h jp-list-gap">已保存的岗位</p>
              <JobList jobs={mine} selected={selected} onPick={onPick} onRemoved={removed} newId={parsed?.id} />
            </>
          ) : !open && (
            <p className="empty jp-list-gap">还没有保存的岗位。点上面「＋ 粘贴新的招聘 JD」贴一份，或者去「模板」里挑一个。</p>
          )}
        </>
      )}
      {tab === 'tpl' && (
        templates === null ? <div className="skeleton" />
          : templates.length === 0 ? <p className="empty">这个方向暂时没有内置模板，先在「我的岗位」里贴一份 JD 吧。</p>
          : <JobList jobs={templates} selected={selected} onPick={onPick} />
      )}
    </TiltCard>
  )
}

function JobList({ jobs, selected, onPick, onRemoved, newId }: {
  jobs: JobBrief[]
  selected: JobBrief | null
  onPick: (job: JobBrief) => void
  onRemoved?: (id: number) => void // 不给就不能删（模板）
  newId?: number // 刚解析出来的那条，标「新」
}) {
  return (
    <div className="pick-list">
      {jobs.map((j) => (
        <PickRow key={j.id} name={j.title} selected={selected?.id === j.id} onPick={() => onPick(j)}
          del={onRemoved && { note: '之前用它的投递不受影响，在「我的投递」里照样能看。', run: () => jobsApi.remove(j.id), onGone: () => onRemoved(j.id) }}>
          <span className="ic">{j.is_template ? j.title.slice(0, 2) : 'JD'}</span>
          <span className="txt">
            <span className="t">{j.title}{j.id === newId && <span className="jp-new">新</span>}</span>
            <span className="s">{j.is_template ? '' : `${j.company ?? '未填公司'} · `}{j.requirement_count} 条要求</span>
          </span>
        </PickRow>
      ))}
    </div>
  )
}
