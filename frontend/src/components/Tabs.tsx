// 分段切换：几个选项等宽，底下的滑块跟着选中项弹过去
import type { CSSProperties, ReactNode } from 'react'

export function Tabs<K extends string>({ tabs, value, onChange }: {
  tabs: { key: K; label: ReactNode }[]
  value: K
  onChange: (key: K) => void
}) {
  const index = tabs.findIndex((t) => t.key === value)
  return (
    <div className="tabs" role="tablist" style={{ '--n': tabs.length, '--i': index } as CSSProperties}>
      <span className="knob" aria-hidden="true" />
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" aria-selected={t.key === value}
          className={t.key === value ? 'on' : ''} onClick={() => onChange(t.key)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}
