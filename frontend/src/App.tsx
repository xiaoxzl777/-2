import { lazy, Suspense, useEffect, type ReactNode } from 'react'
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

// 管理端只有管理员用得到：单独打包，普通用户不用下载
const AdminUsage = lazy(() => import('./pages/admin/Usage'))
const AdminSettings = lazy(() => import('./pages/admin/ModelSettings'))

const splash = <div className="splash">加载中…</div>

/** 需要登录的页面：未登录带回首页并弹出登录框；自己点「退出登录」的只回首页，不弹。管理员只看管理端 */
function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status)
  const leftByChoice = useAuth((s) => s.leftByChoice)
  const role = useAuth((s) => s.user?.role)
  if (status === 'checking') return splash
  if (status === 'guest') return <Navigate to={leftByChoice ? '/' : '/?login=1'} replace />
  if (role === 'admin') return <Navigate to="/admin" replace />
  return children
}

/** 管理端的页面：普通用户打开会被送回工作台（后端的接口另外有权限检查，这里只管页面去哪） */
function RequireAdmin({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status)
  const leftByChoice = useAuth((s) => s.leftByChoice)
  const role = useAuth((s) => s.user?.role)
  if (status === 'checking') return splash
  if (status === 'guest') return <Navigate to={leftByChoice ? '/' : '/?login=1'} replace />
  if (role !== 'admin') return <Navigate to="/app" replace />
  return <Suspense fallback={splash}>{children}</Suspense>
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
        <Route path="/admin" element={<RequireAdmin><AdminUsage /></RequireAdmin>} />
        <Route path="/admin/settings" element={<RequireAdmin><AdminSettings /></RequireAdmin>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
