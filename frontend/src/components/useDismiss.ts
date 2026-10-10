// 下拉菜单打开时：点菜单外面、按 Esc 就收起。配色菜单、方向下拉框、头像菜单共用（原来各写了一遍，一字不差）。
import { useEffect, useRef, type RefObject } from 'react'

export function useDismiss(box: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  const latest = useRef(close)
  latest.current = close

  useEffect(() => {
    if (!open) return
    const outside = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) latest.current() }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') latest.current() }
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', esc)
    }
  }, [box, open])
}
