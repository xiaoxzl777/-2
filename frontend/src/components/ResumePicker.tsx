// 第 ② 步右侧：拖入 / 点选 PDF 上传，或从已上传的简历里选一份。
// 解析在后台进行；解析中的也能选（投递会等它解析完），解析失败的不能选。
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ApiError } from '../api/client'
import { isParsing, MAX_UPLOAD_MB, parseErrorText, resumesApi, type Resume } from '../api/resumes'
import { TiltCard } from './effects'

const POLL_MS = 1500

function statusText(r: Resume): string {
  if (r.parse_status === 'failed') return `解析失败：${parseErrorText(r.parse_error)}`
  if (isParsing(r)) return '解析中…也可以直接投，会等它解析完'
  const d = new Date(r.updated_at)
  return `${r.page_count ? `${r.page_count} 页 · ` : ''}已解析 · ${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

export function ResumePicker({ selected, onPick }: { selected: Resume | null; onPick: (r: Resume | null) => void }) {
  const [resumes, setResumes] = useState<Resume[] | null>(null) // null = 还在加载
  const [upload, setUpload] = useState<{ name: string; error?: string } | null>(null)
  const [over, setOver] = useState(false)
  const selectedRef = useRef(selected)
  selectedRef.current = selected

  useEffect(() => {
    resumesApi.list().then((page) => setResumes(page.items)).catch(() => setResumes([]))
  }, [])

  // 解析中的简历定时刷新状态；选中的那份解析失败了就取消选中
  const parsingIds = (resumes ?? []).filter(isParsing).map((r) => r.id).join(',')
  useEffect(() => {
    if (!parsingIds) return
    const timer = window.setInterval(() => {
      for (const id of parsingIds.split(',').map(Number)) {
        resumesApi.get(id).then((fresh) => {
          setResumes((list) => list?.map((r) => (r.id === id ? fresh : r)) ?? null)
          if (selectedRef.current?.id === id) onPick(fresh.parse_status === 'failed' ? null : fresh)
        }).catch(() => { /* 下一轮再试 */ })
      }
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [parsingIds, onPick])

  const send = async (file: File | undefined) => {
    if (!file) return
    if (!/\.pdf$/i.test(file.name)) return setUpload({ name: file.name, error: '目前只支持 PDF' })
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return setUpload({ name: file.name, error: `文件不能超过 ${MAX_UPLOAD_MB}MB` })
    setUpload({ name: file.name })
    try {
      const out = await resumesApi.upload(file)
      let fresh = await resumesApi.get(out.id)
      // 同一文件上次解析失败：后端已经重新排队解析，只是状态还没来得及改
      if (out.deduplicated && fresh.parse_status === 'failed') fresh = { ...fresh, parse_status: 'pending', parse_error: null }
      setResumes((list) => [fresh, ...(list ?? []).filter((r) => r.id !== fresh.id)])
      setUpload(null)
      onPick(fresh)
    } catch (err) {
      setUpload({ name: file.name, error: err instanceof ApiError ? err.message : '上传失败，请稍后重试' })
    }
  }

  const dragOver = (e: DragEvent) => {
    e.preventDefault()
    setOver(true)
  }
  const dragEnd = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
  }

  return (
    <TiltCard className={over ? 'over' : ''} onDragEnter={dragOver} onDragOver={dragOver} onDragLeave={dragEnd}
      onDrop={(e) => { dragEnd(e); void send(e.dataTransfer.files[0]) }}>
      <label className="drop">
        <input type="file" accept=".pdf,application/pdf" hidden onChange={(e) => { void send(e.target.files?.[0]); e.target.value = '' }} />
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

      {resumes === null ? <div className="skeleton" /> : resumes.length > 0 && (
        <>
          <p className="small-h">已上传</p>
          <div className="pick-list">
            {resumes.map((r) => (
              <button key={r.id} type="button" className={`pick-item ${selected?.id === r.id ? 'sel' : ''}`}
                disabled={r.parse_status === 'failed'} onClick={() => onPick(r)}>
                <span className="ic">PDF</span>
                <span className="txt">
                  <span className="t">{r.title}</span>
                  <span className={`s ${r.parse_status === 'failed' ? 'bad' : ''}`}>{statusText(r)}</span>
                </span>
                <span className="radio" aria-hidden="true" />
              </button>
            ))}
          </div>
        </>
      )}
    </TiltCard>
  )
}
