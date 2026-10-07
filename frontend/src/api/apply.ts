// 对应后端 app/api/apply.py、app/api/task.py 与 app/schemas.py 的 ApplyOut / MatchItemOut / FindingOut
import type { Advice } from './advice'
import { openStream, request, sseEvents } from './client'
import type { Requirement } from './jobs'

export type MatchItem = {
  requirement_id: number
  content: string
  req_type: Requirement['req_type']
  category: Requirement['category']
  weight: number
  skill: string | null
  status: 'hit' | 'partial' | 'miss'
  matched_by: 'dict' | 'profile' | 'fulltext' | null
  reason: string
  evidence_quote: string | null // 简历原文：full_text[char_start:char_end]
  char_start: number | null
  char_end: number | null
  unit_id: string | null
  advice?: Advice | null // 生成过的具体建议（只有没满足 / 部分满足的才会有）
}

export type Finding = {
  id: number
  source: 'rule' | 'llm'
  rule_code: string | null
  risk_type: string | null
  category: string
  severity: 'high' | 'medium' | 'low'
  title: string
  description: string | null
  suggestion: string | null
  unit_id: string | null
  evidence_quote: string | null
  char_start: number | null
  char_end: number | null
  page_no: number | null
  bbox: number[] | null
  verify_result: string
  match_score: number | null
  rewrite: Advice | null // 生成过的具体建议
}

export type Dimension = 'skill' | 'education' | 'experience' | 'other'

export type ApplyResult = {
  id: number
  resume_id: number
  job_id: number
  diagnosis_id: number | null
  status: 'pending' | 'running' | 'success' | 'failed'
  stage: 'parsing' | 'queued' | 'analyzing' | 'done' | 'failed'
  error_msg: string | null
  gate: { passed: boolean; overall_match: number | null; threshold: number } | null // 跑完才有
  dimension_scores: Record<Dimension, number | null> | null // JD 里没有这类要求时为 null
  resume_score: number | null
  gaps: MatchItem[] // 未满足 / 部分满足的要求，重要的在前
  resume_issues: Finding[] // 简历自身最该先改的问题，严重的在前
}

/** 「我的投递」里挂在投递下面的一场面试（ApplyInterviewBrief） */
export type ApplyInterview = {
  id: number
  mode: 'normal' | 'practice'
  status: 'planned' | 'in_progress' | 'completed' | 'abandoned'
  topic_count: number
  current_topic: number // 进行中：正在问第几个话题（从 1 起）；其他状态为 0
  overall: number | null // 结束后的总分
  verdict: 'pass' | 'fail' | 'incomplete' | 'practice' | null
  created_at: string
}

/** 「我的投递」列表的一条（ApplyBrief）：只有结论，明细看 GET /apply/{id} */
export type ApplyBrief = {
  id: number
  status: ApplyResult['status']
  overall_match: number | null
  passed: boolean | null // 跑完才有
  failure: string | null // 失败时给用户看的一句话
  job_id: number
  job_title: string
  company: string | null
  domain: string
  resume_id: number
  resume_title: string
  created_at: string
  interviews: ApplyInterview[] // 新的在前
}

export const isRunning = (r: { status: ApplyResult['status'] }) => r.status === 'pending' || r.status === 'running'

/** 组件卸载时主动断开跟踪抛出的异常，调用方应当忽略 */
export const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

export const applyApi = {
  /** 立即返回；诊断 + 匹配 + 初筛在后台跑。投递 id 就是匹配报告 id */
  start: (resumeId: number, jobId: number) =>
    request<{ id: number; diagnosis_id: number; task_id: string; status: string }>(
      '/apply', { method: 'POST', body: { resume_id: resumeId, job_id: jobId } }),

  get: (id: number) => request<ApplyResult>(`/apply/${id}`),

  /** 我的投递，新的在前。一次取最近 100 条（后端分页的上限），不做翻页 */
  list: () => request<{ items: ApplyBrief[]; total: number }>('/apply?page_size=100'),

  /** 完整的逐条匹配明细（含已满足的），原文纸面上「满足」的标注要用 */
  match: (id: number) => request<{ items: MatchItem[] }>(`/match/${id}`),
}

// ───────────── 跟踪进度 ─────────────
// 后端的 progress 事件 stage ∈ parsing / analyzing / diagnose / match / gate（诊断与匹配并行，先完成的先到）。
// 结束以数据库状态为准：SSE 的 done / error，或轮询 GET /apply/{id} 的 status。

const IDLE_MS = 30_000 // 这么久连心跳都没有，就当连接断了，改用轮询
const POLL_MS = 3_000

/** 一直跟到投递结束，返回最终状态 success / failed。先用 SSE，连不上或中途断了就每 3 秒轮询一次 */
export async function watchApply(id: number, onStage: (stage: string) => void, signal: AbortSignal): Promise<string> {
  try {
    const status = await streamApply(id, onStage, signal)
    if (status) return status
  } catch (e) {
    if (signal.aborted) throw e
  }
  return pollApply(id, onStage, signal)
}

/** 返回 null 表示没等到结束事件（断线 / 超时），交给轮询 */
async function streamApply(id: number, onStage: (stage: string) => void, signal: AbortSignal): Promise<string | null> {
  const ctrl = new AbortController()
  const abort = () => ctrl.abort()
  signal.addEventListener('abort', abort)
  let idle = window.setTimeout(abort, IDLE_MS)
  const alive = () => {
    window.clearTimeout(idle)
    idle = window.setTimeout(abort, IDLE_MS)
  }
  try {
    for await (const event of sseEvents(await openStream(`/tasks/apply/${id}/stream`, ctrl.signal), alive)) {
      if (event.name === 'progress') onStage(String(event.data.stage))
      else if (event.name === 'done') return String(event.data.status)
      // 流开了 10 分钟还没结束，后端会发 status=timeout：任务可能还在跑，改用轮询
      else if (event.name === 'error') return event.data.status === 'timeout' ? null : 'failed'
    }
    return null
  } finally {
    window.clearTimeout(idle)
    signal.removeEventListener('abort', abort)
    ctrl.abort()
  }
}

async function pollApply(id: number, onStage: (stage: string) => void, signal: AbortSignal): Promise<string> {
  for (;;) {
    const r = await applyApi.get(id)
    if (signal.aborted) throw new DOMException('aborted', 'AbortError')
    if (!isRunning(r)) return r.status
    onStage(r.stage === 'parsing' ? 'parsing' : 'analyzing')
    await sleep(POLL_MS, signal)
  }
}

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = window.setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      window.clearTimeout(t)
      reject(new DOMException('aborted', 'AbortError'))
    }, { once: true })
  })
}
