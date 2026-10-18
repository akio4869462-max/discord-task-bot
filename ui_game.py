"""新作ゲーム紹介のスラッシュコマンド（/games）と、気になる作品の選択メニュー"""

from datetime import datetime

import discord
from discord import app_commands
from discord.ui import Select, View

import game_logic
from bot_state import tree

MAX_SELECT_OPTIONS = 25      # Discordのセレクトメニューの選択肢の上限


class GameWatchSelect(Select):
    """一覧に出した作品から、気になるものを選ぶメニュー（選び直せば登録を外せる）"""

    def __init__(self, shown, watched, today):
        self.shown = shown
        options = [
            discord.SelectOption(
                label=r['title'][:100],
                description=f"{game_logic._when_text(r, today)} / {' / '.join(r['platforms'])}"[:100],
                value=str(i),
                default=r['title'].casefold() in watched,
            )
            for i, r in enumerate(shown)
        ]
        super().__init__(
            placeholder="⭐ 気になる作品を選ぶ（発売前に通知します）",
            min_values=0, max_values=len(options), options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen = [self.shown[int(v)]['title'] for v in self.values]
        game_logic.update_watch([r['title'] for r in self.shown], chosen)
        if chosen:
            msg = (f"⭐ この一覧のうち **{len(chosen)}件** を気になる作品にしました。\n"
                   "発売の1週間前・前日・当日と、予約開始日の朝8時に知らせます。")
        else:
            msg = "この一覧の作品は、気になる作品から外しました。"
        await interaction.response.send_message(msg, ephemeral=True)


class GameWatchView(View):
    def __init__(self, shown, watched, today):
        super().__init__(timeout=180)
        self.add_item(GameWatchSelect(shown, watched, today))


@tree.command(name="games", description="新作ゲーム（PC / Switch / Switch 2）の発売予定を紹介します")
@app_commands.describe(
    platform="機種で絞り込み（省略すると全機種）",
    period="期間（省略すると、これから発売される全作品）",
    watching="気になる作品だけを、予約の状況つきで表示する",
)
@app_commands.choices(
    platform=[app_commands.Choice(name=p, value=p) for p in game_logic.PLATFORMS],
    period=[
        app_commands.Choice(name="今後2週間", value=14),
        app_commands.Choice(name="今後1か月", value=30),
        app_commands.Choice(name="今後3か月", value=90),
    ],
)
async def games_command(
    interaction: discord.Interaction,
    platform: app_commands.Choice[str] = None,
    period: app_commands.Choice[int] = None,
    watching: bool = False,
):
    today = datetime.now(game_logic.JST).date()
    releases = game_logic.load_releases()
    watched = game_logic.watched_keys()
    platform_value = platform.value if platform else None
    days = period.value if period else None

    msg = game_logic.build_games_message(
        releases, today,
        platform=platform_value, days=days,
        period_label=period.name if period else '',
        watched=watched, only_watched=watching,
    )

    dated, undated = game_logic.filter_upcoming(
        releases, today, platform=platform_value, days=days,
        only_titles=watched if watching else None)
    shown = (dated + undated)[:MAX_SELECT_OPTIONS]

    view = GameWatchView(shown, watched, today) if shown else None
    if view is None:
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, view=view, ephemeral=True)
