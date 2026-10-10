// 一场面试的小胶囊：没开始 / 进行中的点了去面试页接着面，结束的点了看报告。「我的投递」和初筛结果页的成绩单共用（样式 .ap-pill）
import { Link } from 'react-router-dom'
import type { ApplyInterview } from '../api/apply'

const VERDICT = { pass: ['v-ok', '通过'], fail: ['v-no', '没过'], incomplete: ['v-mid', '没做完'], practice: ['v-mid', '练习不下结论'] } as const

/** 今天 / 10 月 7 日，可带时间 */
/** 「10 月 9 日」 */
export function monthDay(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

export function when(iso: string, withTime = true): string {
  const d = new Date(iso), now = new Date()
  const day = d.toDateString() === now.toDateString() ? '今天' : monthDay(iso)
  return withTime ? `${day} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` : day
}

export const isLive = (v: ApplyInterview) => v.status === 'planned' || v.status === 'in_progress'

export function InterviewPill({ v }: { v: ApplyInterview }) {
  const mode = v.mode === 'practice' ? <span className="m prac">练习</span> : <span className="m">模拟面试</span>
  if (isLive(v)) {
    return (
      <Link className="ap-pill live" to={`/app/interview/${v.id}`}>
        {mode}
        {v.status === 'planned' ? '还没开始' : `进行中 · 第 ${v.current_topic} / ${v.topic_count} 个话题`}
        <span className="act">{v.status === 'planned' ? '开始' : '继续'} →</span>
      </Link>
    )
  }
  const verdict = v.verdict ? VERDICT[v.verdict] : null
  return (
    <Link className="ap-pill" to={`/app/interview/${v.id}/report`}>
      {mode}{when(v.created_at, false)}
      {v.overall != null && <b>{v.overall} 分</b>}
      {verdict && <span className={verdict[0]}>{verdict[1]}</span>}
      <span className="act">报告 →</span>
    </Link>
  )
}
