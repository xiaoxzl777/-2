// 管理端 · 模型设置：/admin/settings。两类模型分开管：
//   对话模型（诊断、匹配、建议、面试都用它）：可以存几家，给现在这家换 Key，或者「换成」另一家；
//   检索模型（向量 + 重排，只在面试贴了超过 3000 字的面经时用）：只有一份配置，改它或者换回 .env 里的。
// 保存、换 Key、切换之前后端都会先真调一次，调不通不改；改完马上生效。API Key 只在提交时发给后端，页面上只显示开头和后四位。
// 样稿：docs/design/管理端用量预览.html
import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from 'react'
import { adminApi, type Provider, type ProviderDraft, type ProviderPreset, type Providers, type ProviderStatus, type Retrieval } from '../../api/admin'
import { ApiError } from '../../api/client'
import { AdminShell } from '../../components/AdminShell'
import { MagneticButton } from '../../components/effects'
import { Headline, Mark } from '../../components/Headline'

type Ask = { id: number; kind: 'key' | 'use' | 'del' }
type Result = { tone: '' | 'ok' | 'bad' | 'wait'; text: string }
const NONE: Result = { tone: '', text: '' }
const TESTING: Result = { tone: 'wait', text: '测试中…' }
const HINT: Result = { tone: '', text: '先测试连接，通过了才能保存' }

const why = (e: unknown) => (e instanceof ApiError ? e.message : '请稍后再试')
const price = (p: Provider) => `输入 ¥${p.price_in} · 输出 ¥${p.price_out}`
const title = (p: Provider) => `${p.name} · ${p.model}`
const nth = (i: number) => ({ '--i': i }) as CSSProperties // 进场的先后

function Said({ result }: { result: Result }) {
  return <span className={`adm-result ${result.tone}`} role="status">{result.tone === 'wait' && <i className="adm-spin" aria-hidden="true" />}{result.text}</span>
}

function Pill({ status }: { status: ProviderStatus | null }) {
  if (status === null) return <span className="adm-pill wait">检查中…</span>
  return status.available ? <span className="adm-pill">服务正常</span> : <span className="adm-pill down">现在用不了：{status.reason}</span>
}

/** 改成功了：让这张卡片亮一下 */
function useFlash() {
  const ref = useRef<HTMLElement>(null)
  const flash = useCallback(() => {
    const el = ref.current
    if (!el) return
    el.classList.remove('flash')
    void el.offsetWidth // 让动画能重新开始
    el.classList.add('flash')
  }, [])
  return [ref, flash] as const
}

export default function AdminSettings() {
  const [data, setData] = useState<Providers | null>(null)
  const [status, setStatus] = useState<ProviderStatus | null>(null) // null = 还在问
  const [error, setError] = useState<string | null>(null)
  const [ask, setAsk] = useState<Ask | null>(null)
  const [fresh, setFresh] = useState<number | null>(null) // 刚添加的那一条，标「新」
  const [nowRef, flashNow] = useFlash()

  const load = useCallback(async () => {
    try {
      setData(await adminApi.providers())
      setError(null)
    } catch (e) {
      setError(why(e))
      return
    }
    setStatus(null)
    // 状态和余额要现问服务商，可能要几秒：页面先画出来，问到了再填上
    adminApi.providerStatus().then(setStatus).catch(() => setStatus({ available: true, reason: null, balance: null }))
  }, [])
  useEffect(() => { void load() }, [load])

  /** 换 Key / 换成它 / 删除 做成了：收起确认框、重新取一遍；动到正在用的那一家时卡片亮一下 */
  const done = (touchesCurrent: boolean) => {
    setAsk(null)
    void load().then(() => { if (touchesCurrent) flashNow() })
  }

  return (
    <AdminShell>
      <div className="adm-page">
        <div className="adm-head">
          <div>
            <Headline badge="管理端" label="模型设置" lines={['用哪家的模型，', <>在这里<Mark>换</Mark>。</>]} />
            <p className="adm-sub fade d2">两类模型分开管：对话模型管诊断、匹配、建议和面试；检索模型只在面试贴了很长的面经时才用。改完马上生效，不用重启服务。</p>
          </div>
        </div>

        <h2 className="adm-sec first fade d2">对话模型<small>诊断、匹配、建议、面试都用它</small></h2>
        {error && !data && <p className="adm-fail-box" role="alert">{error} <button type="button" className="link" onClick={() => void load()}>再试一次</button></p>}
        {!error && !data && <p className="adm-loading">加载中…</p>}
        {data && (
          <>
            <section ref={nowRef} className="adm-card adm-box adm-in" style={nth(2)}>
              <div className="adm-box-head"><h2>正在使用</h2><Pill status={status} /></div>
              <Current p={data.current} status={status} asking={ask?.id === data.current.id ? ask : null} onAsk={setAsk} onDone={() => done(true)} />
            </section>

            <section className="adm-card adm-box adm-others adm-in" style={nth(3)}>
              <h2>其他已保存的</h2>
              <p className="adm-note">想换一家就点「换成它」，换之前会先试一次连不连得上。</p>
              <ul className="adm-provs">
                {data.others.map((p) => (
                  <Row key={p.id} p={p} fresh={p.id === fresh} asking={ask?.id === p.id ? ask : null} onAsk={setAsk}
                    onDone={(kind) => done(kind === 'use')} />
                ))}
              </ul>
              <AddForm presets={data.presets} onSaved={(id) => { setFresh(id); void load() }} />
            </section>
          </>
        )}

        <h2 className="adm-sec fade d3">检索模型<small>向量 + 重排：只在面试时贴了超过 3000 字的面经才用到</small></h2>
        <RetrievalCard />
      </div>
    </AdminShell>
  )
}

function Current({ p, status, asking, onAsk, onDone }: { p: Provider; status: ProviderStatus | null; asking: Ask | null; onAsk: (a: Ask | null) => void; onDone: () => void }) {
  const [result, setResult] = useState<Result>(NONE)
  const busy = result.tone === 'wait'

  const test = async () => {
    setResult(TESTING)
    try {
      const r = await adminApi.testSaved(p.id)
      setResult({ tone: r.ok ? 'ok' : 'bad', text: r.message })
    } catch (e) {
      setResult({ tone: 'bad', text: why(e) })
    }
  }

  return (
    <>
      <div className="adm-now-name"><b>{p.name}</b><code>{p.model}</code></div>
      <dl className="adm-kv">
        <div><dt>API Key</dt><dd>{p.key_hint || '没有配置'}<small>{p.from_env ? '写在 .env 文件里' : '只显示开头和后四位'}</small></dd></div>
        <div><dt>接口地址</dt><dd>{p.base_url}</dd></div>
        <div><dt>单价（每百万 token）</dt><dd>{price(p)}<small>用来估算花费</small></dd></div>
        <div><dt>余额</dt><dd>{status === null ? '…' : status.balance ?? '—'}<small>{status === null ? '正在问这家' : status.balance ? '刚从这家的接口查到的' : '这家没有查余额的接口'}</small></dd></div>
      </dl>
      {asking ? <AskBox p={p} kind={asking.kind} onCancel={() => onAsk(null)} onDone={onDone} /> : (
        <div className="adm-btns">
          <MagneticButton type="button" className="dark" onClick={() => onAsk({ id: p.id, kind: 'key' })}>换 Key</MagneticButton>
          <MagneticButton type="button" className="outline" disabled={busy} onClick={() => void test()}>测试连接</MagneticButton>
          <Said result={result} />
        </div>
      )}
    </>
  )
}

function Row({ p, fresh, asking, onAsk, onDone }: { p: Provider; fresh: boolean; asking: Ask | null; onAsk: (a: Ask | null) => void; onDone: (kind: Ask['kind']) => void }) {
  return (
    <li className="adm-prov">
      <div className="who"><b>{p.name}</b><code>{p.model}</code>{p.from_env && <span className="adm-tagx">.env 里的</span>}{fresh && <span className="adm-new">新</span>}</div>
      <div className="meta">
        {p.key_ok ? p.key_hint : <span className="adm-fail">Key 读不出来了，要重新填</span>} · {p.base_url} · {price(p)}
      </div>
      <div className="acts">
        <MagneticButton type="button" className="dark" disabled={!p.key_ok} onClick={() => onAsk({ id: p.id, kind: 'use' })}>换成它</MagneticButton>
        {!p.from_env && <MagneticButton type="button" className="ghost" onClick={() => onAsk({ id: p.id, kind: 'key' })}>换 Key</MagneticButton>}
        {!p.from_env && <MagneticButton type="button" className="ghost" onClick={() => onAsk({ id: p.id, kind: 'del' })}>删除</MagneticButton>}
      </div>
      {asking && <AskBox p={p} kind={asking.kind} onCancel={() => onAsk(null)} onDone={() => onDone(asking.kind)} />}
    </li>
  )
}

/** 原地问一句再动手：换 Key（填新的）、换成它、删除。前两个后端会先试连，失败的原因显示在按钮旁边，什么都不改 */
function AskBox({ p, kind, onCancel, onDone }: { p: Provider; kind: Ask['kind']; onCancel: () => void; onDone: () => void }) {
  const [key, setKey] = useState('')
  const [result, setResult] = useState<Result>(NONE)
  const busy = result.tone === 'wait'

  const run = async () => {
    if (kind === 'key' && !key.trim()) return setResult({ tone: 'bad', text: '先填新的 API Key' })
    setResult(kind === 'del' ? { tone: 'wait', text: '删除中…' } : TESTING)
    try {
      if (kind === 'key') await adminApi.changeKey(p.id, key.trim())
      else if (kind === 'use') await adminApi.activate(p.id)
      else await adminApi.remove(p.id)
      onDone()
    } catch (e) {
      setResult({ tone: 'bad', text: why(e) })
    }
  }
  const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onCancel() }

  return (
    <div className="adm-ask" role="group" aria-label={title(p)} onKeyDown={onKeyDown}>
      {kind === 'key' && (
        <div className="adm-field">
          <label htmlFor={`key-${p.id}`}>给「{title(p)}」换一把新的 API Key</label>
          <input id={`key-${p.id}`} type="password" autoComplete="off" placeholder="sk-…" value={key} autoFocus disabled={busy}
            onChange={(e) => setKey(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void run() }} />
          <small>{p.from_env ? '这把 Key 写在 .env 文件里，页面改不了它：新的 Key 会照现在的配置另存一条，并换过去。' : '先试一次连不连得上，通过了才换。'}</small>
        </div>
      )}
      {kind === 'use' && (
        <p>换成「<b>{title(p)}</b>」？之后新的诊断、匹配、建议、面试都用它，正在跑的那一次不受影响。<br />
          评测数字是在 DeepSeek 上测的。换了以后判得准不准，要自己再拿几份简历试一试。</p>
      )}
      {kind === 'del' && <p>删除「<b>{title(p)}</b>」这条配置？它的 Key 一起删掉；以前的用量记录不受影响。</p>}
      <div className="adm-btns">
        {kind === 'key' && <MagneticButton type="button" className="dark" disabled={busy} onClick={() => void run()}>测试并保存</MagneticButton>}
        {kind === 'use' && <MagneticButton type="button" className="dark" disabled={busy} autoFocus onClick={() => void run()}>测试并换过去</MagneticButton>}
        {kind === 'del' && <MagneticButton type="button" className="danger" disabled={busy} onClick={() => void run()}>删除</MagneticButton>}
        {/* 删除默认停在「取消」上：误按回车不会删 */}
        <MagneticButton type="button" className="ghost" disabled={busy} autoFocus={kind === 'del'} onClick={onCancel}>取消</MagneticButton>
        <Said result={result} />
      </div>
    </div>
  )
}

const EMPTY = { model: '', base_url: '', api_key: '', price_in: '', price_out: '' }

/** 添加一家：几家的名字直接列出来，点哪家就展开它的表单（接口地址和常用的模型名先填好） */
function AddForm({ presets, onSaved }: { presets: ProviderPreset[]; onSaved: (id: number) => void }) {
  const [kind, setKind] = useState<string | null>(null) // null = 表单收着
  const [form, setForm] = useState(EMPTY)
  const [tested, setTested] = useState(false)
  const [result, setResult] = useState<Result>(HINT)
  const keyRef = useRef<HTMLInputElement>(null)
  const modelRef = useRef<HTMLInputElement>(null)
  const busy = result.tone === 'wait'

  const pick = (key: string) => {
    if (key === kind) return setKind(null)
    const pre = presets.find((x) => x.key === key)
    setForm({ model: pre?.model ?? '', base_url: pre?.base_url ?? '', api_key: '', price_in: pre?.price_in?.toString() ?? '', price_out: pre?.price_out?.toString() ?? '' })
    setTested(false)
    setResult(HINT)
    setKind(key)
    window.setTimeout(() => (pre?.model ? keyRef : modelRef).current?.focus(), 320) // 等展开得差不多了再给焦点
  }
  /** 改了任何一格：之前测过的不算，要重新测 */
  const edit = (patch: Partial<typeof EMPTY>) => { setForm((f) => ({ ...f, ...patch })); setTested(false); setResult(HINT) }

  const draft = (): ProviderDraft | string => {
    const missing = ([['model', '先填模型名'], ['base_url', '先填接口地址'], ['api_key', '先填 API Key'], ['price_in', '先填输入单价'], ['price_out', '先填输出单价']] as const)
      .find(([k]) => !form[k].trim())
    if (missing) return missing[1]
    if (!/^https?:\/\/\S+$/.test(form.base_url.trim())) return '接口地址要以 http:// 或 https:// 开头'
    if (form.api_key.trim().length < 8) return 'API Key 太短了'
    const [pin, pout] = [Number(form.price_in), Number(form.price_out)]
    if (!(pin >= 0) || !(pout >= 0)) return '单价要填数字'
    return { kind: kind ?? 'custom', model: form.model.trim(), base_url: form.base_url.trim(), api_key: form.api_key.trim(), price_in: pin, price_out: pout }
  }

  const test = async () => {
    const d = draft()
    if (typeof d === 'string') return setResult({ tone: 'bad', text: d })
    setResult(TESTING)
    try {
      const r = await adminApi.testDraft(d)
      setTested(r.ok)
      setResult({ tone: r.ok ? 'ok' : 'bad', text: r.ok ? `${r.message}，可以保存了` : r.message })
    } catch (e) {
      setResult({ tone: 'bad', text: why(e) })
    }
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    const d = draft()
    if (!tested || typeof d === 'string') return
    setResult({ tone: 'wait', text: '保存中…' })
    try {
      const saved = await adminApi.create(d)
      setKind(null)
      onSaved(saved.id)
    } catch (err) {
      setTested(false)
      setResult({ tone: 'bad', text: why(err) })
    }
  }

  const open = kind !== null
  return (
    <>
      <div className="adm-chips" role="group" aria-label="添加一家">
        <span>添加一家：</span>
        {presets.map((x) => (
          <button key={x.key} type="button" className={x.key === kind ? 'on' : ''} aria-expanded={x.key === kind} onClick={() => pick(x.key)}>
            {x.key === 'custom' ? '其他（OpenAI 兼容接口）' : x.name}
          </button>
        ))}
      </div>
      <div className={`adm-expand${open ? ' open' : ''}`}>
        <div>
          <form className="adm-form" onSubmit={(e) => void save(e)}>
            <div className="adm-field">
              <label htmlFor="f-model">模型名</label>
              <input id="f-model" ref={modelRef} autoComplete="off" maxLength={50} placeholder="如 deepseek-chat" value={form.model} disabled={busy} onChange={(e) => edit({ model: e.target.value })} />
            </div>
            <div className="adm-field">
              <label htmlFor="f-url">接口地址</label>
              <input id="f-url" autoComplete="off" maxLength={255} placeholder="https://…/v1" value={form.base_url} disabled={busy} onChange={(e) => edit({ base_url: e.target.value })} />
            </div>
            <div className="adm-field full">
              <label htmlFor="f-key">API Key</label>
              <input id="f-key" ref={keyRef} type="password" autoComplete="off" maxLength={300} placeholder="sk-…" value={form.api_key} disabled={busy} onChange={(e) => edit({ api_key: e.target.value })} />
              <small>加密后存进数据库；保存后页面上只显示开头和后四位，谁也看不到完整的</small>
            </div>
            <div className="adm-field">
              <label htmlFor="f-pin">输入单价（元 / 百万 token）</label>
              <input id="f-pin" inputMode="decimal" autoComplete="off" value={form.price_in} disabled={busy} onChange={(e) => edit({ price_in: e.target.value })} />
            </div>
            <div className="adm-field">
              <label htmlFor="f-pout">输出单价（元 / 百万 token）</label>
              <input id="f-pout" inputMode="decimal" autoComplete="off" value={form.price_out} disabled={busy} onChange={(e) => edit({ price_out: e.target.value })} />
              <small>去这家的价格页查，用来估算花费</small>
            </div>
            <div className="adm-field full">
              <div className="adm-btns">
                <MagneticButton type="button" className="outline" disabled={busy} onClick={() => void test()}>测试连接</MagneticButton>
                <MagneticButton type="submit" className="dark" disabled={busy || !tested}>保存</MagneticButton>
                <MagneticButton type="button" className="ghost" disabled={busy} onClick={() => setKind(null)}>取消</MagneticButton>
                <Said result={result} />
              </div>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}

const NO_RETRIEVAL = { base_url: '', api_key: '', embed_model: '', rerank_model: '' }

/** 检索模型：向量（先找出相关的 20 段）+ 重排（再挑最相关的 3 段）。只有一份配置：改它，或者换回 .env 里的 */
function RetrievalCard() {
  const [r, setR] = useState<Retrieval | null>(null)
  const [status, setStatus] = useState<ProviderStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'view' | 'edit' | 'reset'>('view')
  const [form, setForm] = useState(NO_RETRIEVAL)
  const [tested, setTested] = useState(false)
  const [result, setResult] = useState<Result>(NONE) // 卡片上「测试连接」「换回」的结果
  const [formResult, setFormResult] = useState<Result>(HINT)
  const [ref, flash] = useFlash()
  const embedRef = useRef<HTMLInputElement>(null)
  const busy = result.tone === 'wait' || formResult.tone === 'wait'

  const ask = useCallback(() => {
    setStatus(null)
    adminApi.retrievalStatus().then(setStatus).catch(() => setStatus({ available: true, reason: null, balance: null }))
  }, [])
  const load = useCallback(() => {
    adminApi.retrieval().then((x) => { setR(x); setError(null); ask() }).catch((e) => setError(why(e)))
  }, [ask])
  useEffect(load, [load])

  if (!r) {
    return error
      ? <p className="adm-fail-box" role="alert">{error} <button type="button" className="link" onClick={load}>再试一次</button></p>
      : <p className="adm-loading">加载中…</p>
  }

  const edit = (patch: Partial<typeof NO_RETRIEVAL>) => { setForm((f) => ({ ...f, ...patch })); setTested(false); setFormResult(HINT) }
  const startEdit = () => {
    setForm({ base_url: r.base_url, api_key: '', embed_model: r.embed_model, rerank_model: r.rerank_model })
    setTested(false)
    setFormResult(HINT)
    setResult(NONE)
    setMode('edit')
    window.setTimeout(() => embedRef.current?.focus(), 320)
  }
  const draft = () => {
    const missing = ([['base_url', '先填接口地址'], ['embed_model', '先填向量模型'], ['rerank_model', '先填重排模型']] as const).find(([k]) => !form[k].trim())
    if (missing) return missing[1]
    if (!/^https?:\/\/\S+$/.test(form.base_url.trim())) return '接口地址要以 http:// 或 https:// 开头'
    return { base_url: form.base_url.trim(), api_key: form.api_key.trim() || null, embed_model: form.embed_model.trim(), rerank_model: form.rerank_model.trim() }
  }
  const applied = (x: Retrieval) => { setR(x); setMode('view'); setResult(NONE); ask(); flash() }

  const testNow = async () => {
    setResult(TESTING)
    try {
      const t = await adminApi.testRetrieval()
      setResult({ tone: t.ok ? 'ok' : 'bad', text: t.message })
    } catch (e) {
      setResult({ tone: 'bad', text: why(e) })
    }
  }
  const testDraft = async () => {
    const d = draft()
    if (typeof d === 'string') return setFormResult({ tone: 'bad', text: d })
    setFormResult(TESTING)
    try {
      const t = await adminApi.testRetrieval(d)
      setTested(t.ok)
      setFormResult({ tone: t.ok ? 'ok' : 'bad', text: t.ok ? `${t.message}，可以保存了` : t.message })
    } catch (e) {
      setFormResult({ tone: 'bad', text: why(e) })
    }
  }
  const save = async (e: FormEvent) => {
    e.preventDefault()
    const d = draft()
    if (!tested || typeof d === 'string') return
    setFormResult({ tone: 'wait', text: '保存中…' })
    try {
      applied(await adminApi.saveRetrieval(d))
    } catch (err) {
      setTested(false)
      setFormResult({ tone: 'bad', text: why(err) })
    }
  }
  const reset = async () => {
    setResult({ tone: 'wait', text: '换回去…' })
    try {
      applied(await adminApi.resetRetrieval())
    } catch (e) {
      setResult({ tone: 'bad', text: why(e) })
    }
  }

  return (
    <section ref={ref} className="adm-card adm-box adm-in" style={nth(5)}>
      <div className="adm-box-head">
        <div className="adm-now-name flat"><b>{r.name}</b><span className="adm-tagx">{r.from_env ? '.env 里的配置' : '在管理端改过'}</span></div>
        <Pill status={status} />
      </div>
      <dl className="adm-kv">
        <div><dt>API Key</dt><dd>{r.key_hint || '没有配置'}<small>{r.from_env ? '写在 .env 文件里' : '只显示开头和后四位'}</small></dd></div>
        <div><dt>接口地址</dt><dd>{r.base_url}</dd></div>
        <div><dt>向量模型</dt><dd><code>{r.embed_model}</code><small>先找出相关的 20 段</small></dd></div>
        <div><dt>重排模型</dt><dd><code>{r.rerank_model}</code><small>再挑最相关的 3 段</small></dd></div>
      </dl>
      {mode === 'reset' ? (
        <div className="adm-ask" role="group" aria-label="换回 .env 里的配置" onKeyDown={(e) => { if (e.key === 'Escape' && !busy) setMode('view') }}>
          <p>换回 .env 里的配置？向量模型如果跟着变了，正在进行的面试里已经存好的面经切段会作废：那几场照样能面，只是不再带面经。</p>
          <div className="adm-btns">
            <MagneticButton type="button" className="dark" disabled={busy} onClick={() => void reset()}>换回去</MagneticButton>
            <MagneticButton type="button" className="ghost" disabled={busy} autoFocus onClick={() => { setMode('view'); setResult(NONE) }}>取消</MagneticButton>
            <Said result={result} />
          </div>
        </div>
      ) : (
        <div className="adm-btns">
          <MagneticButton type="button" className="dark" disabled={busy || mode === 'edit'} onClick={startEdit}>修改</MagneticButton>
          <MagneticButton type="button" className="outline" disabled={busy} onClick={() => void testNow()}>测试连接</MagneticButton>
          {!r.from_env && <MagneticButton type="button" className="ghost" disabled={busy || mode === 'edit'} onClick={() => { setResult(NONE); setMode('reset') }}>换回 .env 里的配置</MagneticButton>}
          <Said result={result} />
        </div>
      )}
      <div className={`adm-expand${mode === 'edit' ? ' open' : ''}`}>
        <div>
          <form className="adm-form" onSubmit={(e) => void save(e)}>
            <div className="adm-field full">
              <label htmlFor="r-url">接口地址</label>
              <input id="r-url" autoComplete="off" maxLength={255} placeholder="https://…/v1" value={form.base_url} disabled={busy} onChange={(e) => edit({ base_url: e.target.value })} />
              <small>接口格式要和硅基流动一样：向量走 /embeddings，重排走 /rerank</small>
            </div>
            <div className="adm-field full">
              <label htmlFor="r-key">API Key</label>
              <input id="r-key" type="password" autoComplete="off" maxLength={300} placeholder="不换就留空" value={form.api_key} disabled={busy} onChange={(e) => edit({ api_key: e.target.value })} />
            </div>
            <div className="adm-field">
              <label htmlFor="r-embed">向量模型</label>
              <input id="r-embed" ref={embedRef} autoComplete="off" maxLength={50} placeholder="如 BAAI/bge-m3" value={form.embed_model} disabled={busy} onChange={(e) => edit({ embed_model: e.target.value })} />
              <small>把面经切成的小段变成向量，先找出相关的 20 段</small>
            </div>
            <div className="adm-field">
              <label htmlFor="r-rerank">重排模型</label>
              <input id="r-rerank" autoComplete="off" maxLength={100} placeholder="如 BAAI/bge-reranker-v2-m3" value={form.rerank_model} disabled={busy} onChange={(e) => edit({ rerank_model: e.target.value })} />
              <small>再从这 20 段里挑最相关的 3 段给面试官</small>
            </div>
            <p className="adm-warn">换了向量模型，正在进行的面试里已经存好的面经切段会作废：那几场照样能面，只是不再带面经。新开的面试不受影响。</p>
            <div className="adm-field full">
              <div className="adm-btns">
                <MagneticButton type="button" className="outline" disabled={busy} onClick={() => void testDraft()}>测试连接</MagneticButton>
                <MagneticButton type="submit" className="dark" disabled={busy || !tested}>保存</MagneticButton>
                <MagneticButton type="button" className="ghost" disabled={busy} onClick={() => setMode('view')}>取消</MagneticButton>
                <Said result={formResult} />
              </div>
            </div>
          </form>
        </div>
      </div>
    </section>
  )
}
