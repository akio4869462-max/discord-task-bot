"""新作ゲーム紹介モジュール

PC / Switch / Switch 2 の発売予定を読み込み、絞り込み、Discord向けのメッセージに整形します。
気になる作品の登録（ウォッチリスト）と、発売前・予約開始日の通知文も作ります。

データは2か所から読む。
  ・seed/game_releases.json … リポジトリに入っている初期データ（出典URLつき）
  ・data/game_releases.json … 自分で書き足す分。Git管理外で、本番サーバーではホスト側に残る
同じ（タイトル, 発売日）が両方にあるときは data 側を優先する。形式は seed と同じ
（エントリの配列、または {"releases": [...]} ）。

気になる作品は data/game_watch.json に、タイトルの一覧として保存する。⭕ 発売日は延期で
変わるので、日付ではなくタイトルで覚える（日付で覚えると、延期のたびに登録が外れる）。

⭕ 発売予定は先に進むほど古くなる。seed は更新日（"updated"）を持ち、一覧の末尾に出す。
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

SEED_FILE = os.path.join('seed', 'game_releases.json')
USER_FILE = os.path.join('data', 'game_releases.json')
WATCH_FILE = os.path.join('data', 'game_watch.json')
JST = timezone(timedelta(hours=9))

PLATFORMS = ('PC', 'Switch', 'Switch 2')

DIGEST_DAYS = 14          # 月曜の配信で紹介する、今日から何日先までの発売予定
# 気になる作品を、発売の何日前に知らせるか（0は当日）
ALERT_LABELS = {7: "📅 発売まであと1週間", 1: "⏰ 明日発売", 0: "🎉 本日発売"}
# Discordの1メッセージは2000文字まで。余裕を残して、収まる分だけ載せる
MESSAGE_LIMIT = 1800

_WEEKDAYS = '月火水木金土日'


def _read_json(path):
    """JSONを読み込みます。無い・壊れている場合はNone。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ [ERROR] {path} の読み込みに失敗しました: {e}")
        return None


def _entries_of(raw):
    """ファイルの中身から、エントリの配列を取り出します（配列・{"releases": [...]} の両方に対応）。"""
    if isinstance(raw, dict):
        raw = raw.get('releases')
    return raw if isinstance(raw, list) else []


def _parse_date(value):
    """'YYYY-MM-DD' を date にします。変換できなければ None。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _normalize(entry):
    """エントリを検証して整えます。表示できない不正なエントリは None。

    発売日（release_date）か発売時期の文言（release_label）のどちらかが必要。
    対応機種は PLATFORMS のものだけを残し、1つも残らなければ出せない。
    """
    if not isinstance(entry, dict):
        return None
    title = entry.get('title')
    if not isinstance(title, str) or not title.strip():
        return None

    platforms = entry.get('platforms')
    platforms = [p for p in platforms if p in PLATFORMS] if isinstance(platforms, list) else []
    if not platforms:
        return None

    release_date = _parse_date(entry.get('release_date'))
    label = entry.get('release_label')
    label = label.strip() if isinstance(label, str) else ''
    if release_date is None and not label:
        return None

    def _text(key):
        value = entry.get(key)
        return value.strip() if isinstance(value, str) else ''

    return {
        'title': title.strip(),
        'platforms': platforms,
        'release_date': release_date,
        'release_label': label,
        'genre': _text('genre'),
        'note': _text('note'),
        'source': _text('source'),
        'preorder_start': _parse_date(entry.get('preorder_start')),
        'preorder_note': _text('preorder_note'),
        'preorder_source': _text('preorder_source'),
    }


def load_releases():
    """seed と data の発売予定を合わせて読み込みます（data 側を優先）。

    Returns:
        list[dict]: 整えたエントリの一覧。不正なエントリは含めない。
    """
    merged = {}
    for path in (SEED_FILE, USER_FILE):
        for raw in _entries_of(_read_json(path)):
            entry = _normalize(raw)
            if entry is None:
                print(f"⚠️ [WARN] {path} に表示できないエントリがあったので無視しました: {raw!r}")
                continue
            merged[(entry['title'].casefold(), entry['release_date'])] = entry
    return list(merged.values())


def seed_updated():
    """seed の更新日（'YYYY-MM-DD'）。無ければ空文字。"""
    raw = _read_json(SEED_FILE)
    value = raw.get('updated') if isinstance(raw, dict) else None
    return value if isinstance(value, str) else ''


# ====================================================
# 気になる作品（ウォッチリスト）
# ====================================================
def load_watch():
    """気になる作品のタイトル一覧を読み込みます。"""
    raw = _read_json(WATCH_FILE)
    titles = raw.get('titles') if isinstance(raw, dict) else None
    return [t for t in titles if isinstance(t, str) and t.strip()] if isinstance(titles, list) else []


def watched_keys():
    """気になる作品の照合用キー（大文字小文字を区別しないタイトル）の集合。"""
    return {t.casefold() for t in load_watch()}


def _save_watch(titles):
    try:
        os.makedirs(os.path.dirname(WATCH_FILE), exist_ok=True)
        with open(WATCH_FILE, 'w', encoding='utf-8') as f:
            json.dump({'titles': titles}, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] 気になる作品の保存に失敗しました: {e}")


def update_watch(shown_titles, selected_titles):
    """画面に出していた作品について、選ばれたものを気になる作品に登録します。

    ⭕ 入れ替えるのは「画面に出していた作品」だけ。期間や機種で絞って見ているときに、
       画面に出ていない（＝選びようが無かった）作品の登録まで外してしまわないため。
       画面に出ていて選ばれなかった作品は、登録が外れる。

    Returns:
        list[str]: 更新後の、気になる作品のタイトル一覧。
    """
    shown = {t.casefold() for t in shown_titles}
    kept = [t for t in load_watch() if t.casefold() not in shown]

    seen = {t.casefold() for t in kept}
    added = []
    for t in selected_titles:
        if t.casefold() not in seen:
            seen.add(t.casefold())
            added.append(t)

    titles = kept + added
    _save_watch(titles)
    return titles


# ====================================================
# 絞り込み
# ====================================================
def filter_upcoming(releases, today, platform=None, days=None, only_titles=None):
    """これから発売される作品を、発売日の近い順に返します。

    Args:
        releases (list[dict]): load_releases() の戻り値。
        today (date): 基準日。この日に発売のものも含める。
        platform (str, optional): 機種。省略時は全機種。
        days (int, optional): 今日から何日先までか。省略時は期限なし。
        only_titles (set[str], optional): 照合用キー（casefold したタイトル）。指定時はそれだけ。

    Returns:
        tuple: (発売日のある作品, 発売時期だけ分かっている作品)。後者は期間を指定したときは
               空（いつ出るか分からないので、期間に収まるとは言えない）。
    """
    def _fits(r):
        if platform is not None and platform not in r['platforms']:
            return False
        return only_titles is None or r['title'].casefold() in only_titles

    dated = [r for r in releases if r['release_date'] and r['release_date'] >= today and _fits(r)]
    if days is not None:
        limit = today + timedelta(days=days)
        dated = [r for r in dated if r['release_date'] <= limit]
    dated.sort(key=lambda r: (r['release_date'], r['title']))

    undated = []
    if days is None:
        undated = sorted((r for r in releases if r['release_date'] is None and _fits(r)),
                         key=lambda r: r['title'])
    return dated, undated


# ====================================================
# 表示
# ====================================================
def _md(d, today):
    """日付の表示（10/22(木)）。来年以降は年も付ける。"""
    text = f"{d.month}/{d.day}({_WEEKDAYS[d.weekday()]})"
    return f"{d.year}/{text}" if d.year != today.year else text


def _when_text(release, today):
    """発売日の表示（10/22(木)【あと3日】）。"""
    d = release['release_date']
    if d is None:
        return release['release_label']

    text = _md(d, today)
    remaining = (d - today).days
    if remaining == 0:
        text += "【今日発売】"
    elif remaining <= DIGEST_DAYS:
        text += f"【あと{remaining}日】"
    return text


def preorder_text(release, today):
    """予約の状況の文言。分かっていない作品・発売済みの作品は空文字。

    ⭕ データに書いてある情報だけを出す。載っていない作品は「予約できない」のではなく
       「未確認」なので、何も言わない。
    """
    d = release['release_date']
    if d is not None and d < today:
        return ''

    start, note = release['preorder_start'], release['preorder_note']
    if start and start > today:
        status = f"予約は{_md(start, today)}から（あと{(start - today).days}日）"
    elif start:
        status = f"予約受付中（{_md(start, today)}〜）"
    else:
        status = ''

    if status and note:
        return f"{status}／{note}"
    return status or note


def format_release(release, today, detail=False, watched=False):
    """1作品ぶんの表示行を作ります。

    Args:
        detail (bool): True なら備考と予約の状況を行を分けて添える。False（一覧向け）では
            代わりに、気になる作品には ⭐、予約の情報がある作品には 🛒 の印を付ける。
        watched (bool): 気になる作品か。
    """
    line = f"・{'⭐' if watched else ''}{_when_text(release, today)} **{release['title']}** " \
           f"［{' / '.join(release['platforms'])}］"
    if release['genre']:
        line += f" {release['genre']}"

    preorder = preorder_text(release, today)
    if detail:
        if release['note']:
            line += f"\n　{release['note']}"
        if preorder:
            line += f"\n　🛒 {preorder}"
    elif preorder:
        line += " 🛒"
    return line


def _fit_lines(header, lines, footer):
    """文字数の上限に収まる分だけ行を並べます。収まらない分は件数だけ添える。"""
    kept = []
    used = len(header) + len(footer) + 40       # 「ほかN件」の行の余裕
    for line in lines:
        if used + len(line) + 1 > MESSAGE_LIMIT:
            break
        kept.append(line)
        used += len(line) + 1

    body = "\n".join(kept)
    if len(kept) < len(lines):
        body += f"\n…ほか{len(lines) - len(kept)}件"
    return f"{header}{body}\n{footer}"


def build_games_message(releases, today, platform=None, days=None, period_label='',
                        watched=frozenset(), only_watched=False):
    """/games の返信を作ります。

    Args:
        platform (str, optional): 機種での絞り込み。
        days (int, optional): 今日から何日先までか。
        period_label (str): 見出しに添える期間の言い方（例: '今後2週間'）。
        watched (set[str]): 気になる作品の照合用キー。一覧で ⭐ を付ける。
        only_watched (bool): True なら気になる作品だけを、備考・予約の状況つきで出す。
    """
    dated, undated = filter_upcoming(releases, today, platform=platform, days=days,
                                     only_titles=set(watched) if only_watched else None)

    conditions = [c for c in (platform, period_label) if c]
    title = "⭐ **【気になるゲーム】**" if only_watched else "🎮 **【新作ゲーム】**"
    header = f"{title}{'（' + '・'.join(conditions) + '）' if conditions else ''}\n"
    if not dated and not undated:
        if only_watched:
            return header + "気になる作品はまだ登録されていません。`/games` の下のメニューから選べます。"
        return header + "該当する発売予定は見つかりませんでした。"

    def _line(r):
        return format_release(r, today, detail=only_watched, watched=r['title'].casefold() in watched)

    lines = [_line(r) for r in dated]
    if undated:
        lines.append("【発売時期のみ判明】")
        lines += [_line(r) for r in undated]

    updated = seed_updated()
    footer = "※発売日は変更されることがあります" + (f"（データ更新: {updated}）" if updated else "")
    return _fit_lines(header, lines, footer)


def build_weekly_digest(today=None, releases=None):
    """月曜朝のニュース配信に添える、近日発売の新作の紹介を作ります。

    Returns:
        str: 紹介文。今日から DIGEST_DAYS 日以内に発売される作品が無ければ空文字
             （無いときに空のセクションを送らない）。
    """
    today = today or datetime.now(JST).date()
    releases = load_releases() if releases is None else releases
    dated, _ = filter_upcoming(releases, today, days=DIGEST_DAYS)
    if not dated:
        return ""

    header = f"🎮 **【新作ゲーム紹介】**（今日から{DIGEST_DAYS}日以内の発売予定）\n"
    lines = [format_release(r, today, detail=True) for r in dated]
    return _fit_lines(header, lines, "気になる作品は `/games` で登録すると、発売前に通知します。")


# ====================================================
# 気になる作品の通知
# ====================================================
def _alert_reasons(release, today):
    """今日、この作品について知らせるべきこと。無ければ空リスト。"""
    reasons = []
    d = release['release_date']
    if d is not None and (d - today).days in ALERT_LABELS:
        reasons.append(ALERT_LABELS[(d - today).days])
    if release['preorder_start'] == today and (d is None or d >= today):
        reasons.append("🛒 今日から予約開始")
    return reasons


def build_watch_alerts(today=None, releases=None, watched=None):
    """気になる作品のうち、今日知らせるべきものの通知文を作ります。

    ⭕ 毎朝1回だけ呼ばれる前提で、送った記録は持たない（今日が「7日前」「前日」「当日」
       「予約開始日」のどれかに当たる作品だけを拾う）。

    Returns:
        str: 通知文。今日知らせることが無ければ空文字。
    """
    today = today or datetime.now(JST).date()
    releases = load_releases() if releases is None else releases
    watched = watched_keys() if watched is None else watched

    lines = []
    for r in sorted((r for r in releases if r['title'].casefold() in watched),
                    key=lambda r: (r['release_date'] or date.max, r['title'])):
        reasons = _alert_reasons(r, today)
        if not reasons:
            continue
        line = f"・{' / '.join(reasons)}：**{r['title']}** ［{' / '.join(r['platforms'])}］"
        preorder = preorder_text(r, today)
        if preorder:
            line += f"\n　🛒 {preorder}"
        lines.append(line)

    if not lines:
        return ""
    return _fit_lines("⭐ **【気になるゲームのお知らせ】**\n", lines, "一覧は `/games`（気になる作品だけ表示）で見られます。")
