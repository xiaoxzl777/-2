// 配色：三套，领英蓝默认。选择记在 localStorage，<html data-pal> 决定用哪套（色板在 index.css 开头）。
// index.html 里有一小段脚本在渲染前就读出来设好（刷新不闪默认色），这里只管之后的切换。
import { create } from 'zustand'

export const PALETTES = [
  { key: 'linkedin', name: '领英蓝', desc: '默认 · 专业、清爽', bg: '#f4f2ee', accent: '#0a66c2' },
  { key: 'red', name: '朱红', desc: '像红笔批改过的简历', bg: '#fbfaf8', accent: '#c8341f' },
  { key: 'green', name: '墨绿', desc: '米白底，沉稳', bg: '#f2f0e9', accent: '#2d5e4c' },
] as const

export type PaletteKey = (typeof PALETTES)[number]['key']

const STORAGE_KEY = 'resume-ai.palette' // index.html 里读的是同一个
const DEFAULT: PaletteKey = 'linkedin'

function current(): PaletteKey {
  const v = document.documentElement.dataset.pal
  return PALETTES.some((p) => p.key === v) ? (v as PaletteKey) : DEFAULT
}

export const usePalette = create<{ key: PaletteKey; set: (key: PaletteKey) => void }>((set) => ({
  key: current(),
  set(key) {
    const root = document.documentElement
    root.classList.add('theming') // 颜色渐变过去，过后去掉，免得影响别的动画
    window.setTimeout(() => root.classList.remove('theming'), 420)
    if (key === DEFAULT) delete root.dataset.pal
    else root.dataset.pal = key
    try {
      localStorage.setItem(STORAGE_KEY, key)
    } catch {
      /* 存不下就只在这次打开时有效 */
    }
    set({ key })
  },
}))
