// 具体建议：对应后端 app/api/advice.py。点开一条问题 / 差距时现场生成，流式返回（POST + text/event-stream）：
//   delta {text} ×N → done {text, violation_count, …}（数字复检后的全文，以它为准）| error {code, message}
import { ApiError, openStream, sseEvents } from './client'

export type Advice = {
  text: string
  violation_count: number // 被换成【数值】的编造数字个数
  prompt_version: string
  model: string
  created_at: string
}

export const adviceApi = {
  findingPath: (findingId: number) => `/findings/${findingId}/advice`,
  gapPath: (reportId: number, requirementId: number) => `/match/${reportId}/items/${requirementId}/advice`,
}

/** 边生成边回调 onDelta，结束时返回复检后的完整建议；失败抛 ApiError */
export async function streamAdvice(path: string, onDelta: (text: string) => void): Promise<Advice> {
  const stream = await openStream(path, new AbortController().signal, 'POST')
  for await (const event of sseEvents(stream)) {
    if (event.name === 'delta') onDelta(String(event.data.text ?? ''))
    else if (event.name === 'done') return event.data as unknown as Advice
    else if (event.name === 'error') throw new ApiError(Number(event.data.code), String(event.data.message))
  }
  throw new ApiError(0, '连接中断了，请重试')
}
