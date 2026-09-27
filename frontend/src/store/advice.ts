// 具体建议的生成进度。同一条可能同时出现在列表和原文纸面里，所以放在一处共享：
// 一条只生成一次，两边看到的是同一份进度；离开页面也不打断（后端生成完照样存库）。
import { create } from 'zustand'
import { streamAdvice, type Advice } from '../api/advice'
import { ApiError } from '../api/client'

export type AdviceEntry = {
  status: 'loading' | 'streaming' | 'done' | 'error'
  text: string
  error?: string
}

export const useAdviceStore = create<{ entries: Record<string, AdviceEntry> }>(() => ({ entries: {} }))

function put(key: string, entry: AdviceEntry) {
  useAdviceStore.setState((s) => ({ entries: { ...s.entries, [key]: entry } }))
}

/** 需要显示这条建议时调用：已有结果或正在生成就什么都不做；失败过的会重新生成。cached 是接口里已经带回来的 */
export function ensureAdvice(key: string, path: string, cached?: Advice | null) {
  const current = useAdviceStore.getState().entries[key]
  if (current && current.status !== 'error') return
  if (cached?.text) return put(key, { status: 'done', text: cached.text })

  put(key, { status: 'loading', text: '' })
  let text = ''
  streamAdvice(path, (delta) => {
    text += delta
    put(key, { status: 'streaming', text })
  })
    .then((advice) => put(key, { status: 'done', text: advice.text }))
    .catch((err) => put(key, { status: 'error', text, error: err instanceof ApiError ? err.message : '生成失败，请重试' }))
}
