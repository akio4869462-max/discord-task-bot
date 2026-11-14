"""学習タイマー（25分）まわりのView/Modalとスラッシュコマンド（/study timer, stats）

何の勉強にも使える25分のタイマー。分野は選ばず、内容は自由な一言（任意）だけ。
25分たつと自動で記録し、馬の育成（賢さ）にも時間ぶん反映する。
"""

import asyncio
from datetime import datetime, timedelta

import discord
from discord import app_commands

import horse_logic
import study_logic
from bot_state import tree, FOCUS_TIMER_SECONDS, JST, active_focus_timers
from ui_common import build_growth_message
from ui_horse import FocusTimerView


async def run_study_timer(channel, user_id, user_mention, topic, seconds=FOCUS_TIMER_SECONDS):
    """学習タイマー本体。指定秒数がたったら、学習として自動で記録して知らせます。

    途中でキャンセルされた場合（asyncio.CancelledError）は記録せず、静かに終了します。
    """
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    finally:
        # ⭕ 自分のエントリだけを外す。キャンセル直後に始めた次のタイマーを巻き込まないため
        if active_focus_timers.get(user_id) is asyncio.current_task():
            active_focus_timers.pop(user_id, None)

    minutes = round(seconds / 60)
    log_msg = study_logic.log_session(minutes, topic)

    detail = ''
    if not log_msg.startswith('❌'):
        try:
            detail, _ = build_growth_message(horse_logic.add_growth('reading', minutes))
        except Exception as error:      # 記録は済んでいる。育成側の失敗で、知らせまで落とさない
            print(f"❌ [学習タイマー] 育成への反映に失敗しました: {type(error).__name__}: {error}")

    await channel.send(
        f"{user_mention} {minutes}分経過しました！お疲れ様でした。☕ 5分ほど休憩しましょう。\n"
        f"{log_msg}{detail}")


async def begin_study_timer(interaction: discord.Interaction, topic=''):
    """学習タイマーを始めます。"""
    user_id = interaction.user.id
    if user_id in active_focus_timers:
        await interaction.response.send_message("既にタイマーが動いています。", ephemeral=True)
        return

    topic = study_logic.normalize_topic(topic)
    minutes = round(FOCUS_TIMER_SECONDS / 60)
    ends = int((datetime.now(JST) + timedelta(seconds=FOCUS_TIMER_SECONDS)).timestamp())
    what = f"（{topic}）" if topic else ''
    await interaction.response.send_message(
        f"⏱️ {minutes}分の学習タイマーを開始しました{what}。\n"
        f"終了予定: <t:{ends}:t>（<t:{ends}:R>）。終わったら自動で記録します。",
        view=FocusTimerView(user_id), ephemeral=True)

    # ⭕ 開発の集中タイマーと同じ辞書で管理する。ふたつを同時には動かさない
    active_focus_timers[user_id] = asyncio.create_task(
        run_study_timer(interaction.channel, user_id, interaction.user.mention, topic))


class StudyTopicModal(discord.ui.Modal, title='⏱️ 学習タイマー'):
    """何を勉強するかを、自由な一言で聞くモーダル（空欄でも始められる）"""
    topic_input = discord.ui.TextInput(
        label='何を勉強しますか？（空欄でもOK）',
        placeholder='例: 設計の本 / AWS / 応用情報',
        required=False,
        max_length=study_logic.TOPIC_MAX,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await begin_study_timer(interaction, self.topic_input.value)


# ====================================================
# 📚 /study コマンド群
# ====================================================
study_group = app_commands.Group(name="study", description="25分タイマーで学習を記録します")


@study_group.command(name="timer", description="25分の学習タイマーを始めます。終わったら自動で記録します")
@app_commands.describe(topic="何を勉強するか（空欄でもOK）")
async def study_timer_command(interaction: discord.Interaction, topic: str = ''):
    await begin_study_timer(interaction, topic)


@study_group.command(name="stats", description="今日・今週・累計の学習時間と、内容別の合計を表示します")
async def study_stats_command(interaction: discord.Interaction):
    await interaction.response.send_message(study_logic.get_stats_summary(), ephemeral=True)


tree.add_command(study_group)
