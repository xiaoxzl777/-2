// 对应后端 app/api/resume.py 与 app/schemas.py 的 ResumeOut / ResumeListItem / UploadOut
import { request } from './client'

export type ParseStatus = 'pending' | 'parsing' | 'success' | 'failed'

export type Resume = {
  id: number
  title: string
  file_type: string
  file_size: number
  page_count: number | null
  parse_status: ParseStatus
  parse_error: string | null
  layout_type: string
  layout_confidence: number | null
  used_llm_fallback: boolean
  overall_score: number | null
  created_at: string
  updated_at: string
  apply_count?: number // 只有列表接口带：用它投过几次（删除前提示这些投递会一起隐藏）
}

type Page<T> = { items: T[]; total: number; page: number; page_size: number }

export type UploadOut = {
  id: number
  task_id: string
  parse_status: ParseStatus
  deduplicated: boolean // 同一文件之前传过，直接复用那条记录
}

// 与后端上传校验保持一致：目前只收 PDF
export const MAX_UPLOAD_MB = 20

// 选简历的列表一次取多少份（后端每页最多 100）；更早的不显示
export const RESUME_LIST_MAX = 100

/** 解析失败的原因（后端 parse_error）→ 给用户看的短说明 */
export function parseErrorText(code: string | null): string {
  switch (code) {
    case 'scanned_pdf': return '扫描件，读不出文字'
    case 'encrypted_pdf': return '文件已加密'
    case 'interrupted': return '解析被中断，重新上传即可'
    case 'llm_failed': return '调用大模型失败，重新上传即可'
    case 'llm_unavailable': return '模型服务暂时不可用，恢复后重新上传即可'
    default: return '解析失败'
  }
}

export const isParsing = (r: Resume) => r.parse_status === 'pending' || r.parse_status === 'parsing'

/** 解析结果（原文纸面用）：块按阅读顺序排好，char 区间相对 full_text，左闭右开 */
export type ResumeBlocks = {
  full_text: string
  blocks: { block_index: number; char_start: number; char_end: number }[]
  sections: { type: string; block_start: number; block_end: number; matched_by: string }[]
}

type Entry = { block_ids?: number[] }
/** 结构化结果里只用到各条经历由哪些块组成（纸面上把每条经历的标题行加粗） */
export type ResumeStructure = Partial<Record<'education' | 'work' | 'projects' | 'awards', Entry[]>>


export const resumesApi = {
  list: () => request<Page<Resume>>(`/resumes?page_size=${RESUME_LIST_MAX}`),

  get: (id: number) => request<Resume>(`/resumes/${id}`),

  blocks: (id: number) => request<ResumeBlocks>(`/resumes/${id}/blocks`),

  structure: (id: number) => request<ResumeStructure>(`/resumes/${id}/structure`),

  /** 软删除：用它的投递、面试报告也从「我的投递」里隐藏 */
  remove: (id: number) => request<null>(`/resumes/${id}`, { method: 'DELETE' }),

  /** 立即返回，解析在后台进行 */
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadOut>('/resumes', { method: 'POST', body: form })
  },
}
