"""ITニュース取得・フィルタリングロジックモジュール

ITmediaの提供するRSSフィードから最新のニュース記事を取得し、
ユーザーが登録した用語集（glossary.json）に基づいてフィルタリングを行います。
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


def get_it_news(keyword=None):
    """ITmediaのRSSフィードから最新ニュースを取得し、登録中の用語でフィルタリングして返します。

    開発環境（GitHub Codespaces）やホスティング環境（AWS等）における
    外部API（NewsAPI等）のIP制限やリクエスト上限を回避するため、
    クローリングの安定性が高いRSSフィードパース方式を採用しています。

    Args:
        keyword (str, optional): 特定のキーワードで絞り込む場合に使用（将来の拡張用）。

    Returns:
        str: Discordにそのまま投稿可能な、フォーマット済みのメッセージ文字列。
    """
    stock_keywords = []
    
    # 1. 辞書ファイル（glossary.json）から蓄積された用語のキー一覧を取得
    if os.path.exists(GLOSSARY_FILE):
        try:
            with open(GLOSSARY_FILE, 'r', encoding='utf-8') as f:
                glossary_data = json.load(f)
                stock_keywords = list(glossary_data.keys())
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ [ERROR] 用語集（{GLOSSARY_FILE}）の読み込みに失敗しました: {e}")

    # 用語が一件も登録されていない場合のセーフティ処理
    if not stock_keywords:
        return "🗂️ 用語がストックされていません。先にメニューから用語をストックするか、設定ファイルを確認してください。"

    try:
        # 2. RSSフィード（XMLデータ）の通信取得
        req = urllib.request.Request(
            RSS_URL, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()

        # 3. XMLデータのパース（解析）
        root = ET.fromstring(xml_data)
        items = root.findall(".//item")
        
        if not items:
            return "🔍 最新ニュースが見つかりませんでした。"

        # 4. ニュース記事のフィルタリング処理
        filtered_articles = []
        for item in items:
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            
            # 登録用語のいずれかがタイトルに含まれるか走査（ケースインセンシティブ）
            matched_word = None
            for word in stock_keywords:
                if word.lower() in title.lower():
                    matched_word = word
                    break
            
            # マッチした記事の情報を保持
            if matched_word:
                filtered_articles.append({
                    "title": title,
                    "link": link,
                    "word": matched_word
                })

        # 5. Discord表示用の出力メッセージ構築
        if not filtered_articles:
            formatted_keywords = ", ".join(stock_keywords)
            return f"🔍 現在の最新ニュースの中に、ストック中の用語（{formatted_keywords}）が含まれる記事は見つかりませんでした。"

        msg = "🎯 **【ユーザー専用】ストック用語マッチングニュース**\n"
        msg += "ストックされた用語に関連する最新記事を抽出しました。\n"
        msg += "--------------------------------------------\n"
        
        # 指定された最大表示件数まで整形
        for i, article in enumerate(filtered_articles[:MAX_DISPLAY_ARTICLES], 1):
            msg += f"**{i}. [{article['word']}] {article['title']}**\n"
            msg += f"🔗 記事リンク: {article['link']}\n\n"
            
        return msg

    except Exception as e:
        return f"❌ ニュースの取得中にエラーが発生しました: {str(e)}"