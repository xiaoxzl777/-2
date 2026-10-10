// 弹层打开期间共用的几件事（登录弹窗、改密码弹窗、两个原文抽屉）：
// 锁住背后页面的滚动；Esc 关闭；给了 focusRef 就在打开后把焦点放进去（不然 Tab 会先走遍遮罩后面的页面）；
// 关掉后把焦点还给打开它的那个按钮（它还在页面上、还能被 Tab 到的话）。
import { useEffect, useRef, type RefObject } from 'react'

export function useOverlay(open: boolean, onClose: () => void, focusRef?: RefObject<HTMLElement | null>) {
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    if (!open) return
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close.current() }
    window.addEventListener('keydown', onKey)
    const timer = focusRef ? window.setTimeout(() => focusRef.current?.focus(), 60) : 0
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
      window.clearTimeout(timer)
      // 打开它的按钮可能已经不在了（登录成功换了页面）或者收起来了（菜单项）：那就不还
      if (opener?.isConnected && opener.tabIndex >= 0 && opener.offsetParent !== null) opener.focus()
    }
  }, [open, focusRef])
}
