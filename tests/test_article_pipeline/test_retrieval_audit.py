"""Retrieval-layer audit tests — relevance gating, determinism, provenance.

Deliberately offline: no MCP, no SSH, no DuckDuckGo. Every external boundary is
either a temp SQLite file or a stub injected into sys.modules.
"""
import json
import sqlite3
import subprocess
import sys
import types

import pytest

from article_pipeline import research
from article_pipeline.research import (
    _annotation_db_paths,
    _assemble_note,
    _extract_data_points,
    _filter_relevant_annotations,
    _is_content_farm,
    _keyword_tokens,
    _provenance,
    _relevance_score,
    _resolve_encoding,
    _route_topics,
    _search_annotations_sqlite,
    _search_cocobook_ssh,
    build_research_note,
    search_web,
)
from article_pipeline.topic_filter import BenchmarkTopicFilter

ANNOTATION_SCHEMA = """
CREATE TABLE annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER, book_title TEXT, author TEXT, library TEXT,
    claim TEXT, context TEXT, claim_type TEXT, applicable_to TEXT,
    verified_by TEXT, verified_date TEXT, quality TEXT, created_at TEXT
);
"""

# The real failure this module exists to prevent: a systemd article that got
# CPU-architecture and animation-timing claims injected as knowledge.
OFF_TOPIC_ROWS = [
    ("计算机组成与设计", "Patterson", "CPU 时间 = 指令数 × CPI × 时钟周期",
     "第一章 性能公式", "principle", "A"),
    ("Timing for Animation", "Whitaker", "动画的节奏由每个动作的帧数决定",
     "第三章 节奏", "principle", "A"),
    ("影响力", "Cialdini", "承诺与一致原理让人坚持既有选择",
     "第三章", "principle", "B"),
]
ON_TOPIC_ROWS = [
    ("Linux 系统管理手册", "Nemeth", "systemd 的 timer 单元用 OnCalendar 表达周期，"
     "精度受 AccuracySec 限制，默认一分钟",
     "服务管理章节", "technique", "A"),
    ("Systemd 实战", "某译者", "定时器单元需要同名的 service 单元配合，"
     "否则 systemctl list-timers 看不到它",
     "第二章", "technique", "B"),
]


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.executescript(ANNOTATION_SCHEMA)
    conn.executemany(
        "INSERT INTO annotations (book_title, author, claim, context, claim_type, quality)"
        " VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


# ---- topic routing ----

def test_route_topics_returns_empty_for_unrelated_keyword():
    """No index matches 'systemd 定时器' → retrieve nothing, not WordPress docs.

    Regression: the old fallback injected 3 WordPress indexes for ANY unmatched
    keyword, under the heading '官方文档原文段落，这是最高质量的写作参考'.
    """
    assert _route_topics("systemd 定时器怎么调试") == []


def test_route_topics_still_matches_known_signals():
    topics = _route_topics("WordPress 插件缓存")
    assert "wordpress-developer-docs" in topics
    # Deterministic order (was iteration order of a set).
    assert topics == _route_topics("WordPress 插件缓存")
    assert topics == sorted(topics)


# ---- relevance gate ----

def test_keyword_tokens_covers_ascii_and_cjk():
    tokens = _keyword_tokens("systemd 定时器")
    assert "systemd" in tokens
    assert "定时" in tokens and "时器" in tokens


def test_relevance_score_weights_body_above_metadata():
    body_hit = _relevance_score({"claim": "systemd 单元"}, {"systemd"})
    meta_hit = _relevance_score({"book": "systemd 手册"}, {"systemd"})
    assert body_hit > meta_hit


def test_filter_drops_topic_blind_matches():
    items = [dict(book=b, author=a, claim=c, context=ctx, type=t, quality=q)
             for b, a, c, ctx, t, q in OFF_TOPIC_ROWS + ON_TOPIC_ROWS]
    kept = _filter_relevant_annotations(items, "systemd 定时器")
    claims = [k["claim"] for k in kept]
    assert all("CPI" not in c for c in claims), "CPU formula must not survive"
    assert all("动画" not in c for c in claims), "animation timing must not survive"
    assert any("systemd" in c for c in claims)


def test_filter_is_deterministic_and_ranked():
    items = [dict(book=b, author=a, claim=c, context=ctx, type=t, quality=q)
             for b, a, c, ctx, t, q in ON_TOPIC_ROWS + OFF_TOPIC_ROWS]
    first = [i["claim"] for i in _filter_relevant_annotations(list(items), "systemd 定时器")]
    second = [i["claim"] for i in _filter_relevant_annotations(list(items), "systemd 定时器")]
    assert first == second
    scores = [i["_relevance"] for i in
              _filter_relevant_annotations(list(items), "systemd 定时器")]
    assert scores == sorted(scores, reverse=True)


def test_keyword_tokens_drops_function_word_bigrams():
    """'为什么' produced the bigrams 为什/什么/么不, which match nearly every
    Chinese sentence — the gate was leaking through them."""
    tokens = _keyword_tokens("systemd 定时器为什么不触发")
    assert "为什" not in tokens and "什么" not in tokens and "么不" not in tokens
    assert {"systemd", "定时", "时器", "触发"} <= tokens


def test_cjk_bigram_collision_alone_is_not_enough_for_technical_keyword():
    """Real leak found while smoke-testing: an annotation about 触发情绪 scored a
    hit for '...定时器为什么不触发' via the bigram 触发."""
    items = [{"claim": "“情绪日记”可以识别触发情绪的模式", "book": "情绪控制课"}]
    assert _filter_relevant_annotations(items, "systemd 定时器为什么不触发") == []


def test_cjk_only_keyword_still_matches_cjk_material():
    items = [{"claim": "病毒式增长的关键在于用户之间的分享机制", "book": "增长黑客"}]
    assert len(_filter_relevant_annotations(items, "如何做好用户增长")) == 1


def test_mixed_keyword_keeps_strong_cjk_match():
    """A Chinese claim with several keyword bigrams survives even without the
    latin term, so 'WordPress 缓存插件' still finds Chinese cache material."""
    items = [{"claim": "缓存插件的关键是命中率与失效策略", "book": "性能优化"}]
    assert len(_filter_relevant_annotations(items, "WordPress 缓存插件怎么选")) == 1


def test_filter_keeps_everything_when_keyword_has_no_tokens():
    items = [{"claim": "x"}]
    assert _filter_relevant_annotations(items, "!!") == items


# ---- SQLite annotation lookup ----

def test_sqlite_lookup_is_deterministic(tmp_path):
    """No ORDER BY RANDOM(): repeated runs return identical material."""
    db = _make_db(tmp_path / "a.db", ON_TOPIC_ROWS + OFF_TOPIC_ROWS)
    runs = [[r["claim"] for r in _search_annotations_sqlite(
        db, "systemd 定时器", ["technique", "principle"], 5)] for _ in range(5)]
    assert all(r == runs[0] for r in runs)
    assert runs[0], "expected at least one relevant annotation"


def test_sqlite_lookup_excludes_off_topic(tmp_path):
    db = _make_db(tmp_path / "a.db", ON_TOPIC_ROWS + OFF_TOPIC_ROWS)
    rows = _search_annotations_sqlite(db, "systemd 定时器",
                                      ["technique", "principle"], 10)
    assert rows
    for r in rows:
        assert "CPI" not in r["claim"] and "动画" not in r["claim"]


def test_sqlite_lookup_no_wildcard_blowup(tmp_path):
    """'的' and spaces must not become SQL wildcards.

    Old code did keyword.replace('的', '%').replace(' ', '%'), so '缓存的配置'
    became '%缓存%配置%' — and with ORDER BY RANDOM() any loosely matching row
    could win. A keyword sharing no token with the corpus must return nothing.
    """
    db = _make_db(tmp_path / "a.db", OFF_TOPIC_ROWS)
    rows = _search_annotations_sqlite(db, "Nginx 的反向代理配置",
                                      ["technique", "principle"], 10)
    assert rows == []


def test_sqlite_lookup_records_provenance(tmp_path):
    db = _make_db(tmp_path / "anno.db", ON_TOPIC_ROWS)
    rows = _search_annotations_sqlite(db, "systemd 定时器", ["technique"], 5)
    assert rows
    for r in rows:
        assert r["_origin"].startswith("anno.db#")  # traceable to the exact row
        assert r["book"] and r["quality"]


def test_sqlite_lookup_prefers_quality_on_equal_relevance(tmp_path):
    rows = [
        ("B 书", "作者B", "systemd 定时器 的说明", "", "technique", "B"),
        ("A 书", "作者A", "systemd 定时器 的说明", "", "technique", "A"),
    ]
    db = _make_db(tmp_path / "a.db", rows)
    got = _search_annotations_sqlite(db, "systemd 定时器", ["technique"], 2)
    assert [r["quality"] for r in got] == ["A", "B"]


def test_annotation_db_paths_skips_empty_primary(tmp_path, monkeypatch):
    """The published DB has been a 0-byte placeholder since 2026-05-21."""
    empty = tmp_path / "published.db"
    empty.touch()
    stage = _make_db(tmp_path / "stage.db", ON_TOPIC_ROWS)
    monkeypatch.setattr(research, "ANNOTATIONS_DB", str(empty))
    monkeypatch.setattr(research, "ANNOTATIONS_DB_FALLBACKS", [str(stage)])
    paths = [p.name for p in _annotation_db_paths()]
    assert paths == ["stage.db"]


def test_search_annotations_falls_back_to_populated_db(tmp_path, monkeypatch):
    empty = tmp_path / "published.db"
    empty.touch()
    stage = _make_db(tmp_path / "stage.db", ON_TOPIC_ROWS + OFF_TOPIC_ROWS)
    monkeypatch.setattr(research, "ANNOTATIONS_DB", str(empty))
    monkeypatch.setattr(research, "ANNOTATIONS_DB_FALLBACKS", [str(stage)])
    monkeypatch.setattr(research, "_mcp_call", lambda *a, **k: None)
    rows = research._search_annotations("systemd 定时器", "tutorial", limit=5)
    assert rows and all("CPI" not in r["claim"] for r in rows)


# ---- SSH fallback hardening ----

def test_ssh_fallback_survives_undecodable_output(monkeypatch):
    """kk-pc's WSL prints a UTF-16 error; strict decode used to raise
    UnicodeDecodeError *inside* subprocess.run, killing the research stage."""
    def boom(*a, **k):
        raise UnicodeDecodeError("utf-8", b"\xfb", 0, 1, "invalid start byte")
    monkeypatch.setattr(subprocess, "run", boom)
    assert _search_cocobook_ssh("systemd", 5) == []


def test_ssh_fallback_drops_error_payload(monkeypatch):
    captured = {}

    class R:
        returncode = 0
        stdout = json.dumps([{"error": "index missing"},
                             {"title": "Book", "text": "body"}])
        stderr = ""

    def fake_run(cmd, **k):
        captured["cmd"] = cmd
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = _search_cocobook_ssh("systemd", 5)
    assert [o.get("title") for o in out] == ["Book"]
    assert out[0]["_origin"]


def test_ssh_fallback_quotes_query(monkeypatch):
    captured = {}

    class R:
        returncode = 0
        stdout = "[]"
        stderr = ""

    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: (captured.__setitem__("cmd", cmd), R())[1])
    import shlex
    malicious = "it's a 'test'; echo pwned"
    _search_cocobook_ssh(malicious, 5)
    remote = captured["cmd"][-1]
    # The query must appear exactly once, shell-quoted, so `;` cannot start a
    # second command on kk-pc.
    assert shlex.quote(malicious) in remote
    assert remote.endswith(f"{shlex.quote(malicious)} 5")


def test_ssh_fallback_returns_empty_on_nonzero_exit(monkeypatch):
    class R:
        returncode = 255
        stdout = "Failed to attach disk"
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: R())
    assert _search_cocobook_ssh("systemd", 5) == []


# ---- web layer ----

def test_content_farm_filter_covers_cloud_dev_communities():
    assert _is_content_farm("https://cloud.tencent.com/developer/article/1")
    assert _is_content_farm("https://developer.aliyun.com/article/1")
    assert _is_content_farm("https://blog.csdn.net/x/article/details/1")
    assert _is_content_farm("https://zhuanlan.zhihu.com/p/1")
    assert not _is_content_farm("https://www.nginx.com/blog/x/")
    assert not _is_content_farm("https://developer.wordpress.org/reference/")


def _stub_ddgs(monkeypatch, hits):
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results=10):
            return hits

    mod = types.ModuleType("ddgs")
    mod.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", mod)


def test_search_web_caps_results_per_host(monkeypatch):
    hits = [{"title": f"T{i}", "href": f"https://one-site.example/{i}", "body": "b"}
            for i in range(6)]
    hits += [{"title": "Other", "href": "https://other.example/1", "body": "b"}]
    _stub_ddgs(monkeypatch, hits)
    out = search_web("q", limit=5)
    hosts = [h["url"].split("/")[2] for h in out]
    assert hosts.count("one-site.example") <= research.MAX_RESULTS_PER_HOST
    assert "other.example" in hosts


def test_search_web_records_origin(monkeypatch):
    _stub_ddgs(monkeypatch, [{"title": "T", "href": "https://a.example/1", "body": "b"}])
    out = search_web("nginx cache", limit=3)
    assert out[0]["_origin"].startswith("DuckDuckGo")
    assert out[0]["url"] == "https://a.example/1"


def test_resolve_encoding_uses_apparent_when_charset_missing():
    class R:
        headers = {"Content-Type": "text/html"}
        encoding = "ISO-8859-1"
        apparent_encoding = "GB2312"
    assert _resolve_encoding(R()) == "GB2312"


def test_resolve_encoding_respects_declared_charset():
    class R:
        headers = {"Content-Type": "text/html; charset=utf-8"}
        encoding = "utf-8"
        apparent_encoding = "GB2312"
    assert _resolve_encoding(R()) == "utf-8"


# ---- provenance & note assembly ----

def test_provenance_includes_book_author_quality_and_row():
    cite = _provenance({"book": "Linux 系统管理手册", "author": "Nemeth",
                        "quality": "A", "_origin": "stage.db#42"})
    assert "Linux 系统管理手册" in cite
    assert "Nemeth" in cite
    assert "A级标注" in cite
    assert "stage.db#42" in cite


def test_provenance_flags_unverified_ai_annotations():
    """All 1504 rows in the live corpus are quality='AI_draft' /
    verified_by='ai-draft' — LLM paraphrases of books, never human-checked. The
    note must say so instead of implying a graded human annotation."""
    cite = _provenance({"book": "某书", "quality": "AI_draft"})
    assert "未经人工核验" in cite
    assert "AI_draft级标注" not in cite


def test_data_point_source_label_not_empty_for_annotations():
    """Regression: annotations key the book as 'book', but _extract_data_points
    read 'title' — every insight rendered as '(来源: )'."""
    sources = {"cocobook": [{"_source": "annotations", "book": "某书",
                             "author": "某人", "claim": "一个观点",
                             "type": "principle"}]}
    points = _extract_data_points(sources)
    assert points and "(来源: )" not in points[0]
    assert "某书" in points[0]


def test_data_points_accept_unterminated_snippets():
    """DDG snippets are cut mid-sentence; requiring a trailing 。 threw away
    every number they contained."""
    sources = {"web": [{"title": "报告", "url": "https://x.example/r",
                        "snippet": "缓存命中率提升到 92% 后源站负载下降"}]}
    points = _extract_data_points(sources)
    assert any("92%" in p for p in points)
    assert any("https://x.example/r" in p for p in points)


def test_note_keeps_urls_for_web_material():
    sources = {
        "web": [{"title": "文章", "url": "https://nginx.org/en/docs/x.html",
                 "snippet": "缓存命中率提升 32%"}],
        "web_articles": [{"title": "文章", "url": "https://nginx.org/en/docs/x.html",
                          "text": "第一段内容" * 20}],
    }
    note = build_research_note("nginx 缓存", sources)
    assert "https://nginx.org/en/docs/x.html" in note


def test_note_shows_annotation_provenance():
    sources = {"annotations": [{"book": "Linux 系统管理手册", "author": "Nemeth",
                               "quality": "A", "type": "technique",
                               "claim": "timer 单元的精度受 AccuracySec 限制",
                               "context": "服务管理章节",
                               "_origin": "stage.db#42"}]}
    note = build_research_note("systemd 定时器", sources)
    assert "出处:" in note
    assert "Nemeth" in note and "stage.db#42" in note


def test_assemble_note_sacrifices_style_before_facts():
    """The old builder hard-cut the tail at 8000 chars, and style samples are
    emitted first — so facts were what got deleted."""
    style = ["### 写作范本"] + [f"{i}. 风格样例" + "文" * 200 for i in range(40)]
    facts = ["### 关键素材"] + [f"- 数据: 事实 {i} (来源: https://x.example/{i})"
                                for i in range(10)]
    note = _assemble_note([(4, style), (1, facts)], budget=3000)
    assert len(note) <= 3200
    for i in range(10):
        assert f"事实 {i} " in note
    assert "[... 已截断" in note


def test_assemble_note_no_marker_when_within_budget():
    note = _assemble_note([(1, ["### A", "- x"])], budget=1000)
    assert "已截断" not in note


def test_build_research_note_facts_survive_huge_style_block():
    sources = {
        "topic_paragraphs": [{"text": "官方文档段落" * 60, "section": f"S{i}",
                              "topic": "nginx-docs"} for i in range(8)],
        "writing_craft": [{"title": "文心雕龙", "text": "文采" * 150}
                          for _ in range(6)],
        "writing_samples": [{"quality": "A", "type": "principle",
                             "claim": "样例" * 100} for _ in range(5)],
        "annotations": [{"book": "书", "author": "人", "type": "technique",
                         "quality": "A", "claim": f"关键结论{i}",
                         "_origin": f"stage.db#{i}"} for i in range(5)],
        "web": [{"title": "T", "url": "https://nginx.org/a", "snippet": "缓存 32%"}],
        "code": [{"file": "/home/x/nginx.conf"}],
    }
    note = build_research_note("nginx 缓存", sources)
    assert len(note) <= research.NOTE_CHAR_BUDGET + 40
    for i in range(5):
        assert f"关键结论{i}" in note, "book-sourced claims must survive truncation"
    assert "/home/x/nginx.conf" in note, "code evidence must survive truncation"


def test_facts_come_before_style_in_the_note():
    """outline.py feeds only research_note[:2000] to the outline prompt, so the
    facts must be at the top or the skeleton is planned blind."""
    sources = {
        "topic_paragraphs": [{"text": "官方文档段落" * 60, "section": f"S{i}",
                              "topic": "nginx-docs"} for i in range(8)],
        "writing_craft": [{"title": "文心雕龙", "text": "文采" * 150}
                          for _ in range(6)],
        "annotations": [{"book": "书", "author": "人", "type": "technique",
                         "quality": "A", "claim": "关键结论",
                         "_origin": "stage.db#1"}],
        "web": [{"title": "T", "url": "https://nginx.org/a",
                 "snippet": "开启代理缓存后源站请求下降 32%"}],
    }
    note = build_research_note("nginx 缓存", sources)
    head = note[:2000]
    assert "关键结论" in head
    assert note.index("### 相关观点") < note.index("### 写作范本")
    assert note.index("### 关键素材") < note.index("### 原文范本")


def test_writer_sample_format_preserved():
    """writer._extract_samples parses '1. [A级|principle] ...' — keep it intact."""
    from article_pipeline.writer import _extract_samples
    sources = {"writing_samples": [{"quality": "A", "type": "principle",
                                    "claim": "一个判断"}]}
    note = build_research_note("kw", sources)
    assert _extract_samples(note)


def test_unique_claims_requires_topical_relevance():
    """The 'unique' test is low-overlap-with-search, which off-topic claims pass
    trivially — and non-empty unique_claims can carry an article through the
    publish gate. Relevance must come first."""
    annotations = [
        {"claim": "CPU 时间 = 指令数 × CPI × 时钟周期", "book": "计算机组成与设计"},
        {"claim": "systemd 定时器的精度受 AccuracySec 限制", "book": "Linux 系统管理手册"},
    ]
    ddg = [{"title": "systemd timer 教程", "snippet": "OnCalendar 用法"}]
    claims = research.extract_unique_claims(annotations, ddg, keyword="systemd 定时器")
    assert claims == ["systemd 定时器的精度受 AccuracySec 限制"]


def test_unique_claims_without_keyword_is_backwards_compatible():
    annotations = [{"claim": "一个完全无关的论断", "book": "某书"}]
    assert research.extract_unique_claims(annotations, []) == ["一个完全无关的论断"]


# ---- topic filter ----

def _results(titles, body="内容"):
    return [{"title": t, "snippet": body} for t in titles]


def test_benchmark_filter_reads_snippet_key():
    """research.search_web() returns 'snippet'; the filter only read 'body',
    so every filter that inspects result text was blind."""
    results = [{"title": "标题", "snippet": "nginx 缓存配置报错怎么解决 教程 文档"}] * 6
    bf = BenchmarkTopicFilter(search_results=results)
    bf.keyword, bf.category = "nginx 缓存配置", ""
    assert bf._check_search_volume() is True
    assert bf._check_pain_point() is True
    assert bf._check_material_availability() is True


def test_benchmark_filter_body_key_still_works():
    results = [{"title": "标题", "body": "nginx 缓存配置报错怎么解决 教程 文档"}] * 6
    bf = BenchmarkTopicFilter(search_results=results)
    bf.keyword, bf.category = "nginx 缓存配置", ""
    assert bf._check_search_volume() is True


def test_differentiation_not_tripped_by_the_keyword_itself():
    """Old logic: any token in >=50% of titles → homogeneous. Search titles
    almost always contain the keyword, so this was near-always False."""
    bf = BenchmarkTopicFilter(search_results=_results([
        "Nginx 缓存配置错误的排查记录",
        "Nginx 缓存为什么不生效",
        "用 Nginx 缓存挡住突发流量",
        "Nginx 缓存与 CDN 的分工",
        "Nginx 缓存踩过的五个坑",
    ]))
    bf.keyword, bf.category = "Nginx 缓存配置错误", ""
    assert bf._check_differentiation() is True


def test_differentiation_still_detects_real_homogeneity():
    bf = BenchmarkTopicFilter(search_results=_results([
        "Python 入门教程完全指南",
        "Python 入门教程从零开始",
        "Python 入门教程新手必看",
        "Python 入门教程详解",
        "Python 入门教程速成",
    ]))
    bf.keyword, bf.category = "Python 入门", ""
    assert bf._check_differentiation() is False


def test_differentiation_skips_small_samples():
    bf = BenchmarkTopicFilter(search_results=_results(["A 教程", "B 教程"]))
    bf.keyword, bf.category = "systemd 定时器排错", ""
    assert bf._check_differentiation() is True


@pytest.mark.parametrize("keyword,expected", [
    ("Nginx 缓存配置错误修复", True),
    ("什么是Nginx", False),
    ("Nginx 源码分析", False),
])
def test_writability_unchanged(keyword, expected):
    bf = BenchmarkTopicFilter(search_results=[])
    bf.keyword, bf.category = keyword, ""
    assert bf._check_writability() is expected
