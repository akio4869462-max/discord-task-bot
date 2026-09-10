"""厩舎（調教の記録・ステータス・出走登録・レース結果）まわりのView/Modal

⭕ 旧・就活RPGの「作業・ステータス」を置き換えたもの。作業報告はそのまま残っていて、
   加算される先がEXPから馬の能力に変わっている。
"""

import asyncio
import os
import tempfile

import discord
from discord import app_commands
from discord.ui import View, Select

import horse_logic
from bot_state import FOCUS_TIMER_SECONDS, active_focus_timers, tree
from race_sim.tools import make_viewer
from ui_common import parse_positive_int, build_growth_message

# 作業報告のカテゴリ。表示名と、育つ能力の説明。
WORK_CATEGORIES = [
    ('programming', '💻 開発作業', 'スピード'),
    ('document', '📄 書類作成', '根性'),
    ('reading', '📚 インプット', '賢さ'),
]


# ====================================================
# 集中タイマー
# ====================================================
async def run_focus_timer(channel, user_id, user_mention):
    """集中タイマー本体。指定秒数の経過を待ち、開発カテゴリの調教として自動記録します。

    途中でキャンセルされた場合（asyncio.CancelledError）は記録せず、静かに終了します。
    """
    try:
        await asyncio.sleep(FOCUS_TIMER_SECONDS)
    except asyncio.CancelledError:
        return
    finally:
        active_focus_timers.pop(user_id, None)

    minutes = int(FOCUS_TIMER_SECONDS / 60)
    result = horse_logic.add_growth('programming', minutes)
    msg = (f"{user_mention} {minutes}分経過しました！お疲れ様でした。☕\n"
           f"💻 開発作業{minutes}分を調教として記録しました。")

    detail, _ = build_growth_message(result)
    await channel.send(msg + detail)


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


# ====================================================
# 厩舎メニュー
# ====================================================
class StableMenuView(View):
    """厩舎のサブメニュー。調教の記録・ステータス・出走登録をまとめる。"""

    def __init__(self):
        super().__init__(timeout=120)
        data = horse_logic.load_stable()
        if data['current'].get('entry'):
            self.race_btn.label = "🏁 出走登録済み"
            self.race_btn.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="📖 調教を記録", style=discord.ButtonStyle.success, row=0)
    async def work_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "どの調教を記録しますか？", view=WorkReportView(), ephemeral=True)

    @discord.ui.button(label="⏱️ 集中タイマー", style=discord.ButtonStyle.primary, row=0)
    async def timer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id in active_focus_timers:
            await interaction.response.send_message("既にタイマーが動いています。", ephemeral=True)
            return
        minutes = int(FOCUS_TIMER_SECONDS / 60)
        view = FocusTimerView(user_id)
        await interaction.response.send_message(
            f"⏱️ {minutes}分の集中タイマーを開始しました。終わったら開発の調教として記録します。",
            view=view, ephemeral=True)
        active_focus_timers[user_id] = asyncio.create_task(
            run_focus_timer(interaction.channel, user_id, interaction.user.mention))

    @discord.ui.button(label="🐎 厩舎", style=discord.ButtonStyle.success, row=0)
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(horse_logic.format_horse(), ephemeral=True)

    @discord.ui.button(label="🏁 出走登録", style=discord.ButtonStyle.primary, row=1)
    async def race_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_race_entry(interaction)

    @discord.ui.button(label="📜 戦績", style=discord.ButtonStyle.secondary, row=1)
    async def history_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(format_history(), ephemeral=True)


# ====================================================
# 調教の記録
# ====================================================
class WorkReportView(View):
    """調教のカテゴリを選ぶView。⭕ モーダルにはTextInputしか置けないので、
    カテゴリ選択は前段のボタンで済ませる。"""

    def __init__(self):
        super().__init__(timeout=60)
        for cat_id, label, param in WORK_CATEGORIES:
            self.add_item(WorkCategoryButton(cat_id, label, param))


class WorkCategoryButton(discord.ui.Button):
    def __init__(self, cat_id, label, param):
        super().__init__(label=f"{label}（{param}）", style=discord.ButtonStyle.primary)
        self.cat_id = cat_id
        self.cat_label = label

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(WorkReportModal(self.cat_id, self.cat_label))


class WorkReportModal(discord.ui.Modal):
    def __init__(self, cat_id, cat_name):
        super().__init__(title=f"{cat_name}の記録")
        self.cat_id = cat_id
        self.cat_name = cat_name
        self.minutes_input = discord.ui.TextInput(
            label="調教した時間（分）", placeholder="例: 60", required=True, max_length=4)
        self.add_item(self.minutes_input)

    async def on_submit(self, interaction: discord.Interaction):
        minutes = parse_positive_int(self.minutes_input.value)
        if minutes is None or minutes <= 0:
            await interaction.response.send_message("⚠️ 分数は正の数字で入力してください。", ephemeral=True)
            return

        result = horse_logic.add_growth(self.cat_id, minutes)
        detail, public = build_growth_message(result)
        horse = result['horse']
        msg = f"✅ {self.cat_name} {minutes}分を記録しました。（{horse['name']}）{detail}"
        await interaction.response.send_message(msg, ephemeral=True)
        if public:
            await interaction.channel.send(f"📣 {interaction.user.mention} {public}")


# ====================================================
# 出走登録
# ====================================================
async def show_race_entry(interaction):
    """出走できるレースを提示します。登録済みならその内容と取り消しを出します。"""
    data = horse_logic.load_stable()
    horse = data['current']

    if horse.get('entry'):
        e = horse['entry']
        text = (f"📋 **出走登録済み**\n{e['date']} **{e['name']}**\n"
                f"{e['course']}{e['surface']}{e['distance']}m {e['cond']} ／ 脚質 {horse['style']}")
        await interaction.response.send_message(text, view=CancelEntryView(), ephemeral=True)
        return

    day, races = horse_logic.available_races(data)
    if not races:
        await interaction.response.send_message(
            f"{day.isoformat()} に{horse['class']}クラスで出走できるレースがありませんでした。",
            ephemeral=True)
        return

    await interaction.response.send_message(
        horse_logic.format_races(day, races) + "\n\n出走するレースを選んでください。",
        view=RaceSelectView(races), ephemeral=True)


class RaceSelectView(View):
    def __init__(self, races):
        super().__init__(timeout=180)
        self.add_item(RaceDropdown(races))


class RaceDropdown(Select):
    def __init__(self, races):
        self.races = {r['id']: r for r in races}
        options = [
            discord.SelectOption(
                label=f"{r['name']}"[:100],
                value=r['id'],
                description=f"{r['course']}{r['surface']}{r['distance']}m {r['cond']}"
                            f" ／ 1着{r['prize']:,}万円"[:100])
            for r in races
        ]
        super().__init__(placeholder="出走するレースを選択", options=options)

    async def callback(self, interaction: discord.Interaction):
        race = self.races[self.values[0]]
        await interaction.response.edit_message(
            content=f"**{race['name']}**（{race['course']}{race['surface']}{race['distance']}m"
                    f" {race['cond']}）\n脚質を宣言してください。",
            view=StyleSelectView(race))


class StyleSelectView(View):
    """脚質を宣言するView。

    ⭕ 宣言は「意思」であって確約ではない。出走メンバー内で位置取りを競うので、
       行きたい馬が揃えば前を取れないことがある（およそ8割は宣言どおりになる）。
    """

    def __init__(self, race):
        super().__init__(timeout=180)
        for style in ('逃げ', '先行', '差し', '追込'):
            self.add_item(StyleButton(race, style))


class StyleButton(discord.ui.Button):
    def __init__(self, race, style):
        super().__init__(label=style, style=discord.ButtonStyle.primary)
        self.race = race
        self.style_name = style

    async def callback(self, interaction: discord.Interaction):
        horse_logic.enter_race(self.race, style=self.style_name)
        r = self.race
        await interaction.response.edit_message(
            content=(f"✅ **{r['name']}** に出走登録しました。\n"
                     f"{r['date']} {r['course']}{r['surface']}{r['distance']}m {r['cond']}"
                     f" ／ 脚質 **{self.style_name}**（宣言どおりになるとは限りません）"),
            view=None)


class CancelEntryView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="出走を取り消す", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        horse_logic.cancel_entry()
        await interaction.response.edit_message(content="🚫 出走登録を取り消しました。", view=None)


# ====================================================
# レースの実行と結果
# ====================================================
def build_replay_file(result):
    """レース結果を埋め込んだ再生用HTMLを作り、Discordに添付できる形で返します。

    ⭕ 再生ビューアは外部ライブラリを使わない1枚のHTMLなので、そのまま添付すれば
       受け取った側はブラウザで開くだけで見られる。
    """
    html = make_viewer.render(result)
    fd, path = tempfile.mkstemp(suffix='.html', prefix='race_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(html)
    name = f"{result['race'].get('name', 'race')}.html"
    return path, name


async def post_race_result(channel, outcome, mention=None):
    """レース結果をチャンネルへ投稿し、再生用HTMLを添付します。

    ⭕ 添付にはファイル添付の権限が要る。権限が無いときに全体が落ちると、レース結果
       そのものが失われてしまうので、そのときはテキストだけでも必ず投稿する。
    """
    text = horse_logic.format_result(outcome)
    if mention:
        text = f"{mention}\n{text}"

    path, name = await asyncio.to_thread(build_replay_file, outcome['result'])
    try:
        await channel.send(text, file=discord.File(path, filename=name))
    except discord.Forbidden:
        await channel.send(text + "\n（再生用HTMLを添付できませんでした。"
                                  "Botに「ファイルを添付」の権限がありません）")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def run_pending_race(channel, mention=None):
    """登録されているレースを実行して結果を投稿します。

    Returns:
        bool: 実行したらTrue、登録が無ければFalse。
    """
    outcome = await asyncio.to_thread(horse_logic.run_entry)
    if outcome is None:
        return False
    await post_race_result(channel, outcome, mention)
    return True


def format_history(limit=10):
    """現役馬の戦績を整形します。"""
    data = horse_logic.load_stable()
    horse = data['current']
    history = horse.get('history', [])
    if not history:
        return f"{horse['name']} はまだ出走していません。"

    lines = [f"📜 **{horse['name']} の戦績**（{len(history)}戦）"]
    for h in history[-limit:]:
        lines.append(f"{h['date']} {h['race']} {h['course']}{h['surface']}{h['distance']}m"
                     f" {h['cond']} → **{h['finish']}着**/{h['field']}頭"
                     f"（{h['time']:.1f}秒 上がり{h['last3f']:.1f} {h['style']}）")

    retired = data.get('retired', [])
    if retired:
        lines.append("")
        lines.append("🏇 **引退馬**")
        for r in retired[-5:]:
            rec = r['record']
            lines.append(f"・{r['name']}（{r['class']}）{rec['starts']}戦{rec['win']}勝"
                         f" 獲得{rec['prize']:,}万円")
    return '\n'.join(lines)


# ====================================================
# スラッシュコマンド
# ====================================================
@tree.command(name="stable", description="厩舎の状態を表示します")
async def stable_command(interaction: discord.Interaction):
    await interaction.response.send_message(horse_logic.format_horse(), ephemeral=True)


@tree.command(name="entry", description="次のレースへの出走を登録します")
async def entry_command(interaction: discord.Interaction):
    await show_race_entry(interaction)


@tree.command(name="test_race", description="[デバッグ]登録中のレースを今すぐ実行します")
async def test_race_command(interaction: discord.Interaction):
    # ⭕ レース実行とHTML生成に時間がかかるので、3秒制限に触れないよう先にdeferする。
    await interaction.response.defer(ephemeral=True)
    ran = await run_pending_race(interaction.channel, interaction.user.mention)
    if ran:
        await interaction.followup.send("🧪 [デバッグ] レースを実行しました。", ephemeral=True)
    else:
        await interaction.followup.send(
            "出走登録がありません。先に「🏁 出走登録」から登録してください。", ephemeral=True)
