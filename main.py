import discord
import os
import asyncio
from dotenv import load_dotenv
from discord.ext import tasks  # 【追加！】タイマー機能を使うためのパーツよ！
import task_logic
import study_logic
import news_logic

from discord.ui import Button, View
from datetime import datetime, time, timedelta, timezone

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ====================================================
# ⏰ ニュース自動定期配信タスク（バックグラウンド処理）
# ====================================================
# タイムゾーンと配信時刻の設定（日本標準時: JST）
JST = timezone(timedelta(hours=9))
delivery_time = [time(8, 0, tzinfo=JST), time(20, 0, tzinfo=JST)]  # AM/PM 08:00 に配信設定（テスト時は適宜変更）

@tasks.loop(time=delivery_time)
async def xml_news_delivery_task():
    """指定された時刻にバックグラウンドでニュースを自動配信するタスクループ"""
    # Discordクライアントの準備が完全に整うまで待機
    await client.wait_until_ready()
    
    # 投稿先のテキストチャンネルIDを設定
    CHANNEL_ID = 1498093810356453508 
    
    channel = client.get_channel(CHANNEL_ID)
    if channel is not None:
        print("⏰ [定期配信] ニュースを取得中...")
        news_msg = news_logic.get_it_news()
        await channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")
    else:
        print(f"⚠️ [定期配信] 指定されたチャンネルID ({CHANNEL_ID}) が見つかりませんでした。")

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
        if is_up:
            msg += f"\n🎊 レベルアップ！ Lv.{lv} になりました！"
        await interaction.followup.send(msg)

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

    # ⭕ 追加ポイント1：用語一覧表示ボタン (ボタンが詰まってきたのでrow=2に綺麗に並べましょう！)
    @discord.ui.button(label="📚 用語一覧", style=discord.ButtonStyle.secondary, row=2)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        list_msg = study_logic.get_glossary_list()
        await interaction.response.send_message(list_msg, ephemeral=True)

    # ⭕ 追加ポイント2：バグを直した用語クイズボタン (同じくrow=2へ配置！)
    @discord.ui.button(label="🎲 用語クイズ", style=discord.ButtonStyle.secondary, row=2)
    async def quiz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        quiz_msg = study_logic.get_kiso_quiz()
        await interaction.response.send_message(quiz_msg, ephemeral=True)

    # --- 4行目（row=3）：既存のバックアップとニュースをまとめます ---
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
        """NewsAPI（またはRSSフィード）を介して、最新のIT・技術トレンドニュースを表示"""
        await interaction.response.defer(ephemeral=True)
        news_msg = news_logic.get_it_news()
        await interaction.followup.send(news_msg, ephemeral=True)


class TaskCompleteView(View):
    def __init__(self, count):
        super().__init__(timeout=60)
        for i in range(count):
            task_text = task_logic.get_task_text(i)
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
    term = discord.ui.TextInput(label='気になる用語・技術名', placeholder='例: エッジAI, クライアントサイドレンダリング', required=True)
    desc = discord.ui.TextInput(label='簡単なメモ（学術書のページ数や概要など）', style=discord.TextStyle.paragraph, placeholder='例: 書籍〇ページ。ニュース検索キーワードの種。', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        result = study_logic.add_kiso(self.term.value, self.desc.value)
        await interaction.response.send_message(result, ephemeral=True)


class SearchWordModal(discord.ui.Modal, title='ストック用語の検索'):
    keyword = discord.ui.TextInput(label='検索したいキーワード', placeholder='例: エッジAI', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        result_msg = study_logic.search_glossary(self.keyword.value)
        await interaction.response.send_message(result_msg, ephemeral=True)


class WorkReportView(View):
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

        if event == "BOSS_APPEAR":
            msg += f"\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 新たな課題（ボス）が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
        elif event == "BOSS_DAMAGE":
            msg += f"\n⚔️ **TASK ATTACK!**\nあなたの集中した時間がボスに ダメージを与えた！\n"
        elif event == "BOSS_DEFEATED":
            msg += f"\n🎊 **MISSION COMPLETE!!** 🎊\n```fix\n見事に目の前の課題ボスを撃破しました！\n```撃破ボーナスを獲得！次の作業も頑張りましょう。\n"

        if is_up:
            msg += f"\n🎊 レベルアップ！ 各スキルの習得度が Lv.{lv} になりました！"
        
        await interaction.response.send_message(msg, ephemeral=True)


# ====================================================
# 🚀 ボット起動時のイベント
# ====================================================
@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')
    
    # 【超重要！】ボットが起動した瞬間、タイマー（タスクループ）をスタートさせるわ！
    if not xml_news_delivery_task.is_running():
        xml_news_delivery_task.start()
        print("⏰ ニュース自動定期配信タスクを開始しました。")


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    content = message.content
    if content == '!menu' or content == '！':
        view = MainMenuView()
        await message.channel.send("メニューを選んでください：", view=view)
    if content.startswith('!add '):
        await message.channel.send(task_logic.add_task(content[5:]))
    elif content == '!list':
        await message.channel.send(task_logic.list_tasks())
    elif content.startswith('!done '):
        await message.channel.send(task_logic.complete_task(content[6:]))
    elif content.startswith('!s '):
        await message.channel.send(study_logic.search_glossary(content[3:]))

client.run(TOKEN)