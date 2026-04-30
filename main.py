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
        # StudyMenuView クラスの中に追加
    @discord.ui.button(label="📝 学習を報告する", style=discord.ButtonStyle.primary)
    async def report_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 報告用の専用メニュー（分野選択）を表示
        view = StudyReportView()
        await interaction.response.send_message("どの分野を学習しましたか？", view=view, ephemeral=True)

    @discord.ui.button(label="用語検索", style=discord.ButtonStyle.primary)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("`!s 用語` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="用語テスト", style=discord.ButtonStyle.success)
    async def kiso_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(study_logic.get_kiso_quiz())

    @discord.ui.button(label="計算テスト", style=discord.ButtonStyle.success)
    async def math_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(study_logic.get_math_quiz())

    @discord.ui.button(label="用語を追加", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ボタンを押すと入力フォーム（モーダル）が表示される
        await interaction.response.send_modal(KisoAddModal())

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

    # MainMenuView クラスの中に追加
    @discord.ui.button(label="⚔️ ステータス", style=discord.ButtonStyle.danger)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # study_logic から現在のステータスを取得
        status_msg = study_logic.get_status_summary()
        
        # 演出用の Embed（埋め込み）メッセージを作成
        embed = discord.Embed(title=f"🛡️ {interaction.user.display_name} の冒険の記録", color=0xffd700)
        embed.description = status_msg
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

# --- 用語追加用の入力フォーム ---
class KisoAddModal(discord.ui.Modal, title='新しい用語の登録'):
    # 入力項目（1行のテキスト入力）
    term = discord.ui.TextInput(
        label='用語名',
        placeholder='例: CPU',
        required=True,
    )
    # 入力項目（複数行のテキスト入力）
    desc = discord.ui.TextInput(
        label='用語の説明',
        style=discord.TextStyle.paragraph,
        placeholder='例: コンピュータの制御や演算を行う中心的な装置。',
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # フォームが送信された時の処理（study_logicの関数を呼び出す）
        # もし既存の add_kiso が引数2つを想定しているなら、それに合わせます
        result = study_logic.add_kiso(self.term.value, self.desc.value)
        await interaction.response.send_message(result, ephemeral=True)

# 新しく追加する報告用ビュー
class StudyReportView(View):
    def __init__(self):
        super().__init__(timeout=60)
    
    # 分野ごとにボタンを作成
    @discord.ui.button(label="テクノロジ", style=discord.ButtonStyle.secondary)
    async def tech_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_report(interaction, "tech", "テクノロジ")

    @discord.ui.button(label="マネジメント", style=discord.ButtonStyle.secondary)
    async def mgmt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_report(interaction, "mgmt", "マネジメント")

    @discord.ui.button(label="ストラテジ", style=discord.ButtonStyle.secondary)
    async def strat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_report(interaction, "strat", "ストラテジ")

    @discord.ui.button(label="B問題", style=discord.ButtonStyle.secondary)
    async def bquest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_report(interaction, "bquest", "B問題")

    # StudyReportView クラスの中の関数を書き換え
    async def process_report(self, interaction, cat_id, cat_name):
        # ボタンを押すと、数字を入力する画面（モーダル）を表示する
        await interaction.response.send_modal(StudyReportModal(cat_id, cat_name))

# --- 学習数入力用のフォーム ---
class StudyReportModal(discord.ui.Modal):
    def __init__(self, cat_id, cat_name):
        super().__init__(title=f'{cat_name}の学習報告')
        self.cat_id = cat_id
        self.cat_name = cat_name

    # 入力項目（1行のテキスト入力）
    count_input = discord.ui.TextInput(
        label='解いた問題数を入力してください',
        placeholder='例: 10',
        min_length=1,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 入力された値が数字かどうかチェック
        if not self.count_input.value.isdigit():
            await interaction.response.send_message("数字で入力してください！", ephemeral=True)
            return

        count = int(self.count_input.value)
        # study_logicの関数を呼び出す（先ほど作った report_study を使用）
        is_up, lv, earned, event = study_logic.report_study(self.cat_id, count)
        
        msg = f"✅ {self.cat_name}の学習（{count}問分）を記録しました！\n+{earned} EXP 獲得！"

        if event == "BOSS_APPEAR":
            msg += f"\n🚨 **WARNING!! WARNING!!** 🚨\n"
            msg += f"```diff\n- 過去問の深淵より、新たな強敵が出現しました！\n```"
            msg += f"ステータスを確認して、撃破を目指してください！\n"

        elif event == "BOSS_DAMAGE":
            msg += f"\n⚔️ **BOSS ATTACK!**\n"
            msg += f"あなたの学習がボスに **{count*10}** のダメージを与えた！\n"

        elif event == "BOSS_DEFEATED":
            msg += f"\n🎊 **VICTORY!!** 🎊\n"
            msg += f"```fix\n極限の集中力により、過去問ボスを完全に撃破しました！\n```"
            msg += f"撃破ボーナスとして **200 EXP** を獲得！次の戦いへ備えましょう。\n"

        if is_up:
            msg += f"\n🎊 レベルアップ！ Lv.{lv} になりました！"
        
        await interaction.response.send_message(msg, ephemeral=True)

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
