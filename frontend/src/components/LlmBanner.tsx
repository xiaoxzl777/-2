// 模型服务调不通（余额用完、密钥不对、连不上）时，登录后每个页面导航下面一条横幅；恢复后自动消失。
// 进页面问一次，之后每分钟问一次（后端也只存 1 分钟）。不拦按钮，只是让用户先知道会失败。样稿：docs/design/模型不可用提示预览.html
import { useEffect, useState } from 'react'
import { systemApi } from '../api/system'

const RECHECK_MS = 60_000
// 上一次的结论：每个页面都会重新挂载横幅，先按上次的显示，免得每换一页它都晚一拍弹出来、把内容往下推
let lastDown = false

export function LlmBanner() {
  const [down, setDown] = useState(lastDown)

  useEffect(() => {
    let alive = true
    const check = () => systemApi.llm()
      .then((r) => {
        lastDown = !r.available
        if (alive) setDown(lastDown)
      })
      .catch(() => { /* 后端本身连不上时页面另有提示，这里不管 */ })
    check()
    const timer = window.setInterval(check, RECHECK_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  if (!down) return null
  return (
    <div className="llm-down" role="status">
      <i className="i" aria-hidden="true">!</i>
      <span>
        <b>模型服务暂时不可用</b>
        投递分析、修改建议、模拟面试都要用到它，恢复之前会失败；以前的结果和诊断报告照常能看。恢复后这条提示会自动消失。
      </span>
    </div>
  )
}
