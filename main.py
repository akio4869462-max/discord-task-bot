import asyncio
from datetime import datetime
from dotenv import load_dotenv

# 環境変数の読み込み（calendar_logic等がモジュール読み込み時に環境変数を参照するため、
# 他の自作モジュールをimportするより前に行う必要がある）
load_dotenv()

import discord
from discord.ext import tasks
from discord.ui import View

import exam_logic
import horse_logic
import news_logic
import task_logic
import training_logic
import typing_logic

# ⭕ bot_stateがclient/treeを保持する。以降のui_*.pyはこれをimportして
# 同じclient/treeにコマンドやイベントを登録する（循環importを避けるための構成）。
from race_sim import calendar as race_calendar
from bot_state import client, tree, getenv_int, TOKEN, JST, DELIVERY_TIMES, NEWS_CHANNEL_ID, TASK_CHANNEL_ID

# ui_common の関数は tests/test_main.py から main.X として参照され続けるため、
# ここで再エクスポートする（実体はui_common.py側にある）。
from ui_common import (
    parse_positive_int, parse_float, build_growth_message,
    process_task_completion, process_exam_completion, process_session, try_sync_to_calendar,
)

# ⭕ 各ui_*.pyをimportすることで、モジュールレベルの @tree.command 等が実行され、
# 共有のtreeへコマンドが登録される。MainMenuViewが参照するサブメニューViewも
# ここから取り込む。
import ui_task
import ui_horse
import ui_news
import ui_exam
import ui_training
import ui_typing
import ui_utility
from ui_task import TaskSelectCombinedView
from ui_horse import StableMenuView, run_pending_race
from ui_news import NewsTermsMenuView
from ui_exam import ExamMenuView
from ui_training import TrainingMenuView, DailyLogView, send_training_notification
from ui_typing import TypingMenuView, TypingLogView, send_typing_notification
from ui_utility import UtilityMenuView, weekly_backup_task


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
            await send_training_notification(task_channel)

        # 🏁 開催日の朝は、出走登録の有無を知らせる
        # ⭕ レース自体は20:00に自動で走るので、ここは「登録し忘れに気づく」ためだけにある。
        if task_channel is not None:
            notice = horse_logic.format_race_day_notice(today=now_jst.date())
            if notice:
                await task_channel.send(notice)

        # 📅 月曜朝は週間サマリーも配信
        if task_channel is not None and now_jst.weekday() == 0:
            summary_msg = horse_logic.get_weekly_summary()
            completed, scheduled = training_logic.get_weekly_training_rate()
            summary_msg += f"\n💪 今週のトレーニング実施率: {completed}/{scheduled}日"
            summary_msg += exam_logic.get_weekly_exam_summary()
            summary_msg += typing_logic.get_weekly_typing_summary()
            await task_channel.send(summary_msg)

    # 🌃 夜の配信（20:00）
    elif now_jst.hour == 20:
        if news_channel is not None:
            print("⏰ [夜の定期配信] ニュースを取得中...")
            news_msg = await asyncio.to_thread(news_logic.get_it_news)
            await news_channel.send(f"⏰ **【定期ニュース配信】**\n{news_msg}")

        # ⌨️ タイピング訓練の日次メニューを配信
        if task_channel is not None:
            await send_typing_notification(task_channel)

        # 🏁 開催日（土曜・水曜）は登録してあるレースを実行する
        # ⭕ 定期配信のループは1つだけ、という既存のルールを守り、夜の分岐に相乗りする。
        if task_channel is not None and race_calendar.is_race_day(now_jst.date()):
            ran = await run_pending_race(task_channel)
            if not ran:
                print("⏰ [開催日] 出走登録がありませんでした。")


# ====================================================
# 🎯 メインメニュー
# ====================================================
class MainMenuView(View):
    """ボットのコア機能を6つのカテゴリに整理したメインメニューを制御するViewクラス

    各サブメニューの実体はui_*.pyに分割されており、ここではそれらを束ねるだけ。
    """
    def __init__(self):
        super().__init__(timeout=None)
        # ⭕ 出走を控えているときはボタンで分かるようにする（旧RPGのボス襲来表示の後継）。
        data = horse_logic.load_stable()
        if data['current'].get('entry'):
            self.stable_menu.style = discord.ButtonStyle.danger
            self.stable_menu.label = "🏁 出走間近！厩舎"
        else:
            self.stable_menu.style = discord.ButtonStyle.success
            self.stable_menu.label = "🐎 厩舎・調教"

    @discord.ui.button(label="📋 タスク管理メニュー", style=discord.ButtonStyle.primary, row=0)
    async def task_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        list_str = task_logic.list_tasks()
        view = TaskSelectCombinedView()
        await interaction.response.send_message(list_str, view=view, ephemeral=True)

    @discord.ui.button(label="🐎 厩舎・調教", style=discord.ButtonStyle.success, row=0)
    async def stable_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=StableMenuView(), ephemeral=True)

    @discord.ui.button(label="📰 ニュース用語", style=discord.ButtonStyle.secondary, row=0)
    async def news_terms_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=NewsTermsMenuView(), ephemeral=True)

    @discord.ui.button(label="📝 資格学習", style=discord.ButtonStyle.primary, row=1)
    async def exam_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=ExamMenuView(), ephemeral=True)

    @discord.ui.button(label="⌨️ タイピング", style=discord.ButtonStyle.primary, row=1)
    async def typing_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=TypingMenuView(), ephemeral=True)

    @discord.ui.button(label="🏋️ トレーニング", style=discord.ButtonStyle.primary, row=1)
    async def training_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=TrainingMenuView(), ephemeral=True)

    @discord.ui.button(label="🛠️ その他", style=discord.ButtonStyle.secondary, row=1)
    async def utility_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("メニューを選んでください：", view=UtilityMenuView(), ephemeral=True)


# ====================================================
# 🚀 ボット起動時のシステムイベント
# ====================================================
@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')

    # timeout=Noneのボタンは、再起動後も過去の通知上で動くよう明示的に登録し直す必要がある
    client.add_view(DailyLogView())
    client.add_view(TypingLogView())

    await tree.sync()
    print("✅ スラッシュコマンドを同期しました。")
    if not xml_news_delivery_task.is_running():
        xml_news_delivery_task.start()
        print("⏰ ニュース自動定期配信タスクを開始しました。")
    if not weekly_backup_task.is_running():
        weekly_backup_task.start()
        print("🗄️ 週次バックアップタスクを開始しました。")


# ====================================================
# 🔤 スラッシュコマンド（メニュー・デバッグ用）
# ====================================================
@tree.command(name="menu", description="操作メニューを表示します")
async def menu_command(interaction: discord.Interaction):
    view = MainMenuView()
    await interaction.response.send_message("メニューを選んでください：", view=view)


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
        await send_training_notification(task_channel)

    # 🏁 開催日かどうかに関わらず、開催日の告知もテスト発火できるようにする
    if task_channel:
        notice = horse_logic.format_race_day_notice(
            today=race_calendar.next_race_day(datetime.now(JST).date()))
        await task_channel.send(f"🧪 **【デバッグ】開催日の朝の告知**\n{notice}")

    # 曜日に関わらず、週間サマリーもテスト発火できるようにする
    if task_channel:
        summary_msg = horse_logic.get_weekly_summary()
        completed, scheduled = training_logic.get_weekly_training_rate()
        summary_msg += f"\n💪 今週のトレーニング実施率: {completed}/{scheduled}日"
        summary_msg += exam_logic.get_weekly_exam_summary()
        summary_msg += typing_logic.get_weekly_typing_summary()
        await task_channel.send(f"🧪 **【デバッグ】週間サマリーのテスト配信**\n{summary_msg}")


@tree.command(name="test_typing_notify", description="[デバッグ]夜20時のタイピング訓練通知を強制実行します")
async def test_typing_notify_command(interaction: discord.Interaction):
    await interaction.response.send_message("🧪 [デバッグ] 夜20時のタイピング通知を強制実行します...", ephemeral=True)

    task_channel = client.get_channel(TASK_CHANNEL_ID)
    if task_channel:
        await send_typing_notification(task_channel)


if __name__ == "__main__":
    client.run(TOKEN)
