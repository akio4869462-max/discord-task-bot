import json
import os
import re
import sys

import pytest

from race_sim import engine, rivals

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'race_sim', 'tools'))
import make_viewer  # noqa: E402


RACE = {'name': '銀嶺ステークス', 'course': '東京', 'surface': '芝', 'distance': 1600,
        'cond': '良', 'class': '3勝'}


@pytest.fixture(scope='module')
def result():
    entries = rivals.build_field(RACE, size=16, seed=335)
    return engine.simulate(RACE, entries, seed=335)


def embedded_json(html):
    """ビューアのHTMLから、埋め込まれた結果JSONを取り出す。"""
    m = re.search(r'<script id="race-data" type="application/json">(.*?)</script>', html, re.S)
    assert m, '結果JSONの埋め込み先が見つからない'
    return json.loads(m.group(1).replace('<\\/', '</'))


def test_result_round_trips_through_the_template(result):
    html = make_viewer.render(result, fragment=True)
    assert embedded_json(html) == result


def test_placeholder_demo_data_is_replaced(result):
    html = make_viewer.render(result, fragment=True)
    assert 'サンプルホース' not in html
    assert result['horses'][0]['name'] in html


def test_title_becomes_the_race_name(result):
    html = make_viewer.render(result, fragment=True)
    assert '<title>銀嶺ステークス</title>' in html


def test_fragment_has_no_document_wrapper(result):
    """Artifactとして公開するときは <html> や <head> を含んではいけない。"""
    html = make_viewer.render(result, fragment=True)
    assert '<!doctype' not in html.lower()
    assert '<html' not in html.lower()
    assert '<body' not in html.lower()


def test_document_wraps_the_fragment(result):
    html = make_viewer.render(result, fragment=False)
    assert html.lstrip().lower().startswith('<!doctype html>')
    assert '<meta charset="utf-8">' in html
    assert embedded_json(html) == result


def test_script_tag_inside_json_is_escaped():
    """馬名に </script> が紛れてもHTMLが壊れないこと。"""
    hostile = {
        'race': dict(RACE),
        'seed': 1,
        'pace': 0.0,
        'base_time': 94.0,
        'horses': [{
            'no': 1, 'name': '</script><script>alert(1)</script>', 'style': '逃げ',
            'is_player': False, 'finish': 1, 'time': 94.0, 'margin': 0.0, 'last3f': 34.5,
            'splits': [11.75] * 8, 'passing': [1, 1, 1, 1], 'trouble': None,
        }],
    }
    html = make_viewer.render(hostile, fragment=True)
    body = re.search(r'<script id="race-data" type="application/json">(.*?)</script>', html, re.S)

    # ⭕ script要素の中身は `</script` でしか終わらない。中に現れる `<script>` は
    #    ただの文字であって新しい要素を開かないので、守るべき性質は
    #    「データの途中でブロックが閉じられないこと」だけ。
    assert '</script' not in body.group(1)
    assert embedded_json(html)['horses'][0]['name'] == hostile['horses'][0]['name']


def test_viewer_is_self_contained(result):
    """外部スクリプトを読み込まないこと（Botが吐いたHTMLがそのまま開ける）。"""
    html = make_viewer.render(result, fragment=True)
    assert 'src="http' not in html
    # 読み込む外部リソースはGoogle Fontsのスタイルシートだけ
    hrefs = re.findall(r'href="(https?://[^"]+)"', html)
    assert all(h.startswith('https://fonts.googleapis.com/') for h in hrefs), hrefs


def test_splits_are_enough_to_place_every_horse(result):
    """ビューアが位置を補間できる形になっていること。"""
    for h in result['horses']:
        assert len(h['splits']) == 8
        assert sum(h['splits']) == pytest.approx(h['time'], abs=0.02)
        assert min(h['splits']) > 0


def test_write_and_size(tmp_path, result):
    out = tmp_path / 'race.html'
    out.write_text(make_viewer.render(result), encoding='utf-8')
    # 1レースぶんで数十KB。Discordに添付してもEC2に置いても困らない大きさ。
    assert 10_000 < out.stat().st_size < 60_000
