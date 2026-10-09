// 通用方向（「其他」）的「结果可能不够准」提醒：选方向的说明框里、结果页分数卡底下各一处，文字是后端领域包的 note。
// 诊断报告里另有一份黑白的（.rpt-general）。样稿：docs/design/通用方向预览.html
export function GeneralNote({ text }: { text: string }) {
  return (
    <p className="gen-note">
      <i className="i" aria-hidden="true">!</i>
      <span>{text}</span>
    </p>
  )
}
