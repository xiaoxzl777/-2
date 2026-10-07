"""一场面试的"材料"：出题、评分、写总结都从这里取。创建会话时整理一次，之后不变，随图 B 的状态一起存进检查点。

全部是能直接放进 prompt 的纯数据（JSON 可序列化）：
  requirements  岗位要求 + 初筛判定。学历、软素质不进面试（技术面问不出来）
  experiences   简历里的项目 / 工作经历，文本取 PII 掩码后的版本（系统不变量⑤）
  findings      初筛时发现的简历问题（只取能定位到原文的）
  context       用户贴的面经 / 公司介绍：不长时整段放这里；长的切段进向量库，按话题检索（context_mode = retrieval）

每条材料带一个编号（code）：经历 P1、P2…，岗位要求 R+要求 id，简历问题 F+问题 id。话题用它指回材料。
不直接用数字或 projects[0]：实测模型会把"要求 9"写成 requirement[8]（当成从 0 开始的下标），错一位还看不出来。
"""
from __future__ import annotations

from app.domains import DEFAULT

REQ_TYPE = {"hard": "必须", "plus": "加分"}
STATUS = {"hit": "满足", "partial": "部分满足", "miss": "没满足"}
_KIND = {"projects": "项目", "work": "经历"}
MAX_FINDINGS = 6


def build_materials(*, job_title: str, company: str | None, requirements: list[dict], match_items: list[dict],
                    structure: dict, masked_text: str, findings: list[dict], context: str | None,
                    context_mode: str, domain: str = DEFAULT.key) -> dict:
    """findings 已按严重程度排好：[{id, title, description, char_start, char_end}]。"""
    judged = {i["requirement_id"]: i for i in match_items}
    reqs = []
    for r in requirements:
        if r.get("req_type") not in REQ_TYPE or r.get("category") == "education":
            continue
        item = judged.get(r["id"]) or {}
        reqs.append({"code": f"R{r['id']}", "id": r["id"], "content": r["content"], "type": REQ_TYPE[r["req_type"]],
                     "status": STATUS.get(item.get("status"), "未判定"), "reason": item.get("reason") or ""})

    experiences = []
    for key, kind in _KIND.items():
        for i, e in enumerate(structure.get(key) or []):
            start, end = e.get("char_start"), e.get("char_end")
            if start is None or end is None:
                continue
            experiences.append({"code": f"P{len(experiences) + 1}", "unit": f"{key}[{i}]", "kind": kind,
                                "name": e.get("name") or f"{kind} {i + 1}", "text": masked_text[start:end].strip()})

    issues = [{"code": f"F{f['id']}", "id": f["id"], "title": f["title"], "description": f["description"],
               "quote": masked_text[f["char_start"]:f["char_end"]].strip()}
              for f in findings if f.get("char_start") is not None and f.get("char_end") is not None][:MAX_FINDINGS]

    return {"job_title": job_title, "company": company, "domain": domain, "requirements": reqs, "experiences": experiences,
            "findings": issues, "context": context if context_mode == "full" else None, "context_mode": context_mode}


_LISTS = {"project": "experiences", "requirement": "requirements", "finding": "findings"}


def find_source(materials: dict, source: str, ref: str) -> dict | None:
    """话题指向的那一条材料；找不到返回 None（模型编了一个不存在的编号，或者来源和编号对不上）。"""
    key = _LISTS.get(source)
    return next((x for x in materials.get(key) or [] if x["code"] == ref), None) if key else None


def describe_source(materials: dict, topic: dict) -> str:
    """出题、评分时给模型看的"这个话题的相关材料"。"""
    item = find_source(materials, topic["source"], topic["ref"]) or {}
    if topic["source"] == "project":
        return f"简历里的{item.get('kind', '经历')}：{item.get('name', '')}\n{item.get('text', '')}"
    if topic["source"] == "requirement":
        reason = f"（{item['reason']}）" if item.get("reason") else ""
        return f"岗位要求（{item.get('type', '')}）：{item.get('content', '')}\n初筛判定：{item.get('status', '')}{reason}"
    return (f"简历原文：「{item.get('quote', '')}」\n"
            f"初筛发现的问题：{item.get('title', '')}——{item.get('description', '')}")


def experience_names(materials: dict) -> str:
    return "、".join(f"{e['name']}（{e['kind']}）" for e in materials["experiences"]) or "（简历里没有识别出经历）"
