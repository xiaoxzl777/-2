"""求职方向（领域包）：同一套流程，按岗位所属的方向换掉提示词里的角色、示例和评分说明，开关个别规则。

加一个方向 = 在这里登记一个 Domain（再补它的技能词条、岗位模板），流程代码不用改。
提示词里随方向变化的地方写成 [[名字]]（见 llm/prompts.py），拼好提示词的最后一步由 fill() 换成领域包里的文字：
放在 .format() 之后换，领域包里的示例 JSON 就不用管花括号转义。

方向由用户在工作台第一步选，存在岗位上（jobs.domain）；之后诊断、匹配、建议、面试都按岗位的方向取领域包。
简历解析不分方向：上传时还不知道要投哪个岗位，章节词典、结构化抽取只能是全集。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType

from app.domains import cs, finance, general, ops

_MARK = re.compile(r"\[\[(\w+)\]\]")


@dataclass(frozen=True, slots=True)
class Domain:
    key: str
    name: str                    # 下拉框里显示的名字
    icon: str                    # 两个字，下拉框里的图标
    desc: str                    # 一行说明：包含哪些岗位
    rule_hint: str               # 「简历按……诊断」
    interview_hint: str          # 「模拟面试问……」
    interview_label: str         # 页面上对面试的称呼：技术面 / 运营面
    sample_jd: dict              # 「填一份示例 JD」：{title, company, text}
    texts: MappingProxyType      # 提示词片段：[[key]] → 文字
    disabled_rules: frozenset[str] = field(default_factory=frozenset)   # 这个方向不跑的规则（rule_code）
    result_words: tuple[str, ...] = ()   # 规则判断"写没写结果"时，在通用的结果词之外这个方向还认的词
    note: str = ""               # 页面上提醒「结果可能不够准」的一句话：只有通用方向有，专门方向为空、页面不显示


def _load(module) -> Domain:
    return Domain(key=module.KEY, name=module.NAME, icon=module.ICON, desc=module.DESC, rule_hint=module.RULE_HINT,
                  interview_hint=module.INTERVIEW_HINT, interview_label=module.INTERVIEW_LABEL, sample_jd=module.SAMPLE_JD,
                  texts=MappingProxyType(module.TEXTS), disabled_rules=frozenset(module.DISABLED_RULES),
                  result_words=tuple(module.RESULT_WORDS), note=getattr(module, "NOTE", ""))


DOMAINS: dict[str, Domain] = {d.key: d for d in map(_load, (cs, ops, finance, general))}   # 顺序就是下拉框里的顺序，通用的放最后
DEFAULT = DOMAINS[cs.KEY]


def get_domain(key: str | None) -> Domain:
    """没有方向（老数据）或方向已经下线时按默认方向处理，不报错。"""
    return DOMAINS.get(key or "", DEFAULT)


def fill(text: str, domain: Domain) -> str:
    """把 [[名字]] 换成领域包里的文字。领域包缺了某个片段直接 KeyError：宁可当场报错，也不能把标记发给模型。"""
    return _MARK.sub(lambda m: domain.texts[m.group(1)], text)
