// 初筛结果的条目和说明文字：结果页（ApplyResult.tsx）和诊断报告（ApplyReport.tsx）共用，两边说法一致。
import { adviceApi } from '../api/advice'
import type { ApplyResult as Result, Dimension, MatchItem } from '../api/apply'
import { REQ_TYPE_LABEL } from '../api/jobs'
import type { ResumeStructure } from '../api/resumes'
import type { DetailRow } from '../components/IssueItem'
import type { SheetItem } from '../components/ResumePaper'

export const DIMENSIONS: [Dimension, string][] = [['skill', '技能'], ['education', '学历'], ['experience', '经验'], ['other', '其他']]
const MATCHED_BY = { dict: '规则判定（技能词典）', profile: '规则判定（学历 / 年限）', fulltext: '大模型判定' }
export const SEVERITY = { high: ['high', '严重'], medium: ['med', '中等'], low: ['low', '轻微'] } as const

/** 成绩单下面的两句：第一句是分数，第二句是接下来做什么 */
export function verdictSub(data: Result, gate: NonNullable<Result['gate']>): [string, string] {
  const overall = gate.overall_match === null ? null : Math.round(gate.overall_match)
  const hasHardGap = data.gaps.some((g) => g.req_type === 'hard')
  const anythingToFix = data.gaps.length > 0 || data.resume_issues.length > 0
  return gate.passed
    ? [`匹配度 ${overall}，过了 ${gate.threshold} 分的初筛线。`,
      anythingToFix ? '下面还有几处可以写得更好，面试前值得先改。' : '岗位要求都满足了，简历本身也没发现明显问题。']
    : [`匹配度 ${overall ?? '—'}，初筛线是 ${gate.threshold}。`,
      hasHardGap ? '先补「对照岗位」里的必须项，涨分最快；简历本身的问题顺手改掉。' : '先补「对照岗位」里没满足的要求，简历本身的问题顺手改掉。']
}

export function matchedByText(g: MatchItem): string {
  if (!g.matched_by) return '规则无法判定'
  const verified = g.matched_by === 'fulltext' && g.evidence_quote ? ' · 引用已在原文中核实' : ''
  return MATCHED_BY[g.matched_by] + verified
}

export function entryBlocksOf(structure: ResumeStructure): number[] {
  return (['education', 'work', 'projects', 'awards'] as const)
    .flatMap((k) => structure[k] ?? []).map((e) => e.block_ids?.[0]).filter((i): i is number => i !== undefined)
}

export type ListItem = SheetItem & { rows: DetailRow[] }

/** 三类条目：对照岗位的差距、简历本身的问题、满足的要求（只在原文纸面上用）。列表与纸面共用同一份，具体建议也共享 */
export function sheetItems(data: Result, hits: MatchItem[]): ListItem[] {
  const gap = data.gaps.map((g): ListItem => {
    const key = `gap:${data.id}:${g.requirement_id}`
    return {
      key, list: 'gap', color: g.status !== 'miss' && g.char_start !== null ? 'part' : null,
      tag: g.status === 'miss' ? ['miss', '缺失'] : ['part', '部分'], text: g.content,
      why: `${REQ_TYPE_LABEL[g.req_type]} · ${g.reason}`, note: `部分满足：${g.content}`,
      fix: ['判定方式', matchedByText(g)], start: g.char_start, end: g.char_end,
      advice: { key, path: adviceApi.gapPath(data.id, g.requirement_id), cached: g.advice ?? null, kind: 'gap' },
      rows: [
        g.evidence_quote ? { label: '简历原文', value: `「${g.evidence_quote}」`, quote: true } : { label: '简历原文', value: '没有找到相关的内容' },
        { label: '判定方式', value: matchedByText(g) },
      ],
    }
  })
  // 页数、图片这类问题针对整份简历，没有具体的原文。规则的"问题 / 怎么改"是固定模板，太泛，换成针对这一句现场生成的建议
  const self = data.resume_issues.map((f): ListItem => {
    const key = `finding:${f.id}`
    const [cls, label] = SEVERITY[f.severity]
    return {
      key, list: 'self', color: f.char_start !== null ? 'bad' : null, tag: [cls, label],
      text: f.evidence_quote ? `「${f.evidence_quote}」` : f.title, why: f.evidence_quote ? f.title : '针对整份简历',
      note: f.title, start: f.char_start, end: f.char_end,
      advice: { key, path: adviceApi.findingPath(f.id), cached: f.rewrite, kind: 'finding', fallback: f.suggestion },
      rows: [{ label: '来源', value: f.source === 'rule' ? '规则检查' : '大模型审阅 · 引用已在原文中核实' }],
    }
  })
  const hit = hits.map((h): ListItem => ({
    key: `hit:${data.id}:${h.requirement_id}`, list: 'hit', color: h.char_start !== null ? 'good' : null,
    tag: ['hit', '满足'], text: h.content, why: `${REQ_TYPE_LABEL[h.req_type]} · ${h.reason}`, note: `满足：${h.content}`,
    fix: ['判定方式', matchedByText(h)], start: h.char_start, end: h.char_end, rows: [],
  }))
  return [...gap, ...self, ...hit]
}
