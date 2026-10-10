// 对应后端 app/api/admin.py：管理端的模型用量、模型设置。都要管理员登录，不是管理员一律 40301
import { request } from './client'

export type UsageSum = {
  calls: number
  cached: number // 其中命中缓存的次数（没花钱）
  failed: number
  token_input: number
  token_output: number
  cost: number // 元，按单价估算
}
export type UsageDay = UsageSum & { date: string }
export type UsageFeature = UsageSum & { key: string; name: string }
export type UsageUser = UsageSum & {
  user_id: number | null // null = 账号或它的东西已经删掉了，合成一行
  username: string | null
  resumes: number
  applies: number
  interviews: number
  last_used: string | null
}
export type UsageFailure = {
  at: string // 2026-10-09T10:44:07
  feature: string
  username: string | null // null = 账号或它的东西已经删掉了
  reason: string // 归好类的一句话：余额不足、密钥无效、超时……
  detail: string // 原始报错（Key 样子的串后端已经盖掉）
}
/** total / features / users / failures 算的是选中的那一段：给了 day 就是那一天，否则是图上的整段 */
export type Usage = {
  days: number
  day: string | null
  today: string
  total: UsageSum
  window_cost: number
  today_cost: number
  by_day: UsageDay[]
  features: UsageFeature[]
  users: UsageUser[]
  failures: UsageFailure[] // 最近失败的几次，最多 20 条
  registered: number
  other_calls: number // 评测和脚本的调用，不算在上面
  other_cost: number
}
/** 图上画最近几天；0 = 从第一条记录起 */
export type UsageWindow = 7 | 30 | 0

export type Provider = {
  id: number // 0 = .env 里的那一家
  kind: string
  name: string
  base_url: string
  model: string
  key_hint: string // 只有开头和后四位
  price_in: number
  price_out: number
  active: boolean
  from_env: boolean
  key_ok: boolean // false = Key 读不出来了，要重新填
}
export type ProviderPreset = { key: string; name: string; base_url: string; model: string; price_in: number | null; price_out: number | null }
export type Providers = { current: Provider; others: Provider[]; presets: ProviderPreset[] }
export type ProviderDraft = { kind: string; base_url: string; model: string; api_key: string; price_in: number; price_out: number }
export type TestResult = { ok: boolean; message: string; latency_ms: number | null }
export type ProviderStatus = { available: boolean; reason: string | null; balance: string | null }

/** 检索用的向量 + 重排模型：只有一份配置。from_env = 用的是 .env 里的 */
export type Retrieval = { from_env: boolean; name: string; base_url: string; key_hint: string; embed_model: string; rerank_model: string }
/** api_key 给 null = 沿用现在的那把 */
export type RetrievalDraft = { base_url: string; api_key: string | null; embed_model: string; rerank_model: string }

export const adminApi = {
  usage: (days: UsageWindow, day?: string | null) => request<Usage>(`/admin/usage?days=${days}${day ? `&day=${day}` : ''}`),

  providers: () => request<Providers>('/admin/providers'),
  /** 现问一次现在用的这一家：能不能用、余额（只有 DeepSeek 查得到）。可能要几秒，页面先画出来再问 */
  providerStatus: () => request<ProviderStatus>('/admin/providers/status'),
  /** 表单里填的一条，保存之前先试：后端真调一次模型 */
  testDraft: (draft: ProviderDraft) => request<TestResult>('/admin/providers/test', { method: 'POST', body: draft }),
  testSaved: (id: number) => request<TestResult>(`/admin/providers/${id}/test`, { method: 'POST' }),
  /** 下面三个后端都会自己先试一次，连不上返回 40001，message 里是原因 */
  create: (draft: ProviderDraft) => request<Provider>('/admin/providers', { method: 'POST', body: draft }),
  changeKey: (id: number, apiKey: string) => request<null>(`/admin/providers/${id}/key`, { method: 'PUT', body: { api_key: apiKey } }),
  activate: (id: number) => request<null>(`/admin/providers/${id}/activate`, { method: 'POST' }),
  remove: (id: number) => request<null>(`/admin/providers/${id}`, { method: 'DELETE' }),

  retrieval: () => request<Retrieval>('/admin/retrieval'),
  /** 只问模型列表，不花钱：密钥对不对、连不连得上 */
  retrievalStatus: () => request<ProviderStatus>('/admin/retrieval/status'),
  /** 真调一次向量和重排。不给 draft = 试现在用的 */
  testRetrieval: (draft?: RetrievalDraft) => request<TestResult>('/admin/retrieval/test', { method: 'POST', body: draft }),
  /** 后端自己会先试，不通过返回 40001。向量模型换了的话，已经存着的面经切段会一起清掉 */
  saveRetrieval: (draft: RetrievalDraft) => request<Retrieval>('/admin/retrieval', { method: 'PUT', body: draft }),
  resetRetrieval: () => request<Retrieval>('/admin/retrieval', { method: 'DELETE' }),
}
