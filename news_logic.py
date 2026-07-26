"""ITニュース取得・フィルタリングロジックモジュール

ITmediaの提供するRSSフィードから最新のニュース記事を取得し、
ユーザーが登録した用語集（glossary.json）に基づいてフィルタリングを行います。

通信（fetch_rss）・解析（parse_rss_items）・抽出（filter_articles）・
整形（build_news_message）を独立した関数に分離しており、
ネットワークに依存しないユニットテストが可能な構造にしています。
"""

import json
import os
import xml.etree.ElementTree as ET
import urllib.request

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
RSS_URL = "https://rss.itmedia.co.jp/rss/2.0/itmedia_all.xml"
GLOSSARY_FILE = os.path.join('data', 'glossary.json')
MAX_DISPLAY_ARTICLES = 5  # Discordに表示する最大記事数


def load_stock_keywords():
    """用語集ファイル（glossary.json）からストック済み用語の一覧を読み込みます。

    Returns:
        list[str]: 用語のリスト。ファイルが無い・壊れている場合は空リスト。
    """
    if not os.path.exists(GLOSSARY_FILE):
        return []

    try:
        with open(GLOSSARY_FILE, 'r', encoding='utf-8') as f:
            glossary_data = json.load(f)
            return list(glossary_data.keys())
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ [ERROR] 用語集（{GLOSSARY_FILE}）の読み込みに失敗しました: {e}")
        return []


def fetch_rss():
    """RSSフィード（XMLデータ）を通信取得します。

    開発環境（GitHub Codespaces）やホスティング環境（AWS等）における
    外部API（NewsAPI等）のIP制限やリクエスト上限を回避するため、
    クローリングの安定性が高いRSSフィードパース方式を採用しています。

    Returns:
        bytes: 取得したXMLデータ。
    """
    req = urllib.request.Request(
        RSS_URL,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read()


def parse_rss_items(xml_data):
    """RSSのXMLデータを解析し、記事のタイトル・リンクの一覧に変換します。

    Args:
        xml_data (bytes | str): RSSフィードのXMLデータ。

    Returns:
        list[dict]: {"title": str, "link": str} のリスト。
    """
    root = ET.fromstring(xml_data)

    articles = []
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        # 要素が無い・テキストが空(None)のどちらでも安全に空文字へフォールバック
        title = title_elem.text if title_elem is not None and title_elem.text else ""
        link = link_elem.text if link_elem is not None and link_elem.text else ""
        articles.append({"title": title, "link": link})

    return articles


def filter_articles(articles, stock_keywords):
    """登録用語のいずれかがタイトルに含まれる記事だけを抽出します（ケースインセンシティブ）。

    Args:
        articles (list[dict]): {"title", "link"} を持つ記事一覧。
        stock_keywords (list[str]): ストック済み用語の一覧。

    Returns:
        list[dict]: マッチした記事に {"word": マッチした用語} を加えたリスト。
    """
    filtered_articles = []
    for article in articles:
        title = article.get("title", "")

        matched_word = None
        for word in stock_keywords:
            if word.lower() in title.lower():
                matched_word = word
                break

        if matched_word:
            filtered_articles.append({
                "title": title,
                "link": article.get("link", ""),
                "word": matched_word,
            })

    return filtered_articles


def build_news_message(filtered_articles, stock_keywords):
    """フィルタリング済みの記事一覧から、Discord表示用のメッセージを構築します。

    Args:
        filtered_articles (list[dict]): {"title", "link", "word"} を持つ記事一覧。
        stock_keywords (list[str]): ストック済み用語の一覧（0件時の案内文に使用）。

    Returns:
        str: Discordにそのまま投稿可能な、フォーマット済みのメッセージ文字列。
    """
    if not filtered_articles:
        formatted_keywords = ", ".join(stock_keywords)
        return f"🔍 現在の最新ニュースの中に、ストック中の用語（{formatted_keywords}）が含まれる記事は見つかりませんでした。"

    msg = "🎯 **【ユーザー専用】ストック用語マッチングニュース**\n"
    msg += "ストックされた用語に関連する最新記事を抽出しました。\n"
    msg += "--------------------------------------------\n"

    for i, article in enumerate(filtered_articles[:MAX_DISPLAY_ARTICLES], 1):
        msg += f"**{i}. [{article['word']}] {article['title']}**\n"
        msg += f"🔗 記事リンク: {article['link']}\n\n"

    return msg


def get_it_news(keyword=None):
    """ITmediaのRSSフィードから最新ニュースを取得し、登録中の用語でフィルタリングして返します。

    Args:
        keyword (str, optional): 特定のキーワードで絞り込む場合に使用（将来の拡張用）。

    Returns:
        str: Discordにそのまま投稿可能な、フォーマット済みのメッセージ文字列。
    """
    stock_keywords = load_stock_keywords()

    # 用語が一件も登録されていない場合のセーフティ処理
    if not stock_keywords:
        return "🗂️ 用語がストックされていません。先にメニューから用語をストックするか、設定ファイルを確認してください。"

    try:
        articles = parse_rss_items(fetch_rss())

        if not articles:
            return "🔍 最新ニュースが見つかりませんでした。"

        filtered_articles = filter_articles(articles, stock_keywords)
        return build_news_message(filtered_articles, stock_keywords)

    except Exception as e:
        return f"❌ ニュースの取得中にエラーが発生しました: {str(e)}"
