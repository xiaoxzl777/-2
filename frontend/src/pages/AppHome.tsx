// 登录后的落地页。工作台（贴 JD → 选简历 → 投递）做好之前先用这个占位。
import { useNavigate } from 'react-router-dom'
import { Backdrop, MagneticButton } from '../components/effects'
import { Nav } from '../components/Nav'
import { useAuth } from '../store/auth'

export default function AppHome() {
  const user = useAuth((s) => s.user)!
  const logout = useAuth((s) => s.logout)
  const navigate = useNavigate()

  const signOut = () => {
    logout()
    navigate('/')
  }

  return (
    <>
      <Backdrop />
      <Nav actions={
        <>
          <span className="user-chip"><span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span>{user.username}</span>
          <MagneticButton className="ghost" onClick={signOut}>退出登录</MagneticButton>
        </>
      } />
      <main className="wrap app-main">
        <div className="welcome fade">
          <h1>你好，{user.username}</h1>
          <p>登录成功。工作台还在搭建中，做好之后在这里完成下面三步：</p>
          <ol className="todo">
            <li><span>1</span>粘贴目标岗位 JD（或选内置岗位模板）</li>
            <li><span>2</span>上传简历，或选一份已上传的</li>
            <li><span>3</span>点「投递」，看初筛结果与改进建议</li>
          </ol>
          <MagneticButton className="dark" onClick={signOut}>退出登录</MagneticButton>
        </div>
      </main>
    </>
  )
}
