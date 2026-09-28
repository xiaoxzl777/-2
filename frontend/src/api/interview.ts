// 模拟面试：对应后端 app/api/interview.py。创建是普通请求；开始 / 答题是 POST + text/event-stream：
//   topic {idx,label,source,count} → asking {topic_idx,depth} → question {delta} ×N → asked {turn_id,text,…}
//   练习模式答完一题先来 evaluation；面试结束来 finished；出错来 error（之后调 start 能从原处继续）
import { ApiError, openStream, request, sseEvents } from './client'
import type { ApplyResult } from './apply'

export type TopicSource = 'project' | 'requirement' | 'finding'
export const SOURCE_LABEL: Record<TopicSource, string> = { project: '简历项目', requirement: '岗位要求', finding: '简历问题' }

export type Topic = { idx: number; label: string; source: TopicSource }

export type Evaluation = {
  skipped: boolean
  score: number // 0–100
  scores: { correctness: number; depth: number; clarity: number } | null
  evidence: { quote: string }[] // 模型打分的依据：逐字引用回答里的原话（已核实）
  good: string
  bad: string
  better_answer: string
  decision: 'followup' | 'next'
  low_evidence: boolean
}

export type Turn = {
  id: number
  topic_idx: number
  depth: number // 0 = 主问题，1 = 追问
  question: string
  answer: string | null // 还没答为 null；跳过为 ''
  skipped: boolean
  evaluation: Evaluation | null // 正常模式在结束前为 null
}

export type Interview = {
  id: number
  apply_id: number | null
  job_title: string | null
  company_name: string | null
  mode: 'normal' | 'practice'
  status: 'planned' | 'in_progress' | 'completed' | 'abandoned'
  topic_count: number
  topics: Topic[] // 已经问到的话题
  turns: Turn[]
  waiting: boolean
  report_ready: boolean
}

export type Report = {
  overall: number
  verdict: 'pass' | 'fail' | 'practice' | 'incomplete' // incomplete：没聊完所有话题就结束，不下结论
  threshold: number
  mode: 'normal' | 'practice'
  topics: (Topic & { score: number | null })[] // score 为 null = 没聊到
  strengths: { title: string; detail: string }[]
  weaknesses: { title: string; detail: string }[]
  links: { kind: 'finding' | 'requirement'; ref_id: number; topic_idx: number; label: string; text: string }[]
  answered: number
  early: boolean
  summary_ok: boolean
}

export type InterviewReport = Interview & { report: Report }

export type Created = { id: number; mode: Interview['mode']; gate: NonNullable<ApplyResult['gate']>; topic_count: number; context_mode: 'none' | 'full' | 'retrieval' }

export type IvEvent =
  | { name: 'topic'; data: Topic & { count: number } }
  | { name: 'asking'; data: { topic_idx: number; depth: number } }
  | { name: 'question'; data: { delta: string } }
  | { name: 'asked'; data: { turn_id: number; text: string; topic_idx: number; depth: number } }
  | { name: 'evaluation'; data: Evaluation & { turn_id: number } }
  | { name: 'finished'; data: { report_ready: boolean; verdict: Report['verdict']; overall: number } }

export const CONTEXT_MAX = 20000
export const ANSWER_MAX = 3000

export const interviewApi = {
  create: (body: { apply_id: number; company_name?: string; extra_context?: string; practice?: boolean }) =>
    request<Created>('/interviews', { method: 'POST', body }),
  get: (id: number) => request<Interview>(`/interviews/${id}`),
  report: (id: number) => request<InterviewReport>(`/interviews/${id}/report`),
  finish: (id: number) => request<InterviewReport>(`/interviews/${id}/finish`, { method: 'POST' }),
}

/** 还没开始流就被拒了（回答为空 / 太长 / 已经答过、面试已结束…）：这时回答没有落库，页面要撤回刚显示的那条 */
export class RejectedError extends ApiError {}

/** 开始 / 继续（answer 不传）或答题。逐个产出事件；流里的 error 事件转成 ApiError 抛出（回答已经落库，重试用 start） */
export async function* interviewStream(id: number, answer?: { text: string; skip: boolean }): AsyncGenerator<IvEvent> {
  const path = answer ? `/interviews/${id}/answer` : `/interviews/${id}/start`
  let stream: ReadableStream<Uint8Array>
  try {
    stream = await openStream(path, new AbortController().signal, 'POST', answer)
  } catch (err) {
    throw err instanceof ApiError ? new RejectedError(err.code, err.message) : err
  }
  for await (const event of sseEvents(stream)) {
    if (event.name === 'error') throw new ApiError(Number(event.data.code), String(event.data.message))
    yield event as unknown as IvEvent
  }
}
