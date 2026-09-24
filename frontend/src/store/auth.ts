// 登录状态。令牌存 localStorage；刷新页面时用 /auth/me 恢复用户，令牌失效就回到未登录。
import { create } from 'zustand'
import { authApi, type TokenOut, type User } from '../api/auth'
import { setUnauthorizedHandler, tokenStore } from '../api/client'

type Status = 'checking' | 'authed' | 'guest'

type AuthState = {
  user: User | null
  status: Status
  bootstrap: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, email?: string) => Promise<void>
  logout: () => void
}

export const useAuth = create<AuthState>((set) => {
  const signedIn = (out: TokenOut) => {
    tokenStore.set(out.access_token)
    set({ user: out.user, status: 'authed' })
  }
  const signedOut = () => {
    tokenStore.clear()
    set({ user: null, status: 'guest' })
  }
  setUnauthorizedHandler(signedOut)

  return {
    user: null,
    status: tokenStore.get() ? 'checking' : 'guest',

    async bootstrap() {
      if (!tokenStore.get()) return set({ status: 'guest' })
      try {
        set({ user: await authApi.me(), status: 'authed' })
      } catch {
        signedOut() // 过期、被篡改或后端不可用：都按未登录处理
      }
    },

    async login(username, password) {
      signedIn(await authApi.login(username, password))
    },

    async register(username, password, email) {
      signedIn(await authApi.register(username, password, email))
    },

    logout: signedOut,
  }
})
