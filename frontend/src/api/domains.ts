// 对应后端 app/api/domain.py 的 DomainOut：工作台第一步「选方向」的下拉框，以及页面上对面试的称呼
import { request } from './client'

export type Domain = {
  key: string
  name: string
  icon: string // 两个字
  desc: string // 包含哪些岗位：后端 · 前端 · …
  rule_hint: string // 「简历按……诊断」
  interview_hint: string // 「模拟面试问……」
  interview_label: string // 技术面 / 运营面
  interviewer: string // 技术面试官 / 运营面试官
  sample_jd: { title: string; company: string; text: string }
}

export const domainsApi = {
  /** 不用登录；顺序就是下拉框里的顺序 */
  list: () => request<Domain[]>('/domains'),
}
