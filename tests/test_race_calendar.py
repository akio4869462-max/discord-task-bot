import subprocess
import sys
import zlib
from datetime import date, timedelta

from race_sim import calendar as cal
from race_sim import engine, rivals


SATURDAY = date(2026, 9, 12)
WEDNESDAY = date(2026, 9, 16)
FRIDAY = date(2026, 9, 11)


def test_race_days_are_saturday_and_wednesday():
    assert cal.is_race_day(SATURDAY)
    assert cal.is_race_day(WEDNESDAY)
    assert not cal.is_race_day(FRIDAY)
    assert not cal.is_race_day(date(2026, 9, 13))      # 日曜


def test_next_race_day_looks_forward():
    assert cal.next_race_day(FRIDAY) == SATURDAY
    assert cal.next_race_day(SATURDAY) == SATURDAY     # 当日も開催日
    assert cal.next_race_day(date(2026, 9, 13)) == WEDNESDAY


def test_offers_are_stable_within_a_day():
    a = cal.offers('2勝', SATURDAY)
    b = cal.offers('2勝', SATURDAY)
    assert a == b and len(a) == cal.OFFER_COUNT


def test_seed_does_not_depend_on_the_process():
    """⭕ 組み込みの hash() は文字列に対してプロセスごとに違う値を返す。それを種に
       使うとBotを再起動するたびに番組表が変わってしまう。"""
    assert cal._date_seed(SATURDAY, '3勝') == zlib.crc32('2026-09-12|3勝'.encode('utf-8'))


def test_offers_survive_a_restart():
    """別プロセスで作った番組表が一致すること（上の性質の実地確認）。"""
    code = ("import sys, datetime; sys.path.insert(0, '.');"
            "from race_sim import calendar as c;"
            "print([r['id'] + r['name'] for r in c.offers('3勝', datetime.date(2026, 9, 12))])")
    runs = [subprocess.run([sys.executable, '-c', code], capture_output=True,
                           text=True, encoding='utf-8',
                           stdin=subprocess.DEVNULL).stdout.strip() for _ in range(2)]
    assert runs[0] and runs[0] == runs[1]


def test_different_days_give_different_races():
    assert cal.offers('2勝', SATURDAY) != cal.offers('2勝', WEDNESDAY)


def test_every_class_can_find_races():
    for cls in engine.CLASS_ORDER:
        races = cal.offers(cls, SATURDAY)
        assert races, cls
        assert all(r['class'] == cls for r in races)


def test_offers_are_only_conditions_the_pool_can_fill():
    """⭕ ダートのG2のような実在しない番組を組むと、芝の馬が適性ペナルティを
       背負って動員され、勝ち時計が1秒以上遅くなる。"""
    for cls in engine.CLASS_ORDER:
        for race in cal.offers(cls, SATURDAY):
            assert rivals.is_supported(race), race


def test_graded_races_are_held_at_major_courses():
    """G1が福島や小倉で組まれると競馬として嘘になる。"""
    for race in cal.offers('G1', SATURDAY) + cal.offers('G1', WEDNESDAY):
        assert race['course'] in cal.GRADE_COURSES['G1'], race


def test_race_names_are_unique_within_a_day():
    for cls in ('2勝', '3勝', 'OP', 'G1'):
        names = [r['name'] for r in cal.offers(cls, SATURDAY)]
        assert len(names) == len(set(names)), cls


def test_conditional_classes_use_the_class_name():
    for cls in ('未勝利', '1勝'):
        assert all(r['name'] == f"{cls}クラス" for r in cal.offers(cls, SATURDAY))


def test_race_carries_everything_the_engine_and_viewer_need():
    race = cal.offers('G2', SATURDAY)[0]
    for key in ('id', 'name', 'date', 'course', 'surface', 'distance', 'cond',
                'class', 'grade', 'prize', 'course_config'):
        assert key in race, key
    # engine.simulate() にそのまま渡せること
    entries = rivals.build_field(race, size=12, seed=1)
    assert len(engine.simulate(race, entries, seed=1)['horses']) == 12


def test_course_config_is_set_only_where_it_exists():
    for cls in engine.CLASS_ORDER:
        for race in cal.offers(cls, SATURDAY):
            if race['course'] in cal.DUAL_COURSES:
                assert race['course_config'] in ('内', '外')
            else:
                assert race['course_config'] is None


def test_prize_grows_with_the_class():
    prizes = [cal.CLASS_INFO[c]['prize'] for c in engine.CLASS_ORDER]
    assert prizes == sorted(prizes)


def test_aptitude_shifts_the_offers_toward_suited_conditions():
    """得意条件を持たせると、その条件のレースが出やすくなる。"""
    dirt_sprinter = {'turf': 'D', 'dirt': 'A', 'sprint': 'A', 'mile': 'B',
                     'middle': 'D', 'long': 'D'}
    hits = 0
    for day in (SATURDAY, WEDNESDAY, date(2026, 9, 19), date(2026, 9, 23)):
        for race in cal.offers('1勝', day, aptitude=dirt_sprinter):
            if race['surface'] == 'ダ' and race['distance'] <= 1400:
                hits += 1
    assert hits >= 6


def test_find_recovers_a_race_by_id():
    race = cal.offers('OP', SATURDAY)[2]
    assert cal.find(race['id'], 'OP', SATURDAY) == race
    assert cal.find('存在しないid', 'OP', SATURDAY) is None


# ====================================================
# 遠征費
# ====================================================
def test_every_race_carries_its_travel_cost():
    for race in cal.offers('1勝', SATURDAY):
        assert race['travel'] == cal.TRAVEL_COST[race['course']]
    assert all(cal.TRAVEL_COST[c] == 0 for c in cal.HOME_COURSES)


def test_offers_always_include_a_home_race():
    """⭕ 資金0でも出走できるよう、遠征費0の地元レースを必ず1本入れる。
       遠い競馬場ばかり得意な馬でも同じ。"""
    far_lover = {'turf': 'A', 'dirt': 'A', 'sprint': 'A', 'mile': 'A', 'middle': 'A', 'long': 'A'}
    for cls in engine.CLASS_ORDER:
        for i in range(30):
            day = SATURDAY + timedelta(days=7 * i)
            races = cal.offers(cls, day, aptitude=far_lover)
            if races:
                assert any(r['travel'] == 0 for r in races), (cls, day)


def test_offers_are_still_deterministic_with_the_home_guarantee():
    assert cal.offers('3勝', WEDNESDAY) == cal.offers('3勝', WEDNESDAY)
