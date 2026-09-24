// 所有后端请求的唯一出口：拼 /api/v1 前缀、带令牌、拆 {code, message, data} 信封、统一抛 ApiError。

export class ApiError extends Error {
  /** 后端错误码（40101 之类）；网络不通时为 0 */
  readonly code: number

  constructor(code: number, message: string) {
    super(message)
    this.code = code
  }
}

const TOKEN_KEY = 'resume-ai.token'

// localStorage 在隐私模式等情况下可能直接抛异常，读写都兜住
export const tokenStore = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* 存不下就只在本次会话里有效 */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* 同上 */
    }
  },
}

let onUnauthorized: (() => void) | null = null

/** 令牌失效（任意接口返回 401）时的回调，由 auth store 注册 */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

type Envelope<T> = { code: number; message: string; data: T }

export async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`

  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, '网络连接失败，请稍后重试')
  }

  let payload: Envelope<T> | null = null
  try {
    payload = (await res.json()) as Envelope<T>
  } catch {
    // 后端没起来时，开发代理 / nginx 返回的是非 JSON 的错误页
  }
  if (payload === null) throw new ApiError(res.status * 100, '服务暂时不可用，请确认后端已启动')

  if (!res.ok || payload.code !== 0) {
    if (res.status === 401 && token) onUnauthorized?.()
    throw new ApiError(payload.code, payload.message || '请求失败')
  }
  return payload.data
}
