// 列表没取到（网络抖了、后端在重启）：和「还没有」分开说，给一个「再试一次」。工作台的岗位列表、简历列表用。
export function LoadFailed({ what, onRetry, gap = false }: { what: string; onRetry: () => void; gap?: boolean }) {
  return (
    <p className={`empty${gap ? ' jp-list-gap' : ''}`} role="alert">
      {what}没取到，可能是网络问题。<button type="button" className="link" onClick={onRetry}>再试一次</button>
    </p>
  )
}
