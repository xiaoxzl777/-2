// 求职方向的列表：后端的静态配置，整个会话只取一次；各页面按岗位 / 面试的 domain 取名称和对面试的称呼。
import { useEffect } from 'react'
import { create } from 'zustand'
import { domainsApi, type Domain } from '../api/domains'

type State = { list: Domain[] | null; loading: boolean; load: () => Promise<void> }

const useStore = create<State>((set, get) => ({
  list: null,
  loading: false,
  async load() {
    if (get().list || get().loading) return
    set({ loading: true })
    try {
      set({ list: await domainsApi.list() })
    } catch {
      /* 取不到就留着 null，下次用到时再取 */
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

/** 某个方向。key 为空（老数据）或方向已下线时按第一个（默认方向）处理，和后端 get_domain 一致 */
export function useDomain(key: string | null | undefined): Domain | null {
  const list = useDomains()
  return list?.find((d) => d.key === key) ?? list?.[0] ?? null
}
