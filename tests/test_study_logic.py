import json
from datetime import date

import pytest

import study_logic


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """各テストが本物のdata/player_data.json・glossary.jsonに影響しないよう差し替える。"""
    monkeypatch.setattr(study_logic, 'PLAYER_DATA_FILE', str(tmp_path / 'player_data.json'))
    monkeypatch.setattr(study_logic, 'GLOSSARY_FILE', str(tmp_path / 'glossary.json'))


def test_load_player_data_returns_default_when_missing():
    data = study_logic.load_player_data()
    assert data['level'] == 1
    assert data['exp'] == 0
    assert data['is_boss_active'] is False


def test_add_exp_accumulates_time_and_exp():
    study_logic.add_exp('programming', 10)
    data = study_logic.load_player_data()
    assert data['programming'] == 10
    assert data['total_minutes'] == 10
    assert data['exp'] == 10 * study_logic.EXP_PER_MINUTE


def test_check_level_up_formula_matches_required_threshold():
    # Lv.2に必要な経験値は (2-1)^2 * EXP_BASE_UNIT
    required = ((2 - 1) ** 2) * study_logic.EXP_BASE_UNIT
    is_eligible, diffs, next_lv = study_logic.check_level_up({'level': 1, 'exp': required})
    assert is_eligible is True
    assert next_lv == 2


def test_check_level_up_insufficient_exp():
    is_eligible, diffs, next_lv = study_logic.check_level_up({'level': 1, 'exp': 1})
    assert is_eligible is False
    assert diffs['total_exp'] > 0


def test_add_exp_triggers_level_up_when_threshold_reached():
    required_minutes = (((2 - 1) ** 2) * study_logic.EXP_BASE_UNIT) // study_logic.EXP_PER_MINUTE
    result = study_logic.add_exp('programming', required_minutes)
    assert result['is_level_up'] is True
    assert result['new_level'] == 2


def test_boss_appears_after_threshold_minutes():
    first_boss = study_logic.BOSS_LIST[0]

    # 閾値未満ではボスは出現しない
    study_logic.add_exp('programming', first_boss['threshold'] - 1)
    assert study_logic.load_player_data()['is_boss_active'] is False

    # 閾値に到達した瞬間にボス出現
    result = study_logic.add_exp('programming', 1)
    assert result['event'] == 'BOSS_APPEAR'
    data = study_logic.load_player_data()
    assert data['is_boss_active'] is True
    assert data['boss_hp'] == first_boss['hp']


def test_boss_takes_damage_then_is_defeated():
    first_boss = study_logic.BOSS_LIST[0]
    study_logic.add_exp('programming', first_boss['threshold'])  # ボス出現

    # HPより少ない作業ではダメージのみ
    result = study_logic.add_exp('programming', first_boss['hp'] - 1)
    assert result['event'] == 'BOSS_DAMAGE'
    assert study_logic.load_player_data()['is_boss_active'] is True

    # 残りHP分の作業で撃破
    result = study_logic.add_exp('programming', 1)
    assert result['event'] == 'BOSS_DEFEATED'
    data = study_logic.load_player_data()
    assert data['is_boss_active'] is False
    assert data['current_boss_idx'] == 1


def test_streak_starts_at_1_on_first_activity():
    result = study_logic.add_exp('programming', 10)
    assert result['streak'] == 1


def test_streak_does_not_increment_twice_on_same_day():
    result1 = study_logic.add_exp('programming', 10)
    result2 = study_logic.add_exp('programming', 10)
    assert result1['streak'] == result2['streak'] == 1


def test_streak_increments_when_active_on_consecutive_days():
    from datetime import datetime, timedelta
    yesterday = (datetime.now(study_logic.JST) - timedelta(days=1)).strftime('%Y-%m-%d')
    data = study_logic.load_player_data()
    data['last_active_date'] = yesterday
    data['current_streak'] = 2
    study_logic.save_player_data(data)

    result = study_logic.add_exp('programming', 10)
    assert result['streak'] == 3


def test_streak_resets_when_a_day_is_skipped():
    from datetime import datetime, timedelta
    two_days_ago = (datetime.now(study_logic.JST) - timedelta(days=2)).strftime('%Y-%m-%d')
    data = study_logic.load_player_data()
    data['last_active_date'] = two_days_ago
    data['current_streak'] = 5
    study_logic.save_player_data(data)

    result = study_logic.add_exp('programming', 10)
    assert result['streak'] == 1


def test_streak_bonus_is_applied_to_earned_exp():
    from datetime import datetime, timedelta
    yesterday = (datetime.now(study_logic.JST) - timedelta(days=1)).strftime('%Y-%m-%d')
    data = study_logic.load_player_data()
    data['last_active_date'] = yesterday
    data['current_streak'] = 2  # 今日の活動で3日目(閾値3 = +10%)に到達させる
    study_logic.save_player_data(data)

    result = study_logic.add_exp('programming', 10)
    assert result['streak'] == 3
    assert result['earned_exp'] == int(10 * study_logic.EXP_PER_MINUTE * 1.1)


def test_new_badge_awarded_on_first_boss_defeat():
    first_boss = study_logic.BOSS_LIST[0]
    study_logic.add_exp('programming', first_boss['threshold'])  # ボス出現
    result = study_logic.add_exp('programming', first_boss['hp'])  # ちょうど撃破

    badge_ids = [b['id'] for b in result['new_badges']]
    assert 'first_boss' in badge_ids
    assert 'first_boss' in study_logic.load_player_data()['badges']


def test_badge_is_not_awarded_twice():
    first_boss = study_logic.BOSS_LIST[0]
    study_logic.add_exp('programming', first_boss['threshold'])
    result1 = study_logic.add_exp('programming', first_boss['hp'])
    assert any(b['id'] == 'first_boss' for b in result1['new_badges'])

    result2 = study_logic.add_exp('programming', 10)
    assert not any(b['id'] == 'first_boss' for b in result2['new_badges'])


@pytest.mark.parametrize('minutes,expected', [
    (30, '30分'),
    (60, '1時間'),
    (90, '1時間30分'),
])
def test_format_minutes_to_hours(minutes, expected):
    assert study_logic.format_minutes_to_hours(minutes) == expected


def test_get_title_default_for_new_player():
    data = {'programming': 0, 'document': 0, 'reading': 0, 'level': 1}
    assert study_logic.get_title(data) == '🐣 覚醒を待つギーク'


def test_get_title_balanced_top_rank():
    data = {'programming': 500, 'document': 200, 'reading': 200, 'level': 1}
    assert study_logic.get_title(data) == '🏆 フルスタック・就活マスター'


def test_add_kiso_and_search_glossary():
    study_logic.add_kiso('AI', 'テスト概要')
    result = study_logic.search_glossary('AI')
    assert 'AI' in result
    assert 'テスト概要' in result


def test_search_glossary_no_match_returns_not_found_message():
    study_logic.add_kiso('AI', '概要')
    result = study_logic.search_glossary('存在しない用語')
    assert '見つかりませんでした' in result


def test_get_glossary_list_when_empty():
    assert 'ありません' in study_logic.get_glossary_list()


def test_get_kiso_quiz_when_empty():
    msg, term = study_logic.get_kiso_quiz()
    assert '用語が登録されていません' in msg
    assert term is None


# ====================================================
# 用語集の新形式移行 / 間隔反復（SRS）
# ====================================================

TODAY = date(2026, 8, 11)


def test_load_glossary_migrates_legacy_string_format():
    """旧形式（値が解説文の文字列）のデータが、解説を保ったまま新形式へ移行される"""
    with open(study_logic.GLOSSARY_FILE, 'w', encoding='utf-8') as f:
        json.dump({'AI': '人工知能のこと'}, f, ensure_ascii=False)

    glossary = study_logic.load_glossary()

    assert glossary['AI']['desc'] == '人工知能のこと'
    assert glossary['AI']['next_review'] is None
    assert glossary['AI']['interval'] == 0


def test_add_kiso_creates_entry_with_srs_fields():
    study_logic.add_kiso('DNS', '名前解決の仕組み')
    entry = study_logic.load_glossary()['DNS']

    assert entry['desc'] == '名前解決の仕組み'
    assert entry['interval'] == 0
    assert entry['correct_count'] == 0


def test_add_kiso_existing_term_updates_desc_without_resetting_progress():
    study_logic.add_kiso('DNS', '古い説明')
    study_logic.review_term('DNS', remembered=True, today=TODAY)

    study_logic.add_kiso('DNS', '新しい説明')
    entry = study_logic.load_glossary()['DNS']

    assert entry['desc'] == '新しい説明'
    assert entry['correct_count'] == 1  # 復習の進捗は維持される


def test_quiz_asks_for_term_given_description():
    """出題は本番と同じ「説明文→用語」の向きで、答えの用語が伏せられている"""
    study_logic.add_kiso('DNS', '名前解決の仕組み')
    msg, term = study_logic.get_kiso_quiz(today=TODAY)

    assert '名前解決の仕組み' in msg   # 説明文は見える
    assert '||DNS||' in msg           # 用語はスポイラーで隠れている
    assert term == 'DNS'


def test_review_term_correct_answer_extends_interval():
    study_logic.add_kiso('DNS', '説明')

    study_logic.review_term('DNS', remembered=True, today=TODAY)
    assert study_logic.load_glossary()['DNS']['interval'] == 1

    study_logic.review_term('DNS', remembered=True, today=TODAY)
    assert study_logic.load_glossary()['DNS']['interval'] == 2

    study_logic.review_term('DNS', remembered=True, today=TODAY)
    assert study_logic.load_glossary()['DNS']['interval'] == 4


def test_review_term_wrong_answer_resets_interval_to_one_day():
    study_logic.add_kiso('DNS', '説明')
    for _ in range(4):
        study_logic.review_term('DNS', remembered=True, today=TODAY)

    study_logic.review_term('DNS', remembered=False, today=TODAY)
    entry = study_logic.load_glossary()['DNS']

    assert entry['interval'] == 1
    assert entry['next_review'] == '2026-08-12'  # 翌日に再出題
    assert entry['wrong_count'] == 1


def test_review_term_interval_is_capped():
    study_logic.add_kiso('DNS', '説明')
    for _ in range(20):  # 十分な回数正解しても上限を超えない
        study_logic.review_term('DNS', remembered=True, today=TODAY)

    assert study_logic.load_glossary()['DNS']['interval'] == study_logic.MAX_REVIEW_INTERVAL_DAYS


def test_review_term_unknown_term_returns_message():
    assert '見つかりません' in study_logic.review_term('存在しない用語', remembered=True, today=TODAY)


def test_pick_quiz_term_prioritizes_due_terms():
    """復習期限が来ている用語が、まだ先の用語より優先して出題される"""
    study_logic.add_kiso('期限切れ', '説明A')
    study_logic.add_kiso('まだ先', '説明B')

    # 「まだ先」を遠い将来に設定し、「期限切れ」は未出題(None)のまま残す
    glossary = study_logic.load_glossary()
    glossary['まだ先']['next_review'] = '2099-01-01'
    study_logic.save_glossary(glossary)

    for _ in range(10):  # ランダム選択なので複数回試す
        term, entry, is_due = study_logic.pick_quiz_term(today=TODAY)
        assert term == '期限切れ'
        assert is_due is True


def test_pick_quiz_term_falls_back_to_random_when_nothing_due():
    study_logic.add_kiso('まだ先', '説明')
    glossary = study_logic.load_glossary()
    glossary['まだ先']['next_review'] = '2099-01-01'
    study_logic.save_glossary(glossary)

    term, entry, is_due = study_logic.pick_quiz_term(today=TODAY)

    assert term == 'まだ先'
    assert is_due is False  # 期限外なのでランダム出題扱い


def test_get_glossary_list_shows_review_status():
    study_logic.add_kiso('未出題の用語', '説明')
    study_logic.add_kiso('復習済みの用語', '説明')
    study_logic.review_term('復習済みの用語', remembered=True, today=TODAY)

    result = study_logic.get_glossary_list(today=TODAY)

    assert '🆕 未出題' in result
    assert '2026-08-12' in result  # 復習済みの用語の次回予定日
    assert '全2件' in result


def test_weekly_summary_reflects_activity_since_last_snapshot():
    study_logic.add_exp('programming', 60)  # 累計60分, 600 EXP

    summary = study_logic.get_weekly_summary()

    assert '1時間' in summary
    assert '600 EXP' in summary


def test_weekly_summary_updates_snapshot_for_next_comparison():
    study_logic.add_exp('programming', 60)
    study_logic.get_weekly_summary()

    # スナップショット更新後は、追加の活動分だけが「今週」としてカウントされる
    study_logic.add_exp('programming', 30)
    summary = study_logic.get_weekly_summary()

    assert '30分' in summary


def test_weekly_summary_shows_increase_compared_to_previous_week():
    study_logic.add_exp('programming', 30)
    study_logic.get_weekly_summary()  # 先週分: 30分

    study_logic.add_exp('programming', 60)
    summary = study_logic.get_weekly_summary()  # 今週分: 60分 (先週の2倍 = +100%)

    assert '📈' in summary
    assert '100%' in summary
