import { useEffect, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import ApplyReport from './pages/ApplyReport'
import ApplyResult from './pages/ApplyResult'
import Home from './pages/Home'
import Interview from './pages/Interview'
import InterviewReport from './pages/InterviewReport'
import InterviewSetup from './pages/InterviewSetup'
import MyApplies from './pages/MyApplies'
import MyResumes from './pages/MyResumes'
import Workbench from './pages/Workbench'
import { useAuth } from './store/auth'

/** 需要登录的页面：未登录带回首页并弹出登录框；自己点「退出登录」的只回首页，不弹 */
function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status)
  const leftByChoice = useAuth((s) => s.leftByChoice)
  if (status === 'checking') return <div className="splash">加载中…</div>
  if (status === 'guest') return <Navigate to={leftByChoice ? '/' : '/?login=1'} replace />
  return children
}

export default function App() {
  const bootstrap = useAuth((s) => s.bootstrap)
  useEffect(() => { void bootstrap() }, [bootstrap])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/app" element={<RequireAuth><Workbench /></RequireAuth>} />
        <Route path="/app/applies" element={<RequireAuth><MyApplies /></RequireAuth>} />
        <Route path="/app/resumes" element={<RequireAuth><MyResumes /></RequireAuth>} />
        <Route path="/app/apply/:id" element={<RequireAuth><ApplyResult /></RequireAuth>} />
        <Route path="/app/apply/:id/report" element={<RequireAuth><ApplyReport /></RequireAuth>} />
        <Route path="/app/apply/:id/interview" element={<RequireAuth><InterviewSetup /></RequireAuth>} />
        <Route path="/app/interview/:id" element={<RequireAuth><Interview /></RequireAuth>} />
        <Route path="/app/interview/:id/report" element={<RequireAuth><InterviewReport /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
