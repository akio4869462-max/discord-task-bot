import json

import pytest

import news_logic


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ITmedia Total</title>
    <item>
      <title>生成AIの最新動向まとめ</title>
      <link>https://example.com/ai-news</link>
    </item>
    <item>
      <title>Pythonの新バージョンがリリース</title>
      <link>https://example.com/python-news</link>
    </item>
    <item>
      <title>タイトルにキーワードなし</title>
      <link>https://example.com/other-news</link>
    </item>
    <item>
      <title/>
    </item>
  </channel>
</rss>
"""


# ====================================================
# parse_rss_items
# ====================================================

def test_parse_rss_items_extracts_title_and_link():
    articles = news_logic.parse_rss_items(SAMPLE_RSS)

    assert len(articles) == 4
    assert articles[0] == {"title": "生成AIの最新動向まとめ", "link": "https://example.com/ai-news"}


def test_parse_rss_items_missing_title_or_link_falls_back_to_empty_string():
    articles = news_logic.parse_rss_items(SAMPLE_RSS)

    # 4件目は<title/>が空・<link>が存在しないが、クラッシュせず空文字になる
    assert articles[3] == {"title": "", "link": ""}


def test_parse_rss_items_invalid_xml_raises():
    with pytest.raises(Exception):
        news_logic.parse_rss_items("これはXMLではない")


# ====================================================
# filter_articles
# ====================================================

def test_filter_articles_matches_keyword_in_title():
    articles = [{"title": "生成AIの最新動向", "link": "url1"}]
    result = news_logic.filter_articles(articles, ["生成AI"])

    assert len(result) == 1
    assert result[0]["word"] == "生成AI"


def test_filter_articles_is_case_insensitive():
    articles = [{"title": "PYTHONの新機能", "link": "url1"}]
    result = news_logic.filter_articles(articles, ["python"])

    assert len(result) == 1


def test_filter_articles_no_match_returns_empty():
    articles = [{"title": "無関係な記事", "link": "url1"}]
    assert news_logic.filter_articles(articles, ["Kubernetes"]) == []


def test_filter_articles_uses_first_matched_keyword():
    articles = [{"title": "AWSとDockerの比較", "link": "url1"}]
    result = news_logic.filter_articles(articles, ["AWS", "Docker"])

    assert result[0]["word"] == "AWS"


# ====================================================
# build_news_message
# ====================================================

def make_articles(count):
    return [
        {"title": f"記事{i}", "link": f"https://example.com/{i}", "word": "AI"}
        for i in range(count)
    ]


def test_build_news_message_no_match_lists_stock_keywords():
    msg = news_logic.build_news_message([], ["AI", "Docker"])

    assert "見つかりませんでした" in msg
    assert "AI, Docker" in msg


def test_build_news_message_contains_title_and_link():
    msg = news_logic.build_news_message(make_articles(1), ["AI"])

    assert "記事0" in msg
    assert "https://example.com/0" in msg
    assert "[AI]" in msg


def test_build_news_message_caps_at_max_display_articles():
    msg = news_logic.build_news_message(make_articles(10), ["AI"])

    assert f"記事{news_logic.MAX_DISPLAY_ARTICLES - 1}" in msg
    assert f"記事{news_logic.MAX_DISPLAY_ARTICLES}" not in msg


# ====================================================
# load_stock_keywords / get_it_news
# ====================================================

@pytest.fixture
def glossary_file(tmp_path, monkeypatch):
    # load_stock_keywords()は学習用語とニュース追跡語の双方を読むため、
    # 片方だけ差し替えると実データ(data/news_keywords.json)を巻き込んでしまう
    path = tmp_path / "glossary.json"
    monkeypatch.setattr(news_logic, "GLOSSARY_FILE", str(path))
    monkeypatch.setattr(news_logic, "NEWS_KEYWORDS_FILE", str(tmp_path / "news_keywords.json"))
    return path


def test_load_stock_keywords_missing_file_returns_empty(glossary_file):
    assert news_logic.load_stock_keywords() == []


def test_load_stock_keywords_broken_json_returns_empty(glossary_file):
    glossary_file.write_text("{壊れたJSON", encoding="utf-8")
    assert news_logic.load_stock_keywords() == []


def test_load_stock_keywords_returns_keys(glossary_file):
    glossary_file.write_text(json.dumps({"AI": "説明", "Docker": "説明"}), encoding="utf-8")
    assert news_logic.load_stock_keywords() == ["AI", "Docker"]


def test_get_it_news_without_keywords_returns_guide_message(glossary_file):
    msg = news_logic.get_it_news()
    assert "用語がストックされていません" in msg


def test_get_it_news_filters_with_mocked_feed(glossary_file, monkeypatch):
    glossary_file.write_text(json.dumps({"生成AI": "説明"}), encoding="utf-8")
    monkeypatch.setattr(news_logic, "fetch_rss", lambda url=None: SAMPLE_RSS)

    msg = news_logic.get_it_news()

    assert "生成AIの最新動向まとめ" in msg
    assert "https://example.com/ai-news" in msg


def test_get_it_news_network_error_returns_error_message(glossary_file, monkeypatch):
    glossary_file.write_text(json.dumps({"AI": "説明"}), encoding="utf-8")

    def broken_fetch(url=None):
        raise OSError("接続エラー")

    monkeypatch.setattr(news_logic, "fetch_rss", broken_fetch)

    msg = news_logic.get_it_news()
    assert "エラーが発生しました" in msg

# ====================================================
# 未知語検出（extract_term_candidates / detect_unknown_terms）
# ====================================================

def test_extract_strips_feed_prefix():
    """「[ITmedia News] 」の媒体名プレフィックスは候補に含めない"""
    got = news_logic.extract_term_candidates("[ITmedia News] エージェント基盤の話")
    assert "ITmedia" not in got
    assert "News" not in got
    assert "エージェント" in got


def test_extract_alpha_terms_adjacent_to_japanese():
    """日本語に挟まれた英字も抽出する（はUnicodeでは境界にならないため）"""
    got = news_logic.extract_term_candidates("OpenAIのLLMとDuckDBの活用")
    assert {"OpenAI", "LLM", "DuckDB"} <= got


def test_extract_ignores_short_katakana():
    """2文字以下のカタカナはノイズになりやすいので拾わない"""
    assert "アプ" not in news_logic.extract_term_candidates("アプの話")


def test_extract_removes_stopwords():
    got = news_logic.extract_term_candidates("システムのデータをランキング表示")
    assert got == set()


def test_detect_unknown_terms_excludes_registered_terms():
    articles = [{"title": "RAGとエージェントの活用", "link": "u1"}]
    got = news_logic.detect_unknown_terms(articles, ["RAG"])
    assert [t["term"] for t in got] == ["エージェント"]


def test_detect_unknown_terms_is_case_insensitive_against_glossary():
    articles = [{"title": "OpenAIの動向", "link": "u1"}]
    assert news_logic.detect_unknown_terms(articles, ["openai"]) == []


def test_detect_unknown_terms_sorts_by_frequency():
    articles = [
        {"title": "エージェントの話", "link": "u1"},
        {"title": "エージェントとRAG", "link": "u2"},
        {"title": "エージェント基盤", "link": "u3"},
        {"title": "RAGの話", "link": "u4"},
        {"title": "ヒューマノイド", "link": "u5"},
    ]
    got = news_logic.detect_unknown_terms(articles, [])
    assert [t["term"] for t in got] == ["エージェント", "RAG", "ヒューマノイド"]
    assert got[0]["count"] == 3


def test_detect_unknown_terms_counts_each_article_once():
    """同一記事内に同じ語が複数回出ても1件として数える"""
    articles = [{"title": "RAG、RAG、またRAG", "link": "u1"}]
    got = news_logic.detect_unknown_terms(articles, [])
    assert got[0]["count"] == 1


def test_detect_unknown_terms_keeps_example_article():
    articles = [{"title": "RAGの解説記事", "link": "https://example.com/rag"}]
    got = news_logic.detect_unknown_terms(articles, [])
    assert got[0]["title"] == "RAGの解説記事"
    assert got[0]["link"] == "https://example.com/rag"


def test_detect_unknown_terms_respects_limit():
    articles = [{"title": "RAG LLM MCP SBOM VPN", "link": "u1"}]
    assert len(news_logic.detect_unknown_terms(articles, [], limit=2)) == 2


def test_build_unknown_terms_message_empty():
    assert news_logic.build_unknown_terms_message([]) == ""


def test_build_unknown_terms_message_contains_terms():
    msg = news_logic.build_unknown_terms_message(
        [{"term": "RAG", "count": 3, "title": "RAGの記事", "link": "u1"}]
    )
    assert "RAG" in msg
    assert "3件" in msg


# ====================================================
# 複数フィードの取得（fetch_all_articles）
# ====================================================

def test_fetch_all_articles_deduplicates_by_link(monkeypatch):
    """同じ記事が複数フィードに載っていても1件にまとめる"""
    monkeypatch.setattr(news_logic, "fetch_rss", lambda url=None: SAMPLE_RSS)
    articles = news_logic.fetch_all_articles()
    links = [a["link"] for a in articles if a["link"]]
    assert len(links) == len(set(links))


def test_fetch_all_articles_tolerates_partial_failure(monkeypatch):
    """一部のフィードが落ちても、残りのフィードで処理を続ける"""
    def flaky(url=None):
        if url == news_logic.RSS_FEEDS[0]:
            raise OSError("接続エラー")
        return SAMPLE_RSS

    monkeypatch.setattr(news_logic, "fetch_rss", flaky)
    assert len(news_logic.fetch_all_articles()) > 0


def test_fetch_all_articles_raises_when_all_feeds_fail(monkeypatch):
    def broken(url=None):
        raise OSError("接続エラー")

    monkeypatch.setattr(news_logic, "fetch_rss", broken)
    with pytest.raises(OSError):
        news_logic.fetch_all_articles()


def test_get_it_news_appends_unknown_terms_section(glossary_file, monkeypatch):
    glossary_file.write_text(json.dumps({"生成AI": "説明"}), encoding="utf-8")
    monkeypatch.setattr(news_logic, "fetch_rss", lambda url=None: SAMPLE_RSS)

    msg = news_logic.get_it_news()
    assert "まだ用語集に無い頻出語" in msg

# ====================================================
# 学習用語 / ニュース追跡語の分離
# ====================================================

@pytest.fixture
def both_stores(tmp_path, monkeypatch):
    """glossary.json と news_keywords.json の双方を一時ディレクトリへ差し替える"""
    monkeypatch.setattr(news_logic, "GLOSSARY_FILE", str(tmp_path / "glossary.json"))
    monkeypatch.setattr(news_logic, "NEWS_KEYWORDS_FILE", str(tmp_path / "news_keywords.json"))
    return tmp_path


def test_news_keywords_empty_by_default(both_stores):
    assert news_logic.load_news_keywords() == []


def test_add_news_keywords_persists(both_stores):
    added, skipped = news_logic.add_news_keywords(["OpenAI", "Excel"])
    assert added == ["OpenAI", "Excel"]
    assert skipped == []
    assert news_logic.load_news_keywords() == ["OpenAI", "Excel"]


def test_add_news_keywords_skips_duplicates(both_stores):
    news_logic.add_news_keywords(["OpenAI"])
    added, skipped = news_logic.add_news_keywords(["OpenAI", "RAG"])
    assert added == ["RAG"]
    assert skipped == ["OpenAI"]


def test_add_news_keywords_skips_terms_already_in_glossary(both_stores):
    """学習用語は既にニュース照合されるため、追跡語として重複登録しない"""
    (both_stores / "glossary.json").write_text(
        json.dumps({"ゼロトラスト": {"desc": "説明"}}), encoding="utf-8"
    )
    added, skipped = news_logic.add_news_keywords(["ゼロトラスト", "RAG"])
    assert added == ["RAG"]
    assert skipped == ["ゼロトラスト"]


def test_remove_news_keywords(both_stores):
    news_logic.add_news_keywords(["OpenAI", "Excel"])
    removed = news_logic.remove_news_keywords(["Excel"])
    assert removed == ["Excel"]
    assert news_logic.load_news_keywords() == ["OpenAI"]


def test_stock_keywords_merges_both_stores(both_stores):
    """ニュース照合には学習用語と追跡語の両方を使う"""
    (both_stores / "glossary.json").write_text(
        json.dumps({"ゼロトラスト": {"desc": "説明"}}), encoding="utf-8"
    )
    news_logic.add_news_keywords(["OpenAI"])
    assert news_logic.load_stock_keywords() == ["ゼロトラスト", "OpenAI"]


def test_news_keywords_do_not_reach_the_quiz(both_stores, monkeypatch):
    """今回の要点：ニュース追跡語はSRSクイズの出題対象に入らない"""
    import study_logic

    monkeypatch.setattr(study_logic, "GLOSSARY_FILE", str(both_stores / "glossary.json"))
    study_logic.add_kiso("ゼロトラスト", "信頼を前提としない設計")
    news_logic.add_news_keywords(["OpenAI", "Excel"])

    quiz_terms = set(study_logic.load_glossary().keys())
    assert quiz_terms == {"ゼロトラスト"}
    assert "OpenAI" not in quiz_terms

    # 一方でニュース照合には両方が使われる
    assert set(news_logic.load_stock_keywords()) == {"ゼロトラスト", "OpenAI", "Excel"}


def test_detected_terms_exclude_already_tracked(both_stores):
    """一度追跡登録した語は、未知語として再提示されない"""
    news_logic.add_news_keywords(["RAG"])
    articles = [{"title": "RAGとエージェントの話", "link": "u1"}]
    got = news_logic.detect_unknown_terms(articles, news_logic.load_stock_keywords())
    assert [t["term"] for t in got] == ["エージェント"]
