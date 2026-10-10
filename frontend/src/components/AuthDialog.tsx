// 登录 / 注册弹窗：深色背景从点击位置圆形展开，卡片随后浮起。
import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { EMAIL_RE, PASSWORD_MAX, PASSWORD_MIN, USERNAME_RE } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../store/auth'
import { AuthDeco } from './AuthDeco'
import { useOverlay } from './useOverlay'

export type AuthMode = 'login' | 'register'
export type Origin = { x: number; y: number }

const RULE = `用户名 3–50 位，可用中英文、数字、下划线；密码至少 ${PASSWORD_MIN} 位`
type Field = 'username' | 'email' | 'password'

export function AuthDialog({ open, mode, origin, onModeChange, onClose }: {
  open: boolean
  mode: AuthMode
  origin: Origin | null
  onModeChange: (m: AuthMode) => void
  onClose: () => void
}) {
  const login = useAuth((s) => s.login)
  const register = useAuth((s) => s.register)
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [shaking, setShaking] = useState<Field | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const userRef = useRef<HTMLInputElement>(null)

  const isLogin = mode === 'login'

  // 打开时：锁滚动、Esc 关闭、关掉后焦点回到打开它的按钮（useOverlay）；展开动画播完后聚焦用户名
  useOverlay(open, onClose)
  useEffect(() => {
    if (!open) return
    setError(null)
    const focus = window.setTimeout(() => userRef.current?.focus(), 450)
    return () => clearTimeout(focus)
  }, [open])

  useEffect(() => { setError(null) }, [mode])

  const fail = (field: Field, message: string) => {
    // 先清掉再加回，连续输错时动画也能重新播放
    setShaking(null)
    requestAnimationFrame(() => setShaking(field))
    window.setTimeout(() => setShaking((f) => (f === field ? null : f)), 450)
    setError(message)
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (submitting) return
    const name = username.trim()
    if (!USERNAME_RE.test(name)) return fail('username', '用户名需 3–50 位，只能用中英文、数字或下划线')
    if (!isLogin && email && !EMAIL_RE.test(email.trim())) return fail('email', '邮箱格式不正确')
    if (password.length < PASSWORD_MIN) return fail('password', `密码至少 ${PASSWORD_MIN} 位`)
    // 后端用 bcrypt，按 UTF-8 字节数限长
    if (password.length > PASSWORD_MAX || new TextEncoder().encode(password).length > 72) return fail('password', '密码过长')

    setError(null)
    setSubmitting(true)
    try {
      if (isLogin) await login(name, password)
      else await register(name, password, email.trim() || undefined)
      setPassword('')
      onClose()
      navigate('/app')
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '出了点问题，请稍后重试'
      fail(err instanceof ApiError && err.code === 40901 ? 'username' : 'password', message)
    } finally {
      setSubmitting(false)
    }
  }

  const fieldClass = (f: Field) => `field ${shaking === f ? 'shake' : ''}`
  const style = origin ? ({ '--x': `${origin.x}px`, '--y': `${origin.y}px` } as CSSProperties) : undefined

  return (
    <div className={`auth ${open ? 'open' : ''}`} style={style} aria-hidden={!open}>
      <div className="auth-bg" onClick={onClose} />
      <AuthDeco open={open} />
      <form className="panel" onSubmit={onSubmit} noValidate role="dialog" aria-modal="true" aria-labelledby="auth-title">
        <div className="panel-head">
          <h3 id="auth-title">{isLogin ? '欢迎回来' : '创建账号'}</h3>
          <button type="button" className="x" onClick={onClose} aria-label="关闭" tabIndex={open ? 0 : -1}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" /></svg>
          </button>
        </div>

        <div className={`seg ${isLogin ? '' : 'reg'}`} role="tablist">
          <span className="knob" />
          <button type="button" role="tab" aria-selected={isLogin} className={isLogin ? 'on' : ''} onClick={() => onModeChange('login')} tabIndex={open ? 0 : -1}>登录</button>
          <button type="button" role="tab" aria-selected={!isLogin} className={isLogin ? '' : 'on'} onClick={() => onModeChange('register')} tabIndex={open ? 0 : -1}>注册</button>
        </div>

        <div className={fieldClass('username')}>
          <input id="auth-u" ref={userRef} value={username} onChange={(e) => setUsername(e.target.value)} placeholder=" " autoComplete="username" tabIndex={open ? 0 : -1} />
          <label htmlFor="auth-u">用户名</label>
        </div>
        <div className={`expand ${isLogin ? '' : 'open'}`}>
          <div>
            <div className={fieldClass('email')}>
              <input id="auth-e" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder=" " autoComplete="email" tabIndex={open && !isLogin ? 0 : -1} />
              <label htmlFor="auth-e">邮箱（选填）</label>
            </div>
          </div>
        </div>
        <div className={fieldClass('password')}>
          <input id="auth-p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder=" "
            autoComplete={isLogin ? 'current-password' : 'new-password'} tabIndex={open ? 0 : -1} />
          <label htmlFor="auth-p">密码</label>
        </div>

        <p className={`rule ${error ? 'err' : ''}`} role={error ? 'alert' : undefined}>{error ?? RULE}</p>

        <button type="submit" className="btn dark submit" disabled={submitting} tabIndex={open ? 0 : -1}>
          {submitting && <span className="spin" aria-hidden="true" />}
          {submitting ? (isLogin ? '登录中…' : '注册中…') : isLogin ? '登录' : '注册并进入'}
        </button>
      </form>
    </div>
  )
}
