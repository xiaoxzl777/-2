// 投递、面试、报告不存在（或加载失败）时的整屏：「这次投递 找不到了」+ 原因 + 回到工作台
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { MagneticButton } from './effects'
import { Headline, Mark } from './Headline'

/** 不存在（40401）时用 fallback 那句话，其余错误照实显示后端给的原因 */
export function notFoundText(err: unknown, fallback: string): string {
  return err instanceof ApiError && err.code !== 40401 ? err.message : fallback
}

export function NotFound({ badge, what, message }: { badge: string; what: string; message: string }) {
  const navigate = useNavigate()
  return (
    <section className="screen">
      <div>
        <Headline badge={badge} label="—" lines={[what, <>找<Mark>不到</Mark>了。</>]} />
        <p className="sub fade d2">{message}</p>
        <div className="cta fade d3">
          <MagneticButton className="accent lg" onClick={() => navigate('/app')}>回到工作台 <span className="arrow">→</span></MagneticButton>
        </div>
      </div>
    </section>
  )
}
