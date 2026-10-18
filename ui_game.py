"""新作ゲーム紹介のスラッシュコマンド（/games）"""

from datetime import datetime

import discord
from discord import app_commands

import game_logic
from bot_state import tree


@tree.command(name="games", description="新作ゲーム（PC / Switch / Switch 2）の発売予定を紹介します")
@app_commands.describe(
    platform="機種で絞り込み（省略すると全機種）",
    period="期間（省略すると、これから発売される全作品）",
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
):
    today = datetime.now(game_logic.JST).date()
    msg = game_logic.build_games_message(
        game_logic.load_releases(),
        today,
        platform=platform.value if platform else None,
        days=period.value if period else None,
        period_label=period.name if period else '',
    )
    await interaction.response.send_message(msg, ephemeral=True)
