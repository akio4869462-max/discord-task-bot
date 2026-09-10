import os
from datetime import date

import pytest

os.environ.setdefault('DISCORD_TOKEN', 'dummy')  # main.pyのimport時にclient.run用のTOKEN取得で使われるだけ

import bot_state
import horse_logic
import main
import task_logic


# ====================================================
# 環境変数の読み込み（docker-composeの空文字列展開への耐性）
# ====================================================

def test_getenv_int_reads_defined_value(monkeypatch):
    monkeypatch.setenv('SOME_CHANNEL_ID', '12345')
    assert main.getenv_int('SOME_CHANNEL_ID', 999) == 12345


def test_getenv_int_falls_back_when_undefined(monkeypatch):
    monkeypatch.delenv('SOME_CHANNEL_ID', raising=False)
    assert main.getenv_int('SOME_CHANNEL_ID', 999) == 999


def test_getenv_int_falls_back_when_empty_string(monkeypatch):
    """docker-composeの ${VAR} 展開は、.envにキーが無いと空文字列を渡す。
    ここでクラッシュせずデフォルトへフォールバックできることの回帰テスト
    （本番でint('')によりBotが起動時クラッシュした実際の障害に対応）。"""
    monkeypatch.setenv('SOME_CHANNEL_ID', '')
    assert main.getenv_int('SOME_CHANNEL_ID', 999) == 999


@pytest.mark.parametrize('text,expected', [
    ('25', 25),
    ('  25  ', 25),      # 前後の空白は許容
    ('２５', 25),         # 全角数字も受け付ける
    ('0', 0),
    ('-5', -5),          # 符号付きも変換自体は成功する（範囲判定は呼び出し側の責務）
    ('abc', None),
    ('', None),
    ('2.5', None),       # 小数は整数として解釈できない
    ('²', None),         # isdigit()はTrueだがint()できない文字（クラッシュ防止の要）
    (None, None),
])
def test_parse_positive_int(text, expected):
    assert main.parse_positive_int(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('2.5', 2.5),
    ('  2.5  ', 2.5),
    ('10', 10.0),
    ('０.５', 0.5),   # 全角数字も受け付ける
    ('abc', None),
    ('', None),
    (None, None),
])
def test_parse_float(text, expected):
    assert main.parse_float(text) == expected


def make_result(gains=None, streak=1, capped=False, events=None):
    """horse_logic.add_growth() が返す辞書と同じ形の、テスト用の結果データを組み立てる。"""
    return {
        "gains": gains or {},
        "streak": streak,
        "condition": 0,
        "capped": capped,
        "events": events or [],
        "horse": {"name": "テストホース"},
    }


def test_build_growth_message_quiet_when_nothing_happened():
    detail, public = main.build_growth_message(make_result())
    assert detail == ''
    assert public is None


def test_build_growth_message_shows_what_went_up_privately():
    """どの能力が上がったかは毎回の細かい進捗なので、公開告知はしない。"""
    detail, public = main.build_growth_message(make_result(gains={'speed': 12}))
    assert 'スピード' in detail and '+12' in detail
    assert public is None


def test_build_growth_message_announces_the_cap():
    detail, public = main.build_growth_message(make_result(capped=True))
    assert '上限' in detail
    assert public is not None and '上限' in public


def test_build_growth_message_announces_streak_milestones():
    detail, public = main.build_growth_message(make_result(streak=7))
    assert '7日連続' in detail
    assert public is not None and '7日連続' in public


def test_build_growth_message_ignores_non_milestone_streaks():
    _, public = main.build_growth_message(make_result(streak=5))
    assert public is None


def test_build_growth_message_announces_race_events():
    detail, public = main.build_growth_message(
        make_result(events=['🏆 勝利！ 1勝クラスへ昇級しました。']))
    assert '昇級' in detail
    assert public is not None and '昇級' in public


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """⭕ horse_logic は厩舎データと旧RPGデータの2つを読む。両方差し替えないと
       実データを巻き込む。"""
    monkeypatch.setattr(task_logic, 'DB_FILE', str(tmp_path / 'todo.json'))
    monkeypatch.setattr(horse_logic, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(horse_logic, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))


# ====================================================
# 過去問演習 → 賢さの調教への自動連携
# ====================================================
# ⭕ 演習記録(exam_logic)と育成が独立していると、同じ勉強内容を
#    「📚インプットを報告」で二重入力する必要が出る。

def test_process_exam_completion_trains_wit():
    detail, _ = main.process_exam_completion(total=20)  # 20問 × 1.5分 = 30分
    assert '賢さ' in detail
    assert horse_logic.load_stable()['current']['growth']['wit'] == 30


def test_process_exam_completion_uses_rounded_minutes():
    main.process_exam_completion(total=3)   # 3問 × 1.5分 = 4.5分 → 4分か5分に丸め
    assert horse_logic.load_stable()['current']['growth']['wit'] in (4, 5)


def test_process_exam_completion_zero_questions_trains_nothing():
    detail, public = main.process_exam_completion(total=0)
    assert detail == ''
    assert public is None
    assert horse_logic.load_stable()['current']['growth']['wit'] == 0


def test_process_task_completion_trains_the_matching_parameter():
    detail, _ = main.process_task_completion('programming')
    assert 'スピード' in detail
    growth = horse_logic.load_stable()['current']['growth']
    assert growth['speed'] == bot_state.TASK_COMPLETE_MINUTES


def test_process_task_completion_without_a_category_does_nothing():
    detail, public = main.process_task_completion(None)
    assert detail == '' and public is None


def test_build_deadline_reminders_includes_tasks_within_three_days():
    today = date.today()
    task_logic.add_task('今日締切', 'programming', today.strftime('%Y-%m-%d'), 2)
    task_logic.add_task('来月締切', 'programming', '2099-01-01', 2)

    reminders = main.build_deadline_reminders(today)

    assert len(reminders) == 1
    assert '今日が締切' in reminders[0]
    assert '今日締切' in reminders[0]


def test_build_deadline_reminders_empty_when_no_tasks():
    assert main.build_deadline_reminders(date.today()) == []
