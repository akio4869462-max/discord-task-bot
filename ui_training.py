"""自宅ダンベルトレーニングまわりのView/Modal・定期通知・スラッシュコマンド群"""

import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ui import View

import google_health_logic
import steps_logic
import training_logic
from ui_common import process_session, process_walking
from bot_state import tree
from ui_common import parse_float, parse_positive_int


def parse_steps(text):
    """歩数の入力文字列を整数に変換します。カンマ区切り（8,200）や全角数字も受け付けます。"""
    return parse_positive_int(str(text).replace(',', '').replace('，', ''))


async def record_steps(interaction, steps):
    """歩数を記録し、調教に新しく数えられる分があれば馬に反映して返信します。

    モーダルとスラッシュコマンドの両方から呼び、返信の組み立てを一本化している。
    """
    msg, credit = steps_logic.log_steps(steps)
    detail, public_msg = process_walking(credit)
    await interaction.response.send_message(msg + detail, ephemeral=True)
    if public_msg:
        await interaction.channel.send(f"{interaction.user.mention} {public_msg}")


async def import_google_health_steps(day, is_today):
    """Google Health から day の歩数を取り込み、馬の調教にも反映します。

    ⭕ 通信は別スレッドで行う（直接呼ぶとBot全体が固まる）。

    Args:
        day (date): 取り込む日。
        is_today (bool): 今日の歩数か。昨日ぶんを翌朝に取り込むときは False
            （連続記録を今日の記録として伸ばさないため）。

    Returns:
        dict/None: {'steps', 'credit', 'message', 'detail', 'public'}。
                   その日のデータがまだ Google Health に無ければ None。

    Raises:
        google_health_logic.GoogleHealthError: 認証切れ・通信失敗など。
    """
    result = await asyncio.to_thread(google_health_logic.sync_day, day)
    if result is None:
        return None
    detail, public = process_walking(result['credit'], today=day, update_streak=is_today)
    return {**result, 'detail': detail, 'public': public}


async def post_google_health_steps(channel, day, is_today):
    """定期配信用。新しく数える歩数があったときだけ、取り込んだことをチャンネルへ知らせます。"""
    result = await import_google_health_steps(day, is_today)
    if result is None or result['credit'] <= 0:
        return

    label = '今日' if is_today else '昨日'
    await channel.send(f"👟 Google Health から{label}の歩数 {result['steps']:,}歩 を取り込みました。{result['detail']}")
    if result['public']:
        await channel.send(result['public'])


class TrainingMenuView(View):
    """「トレーニング」サブメニュー：今日のメニュー・記録・体組成の記録/履歴をまとめたView

    他の全機能がボタンから辿れるのに対し、トレーニングだけ/trainingスラッシュコマンドの
    みだった対応漏れを埋める。ロジック側の関数はスラッシュコマンド版と共通利用する。
    """
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="💪 今日のメニュー", style=discord.ButtonStyle.success, row=0)
    async def menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        image_paths = training_logic.get_today_menu_image_paths()
        # ⭕ files=None を明示的に渡すとdiscord.py側で例外になる（休養日など画像が無い日に発生）。
        #    空リストなら「添付なし」として正しく扱われる。
        files = [discord.File(p) for p in image_paths]
        await interaction.response.send_message(training_logic.get_today_menu(), files=files, ephemeral=True)

    @discord.ui.button(label="✅ 完了を記録", style=discord.ButtonStyle.primary, row=0)
    async def log_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg, streak = training_logic.log_session()
        # ⭕ 記録できたときだけ調教に反映する。休養日や記録済みの日は streak が None。
        if streak is not None:
            detail, _ = process_session('training')
            msg += detail
        await interaction.response.send_message(msg, ephemeral=True)
        if streak in training_logic.TRAINING_STREAK_MILESTONES:
            await interaction.channel.send(f"{interaction.user.mention} 🔥 筋トレ{streak}日連続達成！")

    @discord.ui.button(label="📏 体組成を記録", style=discord.ButtonStyle.secondary, row=1)
    async def measure_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TrainingMeasureModal())

    @discord.ui.button(label="📈 体組成の履歴", style=discord.ButtonStyle.secondary, row=1)
    async def history_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(training_logic.get_measurement_history(), ephemeral=True)

    @discord.ui.button(label="👟 歩数を記録", style=discord.ButtonStyle.secondary, row=1)
    async def steps_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StepsModal())


class StepsModal(discord.ui.Modal, title='👟 今日の歩数'):
    """今日の合計歩数の入力モーダル（/training steps のボタン版）"""
    steps_input = discord.ui.TextInput(
        label='今日の合計歩数', placeholder='例: 8200（途中で何度書き直してもOK）', required=True, max_length=8)

    async def on_submit(self, interaction: discord.Interaction):
        steps = parse_steps(self.steps_input.value)
        if steps is None:
            await interaction.response.send_message("歩数は数字で入力してください！", ephemeral=True)
            return
        await record_steps(interaction, steps)


class TrainingMeasureModal(discord.ui.Modal, title='📏 体組成の記録'):
    """体重・お腹周りの入力モーダル（/training measureのボタン版）"""
    weight_input = discord.ui.TextInput(label='体重(kg)', placeholder='例: 65.5', required=True, max_length=6)
    waist_input = discord.ui.TextInput(label='お腹周り(cm)', placeholder='例: 82.0', required=True, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        weight_kg = parse_float(self.weight_input.value)
        waist_cm = parse_float(self.waist_input.value)
        if weight_kg is None or waist_cm is None:
            await interaction.response.send_message("体重・お腹周りは数字で入力してください！", ephemeral=True)
            return

        msg = training_logic.log_measurement(weight_kg, waist_cm)
        await interaction.response.send_message(msg, ephemeral=True)


class DailyLogView(View):
    """定期通知にそのまま添えて、ワンタップで実施を記録するためのView

    通知が届いた場所で押せることが要点。メニューを辿らせると記録が続かないため、
    timeout=None で常設し、いつ押しても記録できるようにしている。
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 今日の筋トレ完了", style=discord.ButtonStyle.success, custom_id="log_training")
    async def training_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg, streak = training_logic.log_session()
        if streak is not None:
            detail, _ = process_session('training')
            msg += detail
        await interaction.response.send_message(msg, ephemeral=True)
        if streak in training_logic.TRAINING_STREAK_MILESTONES:
            await interaction.channel.send(
                f"{interaction.user.mention} 🔥 筋トレ{streak}日連続達成！"
            )


async def send_training_notification(channel):
    """今日のトレーニングメニューを、記録ボタン付きで送信します。

    定期配信とデバッグコマンドの両方から呼ぶ。片方だけ直して内容がズレるのを
    防ぐため、「何を送るか」はここに一本化する。
    """
    image_paths = training_logic.get_today_menu_image_paths()
    # 休養日は記録するものが無いのでボタンを出さない
    log_view = None if training_logic.is_rest_day() else DailyLogView()
    # ⭕ files=None を明示的に渡すとdiscord.py側で例外になる（休養日など画像が無い日に発生）。
    #    空リストなら「添付なし」として正しく扱われる。
    files = [discord.File(p) for p in image_paths]
    await channel.send(training_logic.get_today_menu(), files=files, view=log_view)


# ====================================================
# 💪 トレーニング記録コマンド群（/training menu, log, measure, steps, sync_steps, history）
# ====================================================
training_group = app_commands.Group(name="training", description="自宅ダンベルトレーニングの記録")


@training_group.command(name="menu", description="今日のトレーニングメニューを表示します")
async def training_menu_command(interaction: discord.Interaction):
    image_paths = training_logic.get_today_menu_image_paths()
    if image_paths:
        files = [discord.File(p) for p in image_paths]
        await interaction.response.send_message(training_logic.get_today_menu(), files=files, ephemeral=True)
    else:
        await interaction.response.send_message(training_logic.get_today_menu(), ephemeral=True)


@training_group.command(name="log", description="今日のトレーニングを完了として記録します")
@app_commands.describe(note="メモ（任意）")
async def training_log_command(interaction: discord.Interaction, note: str = None):
    msg, streak = training_logic.log_session(note)
    if streak is not None:
        detail, _ = process_session('training')
        msg += detail
    await interaction.response.send_message(msg, ephemeral=True)

    # 連続記録の節目だけチャンネルにも告知する
    if streak in training_logic.TRAINING_STREAK_MILESTONES:
        await interaction.channel.send(f"{interaction.user.mention} 🔥 トレーニング{streak}日連続達成！素晴らしいです！")


@training_group.command(name="measure", description="体重・お腹周りを記録します")
@app_commands.describe(weight_kg="体重(kg)", waist_cm="お腹周り(cm)")
async def training_measure_command(interaction: discord.Interaction, weight_kg: float, waist_cm: float):
    await interaction.response.send_message(training_logic.log_measurement(weight_kg, waist_cm), ephemeral=True)


@training_group.command(name="steps", description="今日の合計歩数を記録します（何度書き直してもOK）")
@app_commands.describe(steps="今日の合計歩数")
async def training_steps_command(interaction: discord.Interaction, steps: int):
    await record_steps(interaction, steps)


@training_group.command(name="sync_steps", description="Google Healthから今日の歩数を今すぐ取り込みます")
async def training_sync_steps_command(interaction: discord.Interaction):
    if not google_health_logic.is_configured():
        await interaction.response.send_message(
            "Google Healthとの連携は未設定です。`tools/google_health_auth.py` で認証すると使えます。"
            "それまでは `/training steps` で手入力できます。", ephemeral=True)
        return

    # ⭕ Googleとの通信があり3秒以内に応答できないので、先に応答を保留する
    await interaction.response.defer(ephemeral=True)
    try:
        result = await import_google_health_steps(datetime.now(steps_logic.JST).date(), True)
    except google_health_logic.GoogleHealthError as e:
        await interaction.followup.send(f"❌ 取り込めませんでした。{e}", ephemeral=True)
        return

    if result is None:
        await interaction.followup.send(
            "Google Healthに、今日の歩数がまだありません。端末の同期を待って、もう一度試してください。",
            ephemeral=True)
    elif result['message'].startswith('❌'):
        await interaction.followup.send(result['message'], ephemeral=True)
    elif result['credit'] <= 0:
        await interaction.followup.send(
            f"👟 今日は {result['steps']:,}歩 です。調教に新しく数える歩数はありません（取り込み済み）。",
            ephemeral=True)
    else:
        await interaction.followup.send(
            f"👟 今日の歩数 {result['steps']:,}歩 を取り込みました。{result['detail']}", ephemeral=True)
        if result['public']:
            await interaction.channel.send(f"{interaction.user.mention} {result['public']}")


@training_group.command(name="history", description="体組成の記録一覧を表示します")
async def training_history_command(interaction: discord.Interaction):
    await interaction.response.send_message(training_logic.get_measurement_history(), ephemeral=True)


tree.add_command(training_group)
