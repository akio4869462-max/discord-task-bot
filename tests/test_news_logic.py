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
    path = tmp_path / "glossary.json"
    monkeypatch.setattr(news_logic, "GLOSSARY_FILE", str(path))
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
    monkeypatch.setattr(news_logic, "fetch_rss", lambda: SAMPLE_RSS)

    msg = news_logic.get_it_news()

    assert "生成AIの最新動向まとめ" in msg
    assert "https://example.com/ai-news" in msg


def test_get_it_news_network_error_returns_error_message(glossary_file, monkeypatch):
    glossary_file.write_text(json.dumps({"AI": "説明"}), encoding="utf-8")

    def broken_fetch():
        raise OSError("接続エラー")

    monkeypatch.setattr(news_logic, "fetch_rss", broken_fetch)

    msg = news_logic.get_it_news()
    assert "エラーが発生しました" in msg
