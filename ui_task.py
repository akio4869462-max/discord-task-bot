"""タスク管理まわりのView/Modalとスラッシュコマンド（/add, /list, /done）"""

import discord
from discord import app_commands
from discord.ui import Button, View, Select

import task_logic
from bot_state import tree
from ui_common import try_sync_to_calendar, process_task_completion


class TaskCategorySelectView(View):
    """タスク追加の1ステップ目：カテゴリをボタンで選ばせるView（typoによる誤登録を防ぐ）"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="💻 開発", style=discord.ButtonStyle.primary)
    async def programming_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TaskAddModal("programming"))

    @discord.ui.button(label="📚 インプット", style=discord.ButtonStyle.primary)
    async def reading_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TaskAddModal("reading"))


class TaskAddModal(discord.ui.Modal, title='📝 新しいタスクの追加'):
    """カテゴリ選択後にポップアップする、タスク内容・期限入力用のモーダルフォーム"""
    task_input = discord.ui.TextInput(
        label='タスクの内容',
        placeholder='例: 職務経歴書の推敲、ボットのUI拡張など',
        required=True
    )
    deadline_input = discord.ui.TextInput(
        label='期限・締切（月/日）',
        placeholder='例: 6/15, 2026-06-15 など（空欄なら期限なし）',
        required=False,
        max_length=15
    )

    def __init__(self, category):
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        # ⭕ 優先度はここでは確定させず、次のステップ（ボタン選択）に引き継ぐ
        view = TaskPrioritySelectView(self.task_input.value, self.category, self.deadline_input.value.strip())
        await interaction.response.send_message("優先度を選んでね：", view=view, ephemeral=True)


class TaskPrioritySelectView(View):
    """タスク追加の最終ステップ：優先度をボタンで選ばせ、登録を確定するView"""
    def __init__(self, task_text, category, deadline_str):
        super().__init__(timeout=60)
        self.task_text = task_text
        self.category = category
        self.deadline_str = deadline_str

    async def _finish(self, interaction: discord.Interaction, priority):
        result_msg = task_logic.add_task(self.task_text, self.category, self.deadline_str, priority)
        # ⭕ 先に登録完了を返信してから、Googleカレンダー連携（外部通信）を後追いで行う。
        # interaction.response.send_message()は受信から約3秒以内に呼ぶ必要があるため、
        # 応答時間が読めない外部API呼び出しを先に待ってしまうと失敗する可能性がある。
        await interaction.response.send_message(result_msg, ephemeral=True)

        calendar_msg = await try_sync_to_calendar(self.task_text, self.category, self.deadline_str)
        if calendar_msg:
            await interaction.followup.send(calendar_msg.strip(), ephemeral=True)

    @discord.ui.button(label="★★★ 高", style=discord.ButtonStyle.danger)
    async def high_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, 3)

    @discord.ui.button(label="★★☆ 中", style=discord.ButtonStyle.primary)
    async def mid_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, 2)

    @discord.ui.button(label="★☆☆ 低", style=discord.ButtonStyle.secondary)
    async def low_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, 1)


class TaskSelectCombinedView(View):
    """タスク一覧テキストの直下に、タスク追加ボタンと完了プルダウンを同時に出すView"""
    def __init__(self):
        super().__init__(timeout=60)

        button = Button(label="新しいタスクを追加", style=discord.ButtonStyle.primary, row=0)
        button.callback = self.add_task_callback
        self.add_item(button)

        # list_tasks()で表示順を確定させ、IDが未付与の古いタスクにIDを補完・保存してから読み込む
        task_logic.list_tasks()
        todo_list = task_logic.load_data()
        options = []
        for i, item in enumerate(todo_list):
            if i >= 25:
                break  # Discordの上限

            task_text, stars = task_logic.get_display_fields(item)
            label_text = f"{i+1}. [{stars}] {task_text}"
            if len(label_text) > 90:
                label_text = label_text[:90] + "..."

            # 一意なIDを渡すことで、選択後にタスクが増減・並び替えされても正しいタスクを特定できる
            options.append(discord.SelectOption(label=label_text, value=item['id']))

        if options:
            self.add_item(TaskDropdownCombined(options))  # row=1 にプルダウンを配置

    async def add_task_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("カテゴリを選んでね：", view=TaskCategorySelectView(), ephemeral=True)


class TaskDropdownCombined(Select):
    def __init__(self, options):
        super().__init__(placeholder='完了したタスクを選んでプルダウンを閉じる...', min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        result_msg, category = task_logic.complete_task(selected_value)
        rpg_msg, public_msg = process_task_completion(category)
        await interaction.response.send_message(f"{result_msg}{rpg_msg}", ephemeral=True)
        if public_msg:
            await interaction.channel.send(f"{interaction.user.mention} {public_msg}")


async def task_autocomplete(interaction: discord.Interaction, current: str):
    """/done コマンドの引数を、現在登録中のタスク名から絞り込み候補として提示する"""
    choices = []
    for item in task_logic.load_data():
        if not isinstance(item, dict):
            continue
        task_text, stars = task_logic.get_display_fields(item)
        label = f"[{stars}] {task_text}"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=item['id']))
    return choices[:25]


@tree.command(name="add", description="新しいタスクを追加します")
@app_commands.describe(
    task="タスクの内容",
    category="カテゴリ",
    deadline="期限（例: 6/15, 2026-06-15）省略可",
    priority="優先度（省略時は中）",
)
@app_commands.choices(
    category=[
        app_commands.Choice(name="💻 開発", value="programming"),
        app_commands.Choice(name="📚 インプット", value="reading"),
    ],
    priority=[
        app_commands.Choice(name="★★★ 高", value=3),
        app_commands.Choice(name="★★☆ 中", value=2),
        app_commands.Choice(name="★☆☆ 低", value=1),
    ],
)
async def add_command(
    interaction: discord.Interaction,
    task: str,
    category: app_commands.Choice[str],
    deadline: str = None,
    priority: app_commands.Choice[int] = None,
):
    category_value = category.value
    priority_value = priority.value if priority is not None else 2

    result_msg = task_logic.add_task(task, category_value, deadline, priority_value)
    await interaction.response.send_message(result_msg, ephemeral=True)

    calendar_msg = await try_sync_to_calendar(task, category_value, deadline)
    if calendar_msg:
        await interaction.followup.send(calendar_msg.strip(), ephemeral=True)


@tree.command(name="list", description="登録されているタスク一覧を表示します")
async def list_command(interaction: discord.Interaction):
    list_str = task_logic.list_tasks()
    if "現在、登録されたタスクはありません" in list_str:
        await interaction.response.send_message(list_str)
    else:
        view = TaskSelectCombinedView()
        await interaction.response.send_message(list_str, view=view)


@tree.command(name="done", description="タスクを完了させます")
@app_commands.describe(task="完了させるタスク")
@app_commands.autocomplete(task=task_autocomplete)
async def done_command(interaction: discord.Interaction, task: str):
    result_msg, category = task_logic.complete_task(task)
    rpg_msg, public_msg = process_task_completion(category)
    await interaction.response.send_message(f"{result_msg}{rpg_msg}", ephemeral=True)
    if public_msg:
        await interaction.channel.send(f"{interaction.user.mention} {public_msg}")
