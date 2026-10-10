// 求职方向的列表：后端的静态配置，整个会话只取一次；各页面按岗位 / 面试的 domain 取名称和对面试的称呼。
import { useEffect } from 'react'
import { create } from 'zustand'
import { domainsApi, type Domain } from '../api/domains'

type State = { list: Domain[] | null; loading: boolean; load: () => Promise<void> }

const RETRY_MS = 3000

const useStore = create<State>((set, get) => ({
  list: null,
  loading: false,
  async load() {
    if (get().list || get().loading) return
    set({ loading: true })
    try {
      set({ list: await domainsApi.list() })
    } catch {
      // 取不到（后端在重启、网络抖了）：过几秒自己再取，和登录状态的恢复同一个做法。不然工作台第一步的下拉框就一直停在「加载中…」
      window.setTimeout(() => void get().load(), RETRY_MS)
    } finally {
      set({ loading: false })
    }
  },
}))

/** 全部方向；还没取到时为 null */
export function useDomains(): Domain[] | null {
  const list = useStore((s) => s.list)
  const load = useStore((s) => s.load)
  useEffect(() => { void load() }, [load])
  return list
}

/** 某个方向。key 为空（老数据）或方向已下线时按第一个（默认方向）处理，和后端 get_domain 一致。
 *  key 是 undefined = 数据还没回来：返回 null、先不显示，不然非计算机方向的面试页会先闪一下「技术面」再换成「专业面」 */
export function useDomain(key: string | null | undefined): Domain | null {
  const list = useDomains()
  if (key === undefined) return null
  return list?.find((d) => d.key === key) ?? list?.[0] ?? null
}
