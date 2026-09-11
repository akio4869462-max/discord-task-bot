"""厩舎（調教の記録・ステータス・出走登録・レース結果）まわりのView/Modal

⭕ 旧・就活RPGの「作業・ステータス」を置き換えたもの。作業報告はそのまま残っていて、
   加算される先がEXPから馬の能力に変わっている。
"""

import asyncio
import os
import re
import tempfile
from datetime import date, datetime, time as dtime, timedelta, timezone

import discord
from discord import app_commands
from discord.ui import View, Select

import horse_logic
import training_logic
import typing_logic
from bot_state import FOCUS_TIMER_SECONDS, JST, active_focus_timers, tree
from race_sim.tools import make_viewer
from ui_common import parse_positive_int, build_growth_message

# 作業報告のカテゴリ。表示名と、育つ能力の説明。
WORK_CATEGORIES = [
    ('programming', '💻 開発作業', 'スピード'),
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
        horse = data['current']
        if horse.get('entry'):
            self.race_btn.label = "🏁 出走登録済み"
            self.race_btn.style = discord.ButtonStyle.secondary
        # ⭕ 多頭のときは、どの馬を見ているかを常に出す。切替はセレクト（行3）
        if len(data['horses']) > 1:
            self.status_btn.label = f"🐎 {horse['name']}"[:80]
            self.add_item(HorseSelect(data))
        if not horse_logic.is_main(data, horse) and len(data['horses']) > 1:
            self.main_btn.disabled = False

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

    @discord.ui.button(label="⏪ あとから記録", style=discord.ButtonStyle.secondary, row=1)
    async def backfill_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "記録し忘れたぶんを、日付を指定して足せます。", view=BackfillView(), ephemeral=True)

    @discord.ui.button(label="🧬 配合", style=discord.ButtonStyle.secondary, row=2)
    async def breed_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_breeding(interaction)

    @discord.ui.button(label="⭐ 主戦にする", style=discord.ButtonStyle.secondary, row=2, disabled=True)
    async def main_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = horse_logic.load_stable()
        horse_logic.set_main(data, data['current']['id'])
        await interaction.response.send_message(
            f"⭐ **{data['current']['name']}** を主戦にしました。これからの記録は全部この馬に入ります"
            f"（他の馬には{int(horse_logic.SUB_SHARE * 100)}%）。", ephemeral=True)

    @discord.ui.button(label="🐴 セリ", style=discord.ButtonStyle.secondary, row=2)
    async def auction_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_auction(interaction)

    @discord.ui.button(label="🎯 今週の重点", style=discord.ButtonStyle.secondary, row=2)
    async def focus_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = horse_logic.load_stable()
        current = horse_logic.focus_param(data)
        head = (f"今週の重点: **{horse_logic.PARAM_NAMES[current]}**" if current else "今週の重点はまだ決めていません。")
        await interaction.response.send_message(
            head + f"\n重点にした能力へ、記録の配分の {int(horse_logic.FOCUS_SHIFT * 100)}% ぶんを寄せます（総量は変わりません）。",
            view=FocusView(), ephemeral=True)


# ====================================================
# 馬の切替
# ====================================================
class HorseSelect(Select):
    """厩舎メニューで見る馬を切り替える。ステータス・出走登録・配合はここで選んだ馬に対して行う。"""
    def __init__(self, data):
        options = []
        for h in data['horses']:
            role = '主戦' if horse_logic.is_main(data, h) else '併せ馬'
            options.append(discord.SelectOption(
                label=f"{h['name']}（{h['class']}・{role}）"[:100], value=h['id'],
                description=(f"{h['record']['starts']}戦{h['record']['win']}勝"
                             + (f" ／ 📋{h['entry']['name']}" if h.get('entry') else ''))[:100],
                default=(h['id'] == data['selected'])))
        super().__init__(placeholder="見る馬を切り替え", options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        data = horse_logic.load_stable()
        horse = horse_logic.select_horse(data, self.values[0])
        await interaction.response.edit_message(
            content=f"🐎 **{horse['name']}** を選びました。", view=StableMenuView())


# ====================================================
# セリ
# ====================================================
# ⭕ 仔馬を買って厩舎を増やす（最大3頭）。「セレクト → 確認 → 名前のモーダル」の3段。
async def show_auction(interaction):
    data = horse_logic.load_stable()
    text = horse_logic.format_auction(data)
    if len(data['horses']) >= horse_logic.MAX_HORSES:
        await interaction.response.send_message(
            text + f"\n\n厩舎は{horse_logic.MAX_HORSES}頭までです。引退を待つか、そのまま眺めてください。", ephemeral=True)
        return
    lots = horse_logic.auction(data)
    if not lots:
        await interaction.response.send_message(text, ephemeral=True)
        return
    await interaction.response.send_message(text + "\n\n買う仔馬を選んでください。",
                                            view=AuctionSelectView(lots), ephemeral=True)


class AuctionSelectView(View):
    def __init__(self, lots):
        super().__init__(timeout=180)
        self.add_item(AuctionDropdown(lots))


class AuctionDropdown(Select):
    def __init__(self, lots):
        self.lots = {lot['key']: lot for lot in lots}
        options = []
        for lot in lots:
            f = lot['foal']
            options.append(discord.SelectOption(
                label=f"{f['name']}（{f['sex']}・{f['growth_type']}） {lot['price']:,}万円"[:100],
                value=lot['key'],
                description=f"父 {lot['sire']}（{lot['sire_class']}） × 母 {lot['dam']}（{lot['dam_class']}）"[:100]))
        super().__init__(placeholder="仔馬を選択", options=options)

    async def callback(self, interaction: discord.Interaction):
        lot = self.lots[self.values[0]]
        f = lot['foal']
        await interaction.response.edit_message(
            content=(f"**{f['name']}**（{f['sex']}・{f['growth_type']}）\n"
                     f"父 {lot['sire']}（{lot['sire_class']}） × 母 {lot['dam']}（{lot['dam_class']}）\n"
                     f"{horse_logic.format_aptitude(f['aptitude'])}\n\n"
                     f"**{lot['price']:,}万円** で買いますか？"),
            view=AuctionConfirmView(lot))


class AuctionConfirmView(View):
    def __init__(self, lot):
        super().__init__(timeout=180)
        self.lot = lot

    @discord.ui.button(label="買う", style=discord.ButtonStyle.success)
    async def ok_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuctionNameModal(self.lot))

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def no_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="買うのはやめました。", view=None)


class AuctionNameModal(discord.ui.Modal):
    def __init__(self, lot):
        super().__init__(title="仔馬の名前")
        self.lot = lot
        self.name_input = discord.ui.TextInput(
            label="名前（空欄ならそのまま）", required=False, max_length=9, placeholder="カタカナ9文字まで")
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            foal, price = horse_logic.buy_foal(self.lot['key'], name=self.name_input.value)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return
        data = horse_logic.load_stable()
        await interaction.response.send_message(
            f"🐴 **{foal['name']}** を {price:,}万円で買いました。併せ馬として厩舎に入ります"
            f"（{len(data['horses'])}/{horse_logic.MAX_HORSES}頭 ／ 残り資金 {data['funds']:,}万円）。\n"
            f"厩舎メニューのセレクトで切り替えて、出走登録や配合ができます。", ephemeral=True)


# ====================================================
# 今週の重点
# ====================================================
class FocusView(View):
    def __init__(self):
        super().__init__(timeout=120)
        for i, key in enumerate(horse_logic.PARAMS):
            self.add_item(FocusButton(key, horse_logic.PARAM_NAMES[key], row=i // 3))
        self.add_item(FocusButton(None, '重点なし', row=2))


class FocusButton(discord.ui.Button):
    def __init__(self, key, label, row):
        super().__init__(label=label, row=row,
                         style=discord.ButtonStyle.primary if key else discord.ButtonStyle.secondary)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        horse_logic.set_focus(self.key)
        text = (f"🎯 今週の重点を **{horse_logic.PARAM_NAMES[self.key]}** にしました。"
                if self.key else "🎯 今週の重点を解除しました。")
        await interaction.response.edit_message(content=text, view=None)


# ====================================================
# 配合
# ====================================================
# ⭕ 15戦目から次の配合を予約し、引退した瞬間に仔が生まれる（調教を止めないため）。
#    相手の選択はモーダルに置けないので「セレクト → 確認 → 名前のモーダル」の3段。
#    数字の根拠は docs/RACE_DESIGN.md §8。
async def show_breeding(interaction):
    data = horse_logic.load_stable()
    horse = data['current']

    plan = horse.get('breeding_plan')
    if plan:
        p = plan['partner']
        text = (f"🧬 **配合予約済み**\n{horse['name']} × **{p['name']}**（{p['sex']}・{p['class']}）\n"
                f"{horse_logic.format_aptitude(p['aptitude'])} ／ 種付け料 {plan['fee']:,}万円"
                + (f"\n仔の名前: {plan['foal_name']}" if plan.get('foal_name') else '')
                + "\n引退した瞬間に仔が生まれます。")
        await interaction.response.send_message(text, view=CancelBreedingView(), ephemeral=True)
        return

    ok, reason = horse_logic.breeding_status(horse)
    if not ok:
        await interaction.response.send_message(
            f"🧬 配合は{horse_logic.BREEDING_OPEN_STARTS}戦目から予約できます。{reason}。",
            ephemeral=True)
        return

    cands = horse_logic.breeding_candidates(data)
    if not cands:
        await interaction.response.send_message("相手がいません。", ephemeral=True)
        return
    await interaction.response.send_message(
        horse_logic.format_candidates(data) + "\n\n相手を選んでください。",
        view=BreedSelectView(cands), ephemeral=True)


class BreedSelectView(View):
    def __init__(self, cands):
        super().__init__(timeout=180)
        self.add_item(BreedDropdown(cands))


class BreedDropdown(Select):
    def __init__(self, cands):
        # ⭕ セレクトは25件まで。自家の引退馬が増えたら新しいものを残し、市場の6頭は必ず出す
        own = [c for c in cands if c['source'] == 'own'][-19:]
        cands = own + [c for c in cands if c['source'] == 'market']
        self.cands = {c['key']: c for c in cands}
        options = []
        for c in cands:
            fee = '無料' if c['fee'] == 0 else f"{c['fee']:,}万円"
            origin = '自家' if c['source'] == 'own' else '市場'
            options.append(discord.SelectOption(
                label=f"[{origin}] {c['name']}（{c['class']}）"[:100],
                value=c['key'],
                description=f"{horse_logic.format_aptitude(c['aptitude'])} ／ {fee}"[:100]))
        super().__init__(placeholder="配合の相手を選択", options=options)

    async def callback(self, interaction: discord.Interaction):
        c = self.cands[self.values[0]]
        fee = '無料' if c['fee'] == 0 else f"{c['fee']:,}万円"
        await interaction.response.edit_message(
            content=(f"{horse_logic.format_candidate(c)}\n\n"
                     f"種付け料 **{fee}** で予約しますか？"),
            view=BreedConfirmView(c))


class BreedConfirmView(View):
    def __init__(self, cand):
        super().__init__(timeout=180)
        self.cand = cand

    @discord.ui.button(label="予約する", style=discord.ButtonStyle.success)
    async def ok_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BreedNameModal(self.cand))

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def no_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="配合はやめました。", view=None)


class BreedNameModal(discord.ui.Modal):
    def __init__(self, cand):
        super().__init__(title="仔の名前")
        self.cand = cand
        self.name_input = discord.ui.TextInput(
            label="仔の名前（空欄なら自動で付けます）", required=False, max_length=9,
            placeholder="カタカナ9文字まで")
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            plan = horse_logic.reserve_breeding(self.cand['key'], foal_name=self.name_input.value)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return
        data = horse_logic.load_stable()
        p = plan['partner']
        await interaction.response.send_message(
            f"🧬 **{p['name']}** と配合を予約しました。種付け料 {plan['fee']:,}万円"
            f" ／ 残り資金 {data['funds']:,}万円"
            + (f"\n仔の名前: {plan['foal_name']}" if plan.get('foal_name') else '')
            + "\n引退した瞬間に仔が生まれます。", ephemeral=True)


class CancelBreedingView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="予約を取り消す（種付け料を戻す）", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        plan = horse_logic.cancel_breeding()
        fee = plan.get('fee', 0) if plan else 0
        await interaction.response.edit_message(
            content=f"🚫 配合の予約を取り消し、{fee:,}万円を戻しました。", view=None)


# ====================================================
# あとから記録する
# ====================================================
# ⭕ やっているのに記録が残っていない状態を埋められるようにする。タイピングは
#    機能追加から18日で記録1件、筋トレは0件だった。ボタンの押し忘れで能力が
#    育たないのでは育成として成立しない。
BACKFILL_CATEGORIES = [
    ('programming', '💻 開発作業', True),
    ('reading', '📚 インプット', True),
    ('training', '💪 筋トレ', False),
    ('typing', '⌨️ タイピング', False),
]


def parse_dates(text, today=None):
    """「09-05, 9/6, 2026-09-08」のような入力を日付のリストにします。

    Returns:
        tuple: (日付のリスト, 読めなかった文字列のリスト)
    """
    today = today or datetime.now(JST).date()
    parsed, bad = [], []
    for chunk in re.split(r'[,、\s]+', (text or '').strip()):
        if not chunk:
            continue
        parts = re.split(r'[-/.]', chunk)
        try:
            if len(parts) == 3:
                day = date(int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(parts) == 2:
                day = date(today.year, int(parts[0]), int(parts[1]))
                # ⭕ 年をまたいだ直後に「12-28」と入れたら去年のこと。未来日にはしない。
                if day > today:
                    day = date(today.year - 1, int(parts[0]), int(parts[1]))
            else:
                bad.append(chunk)
                continue
        except ValueError:
            bad.append(chunk)
            continue
        if day not in parsed:
            parsed.append(day)
    return sorted(parsed), bad


class BackfillView(View):
    def __init__(self):
        super().__init__(timeout=120)
        for cat_id, label, needs_minutes in BACKFILL_CATEGORIES:
            self.add_item(BackfillButton(cat_id, label, needs_minutes))


class BackfillButton(discord.ui.Button):
    def __init__(self, cat_id, label, needs_minutes):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.cat_id = cat_id
        self.cat_label = label
        self.needs_minutes = needs_minutes

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            BackfillModal(self.cat_id, self.cat_label, self.needs_minutes))


class BackfillModal(discord.ui.Modal):
    def __init__(self, cat_id, cat_name, needs_minutes):
        super().__init__(title=f"{cat_name}をあとから記録")
        self.cat_id = cat_id
        self.cat_name = cat_name
        self.needs_minutes = needs_minutes

        self.dates_input = discord.ui.TextInput(
            label="日付（カンマ区切りで複数可）",
            placeholder="例: 09-05, 09-06, 09-08",
            required=True, max_length=200)
        self.add_item(self.dates_input)

        if needs_minutes:
            self.minutes_input = discord.ui.TextInput(
                label="1日あたりの時間（分）", placeholder="例: 60", required=True, max_length=4)
            self.add_item(self.minutes_input)

    async def on_submit(self, interaction: discord.Interaction):
        dates, bad = parse_dates(self.dates_input.value)
        if not dates:
            await interaction.response.send_message(
                "⚠️ 日付を読み取れませんでした。`09-05, 09-06` のように入力してください。",
                ephemeral=True)
            return

        minutes = None
        if self.needs_minutes:
            minutes = parse_positive_int(self.minutes_input.value)
            if minutes is None or minutes <= 0:
                await interaction.response.send_message(
                    "⚠️ 分数は正の数字で入力してください。", ephemeral=True)
                return

        result = horse_logic.backfill(self.cat_id, dates, minutes)
        _record_sessions(self.cat_id, dates)

        detail, public = build_growth_message(result)
        listed = '、'.join(d.strftime('%m/%d') for d in dates)
        msg = f"✅ {self.cat_name} を{result['days']}日ぶん記録しました（{listed}）。{detail}"
        if bad:
            msg += f"\n⚠️ 読み取れなかった入力: {', '.join(bad)}"
        await interaction.response.send_message(msg, ephemeral=True)
        if public:
            await interaction.channel.send(f"📣 {interaction.user.mention} {public}")


def _record_sessions(category, dates):
    """筋トレ・タイピングは、それぞれの記録側にも同じ日付で残します。

    ⭕ 馬の成長だけ足して元の記録を放置すると、連続記録や週間の実施率が食い違う。
    """
    for day in dates:
        try:
            if category == 'training':
                training_logic.log_session(now=datetime.combine(day, dtime(12, 0, tzinfo=JST)))
            elif category == 'typing':
                typing_logic.log_practice(today=day)
        except Exception as e:      # 記録側の都合で育成まで巻き込まないようにする
            print(f"⚠️ [backfill] {category} {day} の記録に失敗: {e}")


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
        resting = horse_logic.rest_reason(horse, day)
        await interaction.response.send_message(
            f"✈️ {resting}" if resting else
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
                label=f"{'🌏 ' if r.get('overseas') else ''}{r['name']}"[:100],
                value=r['id'],
                description=(f"{r['course']}{r['surface']}{r['distance']}m {r['cond']}"
                             f" ／ 1着{r['prize']:,}万円{horse_logic.format_travel(r)}")[:100])
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
        try:
            horse_logic.enter_race(self.race, style=self.style_name)
        except ValueError as e:
            await interaction.response.edit_message(content=f"⚠️ {e}", view=None)
            return
        r = self.race
        travel = f"\n遠征費 {r['travel']:,}万円を払いました。" if r.get('travel') else ''
        await interaction.response.edit_message(
            content=(f"✅ **{r['name']}** に出走登録しました。\n"
                     f"{r['date']} {r['course']}{r['surface']}{r['distance']}m {r['cond']}"
                     f" ／ 脚質 **{self.style_name}**（宣言どおりになるとは限りません）{travel}"),
            view=None)


class CancelEntryView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="出走を取り消す", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        horse_logic.cancel_entry()
        await interaction.response.edit_message(
            content="🚫 出走登録を取り消しました。遠征費は戻しています。", view=None)


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
    # ⭕ ファイル名を SPOILER_ で始めると Discord が黒塗りで表示する。
    #    結果を先に見せずに済む。
    name = f"SPOILER_{result['race'].get('name', 'race')}.html"
    return path, name


async def post_race_result(channel, outcome, mention=None):
    """レース結果をチャンネルへ投稿し、再生用HTMLを添付します。

    ⭕ 添付にはファイル添付の権限が要る。権限が無いときに全体が落ちると、レース結果
       そのものが失われてしまうので、そのときはテキストだけでも必ず投稿する。
    """
    # ⭕ 結果はネタバレで伏せる。開いた瞬間に着順が見えると、再生を先に見る
    #    楽しみが無くなる。タップすれば読める。
    text = horse_logic.format_result(outcome, spoiler=True)
    if outcome.get('horse_name'):
        text = f"🐎 **{outcome['horse_name']}**\n{text}"
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
    """登録されている全馬のレースを、主戦から順に実行して結果を投稿します。

    Returns:
        bool: 1頭でも実行したらTrue、登録が無ければFalse。
    """
    outcomes = await asyncio.to_thread(horse_logic.run_entries)
    for outcome in outcomes:
        await post_race_result(channel, outcome, mention)
    return bool(outcomes)


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


@tree.command(name="breed", description="次の世代の配合を予約します（15戦目から）")
async def breed_command(interaction: discord.Interaction):
    await show_breeding(interaction)


@tree.command(name="pedigree", description="現役馬の血統表を表示します")
async def pedigree_command(interaction: discord.Interaction):
    horse = horse_logic.load_stable()['current']
    await interaction.response.send_message(horse_logic.format_pedigree(horse), ephemeral=True)


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
