// 上传一份简历：先在前端校验 → 上传 → 取回这一条；拖进来和点选两种方式都在这里。工作台选简历、「我的简历」共用。
import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { ApiError } from '../api/client'
import { fileProblem, uploadResume, type Resume } from '../api/resumes'

/** 上传完的那份放到列表最上面。同一个文件以前传过（后端复用了那条记录）：沿用列表里已有的投递次数 */
export function withUploaded(list: Resume[] | null, fresh: Resume): Resume[] {
  const prev = list?.find((r) => r.id === fresh.id)
  return [{ ...prev, ...fresh }, ...(list ?? []).filter((r) => r.id !== fresh.id)]
}

export function useResumeUpload(onDone: (fresh: Resume) => void) {
  const [upload, setUpload] = useState<{ name: string; error?: string } | null>(null) // 正在传的 / 没传成的那份
  const [over, setOver] = useState(false) // 文件正拖在上传框上方
  const done = useRef(onDone)
  done.current = onDone

  const send = async (file: File | undefined) => {
    if (!file) return
    const problem = fileProblem(file)
    if (problem) return setUpload({ name: file.name, error: problem })
    setUpload({ name: file.name })
    try {
      const fresh = await uploadResume(file)
      setUpload(null)
      done.current(fresh)
    } catch (err) {
      setUpload({ name: file.name, error: err instanceof ApiError ? err.message : '上传失败，请稍后重试' })
    }
  }

  const enter = (e: DragEvent) => { e.preventDefault(); setOver(true) }
  const leave = (e: DragEvent) => { e.preventDefault(); setOver(false) }

  return {
    upload,
    over,
    /** 铺在整个上传区域上 */
    dropProps: { onDragEnter: enter, onDragOver: enter, onDragLeave: leave, onDrop: (e: DragEvent) => { leave(e); void send(e.dataTransfer.files[0]) } },
    /** 给上传框里那个看不见的文件输入框（.file-input：Tab 能到，回车打开选文件的窗口） */
    inputProps: {
      type: 'file', accept: '.pdf,application/pdf', className: 'file-input',
      onChange: (e: ChangeEvent<HTMLInputElement>) => { void send(e.target.files?.[0]); e.target.value = '' }, // 清掉，同一个文件能再选一次
    },
  }
}
