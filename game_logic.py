"""新作ゲーム紹介モジュール

PC / Switch / Switch 2 の発売予定を読み込み、絞り込み、Discord向けのメッセージに整形します。

データは2か所から読む。
  ・seed/game_releases.json … リポジトリに入っている初期データ（出典URLつき）
  ・data/game_releases.json … 自分で書き足す分。Git管理外で、EC2ではホスト側に残る
同じ（タイトル, 発売日）が両方にあるときは data 側を優先する。形式は seed と同じ
（エントリの配列、または {"releases": [...]} ）。

⭕ 発売予定は先に進むほど古くなる。seed は更新日（"updated"）を持ち、一覧の末尾に出す。
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

SEED_FILE = os.path.join('seed', 'game_releases.json')
USER_FILE = os.path.join('data', 'game_releases.json')
JST = timezone(timedelta(hours=9))

PLATFORMS = ('PC', 'Switch', 'Switch 2')

DIGEST_DAYS = 14          # 月曜の配信で紹介する、今日から何日先までの発売予定
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


def filter_upcoming(releases, today, platform=None, days=None):
    """これから発売される作品を、発売日の近い順に返します。

    Args:
        releases (list[dict]): load_releases() の戻り値。
        today (date): 基準日。この日に発売のものも含める。
        platform (str, optional): 機種。省略時は全機種。
        days (int, optional): 今日から何日先までか。省略時は期限なし。

    Returns:
        tuple: (発売日のある作品, 発売時期だけ分かっている作品)。後者は期間を指定したときは
               空（いつ出るか分からないので、期間に収まるとは言えない）。
    """
    def _fits(r):
        return platform is None or platform in r['platforms']

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


def _when_text(release, today):
    """発売日の表示（10/22(木)・あと3日）。来年以降は年も付ける。"""
    d = release['release_date']
    if d is None:
        return release['release_label']

    text = f"{d.month}/{d.day}({_WEEKDAYS[d.weekday()]})"
    if d.year != today.year:
        text = f"{d.year}/{text}"

    remaining = (d - today).days
    if remaining == 0:
        text += "【今日発売】"
    elif remaining <= DIGEST_DAYS:
        text += f"【あと{remaining}日】"
    return text


def format_release(release, today, with_note=False):
    """1作品ぶんの表示行を作ります。"""
    line = f"・{_when_text(release, today)} **{release['title']}** ［{' / '.join(release['platforms'])}］"
    if release['genre']:
        line += f" {release['genre']}"
    if with_note and release['note']:
        line += f"\n　{release['note']}"
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


def build_games_message(releases, today, platform=None, days=None, period_label=''):
    """/games の返信を作ります。

    Args:
        platform (str, optional): 機種での絞り込み。
        days (int, optional): 今日から何日先までか。
        period_label (str): 見出しに添える期間の言い方（例: '今後2週間'）。
    """
    dated, undated = filter_upcoming(releases, today, platform=platform, days=days)

    conditions = [c for c in (platform, period_label) if c]
    header = "🎮 **【新作ゲーム】**" + (f"（{'・'.join(conditions)}）" if conditions else "") + "\n"
    if not dated and not undated:
        return header + "該当する発売予定は見つかりませんでした。"

    lines = [format_release(r, today) for r in dated]
    if undated:
        lines.append("【発売時期のみ判明】")
        lines += [format_release(r, today) for r in undated]

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
    lines = [format_release(r, today, with_note=True) for r in dated]
    return _fit_lines(header, lines, "気になる作品は `/games` で機種別にも絞り込めます。")
