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
    def __init__(self):
        super().__init__(timeout=60)

    # 毎日使うメインの報告ボタン（特等席）
    @discord.ui.button(label="📝 学習を報告する", style=discord.ButtonStyle.primary, row=0)
    async def report_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WorkReportView()
        await interaction.response.send_message("どの分野を学習しましたか？", view=view, ephemeral=True)

    # 検索、追加などの補助機能は下の行（row=1）へ格納
    @discord.ui.button(label="用語検索", style=discord.ButtonStyle.secondary, row=1)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("`!s 用語` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="用語を追加", style=discord.ButtonStyle.secondary, emoji="➕", row=1)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KisoAddModal())

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
    def __init__(self):
        super().__init__(timeout=None)
        p_data = study_logic.load_player_data()
        is_boss_active = p_data.get("is_boss_active", False)
        
        if is_boss_active:
            self.study_menu.style = discord.ButtonStyle.danger
            self.study_menu.label = "🚨 ボス襲来！作業の記録"
        else:
            self.study_menu.style = discord.ButtonStyle.success
            self.study_menu.label = "📖 作業の記録"

    # --- 1行目（row=0） ---
    @discord.ui.button(label="📋 タスク管理", style=discord.ButtonStyle.primary, row=0)
    async def task_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        list_str = task_logic.list_tasks()
        view = TaskMenuView()
        await interaction.response.send_message(list_str, view=view, ephemeral=True)

    @discord.ui.button(label="📖 作業の記録", style=discord.ButtonStyle.success, row=0)
    async def study_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WorkReportView()
        await interaction.response.send_message("作業内容：カテゴリを選んでください", view=view, ephemeral=True)

    @discord.ui.button(label="集中タイマー", style=discord.ButtonStyle.secondary, emoji="⏱️", row=0)
    async def timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏱️ 25分間の集中タイムを開始します！開発（programming）の経験値に連動します。", ephemeral=True)
        await asyncio.sleep(1500)
        is_up, lv, earned, event = study_logic.report_study("programming", 25)
        msg = f"{interaction.user.mention} 25分経過しました！お疲れ様でした。☕\n💻 開発作業25分を自動記録しました！（+{earned} EXP）"
        if is_up: msg += f"\n🎊 レベルアップ！ Lv.{lv} になりました！"
        await interaction.followup.send(msg)

    # --- 2行目（row=1）：【大復活！】インプット用のメニューに進化 ---
    @discord.ui.button(label="⚔️ ステータス", style=discord.ButtonStyle.danger, row=1)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        status_msg = study_logic.get_status_summary()
        embed = discord.Embed(title=f"🛡️ {interaction.user.display_name} の冒険の記録 (就活攻略RPG)", color=0xffd700)
        embed.description = status_msg
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # 用語集・ニュース連携用のボタンを「row=1」の空きスペースにスマートに配置！
    @discord.ui.button(label="🔍 用語検索", style=discord.ButtonStyle.secondary, row=1)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """ポップアップ（モーダル）を開いて、ストックした用語を検索します。"""
        # 【大改善！】チャット案内を廃止して、直接検索モーダルを起動！
        await interaction.response.send_modal(SearchWordModal())

    @discord.ui.button(label="➕ 気になる用語をストック", style=discord.ButtonStyle.secondary, row=1)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """学術書などで気になった単語を保存するモーダルを開きます。"""
        await interaction.response.send_modal(KisoAddModal())

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary, row=1)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # glossary.json もバックアップ対象に復活させたわよ！
        files = ['todo.json', 'player_data.json', 'glossary.json']
        found_files = [discord.File(f) for f in files if os.path.exists(f)]
        if found_files:
            await interaction.response.send_message("現在のバックアップデータです：", files=found_files, ephemeral=True)
        else:
            await interaction.response.send_message("バックアップ対象のファイルが見つかりませんでした。", ephemeral=True)

class TaskCompleteView(View):
    """
    動的にタスク名を取得し、完了ボタンを生成するView。
    """
    def __init__(self, count):
        super().__init__(timeout=60)
        
        for i in range(count):
            # 【改善ポイント】インデックスから実際のタスク文字列を取得する
            task_text = task_logic.get_task_text(i)
            
            # 文字数が長いとボタンからはみ出すので、10文字程度でトリミングする
            if task_text and len(task_text) > 10:
                display_label = f"{i+1}. {task_text[:10]}..."
            elif task_text:
                display_label = f"{i+1}. {task_text}"
            else:
                display_label = f"{i+1}"
                
            # スタイルを完了らしく「緑（success）」に、ラベルをタスク名に！
            button = Button(label=display_label, style=discord.ButtonStyle.success)
            button.callback = self.create_callback(i)
            self.add_item(button)

    def create_callback(self, index):
        async def callback(interaction: discord.Interaction):
            result_msg = task_logic.complete_task(str(index + 1))
            # 完了後はメッセージを更新して、ボタンを無効化するか消去するとさらに綺麗よ
            await interaction.response.send_message(result_msg, ephemeral=True)
        return callback

class KisoAddModal(discord.ui.Modal, title='気になる用語のストック'):
    """
    あとからニュース検索などに使い回せるよう、単語とメモを保存するモーダル。
    """
    term = discord.ui.TextInput(label='気になる用語・技術名', placeholder='例: エッジAI, クライアントサイドレンダリング', required=True)
    desc = discord.ui.TextInput(
        label='簡単なメモ（学術書のページ数や概要など）',
        style=discord.TextStyle.paragraph,
        placeholder='例: 書籍〇ページ。今後ニュース機能と連携して自動収集するキーワード。',
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # study_logicの元の関数（add_kiso）をそのまま呼び出すわね
        result = study_logic.add_kiso(self.term.value, self.desc.value)
        await interaction.response.send_message(result, ephemeral=True)

class SearchWordModal(discord.ui.Modal, title='ストック用語の検索'):
    """
    ポップアップでキーワード入力を受け付け、部分一致する用語を検索して返すモーダル。
    """
    keyword = discord.ui.TextInput(
        label='検索したいキーワード', 
        placeholder='例: エッジAI （一部の文字だけでもOK）', 
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        """送信されたキーワードを元に study_logic で検索し、結果を ephemeral（自分だけに見えるメッセージ）で返します。"""
        word = self.keyword.value
        
        # study_logicの既存の検索関数を呼び出すわよ！
        result_msg = study_logic.search_glossary(word)
        
        # 検索結果をポップアップを送信した本人にだけこっそり表示
        await interaction.response.send_message(result_msg, ephemeral=True)

class WorkReportView(View):
    """
    学習した分野（テクノロジ、マネジメント、ストラテジ、B問題）を選択するViewクラス。
    """
    def __init__(self):
        super().__init__(timeout=60)
    
    @discord.ui.button(label="💻 開発を報告", style=discord.ButtonStyle.success)
    async def programming_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 勉強用モーダルを流用して「分単位」の入力モーダルを開く
        await interaction.response.send_modal(WorkReportModal("programming", "開発・ポートフォリオ制作"))

    @discord.ui.button(label="📝 書類・面接を報告", style=discord.ButtonStyle.success)
    async def document_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WorkReportModal("document", "書類作成・面接対策"))

    @discord.ui.button(label="📚 インプットを報告", style=discord.ButtonStyle.success)
    async def reading_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WorkReportModal("reading", "技術書・ニュース学習"))

class WorkReportModal(discord.ui.Modal):
    """
    作業時間（分）を入力させ、EXPの反映やイベントの判定を処理するモーダル。
    """
    def __init__(self, cat_id, cat_name):
        # モーダルのタイトルを「〇〇の作業報告」に動的変更
        super().__init__(title=f'{cat_name}の作業報告')
        self.cat_id = cat_id
        self.cat_name = cat_name

    # 【改善ポイント】ラベルとプレースホルダーを「時間（分）」に変更！
    count_input = discord.ui.TextInput(
        label='作業した時間（分）を入力してください',
        placeholder='例: 25 （半角数字）',
        min_length=1,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """入力された時間をバリデーションし、RPGシステムに反映させます。"""
        # 数字かどうかのチェック
        if not self.count_input.value.isdigit():
            await interaction.response.send_message("数字（分）で入力してください！", ephemeral=True)
            return

        # 入力された文字列を整数（分）に変換
        minutes = int(self.count_input.value)
        
        # 【重要】裏側のロジック（study_logic）に、カテゴリIDと「分」を渡す！
        # ※ロジック側の引数名がまだ count のままであっても、ここに minutes を渡せばOKよ
        is_up, lv, earned, event = study_logic.report_study(self.cat_id, minutes)
        
        # 報告完了メッセージのテキストも「分」に合わせる
        msg = f"✅ {self.cat_name}の作業（{minutes}分間）を記録しました！\n+{earned} EXP 獲得！"

        # ボスイベントに応じた演出（必要に応じて今後テキストを変えても楽しいわね！）
        if event == "BOSS_APPEAR":
            msg += f"\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 新たな課題（ボス）が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
        elif event == "BOSS_DAMAGE":
            msg += f"\n⚔️ **TASK ATTACK!**\nあなたの集中した時間がボスに ダメージを与えた！\n"
        elif event == "BOSS_DEFEATED":
            msg += f"\n🎊 **MISSION COMPLETE!!** 🎊\n```fix\n見事に目の前の課題ボスを撃破しました！\n```撃破ボーナスを獲得！次の作業も頑張りましょう。\n"

        if is_up:
            msg += f"\n🎊 レベルアップ！ 各スキルの習得度が Lv.{lv} になりました！"
        
        await interaction.response.send_message(msg, ephemeral=True)

@client.event
async def on_ready():
    """ボットが正常に起動し、Discordサーバーに接続された際に呼ばれるイベント。"""
    print(f'{client.user} が起動しました。')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content

    if content == '!menu' or content == '！':
        view = MainMenuView()
        await message.channel.send("メニューを選んでください：", view=view)

    # タスク管理コマンド
    if content.startswith('!add '):
        await message.channel.send(task_logic.add_task(content[5:]))
    elif content == '!list':
        await message.channel.send(task_logic.list_tasks())
    elif content.startswith('!done '):
        await message.channel.send(task_logic.complete_task(content[6:]))

    elif content.startswith('!s '):
        word = content[3:]
        await message.channel.send(study_logic.search_glossary(word))

client.run(TOKEN)