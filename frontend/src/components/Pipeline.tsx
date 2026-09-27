// 投递的流程卡：解析简历 → 诊断简历 ∥ 对照岗位 → 初筛判定，下面一条总进度。
// 进度由「哪几步完成了」推出来，只进不退：后端诊断与匹配并行，谁先完成谁的事件先到，
// 而后端给两者写死的百分比（60 / 85）照搬就会倒退。
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { watchApply } from '../api/apply'

type NodeState = 'idle' | 'run' | 'ok'

export type PipeState = {
  started: boolean
  reused: boolean // 简历之前已经解析过，这次直接复用
  parse: NodeState
  diagnose: NodeState
  match: NodeState
  gate: NodeState
  done: boolean
}

const RANK: Record<NodeState, number> = { idle: 0, run: 1, ok: 2 }
const up = (from: NodeState, to: NodeState) => (RANK[to] > RANK[from] ? to : from)

const INITIAL: PipeState = { started: false, reused: false, parse: 'idle', diagnose: 'idle', match: 'idle', gate: 'idle', done: false }

/** action：后端的 stage（parsing / analyzing / diagnose / match / gate），外加前端的 start / start-reused / done */
function reduce(s: PipeState, action: string): PipeState {
  const n = { ...s, started: true }
  const analyzing = () => {
    n.parse = 'ok'
    n.diagnose = up(n.diagnose, 'run')
    n.match = up(n.match, 'run')
  }
  switch (action) {
    case 'start': n.parse = up(n.parse, 'run'); break
    case 'start-reused': n.reused = true; analyzing(); break
    case 'parsing': n.parse = up(n.parse, 'run'); break
    case 'analyzing': analyzing(); break
    case 'diagnose': analyzing(); n.diagnose = 'ok'; break
    case 'match': analyzing(); n.match = 'ok'; break
    case 'gate': n.parse = n.diagnose = n.match = n.gate = 'ok'; break
    case 'done': n.parse = n.diagnose = n.match = n.gate = 'ok'; n.done = true; break
    default: return s
  }
  if (n.diagnose === 'ok' && n.match === 'ok') n.gate = up(n.gate, 'run')
  return n
}

export function percentOf(s: PipeState): number {
  if (s.done) return 100
  if (s.gate === 'ok') return 95
  const finished = [s.diagnose, s.match].filter((x) => x === 'ok').length
  if (finished === 2) return 85
  if (finished === 1) return 60
  if (s.parse === 'ok') return 20
  return s.started ? 5 : 0
}

function messageOf(s: PipeState): string {
  if (s.done) return '完成'
  if (s.gate === 'ok') return '初筛判定完成'
  if (s.gate === 'run') return '正在判定是否通过初筛'
  if (s.diagnose === 'ok') return '简历诊断完成，还在对照岗位'
  if (s.match === 'ok') return '岗位匹配完成，还在诊断简历'
  if (s.diagnose === 'run') return '诊断简历、对照岗位同时进行'
  if (s.parse === 'run') return '正在解析简历'
  return '等待开始'
}

/** 跟踪一次投递：track(id) 一直等到结束，返回最终状态 success / failed。组件卸载时自动断开 */
export function useApplyTracker() {
  const [pipe, dispatch] = useReducer(reduce, INITIAL)
  const ctrl = useRef<AbortController | null>(null)
  useEffect(() => () => ctrl.current?.abort(), [])

  const track = useCallback(async (id: number, opts: { reused?: boolean; stage?: string } = {}) => {
    ctrl.current?.abort()
    const c = new AbortController()
    ctrl.current = c
    dispatch(opts.reused ? 'start-reused' : 'start')
    if (opts.stage) dispatch(opts.stage)
    const status = await watchApply(id, dispatch, c.signal)
    if (status === 'success') dispatch('done')
    return status
  }, [])

  return { pipe, track }
}

function PipeNode({ state, name, desc, note }: { state: NodeState; name: string; desc: string; note?: string }) {
  return (
    <div className={`node ${state === 'idle' ? '' : `is-${state}`}`}>
      <span className="node-mark" aria-hidden="true" />
      <div><div className="n">{name}</div><div className="d">{desc}</div></div>
      {note && <span className="t">{note}</span>}
    </div>
  )
}

export function Pipeline({ pipe }: { pipe: PipeState }) {
  const percent = percentOf(pipe)
  return (
    <>
      <div className="pipe">
        <PipeNode state={pipe.parse} name="解析简历" desc="版面 → 章节 → 结构化" note={pipe.reused ? '已解析过，复用' : undefined} />
        <div className="par-label">同时进行</div>
        <div className="par">
          <PipeNode state={pipe.diagnose} name="诊断简历" desc="规则 + 大模型" />
          <PipeNode state={pipe.match} name="对照岗位" desc="逐条判定要求" />
        </div>
        <PipeNode state={pipe.gate} name="初筛判定" desc="匹配度达到 60 即通过" />
      </div>
      <div className="big" aria-live="polite">
        <div className="big-top"><span>{messageOf(pipe)}</span><b>{percent}%</b></div>
        <div className="bar-track"><i style={{ width: `${percent}%` }} /></div>
      </div>
    </>
  )
}
