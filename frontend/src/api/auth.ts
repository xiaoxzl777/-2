// 对应后端 app/api/auth.py 与 app/schemas.py 的 UserOut / TokenOut
import { request } from './client'

export type User = {
  id: number
  username: string
  email: string | null
  role: string
  created_at: string
}

export type TokenOut = {
  access_token: string
  token_type: string
  expires_in: number // 秒
  user: User
}

export const authApi = {
  login: (username: string, password: string) =>
    request<TokenOut>('/auth/login', { method: 'POST', body: { username, password } }),

  /** 注册成功直接返回令牌，不用再登录一次 */
  register: (username: string, password: string, email?: string) =>
    request<TokenOut>('/auth/register', { method: 'POST', body: { username, password, email: email || null } }),

  me: () => request<User>('/auth/me'),

  /** 先输对当前密码；改完这台设备照常登录。当前密码不对返回 40001（不是 401，不会被当成登录失效） */
  changePassword: (oldPassword: string, newPassword: string) =>
    request<null>('/auth/password', { method: 'POST', body: { old_password: oldPassword, new_password: newPassword } }),
}

// 与后端 schemas._Credentials 的校验保持一致，提交前先在前端拦一道
export const USERNAME_RE = /^[A-Za-z0-9_一-鿿]{3,50}$/
export const PASSWORD_MIN = 6
export const PASSWORD_MAX = 64
export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
