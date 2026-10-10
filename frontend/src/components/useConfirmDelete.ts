// 「原地确认删除」的逻辑：点删除不马上删，先问一句；取消后焦点回到「删除」；删的时候后端说不存在（别的标签页删过）当作删掉了。
// 工作台的岗位 / 简历列表（PickRow）和「我的简历」的卡片共用，确认框长什么样各自画。
import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

const NOT_FOUND = 40401

export function useConfirmDelete(run: () => Promise<unknown>, onGone: () => void) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const delRef = useRef<HTMLButtonElement>(null) // 挂在「删除」按钮上
  const refocus = useRef(false)

  // 取消后确认框没了，焦点不能丢到页面最上面：放回「删除」
  useEffect(() => {
    if (!asking && refocus.current) {
      refocus.current = false
      delRef.current?.focus()
    }
  }, [asking])

  const cancel = () => {
    if (busy) return
    refocus.current = true
    setAsking(false)
    setError(null)
  }

  const confirm = async () => {
    setBusy(true)
    setError(null)
    try {
      await run()
    } catch (err) {
      if (!(err instanceof ApiError && err.code === NOT_FOUND)) {
        setBusy(false)
        setError(err instanceof ApiError ? err.message : '请稍后再试')
        return
      }
    }
    onGone()
  }

  return { asking, busy, error, delRef, ask: () => setAsking(true), cancel, confirm }
}
