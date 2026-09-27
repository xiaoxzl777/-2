// 首页：介绍 + 可玩的演示 + 登录 / 注册入口
import { useCallback, useEffect, useState, type MouseEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AuthDialog, type AuthMode, type Origin } from '../components/AuthDialog'
import { Backdrop, MagneticButton, Reveal } from '../components/effects'
import { Nav } from '../components/Nav'
import { ResumeDemo } from '../components/ResumeDemo'
import { useAuth } from '../store/auth'

const STEPS = [
  { title: '上传简历', desc: '上传 PDF 简历。两栏排版也能按正确顺序读出来，之后所有的问题和依据都能在原文里找到出处。' },
  { title: '贴 JD，看初筛', desc: '把岗位要求拆成一条条，逐条对照简历：满足、部分满足还是缺失，每条都附简历里的原话作依据。' },
  { title: '模拟面试', desc: '先技术面再 HR 面，题目围绕你的简历和这个岗位出；答完一题会追问，结束后给一份完整的面试报告。' },
]

const CHAT = [
  { who: 'ai', text: '你提到用 Redis 把接口从 800ms 降到 120ms。缓存和数据库的数据不一致时，你是怎么处理的？' },
  { who: 'me', text: '先更新数据库，再删除缓存；删除失败的话放进重试队列……' },
  { who: 'eval', text: '' },
  { who: 'typing', text: '' },
] as const

export default function Home() {
  const user = useAuth((s) => s.user)
  const [params, setParams] = useSearchParams()
  const [auth, setAuth] = useState<{ open: boolean; mode: AuthMode; origin: Origin | null }>({ open: false, mode: 'login', origin: null })
  const [activeStep, setActiveStep] = useState(0)
  const [chatShown, setChatShown] = useState(0)
  const [playSignal, setPlaySignal] = useState(0)

  const openAuth = (mode: AuthMode) => (e?: MouseEvent) =>
    setAuth({ open: true, mode, origin: e ? { x: e.clientX, y: e.clientY } : null })
  const closeAuth = useCallback(() => setAuth((a) => ({ ...a, open: false })), [])

  // 未登录访问 /app 会被带回 /?login=1，这里自动弹出登录框
  useEffect(() => {
    if (params.get('login') !== '1') return
    setAuth({ open: true, mode: 'login', origin: null })
    params.delete('login')
    setParams(params, { replace: true })
  }, [params, setParams])

  const playChat = () => {
    CHAT.forEach((_, i) => window.setTimeout(() => setChatShown(i + 1), 650 * (i + 1)))
  }

  const playDemo = () => {
    document.getElementById('demo')?.scrollIntoView({ behavior: 'smooth' })
    window.setTimeout(() => setPlaySignal((n) => n + 1), 300)
  }

  return (
    <>
      <Backdrop />
      <Nav
        links={<><a href="#demo">试一试</a><a href="#steps">怎么用</a><a href="#interview">模拟面试</a></>}
        actions={user ? (
          <Link to="/app" className="btn dark">进入工作台 <span className="arrow">→</span></Link>
        ) : (
          <>
            <MagneticButton className="ghost" onClick={openAuth('login')}>登录</MagneticButton>
            <MagneticButton className="dark" onClick={openAuth('register')}>注册</MagneticButton>
          </>
        )}
      />

      <main>
        <div className="wrap">
          <div className="hero" id="demo">
            <div>
              <span className="tag fade"><b>毕设作品</b>简历诊断 · 岗位初筛 · 模拟面试</span>
              <h1>
                <span className="line"><span>投之前，先让简历</span></span>
                <span className="line"><span>
                  <span className="mark">过一遍初筛
                    <svg viewBox="0 0 300 22" preserveAspectRatio="none" aria-hidden="true"><path d="M4 16 C 80 4, 200 4, 296 12" /></svg>
                  </span>。
                </span></span>
              </h1>
              <p className="sub fade d2">贴上想投的岗位，看看简历哪里不符合要求、哪句话写得太虚，再按这个岗位练一场技术面和 HR 面。</p>
              <div className="cta fade d3">
                {user ? (
                  <Link to="/app" className="btn accent lg">进入工作台 <span className="arrow">→</span></Link>
                ) : (
                  <MagneticButton className="accent lg" onClick={openAuth('register')}>开始使用 <span className="arrow">→</span></MagneticButton>
                )}
                <MagneticButton className="outline lg" onClick={playDemo}>先看演示</MagneticButton>
              </div>
            </div>
            <ResumeDemo playSignal={playSignal} />
          </div>
        </div>

        <section className="section" id="steps">
          <div className="wrap">
            <Reveal>
              <div className="eyebrow">怎么用</div>
              <h2>三步，从一份简历走到一场面试。</h2>
            </Reveal>
            <Reveal className="steps">
              {STEPS.map((s, i) => (
                <div key={s.title} className={`step ${i === activeStep ? 'active' : ''}`} onMouseEnter={() => setActiveStep(i)}>
                  <span className="no">{String(i + 1).padStart(2, '0')}</span>
                  <div><h3>{s.title}</h3><p>{s.desc}</p></div>
                </div>
              ))}
            </Reveal>
          </div>
        </section>

        <section className="section" id="interview">
          <div className="wrap chat-wrap">
            <Reveal>
              <div className="eyebrow">模拟面试</div>
              <h2>面试官会顺着你的简历追问。</h2>
              <p className="sub">问题从你的项目和岗位要求里来，不是题库随机抽。每题的评分都会引用你回答里的原话，说清楚好在哪、差在哪。</p>
            </Reveal>
            <Reveal className="chat" onReveal={playChat}>
              <div className="chat-top"><span className="pill">技术面</span>第 2 题 · 后端开发 · 示例</div>
              {CHAT.map((m, i) => {
                const show = i < chatShown ? 'show' : ''
                if (m.who === 'eval') return (
                  <div key={i} className={`msg eval ${show}`}>评分 <b>4 / 5</b> · 依据：「先更新数据库，再删除缓存」—— 思路正确，可以补充延迟双删的取舍。</div>
                )
                if (m.who === 'typing') return (
                  <div key={i} className={`msg ai ${show}`} aria-label="面试官正在输入"><span className="typing"><i /><i /><i /></span></div>
                )
                return <div key={i} className={`msg ${m.who} ${show}`}>{m.text}</div>
              })}
            </Reveal>
          </div>
        </section>

        <Reveal className="wrap end">
          <h2>下一次投递之前，先来这里过一遍。</h2>
          {user ? (
            <Link to="/app" className="btn accent lg">进入工作台 <span className="arrow">→</span></Link>
          ) : (
            <MagneticButton className="accent lg" onClick={openAuth('register')}>免费注册 <span className="arrow">→</span></MagneticButton>
          )}
        </Reveal>
      </main>

      <footer className="footer"><div className="wrap">求职辅助 · 本科毕业设计</div></footer>

      <AuthDialog
        open={auth.open}
        mode={auth.mode}
        origin={auth.origin}
        onModeChange={(mode) => setAuth((a) => ({ ...a, mode }))}
        onClose={closeAuth}
      />
    </>
  )
}
