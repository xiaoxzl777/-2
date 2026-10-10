// 对应后端 app/api/system.py：模型服务现在能不能用（登录后页面顶上的横幅）
import { request } from './client'

export const systemApi = {
  /** 不用登录；后端问现在用的那一家模型服务（DeepSeek 问余额接口，别家问模型列表），结论存 1 分钟 */
  llm: () => request<{ available: boolean }>('/system/llm'),
}
