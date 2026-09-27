// 具体建议：组件挂载（= 用户点开了这一条）时开始生成，一个字一个字显示；生成过的直接显示。
// 【】里是留给用户按实际填写的占位，标上颜色；【改成】那一行生成完可以一键复制。
import { useEffect, useState, type ReactNode } from 'react'
import type { Advice } from '../api/advice'
import { ensureAdvice, useAdviceStore } from '../store/advice'

export type AdviceSource = {
  key: string // 列表和原文纸面共用同一个 key，同一条只生成一次
  path: string
  cached: Advice | null // 接口里已经带回来的（以前生成过）
  kind: 'finding' | 'gap'
  fallback?: string | null // 生成失败时先给看的通用建议（规则的固定模板）
}

const SECTION = /【(问题|改成|为什么|考察什么|怎么补|面试怎么答)】/g

/** 按【段标题】切开；模型没按格式输出时整段作为一段 */
function sections(text: string): [string, string][] {
  const parts = text.split(SECTION)
  if (parts.length === 1) return text.trim() ? [['', text.trim()]] : []
  const out: [string, string][] = []
  for (let i = 1; i < parts.length; i += 2) out.push([parts[i], (parts[i + 1] ?? '').trim()])
  return out
}

/** 最外层的【…】包成占位高亮（可以嵌套）；还没写完的半个占位先按普通文字显示 */
function withPlaceholders(s: string): ReactNode[] {
  const out: ReactNode[] = []
  let buf = ''
  let depth = 0
  for (const ch of s) {
    if (ch === '【') {
      if (depth === 0 && buf) { out.push(buf); buf = '' }
      depth++
      buf += ch
      continue
    }
    buf += ch
    if (ch === '】' && depth > 0 && --depth === 0) {
      out.push(<span key={out.length} className="ph">{buf}</span>)
      buf = ''
    }
  }
  if (buf) out.push(buf)
  return out
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'ok' | 'fail'>('idle')
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setState('ok')
    } catch {
      setState('fail')
    }
  }
  return <button type="button" className="copy" onClick={() => void copy()}>{state === 'ok' ? '已复制' : state === 'fail' ? '复制失败，请手动选中' : '复制'}</button>
}

export function AdviceBlock({ source }: { source: AdviceSource }) {
  const entry = useAdviceStore((s) => s.entries[source.key])
  useEffect(() => { ensureAdvice(source.key, source.path, source.cached) }, [source.key]) // 同一个 key 的 path / cached 不会变

  const what = source.kind === 'gap' ? '条要求' : '一句'
  const done = entry?.status === 'done'
  // 流到一半时末尾可能是半个段标题（如「【改」），先不显示
  const rows = entry && entry.status !== 'error' ? sections(done ? entry.text : entry.text.replace(/【[^】]{0,5}$/, '')) : []

  let body: ReactNode
  if (entry?.status === 'error') {
    body = (
      <>
        <p className="advice-err">{entry.error}<button type="button" className="copy" onClick={() => ensureAdvice(source.key, source.path)}>重试</button></p>
        {source.fallback && <p><span className="k">通用建议</span><span>{source.fallback}</span></p>}
      </>
    )
  } else if (rows.length === 0) {
    body = <p className="thinking">正在针对这{what}写建议<span className="wait-dots" /></p>
  } else {
    body = rows.map(([label, value], i) => (
      <p key={label || i}>
        {label && <span className="k">{label}</span>}
        <span className={label === '改成' ? 'rewrite' : undefined}>
          {withPlaceholders(value)}
          {!done && i === rows.length - 1 && <i className="caret" aria-hidden="true" />}
          {done && label === '改成' && <CopyButton text={value} />}
        </span>
      </p>
    ))
  }

  return (
    <div className="advice" aria-live="polite" aria-busy={!done}>
      <div className="advice-head">针对这{what}的建议<span>DeepSeek 生成</span></div>
      {body}
      {done && (
        <div className="advice-foot">
          {source.kind === 'gap' ? '「如果你做过」的写法，只在确实做过时再用；【】里按实际填写' : '【】里的内容按你的实际情况填写，别照抄'}
        </div>
      )}
    </div>
  )
}
