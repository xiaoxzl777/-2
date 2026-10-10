import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// 文件拖偏了、没落在上传框里：浏览器默认会在当前标签页打开这个文件，整个页面被替换，选好的方向、没解析完的 JD 全丢。
// 全局挡掉这个默认行为。上传框自己的处理先跑、照常收文件；落在别处的，鼠标显示成「不能放」
window.addEventListener('dragover', (e) => {
  if (e.defaultPrevented) return // 落在上传框上：它自己处理了
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'none'
})
window.addEventListener('drop', (e) => e.preventDefault())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
