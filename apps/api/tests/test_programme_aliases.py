"""Programme alias expansion for LWLSSG / 全方位學習津貼 retrieval."""

from __future__ import annotations

from app.services.chat import build_retrieve_query, needs_history_for_retrieve
from app.services.rag import (
    _keyword_score,
    _query_terms,
    expand_programme_aliases,
)


def test_expand_lwlssg_acronym_adds_chinese_full_name():
    q = expand_programme_aliases("LWLSSG 的學生資助")
    assert q.startswith("LWLSSG 的學生資助")
    assert "全方位學習及姊妹學校津貼" in q
    assert "津貼額" in q  # amount / 資助 intent


def test_expand_lwlssg_with_year_and_rates_intent():
    q = expand_programme_aliases("LWLSSG 2026/27 津貼額")
    assert "全方位學習及姊妹學校津貼" in q
    assert "2026/27" in q
    assert "津貼額" in q


def test_expand_short_chinese_name_adds_full_title():
    q = expand_programme_aliases("全方位學習津貼 2026/27 的學生資助")
    assert "全方位學習及姊妹學校津貼" in q
    assert "LWLSSG" in q
    assert "津貼額" in q


def test_expand_is_idempotent():
    once = expand_programme_aliases("LWLSSG 津貼額")
    twice = expand_programme_aliases(once)
    assert once == twice


def test_expand_leaves_unrelated_query_unchanged():
    q = "公民與社會發展科內地考察 2026/27"
    assert expand_programme_aliases(q) == q


def test_query_terms_include_chinese_title_after_lwlssg_alias():
    terms = _query_terms("LWLSSG 2026/27 津貼額")
    assert "2026/27" in terms
    assert any("全方位學習及姊妹學校津貼" in t for t in terms)
    assert any("津貼額" in t for t in terms)


def test_keyword_score_lwlssg_acronym_prefers_grant_rates_title():
    q = "LWLSSG 的學生資助"
    terms = _query_terms(q)
    amount = _keyword_score(
        terms,
        "全方位學習及姊妹學校津貼2026/27學年津貼額",
        None,
        "小學 $990 中學 $1,350",
        query=q,
    )
    other = _keyword_score(
        terms,
        "校本課後學習及支援計劃-資料及申請簡介",
        None,
        "學生資助 全方位學習活動 支援 LWLSSG",
        query=q,
    )
    assert amount > other
    assert amount >= 0.85


def test_build_retrieve_query_expands_lwlssg_alias():
    q = build_retrieve_query("LWLSSG 的學生資助", [])
    assert "全方位學習及姊妹學校津貼" in q
    assert "津貼額" in q


def test_lwlssg_counts_as_retrieve_topic_cue():
    assert needs_history_for_retrieve("LWLSSG？") is False
