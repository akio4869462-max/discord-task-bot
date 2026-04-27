import discord
import os
from dotenv import load_dotenv
import task_logic
import study_logic

from discord.ui import Button, View

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- ボタンを管理するクラス ---
class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None) # タイムアウトなし

    @discord.ui.button(label="タスク一覧", style=discord.ButtonStyle.primary)
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # task_logicから一覧を取得して返信
        response = task_logic.list_tasks()
        await interaction.response.send_message(response, ephemeral=True) # ephemeral=Trueは自分にだけ見える

    @discord.ui.button(label="用語クイズ", style=discord.ButtonStyle.success)
    async def kiso_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        response = study_logic.get_kiso_quiz()
        await interaction.response.send_message(response)

    @discord.ui.button(label="計算問題", style=discord.ButtonStyle.secondary)
    async def math_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        response = study_logic.get_math_quiz()
        await interaction.response.send_message(response)

    @discord.ui.button(label="タスク完了", style=discord.ButtonStyle.danger)
    async def complete_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        count = task_logic.get_task_count()
        if count == 0:
            await interaction.response.send_message("完了するタスクがありません。", ephemeral=True)
        else:
            view = TaskCompleteView(count)
            await interaction.response.send_message("完了するタスクの番号を押してください：", view=view, ephemeral=True)

# --- タスク完了選択用のビュー ---
class TaskCompleteView(View):
    def __init__(self, count):
        super().__init__(timeout=60)
        # タスクの数だけボタンを自動生成
        for i in range(count):
            # ボタンのラベルは「1」「2」...
            button = Button(label=f"{i+1}", style=discord.ButtonStyle.danger)
            # ボタンが押された時の処理を紐付け
            button.callback = self.create_callback(i)
            self.add_item(button)

    def create_callback(self, index):
        async def callback(interaction: discord.Interaction):
            # 実際の削除処理
            result_msg = task_logic.complete_task(str(index + 1))
            await interaction.response.send_message(result_msg, ephemeral=True)
            # メッセージ自体を更新してボタンを消す場合は以下（任意）
            # await interaction.message.edit(view=None)
        return callback

@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content

    # 【メニュー表示】
    if content == '!menu' or content == '！': # 全角の「！」でも反応するようにするとスマホで楽です
        view = MainMenuView()
        await message.channel.send("メニューを選んでください：", view=view)

    # --- タスク管理系 ---
    if content.startswith('!add '):
        await message.channel.send(task_logic.add_task(content[5:]))

    elif content == '!list':
        await message.channel.send(task_logic.list_tasks())

    elif content.startswith('!done '):
        await message.channel.send(task_logic.complete_task(content[6:]))

    # --- 学習系 ---
    elif content == '!kiso':
        await message.channel.send(study_logic.get_kiso_quiz())

    elif content == '!math':
        await message.channel.send(study_logic.get_math_quiz())

    elif content.startswith('!kiso_add '):
        await message.channel.send(study_logic.add_kiso_word(content[10:]))

    elif content.startswith('!search '):
        word = content[8:] # "!search " の後を取り出す
        await message.channel.send(study_logic.search_glossary(word))

client.run(TOKEN)
