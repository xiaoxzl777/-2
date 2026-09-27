// 登录后各页左侧的大标题：标签 + 两行大字（逐行升起）+ 手绘下划线，同首页首屏
import type { ReactNode } from 'react'

/** 被手绘下划线标出的词 */
export function Mark({ children }: { children: ReactNode }) {
  return (
    <span className="mark">
      {children}
      <svg viewBox="0 0 300 22" preserveAspectRatio="none" aria-hidden="true"><path d="M4 16 C 80 4, 200 4, 296 12" /></svg>
    </span>
  )
}

export function Headline({ badge, label, lines }: { badge: string; label: ReactNode; lines: [ReactNode, ReactNode] }) {
  return (
    <>
      <span className="tag fade d1"><b>{badge}</b>{label}</span>
      <h1>
        <span className="line"><span>{lines[0]}</span></span>
        <span className="line"><span>{lines[1]}</span></span>
      </h1>
    </>
  )
}
