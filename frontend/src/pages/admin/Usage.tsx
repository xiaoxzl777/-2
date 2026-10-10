// 管理端 · 模型用量：/admin。每调一次大模型后端记一笔，这里按时间、功能、用户汇总（只算用户操作产生的）。
// 右上角选今天 / 近 7 天 / 近 30 天 / 全部；点图上一根柱子，四个数、两张表和「最近失败」只算那一天，再点一次看回整段。
// 手感和用户端一套：大标题逐行升起，卡片一张接一张进场，数字滚过去，柱子长出来。样稿：docs/design/管理端用量预览.html
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { adminApi, type Usage, type UsageDay, type UsageWindow } from '../../api/admin'
import { ApiError } from '../../api/client'
import { AdminShell } from '../../components/AdminShell'
import { useTween } from '../../components/effects'
import { Headline, Mark } from '../../components/Headline'
import { Tabs } from '../../components/Tabs'

type Range = 'today' | '7' | '30' | '0'
const RANGES: { key: Range; label: string }[] = [{ key: 'today', label: '今天' }, { key: '7', label: '近 7 天' }, { key: '30', label: '近 30 天' }, { key: '0', label: '全部' }]
const WIN_NAME: Record<UsageWindow, string> = { 7: '近 7 天', 30: '近 30 天', 0: '全部' }
type Measure = 'cost' | 'tok'
const MEASURES: { key: Measure; label: string }[] = [{ key: 'cost', label: '花费' }, { key: 'tok', label: 'Token' }]

const cost = (v: number) => `¥${v.toFixed(v >= 10 ? 2 : 3)}`
const int = (n: number) => Math.round(n).toLocaleString('en-US')
const wan = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : int(n))
const parts = (iso: string) => iso.split('-').map(Number) as [number, number, number]
const monthDay = (iso: string) => iso.slice(5) // 2026-10-06 → 10-06
const dateText = (iso: string) => { const [, m, d] = parts(iso); return `${m} 月 ${d} 日` }
const tokens = (x: { token_input: number; token_output: number }) => x.token_input + x.token_output
const nth = (i: number) => ({ '--i': i }) as CSSProperties // 进场的先后
/** 失败的时间：2026-10-09T10:44:07 → 「今天 10:44」或「10-09 10:44」 */
const clock = (iso: string, today: string) => `${iso.slice(0, 10) === today ? '今天' : iso.slice(5, 10)} ${iso.slice(11, 16)}`

/** 距今天几天：今天 / 昨天 / N 天前。两个都是 YYYY-MM-DD，按本地日期算 */
function ago(iso: string, today: string): string {
  const at = (s: string) => { const [y, m, d] = parts(s); return new Date(y, m - 1, d).getTime() }
  const n = Math.round((at(today) - at(iso)) / 86400000)
  return n <= 0 ? '今天' : n === 1 ? '昨天' : `${n} 天前`
}

/** 纵轴上限取一个好读的数 */
function niceMax(v: number): number {
  if (v <= 0) return 1
  const mag = 10 ** Math.floor(Math.log10(v))
  return ([1, 2, 3, 4, 5, 6, 8, 10].find((m) => v <= m * mag * 1.0001) ?? 10) * mag
}

export default function AdminUsage() {
  const [win, setWin] = useState<UsageWindow>(7)
  const [day, setDay] = useState<string | null>(null) // 只看哪一天；null = 看整段
  const [measure, setMeasure] = useState<Measure>('cost')
  const [data, setData] = useState<Usage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [again, setAgain] = useState(0)

  useEffect(() => {
    let stale = false
    adminApi.usage(win, day)
      .then((d) => { if (!stale) { setData(d); setError(null) } })
      .catch((e) => { if (!stale) setError(e instanceof ApiError ? e.message : '没取到，请稍后再试') })
    return () => { stale = true } // 连着点了几下：只认最后一次的结果
  }, [win, day, again])

  const pick = (key: Range) => {
    if (key !== 'today') { setWin(Number(key) as UsageWindow); setDay(null); return }
    const now = new Date()
    const local = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    if (win === 0) setWin(7) // 今天：图上留着最近几天，好对比
    setDay(data?.today ?? local)
  }
  const range: Range | null = day === null ? (String(win) as Range) : day === data?.today ? 'today' : null

  return (
    <AdminShell>
      <div className="adm-page">
        <div className="adm-head">
          <div>
            <Headline badge="管理端" label="模型用量" lines={['每一次调用，', <>都记了<Mark>一笔</Mark>。</>]} />
            <p className="adm-sub fade d2">这里只算用户操作产生的调用：上传简历、贴岗位、投递、要建议、模拟面试。</p>
          </div>
          <div className="fade d3"><Tabs tabs={RANGES} value={range} onChange={pick} /></div>
        </div>

        {error && !data && <p className="adm-fail-box" role="alert">{error} <button type="button" className="link" onClick={() => setAgain((n) => n + 1)}>再试一次</button></p>}
        {!error && !data && <p className="adm-loading">加载中…</p>}
        {data && <Board data={data} win={win} measure={measure} onMeasure={setMeasure} onDay={setDay} error={error} />}
      </div>
    </AdminShell>
  )
}

/** 会滚的数：从现在显示的值缓动到新的值 */
function Num({ value, fmt }: { value: number; fmt: (v: number) => string }) {
  return <>{fmt(useTween(value))}</>
}

function Board({ data, win, measure, onMeasure, onDay, error }: {
  data: Usage; win: UsageWindow; measure: Measure; onMeasure: (m: Measure) => void; onDay: (day: string | null) => void; error: string | null
}) {
  const { total, day } = data
  const one = day !== null
  const span = one ? '这一天' : '这段时间'
  const top = data.features.reduce((m, f) => Math.max(m, f.cost), 0)
  const rank = new Map([...data.features].sort((a, b) => b.cost - a.cost).map((f, i) => [f.key, i])) // 按花费排，行本身不挪（条的宽度才有过渡）
  const active = data.users.filter((u) => u.user_id !== null).length
  const allTokens = tokens(total)

  return (
    <>
      {/* 现在看的是哪一段：一直占着这一行，切换时下面的内容不跳 */}
      <p className="adm-scope fade d3" aria-live="polite">
        {one
          ? <><span>只看 <b>{dateText(day)}</b>{day === data.today ? '（今天）' : ''}这一天</span><button type="button" onClick={() => onDay(null)}>看回{WIN_NAME[win]}</button></>
          : <span><b>{WIN_NAME[win]}</b>的合计</span>}
        {error && <span className="adm-stale" role="alert">刚才没刷新成功：{error}</span>}
      </p>

      <section className="adm-tiles" aria-label="汇总">
        <div className="adm-card adm-tile adm-in" style={nth(0)}>
          <div className="k">花费（估算）</div><div className="v"><Num value={total.cost} fmt={cost} /></div>
          <div className="s">{one ? `占${WIN_NAME[win]}的 ${data.window_cost ? Math.round((100 * total.cost) / data.window_cost) : 0}%` : `今天 ${cost(data.today_cost)}`}</div>
        </div>
        <div className="adm-card adm-tile adm-in" style={nth(1)}>
          <div className="k">Token</div>
          <div className="v">{allTokens >= 10000 ? <><Num value={allTokens / 10000} fmt={(v) => v.toFixed(1)} /><small>万</small></> : <Num value={allTokens} fmt={int} />}</div>
          <div className="s">输入 {wan(total.token_input)} · 输出 {wan(total.token_output)}</div>
        </div>
        <div className="adm-card adm-tile adm-in" style={nth(2)}>
          <div className="k">调用次数</div><div className="v"><Num value={total.calls} fmt={int} /></div>
          <div className="s">其中 {int(total.cached)} 次命中缓存，没花钱</div>
        </div>
        <div className="adm-card adm-tile adm-in" style={nth(3)}>
          <div className="k">失败</div><div className="v"><Num value={total.failed} fmt={int} /><small>次</small></div>
          <div className="s">占 {total.calls ? ((100 * total.failed) / total.calls).toFixed(1) : '0.0'}%
            {total.failed > 0 && <> · <button type="button" className="adm-tile-link" onClick={() => document.getElementById('adm-fails')?.scrollIntoView({ behavior: 'smooth' })}>看原因 ↓</button></>}
          </div>
        </div>
      </section>

      <section className="adm-row">
        <div className="adm-card adm-box adm-fill adm-in" style={nth(4)}>
          <div className="adm-box-head">
            <h2>{measure === 'tok' ? '每天的 token' : '每天的花费'}</h2>
            <div className="adm-tabs-sm"><Tabs tabs={MEASURES} value={measure} onChange={onMeasure} /></div>
          </div>
          <p className="adm-note">点一根柱子，整页只看那一天；再点一次看回来</p>
          <Chart days={data.by_day} win={win} picked={day} measure={measure} onPick={(d) => onDay(d === day ? null : d)} />
        </div>
        <div className="adm-card adm-box adm-in" style={nth(5)}>
          <h2>按功能</h2>
          <p className="adm-note">钱主要花在哪一步</p>
          <ul className="adm-feat">
            {data.features.map((f) => (
              <li key={f.key} style={{ order: rank.get(f.key) }}>
                <span className="n">{f.name}</span><span className="c">{cost(f.cost)}</span>
                <span className="d">{int(f.calls)} 次 · {wan(tokens(f))} token</span>
                <span className="p">{total.cost ? Math.round((100 * f.cost) / total.cost) : 0}%</span>
                <span className="t"><i style={{ width: `${top ? (100 * f.cost) / top : 0}%`, ...nth(rank.get(f.key) ?? 0) }} /></span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="adm-card adm-box adm-users adm-in" style={nth(6)}>
        <div className="adm-box-head">
          <h2>按用户</h2>
          <p className="adm-note adm-note-side">{span} {active} 人用过 · 共 {data.registered} 人注册 · 按花费从高到低</p>
        </div>
        <p className="adm-swipe">表格可以左右滑动</p>
        <div className="adm-scroll">
          <table className="adm-table">
            <thead><tr><th>用户</th><th>花费</th><th>输入 token</th><th>输出 token</th><th>调用</th><th>失败</th><th>简历</th><th>投递</th><th>面试</th><th>最近使用</th></tr></thead>
            <tbody>
              {data.users.map((u, i) => {
                const gone = u.user_id === null
                return (
                  <tr key={u.user_id ?? 'gone'} style={nth(i)}>
                    <td>{gone ? <span className="adm-gone">已删除的账号</span> : <span className="adm-who"><i>{u.username!.slice(0, 1).toUpperCase()}</i>{u.username}</span>}</td>
                    <td><b>{cost(u.cost)}</b></td><td>{int(u.token_input)}</td><td>{int(u.token_output)}</td><td>{int(u.calls)}</td>
                    <td>{u.failed ? <span className="adm-fail">{u.failed}</span> : <span className="adm-zero">0</span>}</td>
                    <td>{gone ? '—' : u.resumes}</td><td>{gone ? '—' : u.applies}</td><td>{gone ? '—' : u.interviews}</td>
                    <td>{gone || !u.last_used ? '—' : ago(u.last_used, data.today)}</td>
                  </tr>
                )
              })}
              {data.users.length === 0 && <tr><td colSpan={10} className="adm-none">{span}没有人用</td></tr>}
            </tbody>
            {data.users.length > 0 && (
              <tfoot><tr><td>合计</td><td>{cost(total.cost)}</td><td>{int(total.token_input)}</td><td>{int(total.token_output)}</td><td>{int(total.calls)}</td><td>{int(total.failed)}</td><td /><td /><td /><td /></tr></tfoot>
            )}
          </table>
        </div>
      </section>

      <Failures data={data} span={span} />

      {data.other_calls > 0 && <p className="adm-extra">评测脚本和开发时跑的脚本另有 {int(data.other_calls)} 次调用（约 {cost(data.other_cost)}），没有算在上面。</p>}
    </>
  )
}

/** 最近失败的几次调用：什么时候、哪个功能、谁的、为什么。点一条展开看原始报错 */
function Failures({ data, span }: { data: Usage; span: string }) {
  const [open, setOpen] = useState<number | null>(null)
  const { failures, total } = data
  useEffect(() => setOpen(null), [failures]) // 换了时间范围：展开的那条收起

  return (
    <section id="adm-fails" className="adm-card adm-box adm-fails adm-in" style={nth(7)}>
      <div className="adm-box-head">
        <h2>最近失败</h2>
        {failures.length > 0 && (
          <p className="adm-note adm-note-side">
            {total.failed > failures.length ? `${span}共 ${total.failed} 次失败，这里列最近的 ${failures.length} 次` : `${span}的 ${total.failed} 次失败都在这里`} · 点一条看原始报错
          </p>
        )}
      </div>
      {failures.length === 0 ? <p className="adm-fails-none">{span}没有失败的调用。</p> : (
        <ul className="adm-fail-list">
          {failures.map((f, i) => (
            <li key={`${f.at}:${i}`} style={nth(i)}>
              <button type="button" className="adm-fail-row" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
                <span className="at">{clock(f.at, data.today)}</span>
                <span className="ft">{f.feature}</span>
                <span className="who">{f.username ?? '已删除的账号'}</span>
                <span className="why">{f.reason}</span>
                <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M2 4l3 3 3-3" /></svg>
              </button>
              <div className={`adm-expand${open === i ? ' open' : ''}`}><div><pre className="adm-fail-detail">{f.detail}</pre></div></div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** 每天一根柱子。停在上面（或 Tab 到它）出提示；点一下 = 只看那一天。
 *  换了时间范围柱子才重新长一遍（key 里带着范围）；选某一天、切花费 / Token 只变高度和深浅 */
function Chart({ days, win, picked, measure, onPick }: { days: UsageDay[]; win: UsageWindow; picked: string | null; measure: Measure; onPick: (date: string) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const [tip, setTip] = useState<{ i: number; left: number; top: number } | null>(null)
  const [on, setOn] = useState(false) // 提示框收起时内容和位置留着，淡出去才不会闪一下
  const value = (d: UsageDay) => (measure === 'tok' ? tokens(d) : d.cost)
  const axis = (v: number) => (measure === 'tok' ? (v ? wan(v) : '0') : cost(v))
  const top = niceMax(Math.max(0, ...days.map(value)))
  const every = days.length <= 10 ? 1 : days.length <= 31 ? 5 : Math.ceil(days.length / 6)

  // 换了范围：柱子都变了，浮着的提示收掉
  useEffect(() => setOn(false), [days.length, win])

  const show = (i: number, el: HTMLElement) => {
    const frame = box.current?.getBoundingClientRect()
    const bar = el.querySelector('i')?.getBoundingClientRect()
    if (!frame || !bar) return
    const half = 86 // 提示框大约 170 宽：别伸到卡片外面
    setTip({ i, left: Math.min(Math.max(bar.left + bar.width / 2 - frame.left, half), Math.max(half, frame.width - half)), top: Math.max(bar.top - frame.top, 76) })
    setOn(true)
  }
  const shown = tip && days[tip.i] ? days[tip.i] : null

  return (
    <div className="adm-chart" ref={box}>
      <div className="adm-grid" aria-hidden="true">
        {[1, 0.5, 0].map((p) => <span key={p} style={{ top: `${(1 - p) * 100}%` }}><em>{axis(top * p)}</em></span>)}
      </div>
      <div className={`adm-bars${picked ? ' picking' : ''}`}>
        {days.map((d, i) => (
          <div key={`${win}:${d.date}`} className={`adm-bar${d.date === picked ? ' sel' : ''}`} role="button" tabIndex={0} aria-pressed={d.date === picked} style={nth(i)}
            aria-label={`${dateText(d.date)}，花费 ${cost(d.cost)}，${d.calls} 次调用，${wan(tokens(d))} token。点一下只看这一天`}
            onMouseEnter={(e) => show(i, e.currentTarget)} onFocus={(e) => show(i, e.currentTarget)}
            onMouseLeave={() => setOn(false)} onBlur={() => setOn(false)}
            onClick={() => onPick(d.date)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(d.date) } }}>
            <i style={{ height: `${(100 * value(d)) / top}%` }} />
            {(days.length - 1 - i) % every === 0 && <b>{monthDay(d.date)}</b>}
          </div>
        ))}
      </div>
      <div className={`adm-tip${on && shown ? ' on' : ''}`} style={tip ? { left: tip.left, top: tip.top } : undefined} role="status">
        {shown && <><b>{dateText(shown.date)}</b>花费 {cost(shown.cost)}<br />{int(shown.calls)} 次调用 · {wan(tokens(shown))} token</>}
      </div>
    </div>
  )
}
