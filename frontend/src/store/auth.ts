// 登录状态。令牌存 localStorage；刷新页面时用 /auth/me 恢复用户，令牌失效就回到未登录。
import { create } from 'zustand'
import { authApi, type TokenOut, type User } from '../api/auth'
import { setUnauthorizedHandler, tokenStore } from '../api/client'

type Status = 'checking' | 'authed' | 'guest'

const RETRY_MS = 3000

type AuthState = {
  user: User | null
  status: Status
  leftByChoice: boolean // 是自己点的「退出登录」（回首页就行），不是登录失效被踢出来的（那种要弹登录框）
  bootstrap: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, email?: string) => Promise<void>
  logout: () => void
}

export const useAuth = create<AuthState>((set, get) => {
  const signedIn = (out: TokenOut) => {
    tokenStore.set(out.access_token)
    set({ user: out.user, status: 'authed', leftByChoice: false })
  }
  const signedOut = () => {
    tokenStore.clear()
    set({ user: null, status: 'guest' })
  }
  setUnauthorizedHandler(signedOut)

  return {
    user: null,
    status: tokenStore.get() ? 'checking' : 'guest',
    leftByChoice: false,

    async bootstrap() {
      if (!tokenStore.get()) return set({ status: 'guest' })
      try {
        set({ user: await authApi.me(), status: 'authed' })
      } catch {
        // 令牌过期或被篡改（401）时 request 里已经退出登录。令牌还在，说明是后端没起来或断网（开发时重启后端常见）：
        // 令牌留着，过几秒再试，期间停在"加载中"，免得每重启一次后端就得重新登录
        if (tokenStore.get()) setTimeout(() => void get().bootstrap(), RETRY_MS)
      }
    },

    async login(username, password) {
      signedIn(await authApi.login(username, password))
    },

    async register(username, password, email) {
      signedIn(await authApi.register(username, password, email))
    },

    logout() {
      set({ leftByChoice: true }) // 先记下，RequireAuth 看到未登录时就不带 ?login=1
      signedOut()
    },
  }
})
