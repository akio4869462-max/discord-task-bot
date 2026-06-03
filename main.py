import asyncio
import os
from datetime import time, timezone, timedelta
import discord
from discord.ext import tasks
from discord.ui import Button, View
from dotenv import load_dotenv

import news_logic
import study_logic
import task_logic

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Discord クライアントの初期化設定
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ====================================================
# ⚙️ システム定数・設定値
# ====================================================
JST = timezone(timedelta(hours=9))
# ニュースの自動定期配信時刻（AM 08:00 / PM 20:00）
DELIVERY_TIMES = [time(8, 0, tzinfo=JST), time(20, 0, tzinfo=JST)]
# 定期配信先のDiscordチャンネルID
NEWS_CHANNEL_ID = 1498093810356453508
# 集中タイマーの基準時間（25分 = 1500秒）
FOCUS_TIMER_SECONDS = 1500


# ====================================================
# ⏰ ニュース自動定期配信タスク（バックグラウンド処理）
# ====================================================
@tasks.loop(time=DELIVERY_TIMES)
async def xml_news_delivery_task():
    """指定された時刻にバックグラウンドでニュースを自動配信するループ処理"""
    await client.wait_until_ready()
    
    channel = client.get_channel(NEWS_CHANNEL_ID)
    if channel is not None:
        print("⏰ [定期配信] ニュースを取得中...")
        news_msg = news_logic.get_it_news()
        await channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")
    else:
        print(f"⚠️ [定期配信] 指定されたチャンネルID ({NEWS_CHANNEL_ID}) が見つかりませんでした。")


# ====================================================
# 🎯 UI コンポーネント（Views / Modals）
# ====================================================

class TaskMenuView(View):
    """タスク管理機能の下位メニューを制御するViewクラス"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="タスク追加", style=discord.ButtonStyle.primary)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """ユーザーにタスク追加コマンドの書式を提示する（エフェメラル対応）"""
        await interaction.response.send_message("`!add 内容` の形式でチャットに入力してください。", ephemeral=True)

    @discord.ui.button(label="タスク完了", style=discord.ButtonStyle.danger)
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """登録中のタスク一覧を基に完了選択メニューを生成・提示する"""
        count = task_logic.get_task_count()
        if count == 0:
            await interaction.response.send_message("完了するタスクがありません。", ephemeral=True)
        else:
            view = TaskCompleteView(count)
            await interaction.response.send_message("完了する番号を選んでください：", view=view, ephemeral=True)


class MainMenuView(View):
    """ボットのコア機能を網羅したメインメニューを制御するViewクラス"""
    def __init__(self):
        super().__init__(timeout=None)
        # プレイヤーのボス戦状態を読み込み、ボタンのスタイルを動的に変更
        p_data = study_logic.load_player_data()
        is_boss_active = p_data.get("is_boss_active", False)
        if is_boss_active:
            self.study_menu.style = discord.ButtonStyle.danger
            self.study_menu.label = "🚨 ボス襲来！作業の記録"
        else:
            self.study_menu.style = discord.ButtonStyle.success
            self.study_menu.label = "📖 作業の記録"

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
        """25分間のポモドーロ・テクニックに基づく集中タイマーを実行し、終了後にチャンネルへ通知する"""
        # 3秒以内のレスポンス制約を回避するため、即座に受付メッセージを非表示で返す
        await interaction.response.send_message(f"⏱️ {int(FOCUS_TIMER_SECONDS / 60)}分間の集中タイムを開始します！開発（programming）の経験値に連動します。", ephemeral=True)
        
        # タイムアウトエラー（Invalid Webhook Token）回避のため、投稿先のコンテキストを固定保持
        channel = interaction.channel
        user_mention = interaction.user.mention
        
        # 指定時間の待機処理
        await asyncio.sleep(FOCUS_TIMER_SECONDS)
        
        # バックエンドロジックでの経験値・レベル処理
        is_up, lv, earned, event = study_logic.report_study("programming", int(FOCUS_TIMER_SECONDS / 60))
        
        msg = f"{user_mention} {int(FOCUS_TIMER_SECONDS / 60)}分経過しました！お疲れ様でした。☕\n💻 開発作業{int(FOCUS_TIMER_SECONDS / 60)}分を自動記録しました！（+{earned} EXP）"
        if is_up:
            msg += f"\n🎊 レベルアップ！ 各スキルの習得度が Lv.{lv} になりました！"
            
        # チャンネルへ直接メッセージをシリアライズ送信
        await channel.send(msg)

    @discord.ui.button(label="⚔️ ステータス", style=discord.ButtonStyle.danger, row=1)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        status_msg = study_logic.get_status_summary()
        embed = discord.Embed(title=f"🛡️ {interaction.user.display_name} の冒険の記録 (就活攻略RPG)", color=0xffd700)
        embed.description = status_msg
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔍 用語検索", style=discord.ButtonStyle.secondary, row=1)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchWordModal())

    @discord.ui.button(label="➕ 用語ストック", style=discord.ButtonStyle.secondary, row=1)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KisoAddModal())

    @discord.ui.button(label="📚 用語一覧", style=discord.ButtonStyle.secondary, row=2)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """現在蓄積されているIT用語のキー一覧を取得・表示する"""
        list_msg = study_logic.get_glossary_list()
        await interaction.response.send_message(list_msg, ephemeral=True)

    @discord.ui.button(label="🎲 用語クイズ", style=discord.ButtonStyle.secondary, row=2)
    async def quiz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """登録データからランダムに1問を用語クイズとして出題する（辞書型構造対応版）"""
        quiz_msg = study_logic.get_kiso_quiz()
        await interaction.response.send_message(quiz_msg, ephemeral=True)

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary, row=3)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        files = ['todo.json', 'player_data.json', 'glossary.json']
        found_files = [discord.File(f) for f in files if os.path.exists(f)]
        if found_files:
            await interaction.response.send_message("現在のバックアップデータです：", files=found_files, ephemeral=True)
        else:
            await interaction.response.send_message("バックアップ対象のファイルが見つかりませんでした。", ephemeral=True)

    @discord.ui.button(label="📰 最新ITニュースを確認", style=discord.ButtonStyle.primary, row=3)
    async def news_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """外部API経由で最新のITトレンド・技術ニュースを取得・表示する"""
        await interaction.response.defer(ephemeral=True)
        news_msg = news_logic.get_it_news()
        await interaction.followup.send(news_msg, ephemeral=True)


class TaskCompleteView(View):
    """登録中タスクを個別の動的ボタンとしてマッピングし、完了選択を行うViewクラス"""
    def __init__(self, count):
        super().__init__(timeout=60)
        for i in range(count):
            task_text = task_logic.get_task_text(i)
            # 文字列長によるラベルのトリミング処理
            display_label = f"{i+1}. {task_text[:10]}..." if task_text and len(task_text) > 10 else f"{i+1}. {task_text}" if task_text else f"{i+1}"
            button = Button(label=display_label, style=discord.ButtonStyle.success)
            button.callback = self.create_callback(i)
            self.add_item(button)

    def create_callback(self, index):
        async def callback(interaction: discord.Interaction):
            result_msg = task_logic.complete_task(str(index + 1))
            await interaction.response.send_message(result_msg, ephemeral=True)
        return callback


class KisoAddModal(discord.ui.Modal, title='気になる用語のストック'):
    """IT用語の新規インプットを受け付けるモーダルフォームクラス"""
    term = discord.ui.TextInput(label='気になる用語・技術名', placeholder='例: エッジAI, クライアントサイドレンダリング', required=True)
    desc = discord.ui.TextInput(label='簡単なメモ（概要や解説文）', style=discord.TextStyle.paragraph, placeholder='例: 技術の概要、特徴など客観的な文章。', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        result = study_logic.add_kiso(self.term.value, self.desc.value)
        await interaction.response.send_message(result, ephemeral=True)


class SearchWordModal(discord.ui.Modal, title='ストック用語の検索'):
    """キーワードから該当用語の部分一致検索をリクエストするモーダルフォームクラス"""
    keyword = discord.ui.TextInput(label='検索したいキーワード', placeholder='例: エッジAI', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        result_msg = study_logic.search_glossary(self.keyword.value)
        await interaction.response.send_message(result_msg, ephemeral=True)


class WorkReportView(View):
    """作業カテゴリ選択用のボタングループを制御するViewクラス"""
    def __init__(self):
        super().__init__(timeout=60)
    
    @discord.ui.button(label="💻 開発を報告", style=discord.ButtonStyle.success)
    async def programming_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WorkReportModal("programming", "開発・ポートフォリオ制作"))

    @discord.ui.button(label="📝 書類・面接を報告", style=discord.ButtonStyle.success)
    async def document_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WorkReportModal("document", "書類作成・面接対策"))

    @discord.ui.button(label="📚 インプットを報告", style=discord.ButtonStyle.success)
    async def reading_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WorkReportModal("reading", "技術書・ニュース学習"))


class WorkReportModal(discord.ui.Modal):
    """作業時間を分単位で取得し、就活RPGロジックとボス戦の処理を実行するモーダルクラス"""
    def __init__(self, cat_id, cat_name):
        super().__init__(title=f'{cat_name}の作業報告')
        self.cat_id = cat_id
        self.cat_name = cat_name

    count_input = discord.ui.TextInput(label='作業した時間（分）を入力してください', placeholder='例: 25 （半角数字）', min_length=1, max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.count_input.value.isdigit():
            await interaction.response.send_message("数字（分）で入力してください！", ephemeral=True)
            return

        minutes = int(self.count_input.value)
        is_up, lv, earned, event = study_logic.report_study(self.cat_id, minutes)
        msg = f"✅ {self.cat_name}の作業（{minutes}分間）を記録しました！\n+{earned} EXP 獲得！"

        # 各種イベント（ゲーム要素）発生時の文言制御
        if event == "BOSS_APPEAR":
            msg += "\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 新たな課題（ボス）が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
        elif event == "BOSS_DAMAGE":
            msg += "\n⚔️ **TASK ATTACK!**\nあなたの集中した時間がボスに ダメージを与えた！\n"
        elif event == "BOSS_DEFEATED":
            msg += "\n🎊 **MISSION COMPLETE!!** 🎊\n```fix\n見事に目の前の課題ボスを撃破しました！\n```撃破ボーナスを獲得！次の作業も頑張りましょう。\n"

        if is_up:
            msg += f"\n🎊 レベルアップ！ 各スキルの習得度が Lv.{lv} になりました！"
        
        await interaction.response.send_message(msg, ephemeral=True)


# ====================================================
# 🚀 ボット起動時のシステムイベント
# ====================================================
@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')
    
    # 定時ニュースタスクループの自動開始処理
    if not xml_news_delivery_task.is_running():
        xml_news_delivery_task.start()
        print("⏰ ニュース自動定期配信タスクを開始しました。")


@client.event
async def on_message(message):
    """テキストコマンド（プレフィックス形式）のハンドリング処理"""
    if message.author == client.user:
        return
        
    content = message.content
    
    # メインメニュー呼び出し
    if content == '!menu' or content == '！':
        view = MainMenuView()
        await message.channel.send("メニューを選んでください：", view=view)
        
    # タスク管理プレフィックスコマンド
    elif content.startswith('!add '):
        await message.channel.send(task_logic.add_task(content[5:]))
    elif content == '!list':
        await message.channel.send(task_logic.list_tasks())
    elif content.startswith('!done '):
        await message.channel.send(task_logic.complete_task(content[6:]))
        
    # 用語検索簡易コマンド
    elif content.startswith('!s '):
        await message.channel.send(study_logic.search_glossary(content[3:]))


if __name__ == "__main__":
    client.run(TOKEN)