"""自宅ダンベルトレーニングまわりのView/Modal・定期通知・スラッシュコマンド群"""

import discord
from discord import app_commands
from discord.ui import View

import training_logic
from ui_common import process_session
from bot_state import tree
from ui_common import parse_float


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
        files = [discord.File(p) for p in image_paths] if image_paths else None
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
    files = [discord.File(p) for p in image_paths] if image_paths else None
    await channel.send(training_logic.get_today_menu(), files=files, view=log_view)


# ====================================================
# 💪 トレーニング記録コマンド群（/training menu, log, measure, history）
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


@training_group.command(name="history", description="体組成の記録一覧を表示します")
async def training_history_command(interaction: discord.Interaction):
    await interaction.response.send_message(training_logic.get_measurement_history(), ephemeral=True)


tree.add_command(training_group)
