// 「我的简历」里的「看原文」：右侧抽屉，只看系统从 PDF 里读出来的纸面，不画任何标注（结果页那个带标注的是 ResumeSheet）。
// 点遮罩或 Esc 关闭。样稿：docs/design/我的简历预览.html
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ApiError } from '../api/client'
import { resumesApi, type Resume, type ResumeStructure } from '../api/resumes'
import { entryBlocksOf } from '../pages/applyItems'
import { ResumePaper, type SheetDoc } from './ResumePaper'

const noop = () => {}

export function ResumeViewer({ resume, onClose }: { resume: Resume | null; onClose: () => void }) {
  const open = resume !== null
  const [doc, setDoc] = useState<SheetDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  const title = useRef('') // 关上的时候抽屉还在往外滑，标题别先变空
  if (resume) title.current = resume.title

  useEffect(() => {
    if (!resume) return
    let cancelled = false
    setDoc(null)
    setError(null)
    Promise.all([resumesApi.blocks(resume.id), resumesApi.structure(resume.id).catch((): ResumeStructure => ({}))])
      .then(([blocks, structure]) => { if (!cancelled) setDoc({ ...blocks, entryBlocks: entryBlocksOf(structure) }) })
      .catch((err) => { if (!cancelled) setError(err instanceof ApiError ? err.message : '请稍后重试') })
    return () => { cancelled = true }
  }, [resume])

  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  // 挂到 body 下：页面内容区自成层叠上下文，放在里面盖不住导航栏（同 ResumeSheet）
  return createPortal(
    <>
      <div className={`veil ${open ? 'open' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sheet ${open ? 'open' : ''}`} role="dialog" aria-modal="true" aria-labelledby="viewer-title" aria-hidden={!open}>
        <div className="sheet-head">
          <div className="sheet-title" id="viewer-title">简历原文<span>{title.current}</span></div>
          <button type="button" className="x" onClick={onClose} aria-label="关闭">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" /></svg>
          </button>
        </div>
        <p className="mr-view-note">这是系统从 PDF 里读出来的内容和顺序，诊断、匹配都按它来。顺序读乱了或者缺了内容，可以换一份排版简单些的 PDF。</p>
        <ResumePaper doc={doc} loadError={error} items={[]} focusKey={null} onFocus={noop} />
      </aside>
    </>,
    document.body,
  )
}
