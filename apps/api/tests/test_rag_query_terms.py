"""Unit tests for hybrid keyword term extraction and scoring."""

from app.services.rag import _keyword_score, _query_terms


def test_query_terms_keeps_academic_year_not_bare_year():
    terms = _query_terms("全方位學習津貼 2026/27 的學生資助")
    assert "2026/27" in terms
    assert "2026" not in terms
    assert any("全方位學習津貼" in t for t in terms)


def test_query_terms_circular_number():
    terms = _query_terms("EDBC009/2025 津貼額")
    assert any(t.replace(" ", "").upper().startswith("EDBC009/2025") for t in terms)
    assert "2025" not in terms


def test_query_terms_empty():
    assert _query_terms("") == []
    assert _query_terms("   ") == []


def test_keyword_score_prefers_title_match_over_content_only():
    terms = _query_terms("全方位學習及姊妹學校津貼 2026/27 學年津貼額")
    title = "全方位學習及姊妹學校津貼2026/27學年津貼額"
    title_score = _keyword_score(terms, title, None, "其他無關內文")
    weak_score = _keyword_score(
        terms,
        "校本課後學習及支援計劃",
        None,
        "本計劃提供學生資助安排，適用於 2025/26 學年。",
    )
    assert title_score > weak_score
    assert title_score >= 0.7


def test_keyword_score_amount_doc_beats_unrelated_subsidy():
    """Regression: prod miss of LWLSSG 2026/27 grant-rates PDF."""
    terms = _query_terms("全方位學習津貼 2026/27 的學生資助")
    amount = _keyword_score(
        terms,
        "全方位學習及姊妹學校津貼2026/27學年津貼額",
        None,
        "小學 $990 中學 $1,350",
    )
    other = _keyword_score(
        terms,
        "校本課後學習及支援計劃-資料及申請簡介",
        None,
        "學生資助 全方位學習活動 支援",
    )
    assert amount > other
