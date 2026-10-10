// 第 ③ 步右侧：拖入 / 点选 PDF 上传，或从已上传的简历里选一份。
// 解析在后台进行；解析中的也能选（投递会等它解析完），解析失败的不能选。每份都能删（解析失败的也能）。
import { useCallback, useEffect, useRef, useState } from 'react'
import { isParsing, MAX_UPLOAD_MB, parseErrorText, RESUME_LIST_MAX, resumesApi, type Resume } from '../api/resumes'
import { TiltCard } from './effects'
import { monthDay } from './InterviewPill'
import { LoadFailed } from './LoadFailed'
import { PickRow } from './PickRow'
import { useParsingPoll } from './useParsingPoll'
import { useResumeUpload, withUploaded } from './useResumeUpload'

function statusText(r: Resume): string {
  if (r.parse_status === 'failed') return `解析失败：${parseErrorText(r.parse_error)}`
  if (isParsing(r)) return '解析中…也可以直接投，会等它解析完'
  return `${r.page_count ? `${r.page_count} 页 · ` : ''}已解析 · ${monthDay(r.updated_at)}`
}

export function ResumePicker({ selected, onPick }: { selected: Resume | null; onPick: (r: Resume | null) => void }) {
  const [resumes, setResumes] = useState<Resume[] | null>(null) // null = 还在加载
  const [more, setMore] = useState(false) // 超过一次取的份数，更早的没列出来
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  // 传完：排到最上面，并且直接选中
  const { upload, over, dropProps, inputProps } = useResumeUpload((fresh) => {
    setResumes((list) => withUploaded(list, fresh))
    onPick(fresh)
  })

  const [loadFailed, setLoadFailed] = useState(false) // 列表没取到：不能显示成「一份都没传过」
  const load = useCallback(() => {
    setLoadFailed(false)
    resumesApi.list().then((page) => {
      setResumes(page.items)
      setMore(page.total > page.items.length)
    }).catch(() => { setResumes([]); setLoadFailed(true) })
  }, [])
  useEffect(load, [load])

  // 解析中的简历定时刷新状态；选中的那份解析失败了就取消选中
  useParsingPoll(resumes, (fresh) => {
    setResumes((list) => list?.map((r) => (r.id === fresh.id ? { ...r, ...fresh } : r)) ?? null)
    if (selectedRef.current?.id === fresh.id) onPick(fresh.parse_status === 'failed' ? null : fresh)
  })

  return (
    <TiltCard className={over ? 'over' : ''} {...dropProps}>
      <label className="drop">
        <input {...inputProps} />
        <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 15V3M7 8l5-5 5 5" /><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
        </svg>
        <b>拖进来，或点这里选文件</b>
        <span>PDF · {MAX_UPLOAD_MB}MB 以内 · 扫描件读不出文字<br />Word 简历请先另存为 PDF</span>
      </label>

      {upload && (
        <div className={`up ${upload.error ? 'err' : ''}`} role={upload.error ? 'alert' : undefined}>
          <div className="up-top"><b>{upload.name}</b><span>{upload.error ?? '上传中…'}</span></div>
          {!upload.error && <div className="bar-track"><i className="indet" /></div>}
        </div>
      )}

      {loadFailed && <LoadFailed what="上传过的简历" onRetry={load} />}
      {resumes === null ? <div className="skeleton" /> : resumes.length > 0 && (
        <>
          <p className="small-h">已上传</p>
          <div className="pick-list">
            {resumes.map((r) => (
              <PickRow key={r.id} name={r.title} selected={selected?.id === r.id} disabled={r.parse_status === 'failed'} onPick={() => onPick(r)}
                del={{
                  note: r.apply_count ? <>它的 <b>{r.apply_count} 次投递</b>和面试报告也会从「我的投递」里隐藏。</> : '还没用它投过岗位。',
                  run: () => resumesApi.remove(r.id),
                  onGone: () => {
                    setResumes((list) => list?.filter((x) => x.id !== r.id) ?? null)
                    if (selectedRef.current?.id === r.id) onPick(null)
                  },
                }}>
                <span className="ic">PDF</span>
                <span className="txt">
                  <span className="t">{r.title}</span>
                  <span className={`s ${r.parse_status === 'failed' ? 'bad' : ''}`}>{statusText(r)}</span>
                </span>
              </PickRow>
            ))}
          </div>
          {more && <p className="pick-list-foot">只列出最近 {RESUME_LIST_MAX} 份。</p>}
        </>
      )}
    </TiltCard>
  )
}
