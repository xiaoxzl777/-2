// 对应后端 app/api/system.py：模型服务现在能不能用（登录后页面顶上的横幅）
import { request } from './client'

export const systemApi = {
  /** 不用登录；后端问 DeepSeek 的余额接口，结论存 1 分钟 */
  llm: () => request<{ available: boolean }>('/system/llm'),
}
