"""C++タイピング訓練まわりのView/Modal・定期通知・スラッシュコマンド群"""

import discord
from discord import app_commands
from discord.ui import View, Select

import typing_logic
from bot_state import tree
from ui_common import parse_positive_int, parse_float, process_session


class TypingLogView(View):
    """夜のタイピング通知に添える、実施記録用のView"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 今日の練習完了", style=discord.ButtonStyle.success, custom_id="log_typing")
    async def practice_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg, streak = typing_logic.log_practice()
        # ⭕ 記録できたときだけ調教に反映する（記録済みの日は streak が None）。
        if streak is not None:
            detail, _ = process_session('typing')
            msg += detail
        await interaction.response.send_message(msg, ephemeral=True)
        if streak in typing_logic.PRACTICE_STREAK_MILESTONES:
            await interaction.channel.send(
                f"{interaction.user.mention} 🔥 タイピング{streak}日連続達成！"
            )

    @discord.ui.button(label="🎯 計測を記録", style=discord.ButtonStyle.secondary, custom_id="log_typing_measure")
    async def measure_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TypingMeasureModal())


class TypingMenuView(View):
    """「タイピング訓練」サブメニュー：日次メニュー・ドリル本文・計測記録をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="⌨️ 今日のメニュー", style=discord.ButtonStyle.success, row=0)
    async def menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(typing_logic.get_daily_menu(), ephemeral=True)

    @discord.ui.button(label="📄 ドリル本文", style=discord.ButtonStyle.primary, row=0)
    async def drill_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "表示するドリルを選んでください：", view=TypingDrillSelectView(), ephemeral=True
        )

    @discord.ui.button(label="🎯 計測を記録", style=discord.ButtonStyle.primary, row=0)
    async def log_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TypingMeasureModal())

    @discord.ui.button(label="📈 進捗", style=discord.ButtonStyle.secondary, row=1)
    async def progress_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(typing_logic.get_progress_summary(), ephemeral=True)

    @discord.ui.button(label="🖐️ 指の担当表", style=discord.ButtonStyle.secondary, row=1)
    async def keys_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(typing_logic.get_key_guide('jis'), ephemeral=True)

    @discord.ui.button(label="⏭️ 次のドリルへ", style=discord.ButtonStyle.secondary, row=1)
    async def advance_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(typing_logic.advance_drill(), ephemeral=True)


class TypingDrillSelectView(View):
    """表示するドリル（A〜E）をプルダウンで選ばせるView"""
    def __init__(self):
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label=f"Drill {did} — {d['name']}"[:100], value=did)
            for did, d in typing_logic.DRILLS.items()
        ]
        options.append(discord.SelectOption(label="Drill E — 英字の弱点補強（keybr）", value="E"))
        self.add_item(TypingDrillDropdown(options))


class TypingDrillDropdown(Select):
    def __init__(self, options):
        super().__init__(placeholder='ドリルを選択...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            typing_logic.get_drill_text(self.values[0]), ephemeral=True
        )


class TypingMeasureModal(discord.ui.Modal, title='🎯 タイピング計測の記録'):
    """monkeytypeの計測結果を入力するモーダル

    afkはmonkeytypeが「検出された時だけ」リザルトに表示するため、
    表示が無いケース（＝実質0%）でも記録できるよう任意入力にしています。
    """
    wpm_input = discord.ui.TextInput(label='net WPM', placeholder='例: 24', required=True, max_length=3)
    accuracy_input = discord.ui.TextInput(label='accuracy(%)', placeholder='例: 89', required=True, max_length=3)
    consistency_input = discord.ui.TextInput(label='consistency(%)', placeholder='例: 57', required=True, max_length=3)
    afk_input = discord.ui.TextInput(
        label='afk(%)',
        placeholder='リザルトに表示が無ければ空欄でOK（0%扱い）',
        required=False,
        max_length=5,
    )
    note_input = discord.ui.TextInput(label='メモ（任意）', placeholder='例: 30秒台で停止', required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        wpm = parse_positive_int(self.wpm_input.value)
        accuracy = parse_positive_int(self.accuracy_input.value)
        consistency = parse_positive_int(self.consistency_input.value)

        # 空欄はafk検出なし（0%）とみなす。値がある場合のみ数値として解釈する
        afk_raw = (self.afk_input.value or "").strip()
        afk = 0.0 if not afk_raw else parse_float(afk_raw)  # afkは2.5のような小数を取りうる

        if None in (wpm, accuracy, consistency, afk):
            await interaction.response.send_message(
                "各項目は数字で入力してください（afkのみ小数可・空欄可）。", ephemeral=True
            )
            return

        msg = typing_logic.log_measurement(wpm, accuracy, consistency, afk, self.note_input.value)
        await interaction.response.send_message(msg, ephemeral=True)


async def send_typing_notification(channel):
    """今日のタイピングメニューとドリル本文を、記録ボタン付きで送信します。

    定期配信とデバッグコマンドの両方から呼ぶ。片方だけ直して内容がズレるのを
    防ぐため、「何を送るか」はここに一本化する。
    """
    await channel.send(typing_logic.get_daily_menu())
    current_drill = typing_logic.load_typing_data().get('current_drill', 'A')
    # ドリル本文と一緒に記録ボタンを出し、練習後そのまま押せるようにする
    await channel.send(typing_logic.get_drill_text(current_drill), view=TypingLogView())


# ====================================================
# ⌨️ タイピング訓練コマンド群（/typing menu, drill, progress, keys）
# ====================================================
typing_group = app_commands.Group(name="typing", description="C++タイピング訓練")


@typing_group.command(name="menu", description="今日のタイピング訓練メニューを表示します")
async def typing_menu_command(interaction: discord.Interaction):
    await interaction.response.send_message(typing_logic.get_daily_menu(), ephemeral=True)


@typing_group.command(name="drill", description="ドリル本文を表示します（monkeytypeに貼り付け用）")
@app_commands.describe(drill="表示するドリル")
@app_commands.choices(drill=[
    app_commands.Choice(name="A — 右小指の単独ドリル", value="A"),
    app_commands.Choice(name="B — シフト側の数字", value="B"),
    app_commands.Choice(name="C — C++二文字連", value="C"),
    app_commands.Choice(name="D — 実トークン", value="D"),
    app_commands.Choice(name="E — 英字の弱点補強（keybr）", value="E"),
])
async def typing_drill_command(interaction: discord.Interaction, drill: app_commands.Choice[str]):
    await interaction.response.send_message(typing_logic.get_drill_text(drill.value), ephemeral=True)


@typing_group.command(name="progress", description="計測履歴と目標ラインを表示します")
async def typing_progress_command(interaction: discord.Interaction):
    await interaction.response.send_message(typing_logic.get_progress_summary(), ephemeral=True)


@typing_group.command(name="keys", description="記号の指の担当表を表示します")
@app_commands.describe(layout="キーボード配列")
@app_commands.choices(layout=[
    app_commands.Choice(name="JIS配列（日本語配列）", value="jis"),
    app_commands.Choice(name="US配列（英語配列）", value="us"),
])
async def typing_keys_command(interaction: discord.Interaction, layout: app_commands.Choice[str] = None):
    layout_value = layout.value if layout else "jis"
    await interaction.response.send_message(typing_logic.get_key_guide(layout_value), ephemeral=True)


tree.add_command(typing_group)
