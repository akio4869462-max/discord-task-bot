"""応用情報 過去問演習まわりのView/Modalとスラッシュコマンド（/exam log, stats）"""

import discord
from discord import app_commands
from discord.ui import View, Select

import exam_logic
from bot_state import tree
from ui_common import parse_positive_int, process_exam_completion


class ExamMenuView(View):
    """「資格学習」サブメニュー：過去問演習の記録・成績確認をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="📝 演習を記録", style=discord.ButtonStyle.primary, row=0)
    async def log_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "演習した分野を選んでください：", view=ExamFieldSelectView(), ephemeral=True
        )

    @discord.ui.button(label="📊 演習成績", style=discord.ButtonStyle.secondary, row=0)
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(exam_logic.get_stats_summary(), ephemeral=True)


class ExamFieldSelectView(View):
    """演習記録の1ステップ目：分野をプルダウンで選ばせるView

    分野は3つ。かつて6つあった頃の名残でセレクトメニューだが、選ぶ手順は同じなので残す。
    """
    def __init__(self):
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label=display_name[:100], value=field_id)
            for field_id, display_name in exam_logic.EXAM_FIELDS.items()
        ]
        self.add_item(ExamFieldDropdown(options))


class ExamFieldDropdown(Select):
    def __init__(self, options):
        super().__init__(placeholder='演習した分野を選択...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # 選んだ分野を引き継いで、問題数・正解数の入力モーダルを開く
        await interaction.response.send_modal(ExamLogModal(self.values[0]))


class ExamLogModal(discord.ui.Modal, title='📝 過去問演習の記録'):
    """分野選択後にポップアップする、問題数・正解数の入力モーダル"""
    total_input = discord.ui.TextInput(
        label='解いた問題数',
        placeholder='例: 20 （半角数字）',
        required=True,
        max_length=4,
    )
    correct_input = discord.ui.TextInput(
        label='正解した問題数',
        placeholder='例: 13 （半角数字）',
        required=True,
        max_length=4,
    )

    def __init__(self, field):
        super().__init__()
        self.field = field

    async def on_submit(self, interaction: discord.Interaction):
        total = parse_positive_int(self.total_input.value)
        correct = parse_positive_int(self.correct_input.value)
        if total is None or correct is None:
            await interaction.response.send_message("問題数・正解数は数字で入力してください！", ephemeral=True)
            return

        msg = exam_logic.log_session(self.field, total, correct)
        if not msg.startswith("❌"):
            exp_msg, public_msg = process_exam_completion(total)
            msg += exp_msg
        else:
            public_msg = None

        await interaction.response.send_message(msg, ephemeral=True)
        if public_msg:
            await interaction.channel.send(f"{interaction.user.mention} {public_msg}")


# ====================================================
# 📝 応用情報 演習記録コマンド群（/exam log, stats）
# ====================================================
exam_group = app_commands.Group(name="exam", description="応用情報技術者試験の過去問演習の記録")

# 分野の選択肢はexam_logic側の定義から生成し、二重管理を避ける
EXAM_FIELD_CHOICES = [
    app_commands.Choice(name=display_name, value=field_id)
    for field_id, display_name in exam_logic.EXAM_FIELDS.items()
]


@exam_group.command(name="log", description="過去問演習の結果を記録します")
@app_commands.describe(field="演習した分野", total="解いた問題数", correct="正解した問題数")
@app_commands.choices(field=EXAM_FIELD_CHOICES)
async def exam_log_command(
    interaction: discord.Interaction,
    field: app_commands.Choice[str],
    total: int,
    correct: int,
):
    msg = exam_logic.log_session(field.value, total, correct)
    if not msg.startswith("❌"):
        exp_msg, public_msg = process_exam_completion(total)
        msg += exp_msg
    else:
        public_msg = None

    await interaction.response.send_message(msg, ephemeral=True)
    if public_msg:
        await interaction.channel.send(f"{interaction.user.mention} {public_msg}")


@exam_group.command(name="stats", description="分野別の演習成績・弱点分野を表示します")
async def exam_stats_command(interaction: discord.Interaction):
    await interaction.response.send_message(exam_logic.get_stats_summary(), ephemeral=True)


tree.add_command(exam_group)
