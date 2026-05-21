import discord
import os
import asyncio
from dotenv import load_dotenv
import task_logic
import study_logic

from discord.ui import Button, View

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Discordクライアントの初期化とインテントの設定
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

class StudyMenuView(View):
    """
    基本情報技術者試験・ITパスポートの学習メニューを表示・管理するViewクラス。
    各ボタンに応じたクイズの出題やタイマー機能を提供します。
    """
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="📝 学習を報告する", style=discord.ButtonStyle.primary)
    async def report_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """学習分野を選択するための専用メニュー（StudyReportView）を呼び出します。"""
        view = StudyReportView()
        await interaction.response.send_message("どの分野を学習しましたか？", view=view, ephemeral=True)

    @discord.ui.button(label="用語検索", style=discord.ButtonStyle.primary)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """チャットコマンドによる用語検索の方法を案内します。"""
        await interaction.response.send_message("`!s 用語` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="用語テスト", style=discord.ButtonStyle.success)
    async def kiso_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """study_logic から基礎クイズを取得して出題します。"""
        await interaction.response.send_message(study_logic.get_kiso_quiz())

    @discord.ui.button(label="計算テスト", style=discord.ButtonStyle.success)
    async def math_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """study_logic から計算クイズを取得して出題します。"""
        await interaction.response.send_message(study_logic.get_math_quiz())

    @discord.ui.button(label="用語を追加", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """新用語を登録するための入力フォーム（Modal）を表示します。"""
        await interaction.response.send_modal(KisoAddModal())

    @discord.ui.button(label="25分タイマー開始", style=discord.ButtonStyle.secondary, emoji="⏱️")
    async def timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """ポモドーロ・テクニック（25分集中）を模したタイマーを実行します。"""
        await interaction.response.send_message("⏱️ 25分間の集中タイムを開始します！頑張りましょう。", ephemeral=True)
        
        # 25分間（1500秒）非同期で待機
        await asyncio.sleep(1500)
        
        # 終了後にメンションで通知
        await interaction.followup.send(f"{interaction.user.mention} 25分経過しました！5分間の休憩を取りましょう。☕")

class TaskMenuView(View):
    """
    タスク管理（追加案内・完了選択）の操作を提供するViewクラス。
    """
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="タスク追加", style=discord.ButtonStyle.primary)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """チャットコマンドによるタスク追加の方法を案内します。"""
        await interaction.response.send_message("`!add 内容` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="タスク完了", style=discord.ButtonStyle.danger)
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """登録されているタスク数をチェックし、完了選択用のView（TaskCompleteView）を表示します。"""
        count = task_logic.get_task_count()
        if count == 0:
            await interaction.response.send_message("完了するタスクがありません。", ephemeral=True)
        else:
            view = TaskCompleteView(count)
            await interaction.response.send_message("完了する番号を選んでください：", view=view, ephemeral=True)

class MainMenuView(View):
    """
    ボットの核となる、各種機能（タスク・学習・バックアップ・ステータス）への
    アクセスを提供するメインメニューViewクラス。
    """
    def __init__(self):
        super().__init__(timeout=None)  # 永続的なViewとして設定

    @discord.ui.button(label="📋 タスク管理", style=discord.ButtonStyle.primary)
    async def task_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        """現在のタスク一覧を一覧表示し、タスク管理用のサブメニューを表示します。"""
        list_str = task_logic.list_tasks()
        view = TaskMenuView()
        await interaction.response.send_message(list_str, view=view, ephemeral=True)

    @discord.ui.button(label="📖 基本情報の勉強", style=discord.ButtonStyle.success)
    async def study_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        """学習管理用のサブメニューを表示します。"""
        view = StudyMenuView()
        await interaction.response.send_message("勉強モード：機能を選んでください", view=view, ephemeral=True)

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """ローカルのJSONデータを discord.File として抽出し、ユーザーにバックアップとして提供します。"""
        files = ['todo.json', 'glossary.json']
        found_files = []

        for file_name in files:
            if os.path.exists(file_name):
                found_files.append(discord.File(file_name))

        if found_files:
            await interaction.response.send_message("現在のバックアップデータです。ダウンロードして保存してください：", files=found_files, ephemeral=True)
        else:
            await interaction.response.send_message("バックアップ対象のファイルが見つかりませんでした。", ephemeral=True)

    @discord.ui.button(label="⚔️ ステータス", style=discord.ButtonStyle.danger)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """ユーザーの現在のRPGステータス（LvやEXP、ボス状況）をEmbed形式で美しく表示します。"""
        status_msg = study_logic.get_status_summary()
        
        embed = discord.Embed(title=f"🛡️ {interaction.user.display_name} の冒険の記録", color=0xffd700)
        embed.description = status_msg
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TaskCompleteView(View):
    """
    動的にボタンを生成し、タスクを番号順に完了（削除）するためのViewクラス。
    """
    def __init__(self, count):
        super().__init__(timeout=60)
        # 存在するタスクの数だけ動的にボタンを生成
        for i in range(count):
            button = Button(label=f"{i+1}", style=discord.ButtonStyle.danger)
            button.callback = self.create_callback(i)
            self.add_item(button)

    def create_callback(self, index):
        """各ボタンが押された際に実行されるコールバック関数を動的に生成します。"""
        async def callback(interaction: discord.Interaction):
            result_msg = task_logic.complete_task(str(index + 1))
            await interaction.response.send_message(result_msg, ephemeral=True)
        return callback

class KisoAddModal(discord.ui.Modal, title='新しい用語の登録'):
    """
    新しい学習用語をボットに登録するための入力モーダルフォーム。
    """
    term = discord.ui.TextInput(label='用語名', placeholder='例: CPU', required=True)
    desc = discord.ui.TextInput(
        label='用語の説明',
        style=discord.TextStyle.paragraph,
        placeholder='例: コンピュータの制御や演算を行う中心的な装置。',
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """送信された用語と説明を study_logic を介して登録します。"""
        result = study_logic.add_kiso(self.term.value, self.desc.value)
        await interaction.response.send_message(result, ephemeral=True)

class StudyReportView(View):
    """
    学習した分野（テクノロジ、マネジメント、ストラテジ、B問題）を選択するViewクラス。
    """
    def __init__(self):
        super().__init__(timeout=60)
    
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

    async def process_report(self, interaction, cat_id, cat_name):
        """選択された分野に応じた問題数入力モーダルを表示します。"""
        await interaction.response.send_modal(StudyReportModal(cat_id, cat_name))

class StudyReportModal(discord.ui.Modal):
    """
    解いた問題数を入力させ、EXPの反映やボスバトルイベントの判定を処理するモーダル。
    """
    def __init__(self, cat_id, cat_name):
        super().__init__(title=f'{cat_name}の学習報告')
        self.cat_id = cat_id
        self.cat_name = cat_name

    count_input = discord.ui.TextInput(
        label='解いた問題数を入力してください',
        placeholder='例: 10',
        min_length=1,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """入力値をバリデーションし、学習成果をRPGシステムに反映させます。"""
        if not self.count_input.value.isdigit():
            await interaction.response.send_message("数字で入力してください！", ephemeral=True)
            return

        count = int(self.count_input.value)
        is_up, lv, earned, event = study_logic.report_study(self.cat_id, count)
        
        msg = f"✅ {self.cat_name}の学習（{count}問分）を記録しました！\n+{earned} EXP 獲得！"

        # ボスイベントに応じたゲーム演出のテキスト分岐
        if event == "BOSS_APPEAR":
            msg += f"\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 過去問の深淵より、新たな強敵が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
        elif event == "BOSS_DAMAGE":
            msg += f"\n⚔️ **BOSS ATTACK!**\nあなたの学習がボスに **{count*10}** のダメージを与えた！\n"
        elif event == "BOSS_DEFEATED":
            msg += f"\n🎊 **VICTORY!!** 🎊\n```fix\n極限の集中力により、過去問ボスを完全に撃破しました！\n```撃破ボーナスとして **200 EXP** を獲得！次の戦いへ備えましょう。\n"

        if is_up:
            msg += f"\n🎊 レベルアップ！ Lv.{lv} になりました！"
        
        await interaction.response.send_message(msg, ephemeral=True)

@client.event
async def on_ready():
    """ボットが正常に起動し、Discordサーバーに接続された際に呼ばれるイベント。"""
    print(f'{client.user} が起動しました。')

@client.event
async def on_message(message):
    """
    メッセージが送信された際に呼ばれるイベント。
    プレフィックス形式（!コマンド）のチャット入力をルーティングします。
    """
    if message.author == client.user:
        return

    content = message.content

    # メニュー表示コマンド（スマホ操作を考慮し、全角の「！」にも対応）
    if content == '!menu' or content == '！':
        view = MainMenuView()
        await message.channel.send("メニューを選んでください：", view=view)

    # タスク管理コマンドの処理
    if content.startswith('!add '):
        await message.channel.send(task_logic.add_task(content[5:]))
    elif content == '!list':
        await message.channel.send(task_logic.list_tasks())
    elif content.startswith('!done '):
        await message.channel.send(task_logic.complete_task(content[6:]))

    # 学習システムコマンドの処理
    elif content == '!kiso':
        await message.channel.send(study_logic.get_kiso_quiz())
    elif content == '!math':
        await message.channel.send(study_logic.get_math_quiz())
    elif content.startswith('!kiso_add '):
        await message.channel.send(study_logic.add_kiso_word(content[10:]))
    elif content.startswith('!search '):
        word = content[8:]
        await message.channel.send(study_logic.search_glossary(word))

client.run(TOKEN)