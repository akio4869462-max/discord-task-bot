import asyncio
import os
from datetime import time, timezone, timedelta, datetime
from dotenv import load_dotenv

# 環境変数の読み込み（calendar_logic等がモジュール読み込み時に環境変数を参照するため、
# 他の自作モジュールをimportするより前に行う必要がある）
load_dotenv()

import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import Button, View, Select

import calendar_logic
import exam_logic
import news_logic
import study_logic
import task_logic
import training_logic

TOKEN = os.getenv('DISCORD_TOKEN')

# Discord クライアントの初期化設定
# ⭕ スラッシュコマンドはDiscordが構造化データとして送ってくるため、
# テキストコマンド時代に必要だった message_content 特権インテントは不要
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

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

# ⭕ 集中タイマーの多重起動防止用：user_id -> 実行中のasyncio.Taskを保持
active_focus_timers = {}


# ====================================================
# ⏰ 定期自動配信・リマインダータスク（バックグラウンド処理）
# ====================================================
def build_deadline_reminders(today_jst):
    """締切が3日以内に迫っているタスクのリマインダー文言一覧を組み立てます。"""
    reminders = []

    for item in task_logic.load_data():
        if not (isinstance(item, dict) and item.get('deadline')):
            continue
        try:
            deadline_date = datetime.strptime(item['deadline'], "%Y-%m-%d").date()
        except ValueError:
            continue

        days_left = (deadline_date - today_jst).days
        if not (0 <= days_left <= 3):
            continue

        cat_text = task_logic.CATEGORY_MAP.get(item.get('category', 'programming'), '💻 開発')
        if days_left == 0:
            reminders.append(f"🚨 **今日が締切！**: [{cat_text}] {item['task']}")
        else:
            reminders.append(f"⚠️ **あと {days_left} 日**: [{cat_text}] {item['task']}")

    return reminders


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
            news_msg = await asyncio.to_thread(news_logic.get_it_news)
            await news_channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")
        else:
            print(f"⚠️ [定期配信] ニュースチャンネルが見つかりませんでした。")

        if task_channel is not None:
            reminder_tasks = build_deadline_reminders(now_jst.date())
            if reminder_tasks:
                reminder_msg = "📢 **【朝のタスクリマインダー】**\n"
                reminder_msg += "締切が近づいているタスクがあります！計画的に攻略していきましょう！\n\n"
                reminder_msg += "\n".join(reminder_tasks)
                await task_channel.send(reminder_msg)
        else:
            print(f"⚠️ [定期配信] タスクリマインダー用のチャンネルが見つかりませんでした。")

        # 💪 今日のトレーニングメニューも配信
        if task_channel is not None:
            image_paths = training_logic.get_today_menu_image_paths()
            if image_paths:
                files = [discord.File(p) for p in image_paths]
                await task_channel.send(training_logic.get_today_menu(), files=files)
            else:
                await task_channel.send(training_logic.get_today_menu())

        # 📅 月曜朝は週間サマリーも配信
        if task_channel is not None and now_jst.weekday() == 0:
            summary_msg = study_logic.get_weekly_summary()
            completed, scheduled = training_logic.get_weekly_training_rate()
            summary_msg += f"\n💪 今週のトレーニング実施率: {completed}/{scheduled}日"
            summary_msg += exam_logic.get_weekly_exam_summary()
            await task_channel.send(summary_msg)

    # 🌃 夜の配信（20:00）
    elif now_jst.hour == 20:
        if news_channel is not None:
            print("⏰ [夜の定期配信] ニュースを取得中...")
            news_msg = await asyncio.to_thread(news_logic.get_it_news)
            await news_channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")


# ====================================================
# 🗃️ 共通ヘルパー関数
# ====================================================
def parse_positive_int(text):
    """モーダルの入力文字列を整数に変換します。全角数字も受け付けます。

    str.isdigit()は「²」のような文字にもTrueを返す一方でint()は失敗するため、
    判定に頼らず実際にint()を試して例外を捕まえる方式にしています。

    Returns:
        int/None: 変換できた整数。数値として解釈できない場合はNone。
    """
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


def build_event_message(result):
    """study_logic.add_exp()の返り値(dict)から、レベルアップ・ボス・連続記録・実績バッジの
    イベント文言を組み立てます。

    ボスへの通常ダメージ（BOSS_DAMAGE）は毎回起きる細かい進捗なので公開告知の対象外とし、
    レベルアップ・ボス出現・ボス撃破・連続記録の節目・実績バッジ獲得という「節目」だけを
    公開告知の対象にします。

    Returns:
        tuple: (detail_msg: 本人向けの詳細文言, public_msg: 公開告知文言 または None)
    """
    detail_msg = ""
    announcements = []

    event = result["event"]
    if event == "BOSS_APPEAR":
        detail_msg += "\n🚨 **WARNING!! WARNING!!** 🚨\n```diff\n- 新たな課題（ボス）が出現しました！\n```ステータスを確認して、撃破を目指してください！\n"
        announcements.append("🚨 新たな課題（ボス）が出現しました！")
    elif event == "BOSS_DAMAGE":
        detail_msg += "\n⚔️ **TASK ATTACK!**\n集中した努力がボスに ダメージを与えた！\n"
    elif event == "BOSS_DEFEATED":
        detail_msg += "\n🎊 **MISSION COMPLETE!!** 🎊\n```fix\n見事に目の前の課題ボスを撃破しました！\n```撃破ボーナスを獲得！次の作業も頑張りましょう。\n"
        announcements.append("🎊 課題ボスを撃破しました！")

    if result["is_level_up"]:
        level = result["new_level"]
        detail_msg += f"\n🎊 レベルアップ！ 各スキルの習得度が出現 Lv.{level} になりました！"
        announcements.append(f"🎊 レベルアップ！ Lv.{level} になりました！")

    streak = result["streak"]
    if streak in study_logic.STREAK_MILESTONES:
        streak_msg = f"🔥 {streak}日連続達成！EXPボーナスが発生しています！"
        detail_msg += f"\n{streak_msg}"
        announcements.append(streak_msg)

    for badge in result["new_badges"]:
        badge_msg = f"🏅 新しい実績を解除: {badge['name']}"
        detail_msg += f"\n{badge_msg}"
        announcements.append(badge_msg)

    public_msg = "\n".join(announcements) if announcements else None
    return detail_msg, public_msg


async def run_focus_timer(channel, user_id, user_mention):
    """集中タイマー本体。指定秒数の経過を待ち、開発カテゴリのEXPとして自動記録します。

    途中でキャンセルされた場合（asyncio.CancelledError）はEXPを記録せず、
    静かに終了します。
    """
    try:
        await asyncio.sleep(FOCUS_TIMER_SECONDS)
    except asyncio.CancelledError:
        return
    finally:
        # 完了・キャンセルいずれの場合も、多重起動防止の管理対象から外す
        active_focus_timers.pop(user_id, None)

    minutes = int(FOCUS_TIMER_SECONDS / 60)
    result = study_logic.add_exp("programming", minutes)
    msg = f"{user_mention} {minutes}分経過しました！お疲れ様でした。☕\n💻 開発作業{minutes}分を自動記録しました！（+{result['earned_exp']} EXP）"

    event_detail, _ = build_event_message(result)
    msg += event_detail

    await channel.send(msg)


def process_task_completion(category):
    """タスク完了時のカテゴリに応じたEXP加算とゲーム内イベント文言の生成処理

    Returns:
        tuple: (detail_msg: 本人向けの詳細文言, public_msg: 公開告知文言 または None)
    """
    if not category:
        return "", None

    result = study_logic.add_exp(category, TASK_COMPLETE_MINUTES)
    cat_name = task_logic.CATEGORY_MAP.get(category, "開発")
    detail_msg = f"\n✨ タスク完了ボーナス獲得！ 【{cat_name}】+ {result['earned_exp']} EXP"

    event_detail, public_msg = build_event_message(result)
    detail_msg += event_detail

    return detail_msg, public_msg


async def try_sync_to_calendar(task_text, category, deadline_str):
    """期限が指定されていれば、Googleカレンダーにも予定を同期します。

    カレンダー連携が未設定の場合や、期限が指定されていない場合は何もしません。
    Google Calendar APIへの通信は同期処理なので、asyncio.to_threadで別スレッド
    実行し、Bot全体がブロックされないようにしています。

    Returns:
        str: 案内文言（登録できなかった場合は空文字）。
    """
    formatted_deadline = task_logic.parse_deadline(deadline_str)
    if not formatted_deadline:
        return ""

    category_name = task_logic.CATEGORY_MAP.get(category, "開発")
    event_link = await asyncio.to_thread(
        calendar_logic.create_deadline_event, task_text, category_name, formatted_deadline
    )
    return "\n📅 Googleカレンダーにも登録しました。" if event_link else ""


# ====================================================
# 🎯 UI コンポーネント（Views / Modals）
# ====================================================

class TaskCategorySelectView(View):
    """タスク追加の1ステップ目：カテゴリをボタンで選ばせるView（typoによる誤登録を防ぐ）"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="💻 開発", style=discord.ButtonStyle.primary)
    async def programming_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TaskAddModal("programming"))

    @discord.ui.button(label="📝 書類・面接", style=discord.ButtonStyle.primary)
    async def document_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TaskAddModal("document"))

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


class FocusTimerView(View):
    """集中タイマー実行中に表示する、キャンセルボタン付きView"""
    def __init__(self, user_id):
        super().__init__(timeout=FOCUS_TIMER_SECONDS + 10)
        self.user_id = user_id

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.danger, emoji="🛑")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        task = active_focus_timers.get(self.user_id)
        if task and not task.done():
            task.cancel()
            active_focus_timers.pop(self.user_id, None)
            self.stop()
            await interaction.response.edit_message(content="⏹️ 集中タイマーをキャンセルしました。", view=None)
        else:
            await interaction.response.send_message("既に終了しているか、キャンセルできるタイマーがありません。", ephemeral=True)


class StudyStatusMenuView(View):
    """「作業・ステータス」サブメニュー：作業記録・集中タイマー・ステータス確認をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)
        p_data = study_logic.load_player_data()
        is_boss_active = p_data.get("is_boss_active", False)
        if is_boss_active:
            self.study_menu.style = discord.ButtonStyle.danger
            self.study_menu.label = "🚨 ボス襲来！作業の記録"
        else:
            self.study_menu.style = discord.ButtonStyle.success
            self.study_menu.label = "📖 作業の記録"

    @discord.ui.button(label="📖 作業の記録", style=discord.ButtonStyle.success, row=0)
    async def study_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WorkReportView()
        await interaction.response.send_message("作業内容：カテゴリを選んでください", view=view, ephemeral=True)

    @discord.ui.button(label="集中タイマー", style=discord.ButtonStyle.secondary, emoji="⏱️", row=0)
    async def timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        existing_task = active_focus_timers.get(user_id)
        if existing_task and not existing_task.done():
            await interaction.response.send_message("既に集中タイマーが進行中です。先に完了かキャンセルをしてください。", ephemeral=True)
            return

        # ⭕ Discordのタイムスタンプ書式(<t:...:R>)を使うと、Bot側で何もしなくても
        # クライアント側で「あと24分」のように自動でリアルタイム更新される
        end_ts = int((discord.utils.utcnow() + timedelta(seconds=FOCUS_TIMER_SECONDS)).timestamp())
        view = FocusTimerView(user_id)
        await interaction.response.send_message(
            f"⏱️ 集中タイムを開始します！開発（programming）の経験値に連動します。\n"
            f"終了予定: <t:{end_ts}:R>（<t:{end_ts}:t>）",
            view=view,
            ephemeral=True
        )

        task = asyncio.create_task(run_focus_timer(interaction.channel, user_id, interaction.user.mention))
        active_focus_timers[user_id] = task

    @discord.ui.button(label="⚔️ ステータス", style=discord.ButtonStyle.danger, row=0)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        status_msg = study_logic.get_status_summary()
        embed = discord.Embed(title=f"🛡️ {interaction.user.display_name} の冒険 of 就活攻略RPG", color=0xffd700)
        embed.description = status_msg
        await interaction.response.send_message(embed=embed, ephemeral=True)


class GlossaryMenuView(View):
    """「学習・用語」サブメニュー：用語検索・ストック・一覧・クイズをまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="🔍 用語検索", style=discord.ButtonStyle.secondary, row=0)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchWordModal())

    @discord.ui.button(label="➕ 用語ストック", style=discord.ButtonStyle.secondary, row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KisoAddModal())

    @discord.ui.button(label="📚 用語一覧", style=discord.ButtonStyle.secondary, row=0)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        list_msg = study_logic.get_glossary_list()
        await interaction.response.send_message(list_msg, ephemeral=True)

    @discord.ui.button(label="🎲 用語クイズ", style=discord.ButtonStyle.secondary, row=0)
    async def quiz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        quiz_msg = study_logic.get_kiso_quiz()
        await interaction.response.send_message(quiz_msg, ephemeral=True)


class ExamMenuView(View):
    """「資格学習」サブメニュー：過去問演習の記録・成績確認をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="📝 演習を記録", style=discord.ButtonStyle.primary, row=0)
    async def log_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "演習した分野を選んでください：", view=ExamFieldSelectView(), ephemeral=True
        )

    @discord.ui.button(label="📊 演習成績", style=discord.ButtonStyle.secondary, row=0)
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(exam_logic.get_stats_summary(), ephemeral=True)


class ExamFieldSelectView(View):
    """演習記録の1ステップ目：分野をプルダウンで選ばせるView

    分野は6つあり、ボタンだと横幅を圧迫するためセレクトメニューを採用している。
    """
    def __init__(self):
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label=display_name[:100], value=field_id)
            for field_id, display_name in exam_logic.EXAM_FIELDS.items()
        ]
        self.add_item(ExamFieldDropdown(options))


class ExamFieldDropdown(Select):
    def __init__(self, options):
        super().__init__(placeholder='演習した分野を選択...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # 選んだ分野を引き継いで、問題数・正解数の入力モーダルを開く
        await interaction.response.send_modal(ExamLogModal(self.values[0]))


class ExamLogModal(discord.ui.Modal, title='📝 過去問演習の記録'):
    """分野選択後にポップアップする、問題数・正解数の入力モーダル"""
    total_input = discord.ui.TextInput(
        label='解いた問題数',
        placeholder='例: 20 （半角数字）',
        required=True,
        max_length=4,
    )
    correct_input = discord.ui.TextInput(
        label='正解した問題数',
        placeholder='例: 13 （半角数字）',
        required=True,
        max_length=4,
    )

    def __init__(self, field):
        super().__init__()
        self.field = field

    async def on_submit(self, interaction: discord.Interaction):
        total = parse_positive_int(self.total_input.value)
        correct = parse_positive_int(self.correct_input.value)
        if total is None or correct is None:
            await interaction.response.send_message("問題数・正解数は数字で入力してください！", ephemeral=True)
            return

        msg = exam_logic.log_session(self.field, total, correct)
        await interaction.response.send_message(msg, ephemeral=True)


class UtilityMenuView(View):
    """「その他」サブメニュー：データ出力・ニュース確認をまとめたView"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="💾 データ出力", style=discord.ButtonStyle.secondary, row=0)
    async def backup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        files = [os.path.join('data', f) for f in ('todo.json', 'player_data.json', 'glossary.json')]
        found_files = [discord.File(f) for f in files if os.path.exists(f)]
        if found_files:
            await interaction.response.send_message("現在のバックアップデータです：", files=found_files, ephemeral=True)
        else:
            await interaction.response.send_message("バックアップ対象のファイルが見つかりませんでした。", ephemeral=True)

    @discord.ui.button(label="📰 最新ITニュースを確認", style=discord.ButtonStyle.primary, row=0)
    async def news_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        news_msg = await asyncio.to_thread(news_logic.get_it_news)
        await interaction.followup.send(news_msg, ephemeral=True)


class MainMenuView(View):
    """ボットのコア機能を4つのカテゴリに整理したメインメニューを制御するViewクラス"""
    def __init__(self):
        super().__init__(timeout=None)
        p_data = study_logic.load_player_data()
        is_boss_active = p_data.get("is_boss_active", False)
        if is_boss_active:
            self.study_status_menu.style = discord.ButtonStyle.danger
            self.study_status_menu.label = "🚨 ボス襲来！作業・ステータス"
        else:
            self.study_status_menu.style = discord.ButtonStyle.success
            self.study_status_menu.label = "📖 作業・ステータス"

    @discord.ui.button(label="📋 タスク管理メニュー", style=discord.ButtonStyle.primary, row=0)
    async def task_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        list_str = task_logic.list_tasks()
        view = TaskSelectCombinedView()
        await interaction.response.send_message(list_str, view=view, ephemeral=True)

    @discord.ui.button(label="📖 作業・ステータス", style=discord.ButtonStyle.success, row=0)
    async def study_status_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=StudyStatusMenuView(), ephemeral=True)

    @discord.ui.button(label="📚 学習・用語", style=discord.ButtonStyle.secondary, row=0)
    async def glossary_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=GlossaryMenuView(), ephemeral=True)

    @discord.ui.button(label="📝 資格学習", style=discord.ButtonStyle.primary, row=1)
    async def exam_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=ExamMenuView(), ephemeral=True)

    @discord.ui.button(label="🛠️ その他", style=discord.ButtonStyle.secondary, row=1)
    async def utility_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=UtilityMenuView(), ephemeral=True)


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
        minutes = parse_positive_int(self.count_input.value)
        if minutes is None or minutes <= 0:
            await interaction.response.send_message("作業時間は1以上の数字（分）で入力してください！", ephemeral=True)
            return

        result = study_logic.add_exp(self.cat_id, minutes)
        msg = f"✅ {self.cat_name}の作業（{minutes}分間）を記録しました！\n+{result['earned_exp']} EXP 獲得！"

        event_detail, public_msg = build_event_message(result)
        msg += event_detail

        await interaction.response.send_message(msg, ephemeral=True)
        # レベルアップ・ボス出現/撃破など節目のイベントはチャンネルにも告知する
        if public_msg:
            await interaction.channel.send(f"{interaction.user.mention} {public_msg}")


# ====================================================
# 🚀 ボット起動時のシステムイベント
# ====================================================
@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')
    await tree.sync()
    print("✅ スラッシュコマンドを同期しました。")
    if not xml_news_delivery_task.is_running():
        xml_news_delivery_task.start()
        print("⏰ ニュース自動定期配信タスクを開始しました。")


# ====================================================
# 🔤 スラッシュコマンド
# ====================================================
@tree.command(name="menu", description="操作メニューを表示します")
async def menu_command(interaction: discord.Interaction):
    view = MainMenuView()
    await interaction.response.send_message("メニューを選んでください：", view=view)


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
        app_commands.Choice(name="📝 書類・面接", value="document"),
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


@tree.command(name="search", description="ストックした用語を検索します")
@app_commands.describe(keyword="検索したいキーワード")
async def search_command(interaction: discord.Interaction, keyword: str):
    await interaction.response.send_message(study_logic.search_glossary(keyword), ephemeral=True)


# ====================================================
# 💪 トレーニング記録コマンド群（/training menu, log, measure, history）
# ====================================================
training_group = app_commands.Group(name="training", description="自宅ダンベルトレーニングの記録")


@training_group.command(name="menu", description="今日のトレーニングメニューを表示します")
async def training_menu_command(interaction: discord.Interaction):
    image_paths = training_logic.get_today_menu_image_paths()
    if image_paths:
        files = [discord.File(p) for p in image_paths]
        await interaction.response.send_message(training_logic.get_today_menu(), files=files, ephemeral=True)
    else:
        await interaction.response.send_message(training_logic.get_today_menu(), ephemeral=True)


@training_group.command(name="log", description="今日のトレーニングを完了として記録します")
@app_commands.describe(note="メモ（任意）")
async def training_log_command(interaction: discord.Interaction, note: str = None):
    msg, streak = training_logic.log_session(note)
    await interaction.response.send_message(msg, ephemeral=True)

    # 連続記録の節目だけチャンネルにも告知する
    if streak in training_logic.TRAINING_STREAK_MILESTONES:
        await interaction.channel.send(f"{interaction.user.mention} 🔥 トレーニング{streak}日連続達成！素晴らしいです！")


@training_group.command(name="measure", description="体重・お腹周りを記録します")
@app_commands.describe(weight_kg="体重(kg)", waist_cm="お腹周り(cm)")
async def training_measure_command(interaction: discord.Interaction, weight_kg: float, waist_cm: float):
    await interaction.response.send_message(training_logic.log_measurement(weight_kg, waist_cm), ephemeral=True)


@training_group.command(name="history", description="体組成の記録一覧を表示します")
async def training_history_command(interaction: discord.Interaction):
    await interaction.response.send_message(training_logic.get_measurement_history(), ephemeral=True)


tree.add_command(training_group)


# ====================================================
# 📝 応用情報 演習記録コマンド群（/exam log, stats）
# ====================================================
exam_group = app_commands.Group(name="exam", description="応用情報技術者試験の過去問演習の記録")

# 分野の選択肢はexam_logic側の定義から生成し、二重管理を避ける
EXAM_FIELD_CHOICES = [
    app_commands.Choice(name=display_name, value=field_id)
    for field_id, display_name in exam_logic.EXAM_FIELDS.items()
]


@exam_group.command(name="log", description="過去問演習の結果を記録します")
@app_commands.describe(field="演習した分野", total="解いた問題数", correct="正解した問題数")
@app_commands.choices(field=EXAM_FIELD_CHOICES)
async def exam_log_command(
    interaction: discord.Interaction,
    field: app_commands.Choice[str],
    total: int,
    correct: int,
):
    msg = exam_logic.log_session(field.value, total, correct)
    await interaction.response.send_message(msg, ephemeral=True)


@exam_group.command(name="stats", description="分野別の演習成績・弱点分野を表示します")
async def exam_stats_command(interaction: discord.Interaction):
    await interaction.response.send_message(exam_logic.get_stats_summary(), ephemeral=True)


tree.add_command(exam_group)


# 🧪 デバッグ用コマンド
@tree.command(name="test_reminder", description="[デバッグ]朝8時の定期処理を強制実行します")
async def test_reminder_command(interaction: discord.Interaction):
    await interaction.response.send_message("🧪 [デバッグ] 朝8時の定期処理を強制実行します...", ephemeral=True)

    news_channel = client.get_channel(NEWS_CHANNEL_ID)
    task_channel = client.get_channel(TASK_CHANNEL_ID)

    news_msg = await asyncio.to_thread(news_logic.get_it_news)
    if news_channel:
        await news_channel.send(f"🧪 **【デバッグ配信】**\n{news_msg}")

    reminder_tasks = build_deadline_reminders(datetime.now(JST).date())
    if task_channel and reminder_tasks:
        await task_channel.send(f"🧪 **【デバッグリマインダー】**\n締切が近づいているタスクがあります！\n\n" + "\n".join(reminder_tasks))
    elif task_channel:
        await task_channel.send("🧪 [デバッグ] 3日以内に締切のタスクはありませんでした。")

    if task_channel:
        await task_channel.send(f"🧪 **【デバッグ】今日のトレーニングメニュー**\n{training_logic.get_today_menu()}")

    # 曜日に関わらず、週間サマリーもテスト発火できるようにする
    if task_channel:
        summary_msg = study_logic.get_weekly_summary()
        completed, scheduled = training_logic.get_weekly_training_rate()
        summary_msg += f"\n💪 今週のトレーニング実施率: {completed}/{scheduled}日"
        summary_msg += exam_logic.get_weekly_exam_summary()
        await task_channel.send(f"🧪 **【デバッグ】週間サマリーのテスト配信**\n{summary_msg}")


if __name__ == "__main__":
    client.run(TOKEN)