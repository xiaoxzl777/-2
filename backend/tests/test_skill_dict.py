import pytest

from app.matching.skill_dict import SkillDict, SkillEntry, annotate_skills, mentioned_in_experience
from scripts.dump_seed import load_skills

ENTRIES = [
    SkillEntry(1, "Java", ("JDK",)),
    SkillEntry(2, "JavaScript", ("JS", "ES6")),
    SkillEntry(3, "Spring Boot", ("SpringBoot", "spring-boot")),
    SkillEntry(4, "Spring", ("Spring Framework",)),
    SkillEntry(5, "C++", ("CPP",)),
    SkillEntry(6, "C", ("C语言",)),
    SkillEntry(7, "Go", ("Golang",)),
    SkillEntry(8, "微服务", ("微服务架构", "Microservices")),
    SkillEntry(9, "Redis", ("Redis缓存",)),
    SkillEntry(10, ".NET", ("dotnet",)),
    SkillEntry(11, "Kubernetes", ("K8s",)),
]
D = SkillDict(ENTRIES)


def _found(text: str) -> list[tuple[str, str]]:
    return [(D.names[i], text[s:e]) for i, s, e in D.find(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("使用 SpringBoot 开发", [("Spring Boot", "SpringBoot")]),
        ("基于spring-boot与Spring Framework", [("Spring Boot", "spring-boot"), ("Spring", "Spring Framework")]),
        ("熟悉Java、JavaScript", [("Java", "Java"), ("JavaScript", "JavaScript")]),     # Java 不会吃掉 JavaScript 的前缀
        ("C++ 与 C语言，了解 C", [("C++", "C++"), ("C", "C语言"), ("C", "C")]),          # 长的写法优先
        ("落地微服务架构，拆分微服务", [("微服务", "微服务架构"), ("微服务", "微服务")]),
        ("Redis缓存预热，REDIS 集群", [("Redis", "Redis缓存"), ("Redis", "REDIS")]),      # 大小写不敏感
        ("用 Go 写网关，部署到 k8s", [("Go", "Go"), ("Kubernetes", "k8s")]),
        ("了解 .NET 平台", [(".NET", ".NET")]),
    ],
)
def test_find(text, expected):
    assert _found(text) == expected


@pytest.mark.parametrize(
    "text",
    ["Google 搜索与 Django", "let's go ahead", "category 与 Cache", "JSON 解析、JSX 语法", "Javas", "英语 CET-6"],
)
def test_no_false_positives_inside_other_words(text):
    assert _found(text) == []


def test_short_words_are_case_sensitive_but_long_ones_are_not():
    assert _found("GO") == [] and _found("js") == []
    assert _found("JS") == [("JavaScript", "JS")] and _found("golang") == [("Go", "golang")]


def test_lookup_whole_word():
    assert D.lookup(" springboot ") == 3 and D.lookup("K8S") == 11 and D.lookup("JS") == 2
    assert D.lookup("js") is None and D.lookup("Feign") is None and D.lookup("") is None


def test_annotate_structure():
    text = "专业技能\n熟悉 SpringBoot、Feign\n项目经历\n订单系统\n基于 spring-boot 与 Redis缓存 开发"
    sections = [{"type": "skills", "char_start": 0, "char_end": 23},
                {"type": "projects", "char_start": 24, "char_end": len(text)}]
    structure = {"skills": [{"name": "SpringBoot"}, {"name": "Feign"}], "work": [],
                 "projects": [{"tech_stack": [{"name": "redis", "skill_id": None}, {"name": "Seata", "skill_id": None}]}]}

    annotate_skills(structure, text, sections, D)

    assert [(m["surface"], m["section_type"], m["skill_id"]) for m in structure["skill_mentions"]] == [
        ("SpringBoot", "skills", 3), ("spring-boot", "projects", 3), ("Redis缓存", "projects", 9)]
    assert all(text[m["char_start"]:m["char_end"]] == m["surface"] for m in structure["skill_mentions"])
    assert [s["skill_id"] for s in structure["skills"]] == [3, None]            # 词典里没有 Feign
    assert [t["skill_id"] for t in structure["projects"][0]["tech_stack"]] == [9, None]
    assert mentioned_in_experience(structure) == {3, 9}


def test_the_real_seed_dictionary_compiles_and_works():
    seed = SkillDict(SkillEntry(s["id"], s["canonical_name"], tuple(s["aliases"])) for s in load_skills())
    assert len(seed) >= 100
    text = "基于 LangGraph 构建意图识别节点，使用 Chroma 向量库与 FastAPI，部署在 k8s；熟悉 MySQL 索引优化"
    names = {seed.names[i] for i, _, _ in seed.find(text)}
    assert {"LangGraph", "Chroma", "FastAPI", "Kubernetes", "MySQL", "索引优化"} <= names
