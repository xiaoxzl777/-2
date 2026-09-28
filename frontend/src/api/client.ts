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

/** body 是 FormData（上传文件）时原样发送，由浏览器自己带 multipart 边界；其余按 JSON 发 */
export async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const isForm = options.body instanceof FormData
  if (options.body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`

  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
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

/** 带令牌打开一个流式响应（SSE）。EventSource 带不了请求头，也发不了 POST，所以用 fetch 读流；401 同样触发退出。body 按 JSON 发 */
export async function openStream(path: string, signal: AbortSignal, method = 'GET', body?: unknown): Promise<ReadableStream<Uint8Array>> {
  const headers: Record<string, string> = {}
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal })
  } catch (e) {
    if (signal.aborted) throw e
    throw new ApiError(0, '网络连接失败，请稍后重试')
  }
  if (res.status === 401 && token) onUnauthorized?.()
  if (!res.ok || !res.body) {
    // 还没开始流就被拒（404、409…）时，后端回的是普通的 {code, message}
    const payload = (await res.json().catch(() => null)) as Envelope<unknown> | null
    throw new ApiError(payload?.code ?? res.status * 100, payload?.message ?? '连接失败，请稍后重试')
  }
  return res.body
}

export type SseEvent = { name: string; data: Record<string, unknown> }

/** 把 SSE 字节流切成一个个事件，心跳注释行（": keep-alive"）跳过。onChunk：每收到一段数据就调一次，用来做"多久没动静"的判断 */
export async function* sseEvents(stream: ReadableStream<Uint8Array>, onChunk?: () => void): AsyncGenerator<SseEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    onChunk?.()
    buffer += decoder.decode(value, { stream: true })
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const event = parseEvent(buffer.slice(0, cut))
      buffer = buffer.slice(cut + 2)
      if (event) yield event
    }
  }
}

function parseEvent(block: string): SseEvent | null {
  let name = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  try {
    return { name, data: JSON.parse(data) as Record<string, unknown> }
  } catch {
    return null
  }
}
