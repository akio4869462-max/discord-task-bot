import json
from datetime import date

import pytest

import horse_logic as hl


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """各テストが本物の data/ を読み書きしないよう差し替える。

    ⭕ horse_logic は厩舎データと旧RPGデータの2つを読む。片方だけ差し替えると
       実データを巻き込む（news_logic で実際に起きたのと同じ事故）。
    """
    monkeypatch.setattr(hl, 'STABLE_FILE', str(tmp_path / 'stable.json'))
    monkeypatch.setattr(hl, 'LEGACY_PLAYER_FILE', str(tmp_path / 'player_data.json'))
    return tmp_path


TODAY = date(2026, 9, 11)          # 金曜
RACE_DAY = date(2026, 9, 12)       # 土曜


def grown(data, hours, today=TODAY):
    """指定時間ぶん、6つの能力に均等に積む。"""
    minutes = hours * 60 / len(hl.PARAMS)
    for category, weights in hl.ACTIVITY_PARAMS.items():
        share = sum(weights.values())
        hl.add_growth(category, minutes * len(weights) / share, today=today,
                      data=data, save=False)
    return data


# ====================================================
# 成長カーブ
# ====================================================
def test_ability_starts_at_debut_level():
    assert hl.ability_of(0) == hl.BASE_ABILITY == 140


def test_g1_level_takes_most_of_a_career_without_breeding():
    """⭕ 「配合も育成も上手くやってG1を7勝」の弧。育成だけでG1平均(680)に届くには
       134時間（換算19h/週で7週）要り、上限1000は配合の上積みが無いと現役中に届かない。"""
    per_param = 134 * 60 / len(hl.PARAMS)
    assert hl.ability_of(per_param) == pytest.approx(680, abs=3)
    ten_weeks = 19 * 10 * 60 / len(hl.PARAMS)        # 換算19h/週 × 10週
    assert 680 < hl.ability_of(ten_weeks) < hl.ABILITY_CAP


def test_growth_curve_matches_the_documented_milestones():
    """docs/RACE_DESIGN.md の到達時間の表と一致すること。"""
    for hours, ability in [(25.7, 310), (47.1, 400), (74.9, 500), (133.7, 680), (260.0, 1000)]:
        per_param = hours * 60 / len(hl.PARAMS)
        assert hl.ability_of(per_param) == pytest.approx(ability, abs=4), hours


def test_ability_is_capped():
    assert hl.ability_of(10 ** 6) == hl.ABILITY_CAP


def test_growth_has_diminishing_returns():
    """同じ1時間でも、序盤のほうが伸びる。"""
    early = hl.ability_of(60) - hl.ability_of(0)
    late = hl.ability_of(660) - hl.ability_of(600)
    assert early > late * 2


def test_derive_params_covers_every_parameter():
    params = hl.derive_params({'speed': 600})
    assert set(params) == set(hl.PARAMS)
    assert params['speed'] > params['stamina']


# ====================================================
# 厩舎データと旧RPGからの移行
# ====================================================
def test_new_stable_has_a_debut_horse():
    data = hl.load_stable(TODAY)
    assert data['generation'] == 1
    assert data['current']['class'] == '未勝利'
    assert data['current']['record']['starts'] == 0
    assert hl.derive_params(data['current']['growth'])['speed'] == 140


def test_legacy_rpg_data_becomes_the_first_horse(isolated_files):
    """旧 player_data.json の累積時間を初代馬の成長に読み替えること。"""
    (isolated_files / 'player_data.json').write_text(json.dumps({
        'level': 5, 'exp': 2180, 'programming': 135, 'document': 55, 'reading': 8,
        'last_active_date': '2026-09-08', 'current_streak': 3,
        'badges': ['first_boss'],
    }), encoding='utf-8')

    data = hl.load_stable(TODAY)
    growth = data['current']['growth']
    assert growth['speed'] == 135        # 開発 → スピード
    assert growth['guts'] == 55          # 書類 → 根性
    assert growth['wit'] == 8            # インプット → 賢さ
    assert data['current_streak'] == 3
    # レベル・EXP・バッジは引き継がない
    assert 'level' not in data and 'badges' not in data


def test_missing_keys_are_filled_on_load(isolated_files):
    """古い厩舎データを読んでも落ちないこと。"""
    (isolated_files / 'stable.json').write_text(json.dumps({
        'generation': 2,
        'current': {'id': 'x', 'name': 'テスト', 'sex': '牡', 'class': '1勝',
                    'aptitude': {}, 'growth': {'speed': 100}},
    }), encoding='utf-8')

    data = hl.load_stable(TODAY)
    assert data['current']['entry'] is None
    assert data['current']['record']['starts'] == 0
    assert data['current']['growth']['dash'] == 0.0
    assert data['retired'] == [] and data['stallions'] == []


def test_save_and_reload_round_trips():
    data = hl.load_stable(TODAY)
    hl.add_growth('programming', 120, today=TODAY, data=data)
    reloaded = hl.load_stable(TODAY)
    share = hl.ACTIVITY_PARAMS['programming']['speed']
    assert reloaded['current']['growth']['speed'] == 120 * share


# ====================================================
# 活動と成長
# ====================================================
def test_each_activity_feeds_its_own_parameter():
    for category, weights in hl.ACTIVITY_PARAMS.items():
        data = hl.load_stable(TODAY)
        hl.add_growth(category, 100, today=TODAY, data=data, save=False)
        for param in hl.PARAMS:
            expected = 100 * weights.get(param, 0)
            assert data['current']['growth'][param] == pytest.approx(expected), (category, param)


def test_training_and_typing_are_counted_as_sessions():
    """時間を記録していない活動は回数で換算する。"""
    data = hl.load_stable(TODAY)
    hl.log_training(today=TODAY, data=data, save=False)
    hl.log_typing(today=TODAY, data=data, save=False)
    growth = data['current']['growth']
    assert growth['stamina'] == hl.TRAINING_MINUTES * hl.ACTIVITY_PARAMS['training']['stamina']
    assert growth['power'] == hl.TRAINING_MINUTES * hl.ACTIVITY_PARAMS['training']['power']
    assert growth['dash'] == hl.TYPING_MINUTES * hl.ACTIVITY_PARAMS['typing']['dash']


def test_add_growth_reports_what_went_up():
    data = hl.load_stable(TODAY)
    result = hl.add_growth('programming', 120, today=TODAY, data=data, save=False)
    assert set(result['gains']) == set(hl.ACTIVITY_PARAMS['programming'])
    assert all(v > 0 for v in result['gains'].values())


def test_every_parameter_has_at_least_one_source():
    """⭕ 供給源の無い能力があると、その能力は140のまま張り付く。書類作成を廃止した
       ときに根性がこの状態になった。"""
    fed = set()
    for category, weights in hl.ACTIVITY_PARAMS.items():
        if category == 'document':      # 廃止済み。古いタスク用に残しているだけ
            continue
        fed |= set(weights)
    assert fed == set(hl.PARAMS), f"供給源が無い能力: {set(hl.PARAMS) - fed}"


def test_activity_weights_sum_to_one():
    """配分の合計が1でないと、活動によって1分の価値が変わってしまう。"""
    for category, weights in hl.ACTIVITY_PARAMS.items():
        assert sum(weights.values()) == pytest.approx(1.0), category


def test_realistic_week_does_not_leave_a_parameter_far_behind():
    """⭕ 実際の1週（開発6h・インプット3h・筋トレ5回・タイピング5回）を4週続けたとき、
       一番伸びる能力と一番伸びない能力の差が2倍を超えないこと。

       開発作業は時間で記録されるのに対し筋トレ・タイピングは回数なので、換算値が
       小さいとスタミナ・パワーだけ置いていかれる（15分相当だった頃は2.66倍あった）。
       ACTIVITY_PARAMS の重みや換算値をいじったときに、この偏りが再発すると落ちる。"""
    week = {
        'programming': 6 * 60,
        'reading': 3 * 60,
        'training': 5 * hl.TRAINING_MINUTES,
        'typing': 5 * hl.TYPING_MINUTES,
    }
    growth = {p: 0.0 for p in hl.PARAMS}
    for category, minutes in week.items():
        for param, share in hl.ACTIVITY_PARAMS[category].items():
            growth[param] += minutes * share * 4

    values = list(hl.derive_params(growth).values())
    assert max(values) / min(values) < 2.0, hl.derive_params(growth)


# ====================================================
# あとから記録する
# ====================================================
def test_backfill_adds_several_days_at_once():
    data = hl.load_stable(TODAY)
    days = [date(2026, 9, d) for d in (5, 6, 8)]
    result = hl.backfill('typing', days, data=data, save=False)

    assert result['days'] == 3
    expected = hl.TYPING_MINUTES * 3 * hl.ACTIVITY_PARAMS['typing']['dash']
    assert data['current']['growth']['dash'] == pytest.approx(expected)


def test_backfill_takes_minutes_for_timed_activities():
    data = hl.load_stable(TODAY)
    hl.backfill('programming', [date(2026, 9, 5), date(2026, 9, 6)], minutes=90,
                data=data, save=False)
    share = hl.ACTIVITY_PARAMS['programming']['speed']
    assert data['current']['growth']['speed'] == pytest.approx(180 * share)


def test_backfill_does_not_touch_the_streak():
    """⭕ 連続記録は「今日やったか」の指標。昔の日を足しても伸ばしてはいけないし、
       last_active_date を過去に巻き戻してもいけない。"""
    data = hl.load_stable(TODAY)
    hl.add_growth('programming', 30, today=TODAY, data=data, save=False)
    before_streak = data['current_streak']
    before_date = data['last_active_date']

    hl.backfill('typing', [date(2026, 8, 1), date(2026, 8, 2)], data=data, save=False)

    assert data['current_streak'] == before_streak
    assert data['last_active_date'] == before_date


def test_backfill_ignores_empty_input():
    data = hl.load_stable(TODAY)
    result = hl.backfill('typing', [], data=data, save=False)
    assert result['days'] == 0 and result['gains'] == {}
    assert hl.total_minutes(data['current']['growth']) == 0


def test_backfill_is_capped_per_call():
    data = hl.load_stable(TODAY)
    days = [date(2026, 8, d) for d in range(1, 25)]
    result = hl.backfill('typing', days, data=data, save=False)
    assert result['days'] == hl.BACKFILL_MAX_DATES


def test_unknown_category_changes_nothing():
    data = hl.load_stable(TODAY)
    result = hl.add_growth('存在しない', 120, today=TODAY, data=data, save=False)
    assert result['gains'] == {}
    assert hl.total_minutes(data['current']['growth']) == 0


# ====================================================
# 連続記録と調子
# ====================================================
def test_streak_counts_consecutive_days():
    data = hl.load_stable(TODAY)
    for i in range(3):
        hl.add_growth('programming', 30, today=date(2026, 9, 9 + i), data=data, save=False)
    assert data['current_streak'] == 3


def test_streak_resets_after_a_gap():
    data = hl.load_stable(TODAY)
    hl.add_growth('programming', 30, today=date(2026, 9, 1), data=data, save=False)
    hl.add_growth('programming', 30, today=date(2026, 9, 5), data=data, save=False)
    assert data['current_streak'] == 1


def test_same_day_does_not_double_count_the_streak():
    data = hl.load_stable(TODAY)
    hl.add_growth('programming', 30, today=TODAY, data=data, save=False)
    hl.add_growth('reading', 30, today=TODAY, data=data, save=False)
    assert data['current_streak'] == 1


def test_condition_improves_with_a_long_streak():
    data = hl.load_stable(TODAY)
    data['last_active_date'] = TODAY.isoformat()
    data['current_streak'] = 25
    assert hl.condition_of(data, TODAY) == 2
    data['current_streak'] = 8
    assert hl.condition_of(data, TODAY) == 1


def test_condition_falls_when_days_are_missed():
    data = hl.load_stable(TODAY)
    data['last_active_date'] = date(2026, 9, 9).isoformat()
    data['current_streak'] = 30
    assert hl.condition_of(data, TODAY) == -1        # 2日空いた
    data['last_active_date'] = date(2026, 9, 5).isoformat()
    assert hl.condition_of(data, TODAY) == -2        # 6日空いた


# ====================================================
# 出走
# ====================================================
def test_available_races_are_for_the_current_class():
    data = hl.load_stable(TODAY)
    data['current']['class'] = '2勝'
    day, races = hl.available_races(data, on=TODAY)
    assert day == RACE_DAY
    assert races and all(r['class'] == '2勝' for r in races)


def test_entering_a_race_records_the_declared_style():
    data = hl.load_stable(TODAY)
    _, races = hl.available_races(data, on=TODAY)
    hl.enter_race(races[0], style='逃げ', data=data, save=False)
    assert data['current']['entry']['id'] == races[0]['id']
    assert data['current']['style'] == '逃げ'


def test_cancelling_clears_the_entry():
    data = hl.load_stable(TODAY)
    _, races = hl.available_races(data, on=TODAY)
    hl.enter_race(races[0], data=data, save=False)
    hl.cancel_entry(data=data, save=False)
    assert data['current']['entry'] is None


def test_running_without_an_entry_returns_nothing():
    data = hl.load_stable(TODAY)
    assert hl.run_entry(data=data, today=RACE_DAY, save=False) is None


def test_running_a_race_updates_the_record():
    data = grown(hl.load_stable(TODAY), 12)
    _, races = hl.available_races(data, on=TODAY)
    hl.enter_race(races[0], data=data, save=False)
    out = hl.run_entry(data=data, today=RACE_DAY, save=False)

    assert 1 <= out['finish'] <= len(out['result']['horses'])
    assert data['current']['record']['starts'] == 1
    assert data['current']['entry'] is None
    assert len(data['current']['history']) == 1
    assert data['current']['history'][0]['race'] == races[0]['name']


def test_the_same_horse_and_race_always_give_the_same_result():
    """seedは馬とレースから決まるので、結果は再現できる。"""
    import copy
    base = grown(hl.load_stable(TODAY), 12)
    base['current']['id'] = 'fixed-id'
    finishes = []
    for _ in range(2):
        data = copy.deepcopy(base)                   # 同じ馬（適性・性別も同じ）で2回走らせる
        _, races = hl.available_races(data, on=TODAY)
        hl.enter_race(races[0], data=data, save=False)
        finishes.append(hl.run_entry(data=data, today=RACE_DAY, save=False)['finish'])
    assert finishes[0] == finishes[1]


def test_winning_promotes_one_class():
    data = grown(hl.load_stable(TODAY), 30)
    race = {'id': 'x', 'name': 'テスト', 'date': RACE_DAY.isoformat(), 'course': '東京',
            'surface': '芝', 'distance': 1600, 'cond': '良', 'class': '未勝利',
            'grade': None, 'prize': 520, 'course_config': None}
    mine = {'finish': 1, 'time': 95.0, 'last3f': 34.0, 'passing': [3, 3], 'style': '差し'}
    events = hl._apply_result(data, race, mine, RACE_DAY, 16)

    assert data['current']['class'] == '1勝'
    assert data['current']['record']['prize'] == 520
    assert any('昇級' in e for e in events)


def test_losing_does_not_promote():
    data = hl.load_stable(TODAY)
    race = {'id': 'x', 'name': 'テスト', 'date': RACE_DAY.isoformat(), 'course': '東京',
            'surface': '芝', 'distance': 1600, 'cond': '良', 'class': '未勝利',
            'grade': None, 'prize': 520, 'course_config': None}
    mine = {'finish': 4, 'time': 96.0, 'last3f': 35.0, 'passing': [8, 6], 'style': '差し'}
    hl._apply_result(data, race, mine, RACE_DAY, 16)

    assert data['current']['class'] == '未勝利'
    assert data['current']['record']['win'] == 0
    assert data['current']['record']['prize'] == int(520 * hl.PRIZE_SHARE[4])


def test_g1_winner_stays_at_the_top():
    data = hl.load_stable(TODAY)
    data['current']['class'] = 'G1'
    race = {'id': 'x', 'name': 'テスト', 'date': RACE_DAY.isoformat(), 'course': '東京',
            'surface': '芝', 'distance': 2000, 'cond': '良', 'class': 'G1',
            'grade': 'G1', 'prize': 15000, 'course_config': None}
    mine = {'finish': 1, 'time': 118.0, 'last3f': 34.0, 'passing': [2, 2], 'style': '先行'}
    events = hl._apply_result(data, race, mine, RACE_DAY, 16)

    assert data['current']['class'] == 'G1'
    assert any('G1制覇' in e for e in events)


# ====================================================
# 引退と世代交代
# ====================================================
def test_retires_after_twenty_starts():
    data = hl.load_stable(TODAY)
    first_name = data['current']['name']
    data['current']['record']['starts'] = hl.RETIRE_STARTS - 1
    race = {'id': 'x', 'name': 'テスト', 'date': RACE_DAY.isoformat(), 'course': '東京',
            'surface': '芝', 'distance': 1600, 'cond': '良', 'class': '1勝',
            'grade': None, 'prize': 770, 'course_config': None}
    mine = {'finish': 5, 'time': 96.0, 'last3f': 35.0, 'passing': [7, 7], 'style': '差し'}
    events = hl._apply_result(data, race, mine, RACE_DAY, 16)

    assert any('引退' in e for e in events)
    assert data['generation'] == 2
    assert data['current']['name'] != first_name
    assert data['current']['record']['starts'] == 0
    assert len(data['retired']) == 1


def test_the_next_generation_inherits_from_the_parent():
    data = grown(hl.load_stable(TODAY), 40)
    parent = data['current']['name']
    parent_growth = dict(data['current']['growth'])
    hl.retire(data, RACE_DAY)

    child = data['current']
    parents = [hl._ped_name(child['pedigree'][s]) for s in ('sire', 'dam')]
    assert parent in parents and '－' in parents        # 相手なしなら片親だけ
    for key in hl.PARAMS:
        assert 0 < child['growth'][key] < parent_growth[key]
    assert hl.derive_params(child['growth'])['speed'] > hl.BASE_ABILITY


def test_retired_horses_are_kept_as_breeding_stock():
    """⭕ 配合を後から足せるよう、引退馬は能力と成績を持った実体として残す。"""
    data = grown(hl.load_stable(TODAY), 20)
    data['current']['record']['win'] = 5
    hl.retire(data, RACE_DAY)

    stud = data['stallions'][0]
    assert set(stud['params']) == set(hl.PARAMS)
    assert stud['record']['win'] == 5
    assert stud['aptitude']
    assert stud['stud_value'] > 1.0


def test_winning_more_raises_the_stud_value():
    plain = {'record': {'win': 0}, 'class': '1勝'}
    winner = {'record': {'win': 6}, 'class': 'G1'}
    assert hl.stud_value(winner) > hl.stud_value(plain)


# ====================================================
# 表示
# ====================================================
def test_format_horse_shows_the_essentials():
    data = grown(hl.load_stable(TODAY), 10)
    text = hl.format_horse(data, TODAY)
    assert data['current']['name'] in text
    assert '未勝利' in text
    assert 'スピード' in text and '適性' in text
    assert f"残り{hl.RETIRE_STARTS}戦" in text


def test_format_races_lists_every_offer():
    data = hl.load_stable(TODAY)
    day, races = hl.available_races(data, on=TODAY)
    text = hl.format_races(day, races)
    for r in races:
        assert r['name'] in text
        assert f"{r['distance']}m" in text


def test_format_races_handles_an_empty_day():
    assert '出走できるレースがありません' in hl.format_races(RACE_DAY, [])


def raced(hours=12):
    """1レース走らせて結果を返す。"""
    data = grown(hl.load_stable(TODAY), hours)
    _, races = hl.available_races(data, on=TODAY)
    hl.enter_race(races[0], data=data, save=False)
    return data, races[0], hl.run_entry(data=data, today=RACE_DAY, save=False)


def test_format_result_reports_the_finish():
    data, race, out = raced()
    text = hl.format_result(out)

    assert race['name'] in text
    # ⭕ 着順表は馬名を表示幅で切り詰めるので、全文ではなく先頭で探す
    #    （9文字の名前を引いたときだけ落ちる flaky があった）
    assert '★' + data['current']['name'][:6] in text   # 自分の馬が着順表にいて印が付く
    if out['finish'] == 1:
        assert '勝ちました' in text
    else:
        assert f"{out['finish']}着" in text


def test_format_result_always_shows_my_horse_even_when_beaten():
    """⭕ 上位5頭だけだと、大敗したとき自分の行が消えて結果が分からない。"""
    _, _, out = raced()
    me = next(h for h in out['result']['horses'] if h['is_player'])
    me['finish'] = 12                                # 大敗したことにする
    out['finish'] = 12
    text = hl.format_result(out)
    assert '★' in text and '12着' in text


def test_format_result_can_hide_the_outcome():
    """Discordのネタバレ（||…||）で結果だけ伏せられること。"""
    _, race, out = raced()
    hidden = hl.format_result(out, spoiler=True)

    # レース名は見えたまま、結果はネタバレの中
    head, body = hl.format_result_parts(out)
    assert hidden.startswith(head)
    assert f"||{body}||" in hidden
    assert race['name'] not in body                  # 見出しに結果は含まれない


def test_format_result_is_plain_by_default():
    """CLIから呼ぶときは伏せない（ターミナルでは `||` がただの文字になる）。"""
    _, _, out = raced()
    assert '||' not in hl.format_result(out)


# ====================================================
# 開催日の朝の告知
# ====================================================
def test_race_day_notice_is_silent_on_a_non_race_day():
    """開催日以外は何も出さない（毎朝うるさくしない）。"""
    assert hl.format_race_day_notice(today=TODAY) is None


def test_race_day_notice_warns_when_nothing_is_entered():
    """⭕ レースは20:00に自動で走るので、登録忘れに気づく手段がこれしか無い。"""
    data = grown(hl.load_stable(TODAY), 12)
    text = hl.format_race_day_notice(data=data, today=RACE_DAY)

    assert '出走登録がありません' in text
    assert '20:00' in text
    _, races = hl.available_races(data, on=RACE_DAY)
    assert races[0]['name'] in text          # その日の番組表も一緒に出す


def test_race_day_notice_confirms_the_entry():
    data = grown(hl.load_stable(TODAY), 12)
    _, races = hl.available_races(data, on=RACE_DAY)
    hl.enter_race(races[0], data=data, save=False)

    text = hl.format_race_day_notice(data=data, today=RACE_DAY)

    assert races[0]['name'] in text
    assert '出走登録がありません' not in text
    assert '20:00' in text


def test_race_day_notice_flags_an_entry_left_over_from_another_day():
    """⭕ run_entry() は登録の日付を見ないので、Botが落ちて走り損なった登録は
       今夜そのまま古いレースとして走る。黙ってそうなると面食らうので告知する。"""
    data = grown(hl.load_stable(TODAY), 12)
    _, races = hl.available_races(data, on=RACE_DAY)
    stale = dict(races[0], date='2026-09-09')
    hl.enter_race(stale, data=data, save=False)

    text = hl.format_race_day_notice(data=data, today=RACE_DAY)

    assert '2026-09-09' in text
    assert '取り直して' in text
    assert '今夜20:00' in text       # 黙って消えるのではなく、それが走ると伝える
