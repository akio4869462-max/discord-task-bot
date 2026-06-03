import asyncio
import os
from datetime import time, timezone, timedelta, datetime
import discord
from discord.ext import tasks
from discord.ui import Button, View, Select  # ⭕ Selectをインポート
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
DELIVERY_TIMES = [time(8, 0, tzinfo=JST), time(20, 0, tzinfo=JST)]
NEWS_CHANNEL_ID = int(os.getenv('NEWS_CHANNEL_ID', 1498093810356453508))
TASK_CHANNEL_ID = int(os.getenv('TASK_CHANNEL_ID', NEWS_CHANNEL_ID))
FOCUS_TIMER_SECONDS = 1500

# タスク完了時に獲得できる疑似作業時間（15分 = 150 EXP）
TASK_COMPLETE_MINUTES = 15


# ====================================================
# ⏰ 定期自動配信・リマインダータスク（バックグラウンド処理）
# ====================================================
@tasks.loop(time=DELIVERY_TIMES)
async def xml_news_delivery_task():
    """指定された時刻にニュースの自動配信と、朝の時間帯に期限間近のタスクリマインダーを実行します"""
    await client.wait_until_ready()
    
    news_channel = client.get_channel(NEWS_CHANNEL_ID)
    task_channel = client.get_channel(TASK_CHANNEL_ID)
    
    now_jst = datetime.now(JST)
    
    # 🌅 朝の配信（8:00）
    if now_jst.hour == 8:
        print("⏰ [朝の定期処理] ニュース取得 ＆ タスクリマインダーを実行中...")
        
        if news_channel is not None:
            news_msg = news_logic.get_it_news()
            await news_channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")
        else:
            print(f"⚠️ [定期配信] ニュースチャンネルが見つかりませんでした。")
        
        if task_channel is not None:
            todo_list = task_logic.load_data()
            reminder_tasks = []
            today_jst = now_jst.date()
            
            for item in todo_list:
                if isinstance(item, dict) and item.get('deadline'):
                    try:
                        deadline_date = datetime.strptime(item['deadline'], "%Y-%m-%d").date()
                        days_left = (deadline_date - today_jst).days
                        
                        if 0 <= days_left <= 3:
                            cat_key = item.get('category', 'programming')
                            cat_text = task_logic.CATEGORY_MAP.get(cat_key, '💻 開発')
                            
                            if days_left == 0:
                                reminder_tasks.append(f"🚨 **今日が締切！**: [{cat_text}] {item['task']}")
                            else:
                                reminder_tasks.append(f"⚠️ **あと {days_left} 日**: [{cat_text}] {item['task']}")
                    except ValueError:
                        continue
            
            if reminder_tasks:
                reminder_msg = "📢 **【朝のタスクリマインダー】**\n"
                reminder_msg += "締切が近づいているタスクがあります！計画的に攻略していきましょう！\n\n"
                reminder_msg += "\n".join(reminder_tasks)
                await task_channel.send(reminder_msg)
        else:
            print(f"⚠️ [定期配信] タスクリマインダー用のチャンネルが見つかりませんでした。")
            
    # 🌃 夜の配信（20:00）
    elif now_jst.hour == 20:
        if news_channel is not None:
            print("⏰ [夜の定期配信] ニュースを取得中...")
            news_msg = news_logic.get_it_news()
            await news_channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")


# ====================================================
# 🗃️ 共通ヘルパー関数
# ====================================================
def process_task_completion(category):
    """タスク完了時のカテゴリに応じたEXP加算とゲーム内イベント文言の生成処理"""
    if not category:
        return ""
        
    is_up, _, event = study_logic.add_exp(category, TASK_COMPLETE_MINUTES)
    cat_name = task_logic.CATEGORY_MAP.get(category, "開発")
    earned_exp = TASK_COMPLETE_MINUTES * 10
    msg = f"\n✨ タスク完了ボーナス獲得！ 【{cat_name}】+ {earned_exp} EXP"

    if event == "BOSS_APPEAR":
        msg += "\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 新たな課題（ボス）が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
    elif event == "BOSS_DAMAGE":
        msg += "\n⚔️ **TASK ATTACK!**\n集中した努力がボスに ダメージを与えた！\n"
    elif event == "BOSS_DEFEATED":
        msg += "\n🎊 **MISSION COMPLETE!!** 🎊\n```fix\n見面に目の前の課題ボスを撃破しました！\n```撃破ボーナスを獲得！次の作業も頑張りましょう。\n"

    if is_up:
        p_data = study_logic.load_player_data()
        current_lv = p_data.get("level", 1)
        msg += f"\n🎊 レベルアップ！ 各スキルの習得度が出現 Lv.{current_lv} になりました！"
        
    return msg


# ====================================================
# 🎯 UI コンポーネント（Views / Modals）
# ====================================================

class TaskMenuView(View):
    """タスク管理機能の下位メニューを制御するViewクラス"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="タスク追加", style=discord.ButtonStyle.primary)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TaskAddModal())

    @discord.ui.button(label="タスク完了プルダウン", style=discord.ButtonStyle.danger)
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        count = task_logic.get_task_count()
        if count == 0:
            await interaction.response.send_message("完了するタスクがありません。", ephemeral=True)
        else:
            # ⭕ タスク完了用のプルダウンUIを単体で呼び出す
            view = TaskSelectView()
            await interaction.response.send_message("完了するタスクをメニューから選んでね：", view=view, ephemeral=True)


class TaskAddModal(discord.ui.Modal, title='📝 新しいタスクの追加'):
    """ボタン押下時にポップアップするタスク入力モーダルフォーム"""
    task_input = discord.ui.TextInput(
        label='タスクの内容', 
        placeholder='例: 職務経歴書の推敲、ボットのUI拡張など', 
        required=True
    )
    category_input = discord.ui.TextInput(
        label='カテゴリ（開発 / 書類 / 本）', 
        placeholder='「開発」「書類」「本」のいずれか（空欄なら開発）', 
        required=False,
        max_length=10
    )
    deadline_input = discord.ui.TextInput(
        label='期限・締切（月/日）', 
        placeholder='例: 6/15, 2026-06-15 など（空欄なら期限なし）', 
        required=False,
        max_length=15
    )
    # ⭕ 優先度を入力できる欄を新設！
    priority_input = discord.ui.TextInput(
        label='優先度（3:高 / 2:中 / 1:低）', 
        placeholder='数字の 1 ～ 3 を入力してね（空欄なら 2:中 になります）', 
        required=False,
        max_length=1
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw_cat = self.category_input.value.strip()
        raw_deadline = self.deadline_input.value.strip()
        raw_priority = self.priority_input.value.strip()
        
        # カテゴリのマッピング
        category = 'programming'
        if raw_cat in ['書類', '面接', 'document', 'd']:
            category = 'document'
        elif raw_cat in ['インプット', '本', '読書', 'reading', 'r']:
            category = 'reading'
            
        # ⭕ 優先度数値のパース処理
        priority = 2
        if raw_priority.isdigit():
            p_val = int(raw_priority)
            if p_val in [1, 2, 3]:
                priority = p_val
            
        result_msg = task_logic.add_task(self.task_input.value, category, raw_deadline, priority)
        await interaction.response.send_message(result_msg, ephemeral=True)


# ⭕ 新設：セレクトメニュー（プルダウン）を内包するタスク完了Viewクラス
class TaskSelectView(View):
    """登録中タスクから動的にプルダウンメニューを生成して完了処理を行うView"""
    def __init__(self):
        super().__init__(timeout=60)
        todo_list = task_logic.load_data()
        
        options = []
        for i, item in enumerate(todo_list):
            # 表示上限が25個までなので安全対策
            if i >= 25:
                break
                
            if isinstance(item, str):
                task_text = item
                stars = "★★☆"
            else:
                task_text = item.get('task', '')
                p_val = item.get('priority', 2)
                stars = task_logic.PRIORITY_MAP.get(p_val, '★★☆')
            
            # プルダウンの選択肢ラベル（100文字以内のトリミング）
            label_text = f"{i+1}. [{stars}] {task_text}"
            if len(label_text) > 90:
                label_text = label_text[:90] + "..."
                
            options.append(discord.SelectOption(
                label=label_text,
                description=f"このタスクを完了状態（クエストクリア）にします",
                value=str(i + 1)  # 1番から始まるインデックス文字列を渡す
            ))
            
        # セレクトメニューコンポーネントを定義してViewに追加
        if options:
            self.add_item(TaskDropdown(options))


class TaskDropdown(Select):
    def __init__(self, options):
        super().__init__(placeholder='パーフェクトにこなしたタスクを選択...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # ユーザーが選択したvalue（番号文字列）を取得
        selected_number = self.values[0]
        result_msg, category = task_logic.complete_task(selected_number)
        rpg_msg = process_task_completion(category)
        
        # 完了メッセージを返却
        await interaction.response.send_message(f"{result_msg}{rpg_msg}", ephemeral=True)


class MainMenuView(View):
    """ボットのコア機能を網羅したメインメニューを制御するViewクラス"""
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

    @discord.ui.button(label="📋 タスク管理メニュー", style=discord.ButtonStyle.primary, row=0)
    async def task_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        list_str = task_logic.list_tasks()
        # ⭕ タスクメニューを開いた際、一緒に完了プルダウンも表示する最強の合わせ技Viewに変更！
        view = TaskSelectCombinedView()
        await interaction.response.send_message(list_str, view=view, ephemeral=True)

    @discord.ui.button(label="📖 作業の記録", style=discord.ButtonStyle.success, row=0)
    async def study_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WorkReportView()
        await interaction.response.send_message("作業内容：カテゴリを選んでください", view=view, ephemeral=True)

    @discord.ui.button(label="集中タイマー", style=discord.ButtonStyle.secondary, emoji="⏱️", row=0)
    async def timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"⏱️ {int(FOCUS_TIMER_SECONDS / 60)}分間の集中タイムを開始します！開発（programming）の経験値に連動します。", ephemeral=True)
        
        channel = interaction.channel
        user_mention = interaction.user.mention
        await asyncio.sleep(FOCUS_TIMER_SECONDS)
        
        is_up, lv, earned, event = study_logic.report_study("programming", int(FOCUS_TIMER_SECONDS / 60))
        msg = f"{user_mention} {int(FOCUS_TIMER_SECONDS / 60)}分経過しました！お疲れ様でした。☕\n💻 開発作業{int(FOCUS_TIMER_SECONDS / 60)}分を自動記録しました！（+{earned} EXP）"
        if is_up:
            msg += f"\n🎊 レベルアップ！ 各スキルの習得度が出現 Lv.{lv} になりました！"
            
        await channel.send(msg)

    @discord.ui.button(label="⚔️ ステータス", style=discord.ButtonStyle.danger, row=1)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        status_msg = study_logic.get_status_summary()
        embed = discord.Embed(title=f"🛡️ {interaction.user.display_name} の冒険 of 就活攻略RPG", color=0xffd700)
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
        list_msg = study_logic.get_glossary_list()
        await interaction.response.send_message(list_msg, ephemeral=True)

    @discord.ui.button(label="🎲 用語クイズ", style=discord.ButtonStyle.secondary, row=2)
    async def quiz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        await interaction.response.defer(ephemeral=True)
        news_msg = news_logic.get_it_news()
        await interaction.followup.send(news_msg, ephemeral=True)


# ⭕ 新設：「タスク管理画面」用の、ボタン＋プルダウンが合体したView
class TaskSelectCombinedView(View):
    """タスク一覧テキストの直下に、タスク追加ボタンと完了プルダウンを同時に出すView"""
    def __init__(self):
        super().__init__(timeout=60)
        
        # 1. 最初に「タスク追加」のボタンを配置
        button = Button(label="新しいタスクを追加", style=discord.ButtonStyle.primary, row=0)
        button.callback = self.add_task_callback
        self.add_item(button)
        
        # 2. 次に、現在のタスク一覧からプルダウンの選択肢を作成して配置
        todo_list = task_logic.load_data()
        options = []
        for i, item in enumerate(todo_list):
            if i >= 25: break  # Discordの上限
            if isinstance(item, str):
                task_text = item
                stars = "★★☆"
            else:
                task_text = item.get('task', '')
                p_val = item.get('priority', 2)
                stars = task_logic.PRIORITY_MAP.get(p_val, '★★☆')
                
            label_text = f"{i+1}. [{stars}] {task_text}"
            if len(label_text) > 90: label_text = label_text[:90] + "..."
            
            options.append(discord.SelectOption(
                label=label_text,
                value=str(i + 1)
            ))
            
        if options:
            # row=1 にプルダウンを配置
            self.add_item(TaskDropdownCombined(options))

    async def add_task_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TaskAddModal())


class TaskDropdownCombined(Select):
    def __init__(self, options):
        super().__init__(placeholder='完了したタスクを選んでプルダウンを閉じる...', min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        selected_number = self.values[0]
        result_msg, category = task_logic.complete_task(selected_number)
        rpg_msg = process_task_completion(category)
        await interaction.response.send_message(f"{result_msg}{rpg_msg}", ephemeral=True)


class KisoAddModal(discord.ui.Modal, title='気になる用語のストック'):
    term = discord.ui.TextInput(label='気になる用語・技術名', placeholder='例: エッジAI, クライアントサイドレンダリング', required=True)
    desc = discord.ui.TextInput(label='簡単なメモ（概要や解説文）', style=discord.TextStyle.paragraph, placeholder='例: 技術の概要、特徴など客観的な文章。', required=True)

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
            msg += "\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 新たな課題（ボス）が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
        elif event == "BOSS_DAMAGE":
            msg += "\n⚔️ **TASK ATTACK!**\nあなたの集中した時間がボスに ダメージを与えた！\n"
        elif event == "BOSS_DEFEATED":
            msg += "\n🎊 **MISSION COMPLETE!!** 🎊\n```fix\n見事に目の前の課題ボスを撃破しました！\n```撃破ボーナスを獲得！次の作業も頑張りましょう。\n"

        if is_up:
            msg += f"\n🎊 レベルアップ！ 各スキルの習得度が出現 Lv.{lv} になりました！"
        
        await interaction.response.send_message(msg, ephemeral=True)


# ====================================================
# 🚀 ボット起動時のシステムイベント
# ====================================================
@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')
    if not xml_news_delivery_task.is_running():
        xml_news_delivery_task.start()
        print("⏰ ニュース自動定期配信タスクを開始しました。")


@client.event
async def on_message(message):
    """テキストコマンド（プレフィックス形式）のハンドリング処理"""
    if message.author == client.user:
        return
        
    content = message.content
    
    if content == '!menu' or content == '！':
        view = MainMenuView()
        await message.channel.send("メニューを選んでください：", view=view)
        
    elif content.startswith('!add '):
        raw_args = content[5:].strip()
        parts = raw_args.split(maxsplit=2)
        
        category = 'programming'
        task_text = raw_args
        deadline = None
        priority = 2  # テキストコマンドはとりあえずデフォルト「中」
        
        if len(parts) >= 2:
            prefix_cat = parts[0]
            if prefix_cat in ['開発', 'programming', 'code', 'p']:
                category = 'programming'
            elif prefix_cat in ['書類', '面接', 'document', 'd']:
                category = 'document'
            elif prefix_cat in ['インプット', '本', '読書', 'reading', 'r']:
                category = 'reading'
                
            if len(parts) == 3 and ('/' in parts[1] or '-' in parts[1]):
                deadline = parts[1]
                task_text = parts[2]
            else:
                task_text = parts[1] if len(parts) == 2 else raw_args

        await message.channel.send(task_logic.add_task(task_text, category, deadline, priority))
        
    elif content == '!list':
        # ⭕ テキスト入力の !list コマンドの時も、リッチなボタン＆プルダウンViewを一緒に表示！
        list_str = task_logic.list_tasks()
        if "現在、登録されたタスクはありません" in list_str:
            await message.channel.send(list_str)
        else:
            view = TaskSelectCombinedView()
            await message.channel.send(list_str, view=view)
        
    elif content.startswith('!done '):
        result_msg, category = task_logic.complete_task(content[6:].strip())
        rpg_msg = process_task_completion(category)
        await message.channel.send(f"{result_msg}{rpg_msg}")
        
    elif content.startswith('!s '):
        await message.channel.send(study_logic.search_glossary(content[3:]))

    # 🧪 デバッグ用の隠しコマンド
    elif content == '!test_reminder':
        await message.channel.send("🧪 [デバッグ] 朝8時の定期処理を強制実行します...")
        
        news_channel = client.get_channel(NEWS_CHANNEL_ID)
        task_channel = client.get_channel(TASK_CHANNEL_ID)
        
        news_msg = news_logic.get_it_news()
        if news_channel:
            await news_channel.send(f"🧪 **【デバッグ配信】**\n{news_msg}")
            
        todo_list = task_logic.load_data()
        reminder_tasks = []
        
        now_jst = datetime.now(JST)
        today_jst = now_jst.date()
        
        for item in todo_list:
            if isinstance(item, dict) and item.get('deadline'):
                try:
                    deadline_date = datetime.strptime(item['deadline'], "%Y-%m-%d").date()
                    days_left = (deadline_date - today_jst).days
                    
                    if 0 <= days_left <= 3:
                        cat_key = item.get('category', 'programming')
                        cat_text = task_logic.CATEGORY_MAP.get(cat_key, '💻 開発')
                        
                        if days_left == 0:
                            reminder_tasks.append(f"🚨 **今日が締切！**: [{cat_text}] {item['task']}")
                        else:
                            reminder_tasks.append(f"⚠️ **あと {days_left} 日**: [{cat_text}] {item['task']}")
                except ValueError:
                    continue
        
        if task_channel and reminder_tasks:
            await task_channel.send(f"🧪 **【デバッグリマインダー】**\n締切が近づいているタスクがあります！\n\n" + "\n".join(reminder_tasks))
        elif task_channel:
            await task_channel.send("🧪 [デバッグ] 3日以内に締切のタスクはありませんでした。")


if __name__ == "__main__":
    client.run(TOKEN)