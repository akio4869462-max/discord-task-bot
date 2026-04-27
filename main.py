import discord
import os
import asyncio
from dotenv import load_dotenv
import task_logic
import study_logic

from discord.ui import Button, View

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

class StudyMenuView(View):
    def __init__(self):
        super().__init__(timeout=60)

    # 全ての関数に "button" 引数を追加します
    @discord.ui.button(label="用語検索", style=discord.ButtonStyle.primary)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("`!s 用語` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="用語テスト", style=discord.ButtonStyle.success)
    async def kiso_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(study_logic.get_kiso_quiz())

    @discord.ui.button(label="計算テスト", style=discord.ButtonStyle.success)
    async def math_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(study_logic.get_math_quiz())

    @discord.ui.button(label="25分タイマー開始", style=discord.ButtonStyle.secondary, emoji="⏱️")
    async def timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # タイマー開始を自分にだけ通知
        await interaction.response.send_message("⏱️ 25分間の集中タイムを開始します！頑張りましょう。", ephemeral=True)
        
        # 25分間（1500秒）待機
        await asyncio.sleep(1500)
        
        # 終了後にメンションで通知（これは全員に見える形式の方が気づきやすいです）
        await interaction.followup.send(f"{interaction.user.mention} 25分経過しました！5分間の休憩を取りましょう。☕")

class TaskMenuView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="タスク追加", style=discord.ButtonStyle.primary)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("`!add 内容` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="タスク完了", style=discord.ButtonStyle.danger)
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        count = task_logic.get_task_count()
        if count == 0:
            await interaction.response.send_message("完了するタスクがありません。", ephemeral=True)
        else:
            view = TaskCompleteView(count)
            await interaction.response.send_message("完了する番号を選んでください：", view=view, ephemeral=True)

# --- ボタンを管理するクラス ---
class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📋 タスク管理", style=discord.ButtonStyle.primary)
    async def task_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        # タスク管理ボタンを押した瞬間に一覧を表示しつつ、専用メニューを出す
        list_str = task_logic.list_tasks()
        view = TaskMenuView()
        await interaction.response.send_message(list_str, view=view, ephemeral=True)

    @discord.ui.button(label="📖 基本情報の勉強", style=discord.ButtonStyle.success)
    async def study_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = StudyMenuView()
        await interaction.response.send_message("勉強モード：機能を選んでください", view=view, ephemeral=True)

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 送信したいファイルのリスト
        files = ['todo.json', 'glossary.json']
        found_files = []

        for file_name in files:
            if os.path.exists(file_name):
                # discord.File を使ってファイルを準備
                found_files.append(discord.File(file_name))

        if found_files:
            await interaction.response.send_message("現在のバックアップデータです。ダウンロードして保存してください：", files=found_files, ephemeral=True)
        else:
            await interaction.response.send_message("バックアップ対象のファイルが見つかりませんでした。", ephemeral=True)

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
