import asyncio
import os
from datetime import date

import pytest

os.environ.setdefault('DISCORD_TOKEN', 'dummy')

import game_logic
import ui_game

TODAY = date(2026, 10, 19)


@pytest.fixture(autouse=True)
def isolated_watch_file(tmp_path, monkeypatch):
    """実データ（data/）を巻き込まないよう、気になる作品の保存先だけを差し替える。
    発売予定は、同梱の実際の seed をそのまま使う（Discordの制限に収まるかを見るため）。"""
    monkeypatch.setattr(game_logic, 'USER_FILE', str(tmp_path / 'user.json'))
    monkeypatch.setattr(game_logic, 'WATCH_FILE', str(tmp_path / 'watch.json'))


class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, **kwargs):
        self.sent.append(content)


class FakeInteraction:
    def __init__(self):
        self.response = FakeResponse()


def shown_from_seed():
    dated, undated = game_logic.filter_upcoming(game_logic.load_releases(), TODAY)
    return (dated + undated)[:ui_game.MAX_SELECT_OPTIONS]


def test_select_options_fit_discords_limits_with_the_real_seed():
    """⭕ タイトルや説明が長すぎる・選択肢が多すぎると、Discord側で送信に失敗してコマンドが無応答になる。"""
    async def run():
        select = ui_game.GameWatchSelect(shown_from_seed(), set(), TODAY)
        assert 1 <= len(select.options) <= 25
        assert select.max_values == len(select.options)
        assert select.min_values == 0
        for option in select.options:
            assert 1 <= len(option.label) <= 100
            assert len(option.description) <= 100
            assert len(option.value) <= 100
    asyncio.run(run())


def test_already_watched_titles_are_preselected():
    async def run():
        shown = shown_from_seed()
        select = ui_game.GameWatchSelect(shown, {shown[1]['title'].casefold()}, TODAY)
        assert [o.default for o in select.options].count(True) == 1
        assert select.options[1].default is True
    asyncio.run(run())


def test_choosing_in_the_menu_registers_those_titles():
    async def run():
        shown = shown_from_seed()
        select = ui_game.GameWatchSelect(shown, set(), TODAY)
        interaction = FakeInteraction()
        select._values = ['0', '2']          # ユーザーが1つ目と3つ目を選んだ状態
        await select.callback(interaction)

        assert set(game_logic.load_watch()) == {shown[0]['title'], shown[2]['title']}
        assert '2件' in interaction.response.sent[0]
    asyncio.run(run())


def test_choosing_nothing_clears_the_registration_of_the_shown_titles():
    async def run():
        shown = shown_from_seed()
        game_logic.update_watch([r['title'] for r in shown], [shown[0]['title']])

        select = ui_game.GameWatchSelect(shown, {shown[0]['title'].casefold()}, TODAY)
        select._values = []
        await select.callback(FakeInteraction())

        assert game_logic.load_watch() == []
    asyncio.run(run())
