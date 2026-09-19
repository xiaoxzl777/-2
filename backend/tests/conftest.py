"""测试用 PDF 由代码现场生成，不依赖任何真实简历文件。"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

A4 = (595, 842)


def make_pdf(path: Path, items: list[tuple], *, encrypt: bool = False) -> Path:
    """items: [(x, y, text, fontsize, fontname)]；fontname: 'china-s' 中文, 'helv' 常规, 'hebo' 加粗。"""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    for x, y, text, size, font in items:
        page.insert_text((x, y), text, fontsize=size, fontname=font)
    if encrypt:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    else:
        doc.save(path)
    doc.close()
    return path


@pytest.fixture
def single_column_pdf(tmp_path) -> Path:
    body = "负责订单服务的开发与性能优化，使用 Spring Boot 与 Redis 完成缓存改造并上线，"
    items = [
        (250, 60, "Zhang San", 24, "hebo"),
        (40, 120, "Education", 12, "hebo"),
        (40, 140, "某某大学 计算机科学与技术 本科 2023.09-2027.06", 10.5, "china-s"),
        (40, 180, "Projects", 12, "hebo"),
    ]
    items += [(40, 200 + i * 16, f"{i + 1}. {body}", 10.5, "china-s") for i in range(6)]
    return make_pdf(tmp_path / "single.pdf", items)


@pytest.fixture
def image_only_pdf(tmp_path) -> Path:
    """模拟扫描件：页面上只有一张图，没有文本层。"""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(50, 50, 545, 792), pixmap=pix)
    path = tmp_path / "scanned.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def encrypted_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "enc.pdf", [(40, 100, "secret resume " * 20, 10.5, "helv")], encrypt=True)


# ───────────── 接口测试：SQLite 内存库替换 MySQL，不跑 lifespan（因此也不需要 Redis）─────────────


@pytest.fixture
def db_session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base

    # StaticPool：所有连接共用同一个内存库；接口在线程池里执行，所以关掉同线程检查
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


class FakeLLM:
    """脚本化的假模型。replies 的键可以是 schema 类名，或 "类名:某段文字"——后者只在 prompt 里出现这段文字时命中，
    用来区分同一 schema 的多次调用（不同章节、不同经历）。并行调用下结果依然确定。

    找不到预设回复时返回一个对所有 schema 都合法的空结果，所以接口测试不必关心结构化抽取。
    """

    EMPTY = '{"entries": [], "items": []}'

    def __init__(self, replies: dict[str, list] | None = None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.calls: dict[str, list] = {}

    def invoke(self, scene, messages, *, prompt_version, schema=None, ref=None, **_):
        from app.llm.client import LLMResult, parse_json

        name = schema.__name__ if schema else scene
        haystack = "\n".join(content for _, content in messages)
        key = next((k for k in self.replies if k.startswith(f"{name}:") and k.split(":", 1)[1] in haystack), name)
        self.calls.setdefault(key, []).append(list(messages))
        queue = self.replies.get(key)
        reply = queue.pop(0) if queue else self.EMPTY
        if isinstance(reply, Exception):
            raise reply
        parsed, error = parse_json(reply, schema) if schema else (None, None)
        return LLMResult(reply, parsed, error, 100, 50, 0.001, False, "fake", "fp", 1)

    @property
    def sent_text(self) -> str:
        return "\n".join(content for calls in self.calls.values() for msgs in calls for _, content in msgs)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(db_session_factory, fake_llm, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.cache.pubsub import get_publisher
    from app.config import settings
    from app.database import get_db, get_session_factory
    from app.llm.client import get_llm_client
    from app.main import app

    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")  # 上传文件落到临时目录，不碰真实 data/
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: db_session_factory  # 后台任务也用测试库
    app.dependency_overrides[get_llm_client] = lambda: fake_llm                 # 不发真实的模型请求
    app.dependency_overrides[get_publisher] = lambda: lambda *_: None           # 进度推送默认丢弃（不连 Redis）
    yield TestClient(app)  # 不用 with：不触发 lifespan 里的 MySQL / Redis 检查
    app.dependency_overrides.clear()


def upload_pdf(client, headers: dict, path: Path, filename: str | None = None, **form):
    """POST /resumes。TestClient 会在响应返回后同步跑完后台解析，所以返回时解析已结束。"""
    with path.open("rb") as f:
        files = {"file": (filename or path.name, f, "application/pdf")}
        return client.post("/api/v1/resumes", headers=headers, files=files, data=form)


@pytest.fixture
def auth_headers(client) -> dict:
    r = client.post("/api/v1/auth/register", json={"username": "tester", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


# ───────────── 投递（POST /apply）相关测试共用：一份解析好的简历、一个解析好的岗位、假向量库、假模型的回复 ─────────────

H_VAGUE = "1. 负责系统的优化工作，持续改进各项功能。"
H_GOOD = "2. 热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms。"
JD = """任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟悉 Redis；
3. 有缓存性能优化经验者优先；
4. 熟悉 Kafka 消息队列。"""


def parsed_resume(client, headers, tmp_path, db_session_factory) -> int:
    """上传一份现场生成的 PDF，再手工填好 structure（结构化抽取另有测试）：一个项目两条描述、本科学历、项目里用了 Redis。"""
    from app.models import Resume

    lines = [H_VAGUE, H_GOOD]
    items = [(40, 60, "Education", 12, "hebo"),                       # 凑够字数，否则会被判成扫描件
             (40, 80, "某某大学 计算机科学与技术 本科 2023.09-2027.06，主修数据结构、操作系统、计算机网络、数据库原理", 10.5, "china-s"),
             (40, 110, "Projects", 12, "hebo")]
    items += [(40, 140 + i * 20, t, 10.5, "china-s") for i, t in enumerate(lines)]
    rid = upload_pdf(client, headers, make_pdf(tmp_path / "r.pdf", items)).json()["data"]["id"]
    with db_session_factory() as db:
        resume = db.get(Resume, rid)
        text = resume.full_text
        hs = [{"text": t, "char_start": text.index(t), "char_end": text.index(t) + len(t)} for t in lines]
        edu, redis_at = text.index("某某大学"), text.index("Redis")
        resume.structure = {
            "projects": [{"name": "订单系统", "char_start": hs[0]["char_start"], "char_end": hs[-1]["char_end"], "highlights": hs}],
            "education": [{"degree": "本科", "char_start": edu, "char_end": text.index("\n", edu)}],
            "skill_mentions": [{"skill_id": 3, "surface": "Redis", "char_start": redis_at, "char_end": redis_at + 5,
                                "section_type": "projects"}]}
        db.commit()
    return rid


def review_reply(*items) -> str:
    """诊断：模型对一条经历的审查结果。items: (risk_type, severity, evidence_quote)"""
    import json
    return json.dumps({"findings": [{"risk_type": t, "severity": s, "evidence_quote": q, "reason": "r", "suggestion": "s"}
                                    for t, s, q in items]}, ensure_ascii=False)


def jd_item(req_type, category, skill, quote, content="c") -> dict:
    return {"req_type": req_type, "category": category, "skill": skill, "quote": quote, "content": content}


def jd_reply(*items) -> str:
    import json
    return json.dumps({"requirements": list(items)}, ensure_ascii=False)


def judge_reply(status, unit_no=None) -> str:
    """匹配（RAG）：模型对一条要求的判定。"""
    import json
    return json.dumps({"status": status, "unit_no": unit_no, "reason": "r"}, ensure_ascii=False)


def fulltext_reply(*results) -> str:
    """匹配（全文）：results: (requirement_id, status, evidence_quote)"""
    import json
    return json.dumps({"results": [{"id": i, "status": s, "evidence_quote": q, "reason": "r"} for i, s, q in results]},
                      ensure_ascii=False)


class FakeEmbedder:
    """字符二元组哈希成 64 维词袋：共用的字越多越相似。重排按与 query 的共有字符数打分。"""

    def __init__(self):
        self.embedded: list[str] = []
        self.reranked: list[list[str]] = []

    def embed(self, texts, *, ref=None):
        self.embedded += list(texts)
        return [self._vector(t) for t in texts]

    def rerank(self, query, documents, top_n, *, ref=None):
        self.reranked.append(list(documents))
        scores = [(i, len(set(query) & set(d)) / len(set(query))) for i, d in enumerate(documents)]
        return sorted(scores, key=lambda pair: -pair[1])[:top_n]

    @staticmethod
    def _vector(text: str) -> list[float]:
        import hashlib
        v = [0.0] * 64
        for a, b in zip(text, text[1:]):
            v[int(hashlib.md5((a + b).encode()).hexdigest(), 16) % 64] += 1.0
        return v


@pytest.fixture
def store(client):
    """内存 Chroma + 假向量，替换掉真实的检索库。"""
    import uuid

    import chromadb

    from app.main import app
    from app.retrieval.unit_store import ResumeUnitStore, get_unit_store

    collection = chromadb.EphemeralClient().create_collection(f"t_{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"},
                                                              embedding_function=None)
    unit_store = ResumeUnitStore(collection, FakeEmbedder())
    app.dependency_overrides[get_unit_store] = lambda: unit_store
    return unit_store


@pytest.fixture
def events(client) -> list:
    """收集后台任务推送的进度事件：[(task_id, event, data)]"""
    from app.cache.pubsub import get_publisher
    from app.main import app

    collected: list[tuple[str, str, dict]] = []
    app.dependency_overrides[get_publisher] = lambda: lambda task_id, event, data: collected.append((task_id, event, data))
    return collected


@pytest.fixture
def resume_and_job(client, auth_headers, tmp_path, db_session_factory, fake_llm, store) -> tuple[int, int]:
    """(resume_id, job_id)：岗位有 4 条要求——学历与 Redis 规则可判，另外两条要靠模型。"""
    from app.models import Skill

    with db_session_factory() as db:
        db.add(Skill(id=3, canonical_name="Redis", category="middleware", aliases=[]))
        db.commit()
    rid = parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    fake_llm.replies["_JdOut"] = [jd_reply(
        jd_item("hard", "education", None, "本科及以上学历，计算机相关专业", "本科及以上学历"),
        jd_item("hard", "skill", "Redis", "熟悉 Redis", "熟悉 Redis"),
        jd_item("plus", "experience", None, "有缓存性能优化经验者优先", "有缓存性能优化经验"),
        jd_item("hard", "skill", "Kafka", "熟悉 Kafka 消息队列", "熟悉 Kafka"))]
    jid = client.post("/api/v1/jobs", headers=auth_headers, json={"title": "后端开发", "raw_text": JD}).json()["data"]["id"]
    return rid, jid


def apply(client, headers, rid, jid, **extra) -> dict:
    """POST /apply。TestClient 会同步跑完后台任务，返回时诊断与匹配都已结束。"""
    return client.post("/api/v1/apply", headers=headers, json={"resume_id": rid, "job_id": jid, **extra}).json()
