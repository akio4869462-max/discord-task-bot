"""応用情報 過去問の復習ノートモジュール

過去問道場で間違えた（復習が必要な）問題を、分野・キーワード付きで溜めておき、
あとで合格教本を引くときにまとめて見られるようにします。

復習の流れは 未学習 → 教本学習済 → 類似問題で復習中 → 完了 の4段階で、
「完了」になった問題は復習対象から外れます。
"""

import csv
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import exam_logic

REVIEW_DATA_FILE = os.path.join('data', 'review_data.json')
JST = timezone(timedelta(hours=9))

STATUS_LABELS = ("未学習", "教本学習済", "類似問題で復習中", "完了")
STATUS_DONE = 3
# 「教本で調べる」対象。教本を読み終えた問題（教本学習済）はキーワード一覧から外す
STATUS_NEEDS_TEXTBOOK = 0
# 次のステップへ進めるボタンの文言（現在の状態 → ボタン名）
ADVANCE_LABELS = ("教本で学習した", "類似問題に取り組む", "完了にする")

MAX_KEYWORDS = 10


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ [ERROR] {path} の読み込みに失敗しました: {e}")
        return default


def load_review_data():
    """復習ノートをファイルから読み込みます。"""
    data = _load_json(REVIEW_DATA_FILE, {"items": []})
    data.setdefault("items", [])
    for item in data["items"]:
        item.setdefault("topic", "")  # 旧データ（分類の追加前）を補完
    return data


def save_review_data(data):
    try:
        os.makedirs(os.path.dirname(REVIEW_DATA_FILE), exist_ok=True)
        with open(REVIEW_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"⚠️ [ERROR] 復習ノートの保存に失敗しました: {e}")


def parse_keywords(text):
    """「、」「,」改行などで区切られた文字列をキーワードのリストにします（重複は除く）。"""
    seen = []
    for k in re.split(r'[、,，\n]+', text or ''):
        k = k.strip()
        if k and k not in seen:
            seen.append(k)
    return seen[:MAX_KEYWORDS]


def add_item(title, field, keywords, memo='', now=None):
    """間違えた問題を登録します。

    Returns:
        tuple: (成功したか, メッセージ)
    """
    title = (title or '').strip()
    if not title:
        return False, "❌ 問題の識別名（例: R5秋 午前 問23）を入力してください。"
    if field not in exam_logic.EXAM_FIELDS:
        return False, "❌ 不明な分野です。"

    now = now or datetime.now(JST)
    data = load_review_data()
    data['items'].append({
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "field": field,
        "keywords": list(keywords)[:MAX_KEYWORDS],
        "memo": (memo or '').strip(),
        "status": 0,
        "wrong": 1,
        "created": now.strftime('%Y-%m-%d'),
        "updated": now.strftime('%Y-%m-%d'),
    })
    save_review_data(data)
    kw = '、'.join(keywords) if keywords else '（未設定）'
    return True, (f"📚 復習ノートに登録しました！\n"
                  f"{title}（{exam_logic.EXAM_FIELDS[field]}）\nキーワード: {kw}")


# ====================================================
# 過去問道場のCSV（成績のエクスポート）からの一括登録
# ====================================================

_WRONG_MARKS = ('×', '✕', '✖', '╳', 'Ｘ')
_HYPERLINK_LABEL = re.compile(r'=HYPERLINK\("[^"]*","([^"]*)"\)')
MAX_CSV_BYTES = 1_000_000


def decode_csv_bytes(raw):
    """CSVのバイト列を文字列にします。過去問道場の出力はShift-JIS(cp932)。"""
    for enc in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def parse_dojo_csv(text):
    """過去問道場のCSV（No.,正誤,分野名,大分類,中分類,出典,学習日）から、
    各問題の「最後の結果」が×のものを取り出します。

    同じ問題を複数回解いている場合は、No.が最も大きい（＝最新の）行を採用するので、
    一度間違えても後で正解した問題は登録されません。

    Returns:
        list[dict]: [{"title", "field", "keywords"}]。ヘッダーが想定外なら空。
    """
    rows = list(csv.reader((text or '').splitlines()))
    if not rows or '正誤' not in rows[0] or '出典' not in rows[0]:
        return []
    col = {name: i for i, name in enumerate(rows[0])}
    name_to_id = {v: k for k, v in exam_logic.EXAM_FIELDS.items()}

    latest = {}  # title -> (連番, 行)
    for n, row in enumerate(rows[1:]):
        try:
            source = row[col['出典']]
            result = row[col['正誤']].strip()
        except IndexError:
            continue
        m = _HYPERLINK_LABEL.search(source)
        title = re.sub(r'\s+', ' ', m.group(1) if m else source).strip()
        if not title:
            continue
        latest[title] = (n, row, result)

    def cell(row, name):
        i = col.get(name)
        return row[i].strip() if i is not None and i < len(row) else ''

    entries = []
    for title, (_, row, result) in sorted(latest.items(), key=lambda kv: kv[1][0]):
        if not any(c in result for c in _WRONG_MARKS):
            continue
        # 中分類・大分類は教本で引くには広すぎるので、キーワードではなく「分類」として持つ
        entries.append({
            "title": title,
            "field": name_to_id.get(cell(row, '分野名')),
            "keywords": [],
            "topic": cell(row, '中分類') or cell(row, '大分類'),
        })
    return entries


def add_items_from_csv(raw, now=None):
    """過去問道場のCSV（バイト列）から間違えた問題を一括登録します。"""
    if len(raw) > MAX_CSV_BYTES:
        return "❌ ファイルが大きすぎます（1MBまで）。"
    text = decode_csv_bytes(raw)
    entries = parse_dojo_csv(text) if text is not None else []
    if not entries:
        return ("❌ 登録できる問題が見つかりませんでした。\n"
                "過去問道場の成績CSV（正誤・出典の列を含むもの）を添付してください。"
                "最後の結果が×の問題がない場合も登録されません。")
    return register_entries(entries, now)


def register_entries(entries, now=None):
    """解析済みの問題リストを復習ノートに登録します（登録済みの識別名は飛ばす）。"""
    now = now or datetime.now(JST)
    data = load_review_data()
    existing = {i['title'] for i in data['items'] if i['status'] < STATUS_DONE}
    added, skipped = [], []
    for e in entries:
        if e['title'] in existing:
            skipped.append(e['title'])
            continue
        data['items'].append({
            "id": uuid.uuid4().hex[:8],
            "title": e['title'],
            "field": e['field'],
            "keywords": e['keywords'],
            "topic": e.get('topic', ''),
            "memo": "",
            "status": 0,
            "wrong": 1,
            "created": now.strftime('%Y-%m-%d'),
            "updated": now.strftime('%Y-%m-%d'),
        })
        added.append(e['title'])
    save_review_data(data)

    msg = f"📥 {len(added)}問を復習ノートに登録しました。"
    if added:
        msg += "\n" + "\n".join(f"・{t}" for t in added[:30])
        if len(added) > 30:
            msg += f"\n…ほか{len(added) - 30}問"
    if skipped:
        msg += f"\n（登録済みのため{len(skipped)}問は飛ばしました）"
    if added:
        msg += "\n🔑 キーワードは「📋 復習一覧」→問題を選択→「🔑 キーワード編集」で追加できます。"
    return msg


def _find(data, item_id):
    for item in data['items']:
        if item['id'] == item_id:
            return item
    return None


def get_item(item_id):
    return _find(load_review_data(), item_id)


def list_items(include_done=False):
    """復習対象（既定では完了以外）を、状態が浅い順・古い順で返します。"""
    items = load_review_data()['items']
    if not include_done:
        items = [i for i in items if i['status'] < STATUS_DONE]
    return sorted(items, key=lambda i: (i['status'], i['created']))


def advance(item_id, now=None):
    """状態を1段階進めます。Returns: 更新後のitem。見つからなければNone。"""
    now = now or datetime.now(JST)
    data = load_review_data()
    item = _find(data, item_id)
    if item is None:
        return None
    item['status'] = min(STATUS_DONE, item['status'] + 1)
    item['updated'] = now.strftime('%Y-%m-%d')
    save_review_data(data)
    return item


def mark_wrong_again(item_id, now=None):
    """類似問題などでまた間違えたとき、未学習に戻して間違え回数を増やします。"""
    now = now or datetime.now(JST)
    data = load_review_data()
    item = _find(data, item_id)
    if item is None:
        return None
    item['status'] = 0
    item['wrong'] = item.get('wrong', 1) + 1
    item['updated'] = now.strftime('%Y-%m-%d')
    save_review_data(data)
    return item


def delete_item(item_id):
    data = load_review_data()
    before = len(data['items'])
    data['items'] = [i for i in data['items'] if i['id'] != item_id]
    save_review_data(data)
    return len(data['items']) < before


def format_item(item):
    field = exam_logic.EXAM_FIELDS.get(item.get('field'), '分野未設定')
    kw = '、'.join(item['keywords']) if item['keywords'] else '（未設定 ─「🔑 キーワード編集」で追加）'
    topic = f"／{item['topic']}" if item.get('topic') else ''
    msg = f"**{item['title']}**［{STATUS_LABELS[item['status']]}］\n{field}{topic}／間違えた回数 {item.get('wrong', 1)}\n🔑 {kw}"
    if item.get('memo'):
        msg += f"\n📝 {item['memo']}"
    return msg


def build_keyword_list():
    """教本で調べるべきキーワードを分野別にまとめます（未学習の問題が対象）。"""
    groups, unset = {}, []
    for item in list_items():
        if item['status'] != STATUS_NEEDS_TEXTBOOK:
            continue
        if not item['keywords']:
            unset.append(item)
            continue
        field = exam_logic.EXAM_FIELDS.get(item.get('field'), '分野未設定')
        words = groups.setdefault(field, {})
        for k in item['keywords']:
            words.setdefault(k, []).append(item['title'])

    if not groups and not unset:
        return "📚 教本で調べる問題はありません。"

    # 分類名（例: データベース）は広すぎて教本で引けないので、キーワードとは別枠にする
    msg = "📚 **【教本で調べるキーワード】**\n"
    for field, words in groups.items():
        msg += f"\n**■ {field}**\n"
        for k, titles in words.items():
            msg += f"・{k}　`{' / '.join(titles)}`\n"
    if unset:
        msg += f"\n**■ キーワード未設定（{len(unset)}問）**\n"
        msg += "「📋 復習一覧」→問題を選択→「🔑 キーワード編集」で、教本で引いた用語を入力できます。\n"
        for item in unset[:15]:
            topic = f"（{item['topic']}）" if item.get('topic') else ''
            msg += f"・{item['title']}{topic}\n"
        if len(unset) > 15:
            msg += f"…ほか{len(unset) - 15}問\n"
    return msg[:1990]


def set_keywords(item_id, keywords, now=None):
    """問題のキーワードを置き換えます。Returns: 更新後のitem。見つからなければNone。"""
    now = now or datetime.now(JST)
    data = load_review_data()
    item = _find(data, item_id)
    if item is None:
        return None
    item['keywords'] = list(keywords)[:MAX_KEYWORDS]
    item['updated'] = now.strftime('%Y-%m-%d')
    save_review_data(data)
    return item


def build_morning_notice():
    """朝の通知文言。復習対象が無ければ空文字を返します。"""
    items = list_items()
    if not items:
        return ""
    counts = [sum(1 for i in items if i['status'] == s) for s in range(STATUS_DONE)]
    msg = "📚 **【復習ノート】**\n"
    msg += "　".join(f"{STATUS_LABELS[s]} {counts[s]}問" for s in range(STATUS_DONE))
    if counts[0]:
        msg += "\n/menu →「📝 資格学習」→「📚 復習ノート」で、教本で調べるキーワードを確認できます。"
    return msg
