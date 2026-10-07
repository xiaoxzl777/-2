// 对应后端 app/api/job.py 与 app/schemas.py 的 JobBrief / JobOut / RequirementOut
import { request } from './client'

export type Requirement = {
  id: number
  req_type: 'hard' | 'plus' | 'soft'
  category: 'skill' | 'education' | 'experience' | 'other'
  content: string
  skill: string | null
  skill_id: number | null
  weight: number
  quote: string // JD 原文的逐字引用
  char_start: number
  char_end: number
}

export type JobBrief = {
  id: number
  title: string
  company: string | null
  domain: string // 求职方向的 key，见 api/domains.ts
  is_template: boolean
  requirement_count: number
  created_at: string
}

export type Job = JobBrief & { raw_text: string; requirements: Requirement[] }

export const REQ_TYPE_LABEL: Record<Requirement['req_type'], string> = { hard: '必须项', plus: '加分项', soft: '软素质' }

// 与后端 JobIn 的校验保持一致
export const JD_MIN = 30
export const JD_MAX = 10000

export const jobsApi = {
  /** 同步解析（约 2–4 秒）：返回时要求项已经拆好 */
  create: (title: string, company: string, rawText: string, domain: string) =>
    request<Job>('/jobs', { method: 'POST', body: { title, company: company || null, raw_text: rawText, domain } }),

  /** 我的岗位（新的在前）+ 内置模板（排在后面） */
  list: () => request<JobBrief[]>('/jobs?include_templates=1'),

  get: (id: number) => request<Job>(`/jobs/${id}`),
}
