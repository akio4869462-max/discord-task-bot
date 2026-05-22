import urllib.request
import xml.etree.ElementTree as ET
import json
import os

def get_it_news(keyword=None):
    """
    ITmediaのRSSフィードから最新ニュースを取得し、
    ユーザーがストックした用語（glossary.json）でフィルタリングして返します。
    
    ※開発環境（GitHub Codespaces）やホスティング環境（AWS等）における
      外部API（NewsAPI等）のIP制限を回避するため、安定性の高いRSSフィード方式を採用。
    """
    rss_url = "https://rss.itmedia.co.jp/rss/2.0/itmedia_all.xml"
    glossary_file = "glossary.json"
    
    # 1. glossary.json からストック中の用語（キー名）を取得
    stock_keywords = []
    if os.path.exists(glossary_file):
        try:
            with open(glossary_file, 'r', encoding='utf-8') as f:
                glossary_data = json.load(f)
                stock_keywords = list(glossary_data.keys())
        except Exception as e:
            print(f"用語集の読み込みエラー: {e}")

    # 用語が何もストックされていない場合のセーフティ処理
    if not stock_keywords:
        return "🗂️ 用語がストックされていません。先にメニューから用語をストックするか、`glossary.json` を確認してください。"

    try:
        # 2. RSSフィード（XMLデータ）をインターネット経由で取得
        req = urllib.request.Request(
            rss_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()

        # 3. XMLデータのパース（解析）
        root = ET.fromstring(xml_data)
        items = root.findall(".//item")
        
        if not items:
            return "🔍 最新ニュースが見つかりませんでした。"

        # 4. ニュース記事をストック用語でフィルタリング
        filtered_articles = []
        for item in items:
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            
            # ストックした単語のいずれかが、ニュースのタイトルに含まれているかチェック（大文字・小文字を区別しない）
            matched_word = None
            for word in stock_keywords:
                if word.lower() in title.lower():
                    matched_word = word
                    break
            
            # マッチした記事があれば、対象単語の情報を付与してリストに追加
            if matched_word:
                filtered_articles.append({
                    "title": title,
                    "link": link,
                    "word": matched_word
                })

        # 5. Discord表示用のメッセージ構築
        if not filtered_articles:
            return f"🔍 現在の最新ニュースの中に、ストック中の用語（{', '.join(stock_keywords)}）が含まれる記事は見つかりませんでした。"

        msg = "🎯 **【ユーザー専用】ストック用語マッチングニュース**\n"
        msg += "ストックされた用語に関連する最新記事を抽出しました。\n"
        msg += "--------------------------------------------\n"
        
        # マッチした記事を最大5件まで整形
        for i, article in enumerate(filtered_articles[:5], 1):
            msg += f"**{i}. [{article['word']}] {article['title']}**\n"
            msg += f"🔗 記事リンク: {article['link']}\n\n"
            
        return msg

    except Exception as e:
        return f"❌ ニュースの取得中にエラーが発生しました: {str(e)}"