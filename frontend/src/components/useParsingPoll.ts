// 解析中的简历每 1.5 秒取一次状态，直到解析完。工作台选简历、我的简历共用。
import { useEffect, useRef } from 'react'
import { isParsing, resumesApi, type Resume } from '../api/resumes'

const POLL_MS = 1500

export function useParsingPoll(resumes: Resume[] | null, onFresh: (fresh: Resume) => void) {
  const latest = useRef(onFresh)
  latest.current = onFresh
  const ids = (resumes ?? []).filter(isParsing).map((r) => r.id).join(',')

  useEffect(() => {
    if (!ids) return
    const timer = window.setInterval(() => {
      for (const id of ids.split(',').map(Number)) {
        resumesApi.get(id).then((fresh) => latest.current(fresh)).catch(() => { /* 下一轮再试 */ })
      }
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [ids])
}
