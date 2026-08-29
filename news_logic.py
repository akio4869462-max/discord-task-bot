"""ITニュース取得・フィルタリングロジックモジュール

ITmediaの提供するRSSフィードから最新のニュース記事を取得し、
ユーザーが登録した用語集（glossary.json）に基づいてフィルタリングを行います。

通信（fetch_rss）・解析（parse_rss_items）・抽出（filter_articles）・
整形（build_news_message）を独立した関数に分離しており、
ネットワークに依存しないユニットテストが可能な構造にしています。
"""

import json
import os
import re
import xml.etree.ElementTree as ET
import urllib.request

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
# 技術系チャンネルのフィードのみを対象にする。
# 総合フィード(itmedia_all.xml)はスマホ販売ランキングや飲食チェーンの話題まで含むため、
# 用語抽出をかけると製品名・消費者向け話題が大量に混入して実用にならなかった。
RSS_FEEDS = [
    "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml",      # ITmedia AI+
    "https://rss.itmedia.co.jp/rss/2.0/enterprise.xml",  # ITmedia エンタープライズ
    "https://rss.itmedia.co.jp/rss/2.0/ait.xml",         # @IT（開発者向け）
]

GLOSSARY_FILE = os.path.join('data', 'glossary.json')
# ニュース追跡専用のキーワード。学習用語（glossary.json）と分けることで、
# トレンド語や製品名がSRSクイズの出題対象に混ざらないようにしている。
NEWS_KEYWORDS_FILE = os.path.join('data', 'news_keywords.json')
MAX_DISPLAY_ARTICLES = 5   # Discordに表示する最大記事数
MAX_UNKNOWN_TERMS = 8      # 未登録語として提示する最大件数

# ====================================================
# 🆕 未知語検出の設定
# ====================================================
# 用語候補の抽出パターン
_KATAKANA_PATTERN = re.compile(r'[ァ-ヴー]{3,}')  # 3文字以上のカタカナ語
_ALPHA_PATTERN = re.compile(r'(?<![A-Za-z0-9])[A-Z][A-Za-z0-9]{1,7}(?![A-Za-z0-9])')  # 大文字始まりの英字（LLM, OpenAI, DuckDB 等）
_FEED_PREFIX_PATTERN = re.compile(r'^\[[^\]]*\]\s*')  # 「[ITmedia News] 」のような媒体名プレフィックス

# 検出しても学習価値が薄い語。実フィードで頻出したノイズを基に構成しており、
# 運用しながら追加していく前提のリスト。
TERM_STOPWORDS = {
    # 一般語・ビジネス語
    "ランキング", "ポイント", "キャリア", "リストラ", "ニーズ", "トップ", "ブーム",
    "ラッシュ", "スキル", "ギャップ", "ゲーム", "サービス", "ユーザー", "メーカー",
    "ビジネス", "ケース", "チーム", "グループ", "プロジェクト", "コスト", "リスク",
    "メリット", "デメリット", "ポジション", "スタート", "トラック", "ランナー",
    # 基礎的すぎる技術語（今さら用語集に登録しても学びが薄い）
    "データ", "システム", "ソフト", "アプリ", "サーバ", "サーバー", "ネットワーク",
    "アクセス", "コード", "モデル", "カメラ", "スマホ", "モバイル", "パスワード",
    "ツール", "ファイル", "メール", "サイト", "ページ", "バージョン", "アップデート",
    "リリース", "エンジニア", "コンピュータ", "パソコン",
    # 企業名・製品名・一般英単語（概念語ではないため）
    "Google", "Microsoft", "Apple", "Amazon", "Windows", "Mac", "iPhone", "Android",
    "Server", "Desktop", "Notebook", "Expert", "Face", "Pro", "Studio", "Ultra",
    "Plus", "Max", "Mini", "News", "Web", "App", "Mobile", "PC", "IT", "SE",
}


def load_glossary_terms():
    """学習用語集（glossary.json）に登録された用語名の一覧を読み込みます。

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
        print(f"WARN: 用語集（{GLOSSARY_FILE}）の読み込みに失敗しました: {e}")
        return []


def load_news_keywords():
    """ニュース追跡専用キーワードの一覧を読み込みます。

    こちらに登録された語はニュースの照合にのみ使われ、SRSクイズには出題されません。

    Returns:
        list[str]: キーワードのリスト。
    """
    if not os.path.exists(NEWS_KEYWORDS_FILE):
        return []

    try:
        with open(NEWS_KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return list(data) if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError) as e:
        print(f"WARN: ニュース追跡語（{NEWS_KEYWORDS_FILE}）の読み込みに失敗しました: {e}")
        return []


def save_news_keywords(keywords):
    """ニュース追跡専用キーワードを保存します。

    Returns:
        bool: 保存に成功したかどうか。
    """
    try:
        os.makedirs(os.path.dirname(NEWS_KEYWORDS_FILE), exist_ok=True)
        with open(NEWS_KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(keywords, f, ensure_ascii=False, indent=4)
        return True
    except IOError as e:
        print(f"WARN: ニュース追跡語の保存に失敗しました: {e}")
        return False


def add_news_keywords(terms):
    """ニュース追跡専用キーワードを追加します（重複は無視）。

    Returns:
        tuple: (実際に追加された語のリスト, 既に登録済みだった語のリスト)
    """
    existing = load_news_keywords()
    lowered = {k.lower() for k in existing}
    # 学習用語に既にある語は、そちらで既にニュース照合されるため追加しない
    lowered |= {t.lower() for t in load_glossary_terms()}

    added, skipped = [], []
    for term in terms:
        if term.lower() in lowered:
            skipped.append(term)
            continue
        existing.append(term)
        lowered.add(term.lower())
        added.append(term)

    if added:
        save_news_keywords(existing)
    return added, skipped


def remove_news_keywords(terms):
    """ニュース追跡専用キーワードを削除します。

    Returns:
        list[str]: 実際に削除された語のリスト。
    """
    existing = load_news_keywords()
    targets = {t.lower() for t in terms}

    remaining = [k for k in existing if k.lower() not in targets]
    removed = [k for k in existing if k.lower() in targets]

    if removed:
        save_news_keywords(remaining)
    return removed


def load_stock_keywords():
    """ニュース照合に使う全キーワード（学習用語＋ニュース追跡語）を返します。

    Returns:
        list[str]: 重複を除いたキーワードの一覧。
    """
    keywords = load_glossary_terms()
    lowered = {k.lower() for k in keywords}
    for k in load_news_keywords():
        if k.lower() not in lowered:
            keywords.append(k)
            lowered.add(k.lower())
    return keywords


def fetch_rss(url=None):
    """RSSフィード（XMLデータ）を通信取得します。

    開発環境（GitHub Codespaces）やホスティング環境（AWS等）における
    外部API（NewsAPI等）のIP制限やリクエスト上限を回避するため、
    クローリングの安定性が高いRSSフィードパース方式を採用しています。

    Args:
        url (str, optional): 取得するフィードのURL。省略時は先頭のフィード。

    Returns:
        bytes: 取得したXMLデータ。
    """
    req = urllib.request.Request(
        url or RSS_FEEDS[0],
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read()


def fetch_all_articles():
    """設定された全フィードから記事を取得し、1つのリストに統合します。

    一部のフィードだけが落ちても残りで処理を続けられるよう、失敗はフィード単位で捕まえます。
    ただし全滅した場合は、呼び出し側でエラーとして扱えるよう例外を送出します。

    Returns:
        list[dict]: {"title", "link"} の一覧（リンク重複は除去済み）。
    """
    articles = []
    seen_links = set()
    failures = 0

    for url in RSS_FEEDS:
        try:
            for article in parse_rss_items(fetch_rss(url)):
                link = article.get('link', '')
                # 同じ記事が複数チャンネルのフィードに載ることがあるため重複を除く
                if link and link in seen_links:
                    continue
                seen_links.add(link)
                articles.append(article)
        except Exception as e:
            failures += 1
            print(f"WARN: フィードの取得に失敗しました({url}): {e}")

    if failures == len(RSS_FEEDS):
        raise OSError("すべてのRSSフィードの取得に失敗しました")

    return articles


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


def extract_term_candidates(title):
    """記事タイトルから用語候補（カタカナ語・大文字始まりの英字）を抽出します。

    媒体名のプレフィックス（「[ITmedia News] 」）は抽出対象から除外します。

    Returns:
        set[str]: 用語候補の集合（ストップワード除去済み）。
    """
    cleaned = _FEED_PREFIX_PATTERN.sub('', title or '')
    candidates = set(_KATAKANA_PATTERN.findall(cleaned))
    candidates |= set(_ALPHA_PATTERN.findall(cleaned))
    return {c for c in candidates if c not in TERM_STOPWORDS}


def detect_unknown_terms(articles, stock_keywords, limit=None):
    """記事タイトルに頻出するが、まだ用語集に登録されていない語を検出します。

    既存のfilter_articles()が「既知の語を含む記事」を拾うのに対し、こちらは逆方向に
    「まだ知らない語」を拾うことで、用語集に無い新しい概念を取りこぼさないようにします。

    Args:
        articles (list[dict]): {"title", "link"} を持つ記事一覧。
        stock_keywords (list[str]): 登録済み用語の一覧（大小文字を無視して除外する）。
        limit (int, optional): 返す最大件数。省略時は MAX_UNKNOWN_TERMS。

    Returns:
        list[dict]: [{"term", "count", "title", "link"}] を出現回数の多い順に並べたもの。
    """
    limit = limit or MAX_UNKNOWN_TERMS
    known = {k.lower() for k in stock_keywords}

    counts = {}
    examples = {}
    for article in articles:
        for term in extract_term_candidates(article.get('title', '')):
            if term.lower() in known:
                continue
            counts[term] = counts.get(term, 0) + 1
            # 判断材料として、その語が最初に現れた記事を例として保持する
            examples.setdefault(term, article)

    # 出現回数の多い順。同数の場合は語順を固定して結果を安定させる
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {
            "term": term,
            "count": count,
            "title": examples[term].get('title', ''),
            "link": examples[term].get('link', ''),
        }
        for term, count in ordered[:limit]
    ]


def build_unknown_terms_message(unknown_terms):
    """検出した未登録語を、Discord表示用のメッセージに整形します。

    Returns:
        str: 未登録語のセクション。検出が無ければ空文字。
    """
    if not unknown_terms:
        return ""

    msg = "\n🆕 **【まだ用語集に無い頻出語】**\n"
    msg += "気になるものは「📚 学習・用語」→「🆕 ニュースの新語」から追跡登録できます。\n"
    for item in unknown_terms:
        count_label = f"（{item['count']}件）" if item['count'] > 1 else ""
        msg += f"・**{item['term']}**{count_label} … {item['title'][:50]}\n"
    return msg


def get_unknown_terms():
    """RSSを取得し、未登録の用語候補を検出して返します（UIからの登録導線用）。

    Returns:
        list[dict]: [{"term", "count", "title", "link"}]。取得に失敗した場合は空リスト。
    """
    try:
        articles = parse_rss_items(fetch_rss())
    except Exception as e:
        print(f"⚠️ [ERROR] 未知語検出のためのRSS取得に失敗しました: {e}")
        return []

    return detect_unknown_terms(articles, load_stock_keywords())


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
        articles = fetch_all_articles()

        if not articles:
            return "🔍 最新ニュースが見つかりませんでした。"

        filtered_articles = filter_articles(articles, stock_keywords)
        msg = build_news_message(filtered_articles, stock_keywords)

        # 既知の用語にヒットが無かった場合でも、未登録の頻出語は学習の手がかりになるため必ず添える
        msg += build_unknown_terms_message(detect_unknown_terms(articles, stock_keywords))
        return msg

    except Exception as e:
        return f"❌ ニュースの取得中にエラーが発生しました: {str(e)}"
