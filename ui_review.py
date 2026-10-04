"""応用情報 復習ノートのView/Modal（資格学習メニューの「📚 復習ノート」から開く）"""

import discord
from discord import app_commands
from discord.ui import View, Select

import exam_logic
import review_logic
from bot_state import tree


class ReviewMenuView(View):
    """復習ノートのサブメニュー"""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="➕ 間違えた問題を登録", style=discord.ButtonStyle.primary, row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "問題の分野を選んでください：", view=ReviewFieldSelectView(), ephemeral=True
        )

    @discord.ui.button(label="📊 過去問道場のCSVを取り込む", style=discord.ButtonStyle.primary, row=0)
    async def csv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewCsvModal())

    @discord.ui.button(label="📋 復習一覧", style=discord.ButtonStyle.secondary, row=1)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        items = review_logic.list_items()
        if not items:
            await interaction.response.send_message("復習対象の問題はありません 🎉", ephemeral=True)
            return
        view = ReviewItemSelectView(items)
        await interaction.response.send_message(view.header(), view=view, ephemeral=True)

    @discord.ui.button(label="🔑 教本で調べるキーワード", style=discord.ButtonStyle.secondary, row=1)
    async def keyword_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(review_logic.build_keyword_list(), ephemeral=True)


class ReviewFieldSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        options = [
            discord.SelectOption(label=name[:100], value=fid)
            for fid, name in exam_logic.EXAM_FIELDS.items()
        ]
        self.add_item(ReviewFieldDropdown(options))


class ReviewFieldDropdown(Select):
    def __init__(self, options):
        super().__init__(placeholder='分野を選択...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReviewAddModal(self.values[0]))


class ReviewAddModal(discord.ui.Modal, title='📚 復習ノートに登録'):
    title_input = discord.ui.TextInput(
        label='問題の識別名', placeholder="例: R6春 問26(令和6年春期 問26 の形に揃います)", required=True, max_length=60)
    keywords_input = discord.ui.TextInput(
        label='キーワード（「、」区切り・任意）',
        placeholder='例: デッドロック、排他制御', required=False, max_length=200)
    memo_input = discord.ui.TextInput(
        label='メモ（間違えた理由など）', required=False, max_length=200)

    def __init__(self, field):
        super().__init__()
        self.field = field

    async def on_submit(self, interaction: discord.Interaction):
        keywords = review_logic.parse_keywords(self.keywords_input.value)
        _, msg = review_logic.add_item(self.title_input.value, self.field, keywords, self.memo_input.value)
        await interaction.response.send_message(msg, ephemeral=True)


class ReviewCsvModal(discord.ui.Modal, title='📊 過去問道場のCSVを取り込む'):
    """過去問道場からエクスポートした成績CSVを選ぶモーダル（最後の結果が×の問題だけ登録する）"""
    csv_file = discord.ui.Label(
        text='成績CSVファイル',
        description='道場の成績画面からダウンロードしたCSV',
        component=discord.ui.FileUpload(required=True, min_values=1, max_values=1),
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        files = self.csv_file.component.values
        if not files:
            await interaction.followup.send("❌ ファイルが選択されていません。", ephemeral=True)
            return
        if files[0].size > review_logic.MAX_CSV_BYTES:
            await interaction.followup.send("❌ ファイルが大きすぎます（1MBまで）。", ephemeral=True)
            return
        raw = await files[0].read()
        await interaction.followup.send(review_logic.add_items_from_csv(raw), ephemeral=True)


class ReviewKeywordModal(discord.ui.Modal, title='🔑 キーワード編集'):
    """教本で引いた用語を直接入力する"""
    keywords_input = discord.ui.TextInput(
        label='キーワード（「、」区切り）', required=False, max_length=200,
        placeholder='例: ダイナミックルーティング、OSPF')

    def __init__(self, item):
        super().__init__()
        self.item_id = item['id']
        self.keywords_input.default = '、'.join(item['keywords'])

    async def on_submit(self, interaction: discord.Interaction):
        item = review_logic.set_keywords(self.item_id, review_logic.parse_keywords(self.keywords_input.value))
        if item is None:
            await interaction.response.send_message("その問題は見つかりませんでした。", ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ キーワードを更新しました。\n" + review_logic.format_item(item), ephemeral=True)


class ReviewItemSelectView(View):
    """復習一覧のプルダウン。Discordのセレクトは最大25件なので、ページ送りで全件を選べるようにする"""
    PAGE_SIZE = 25

    def __init__(self, items, page=0):
        super().__init__(timeout=180)
        self.items = items
        self.pages = max(1, -(-len(items) // self.PAGE_SIZE))
        self.page = min(page, self.pages - 1)
        self._build()

    def header(self):
        return (f"復習対象は{len(self.items)}問です（{self.page + 1}/{self.pages}ページ）。"
                "操作する問題を選んでください：")

    def _build(self):
        self.clear_items()
        chunk = self.items[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        options = []
        for i in chunk:
            detail = '、'.join(i['keywords']) or (f"分類: {i['topic']}" if i.get('topic') else 'キーワード未設定')
            options.append(discord.SelectOption(
                label=i['title'][:100],
                description=f"{review_logic.STATUS_LABELS[i['status']]}／{detail}"[:100],
                value=i['id'],
            ))
        self.add_item(ReviewItemDropdown(options))
        if self.pages > 1:
            prev_btn = discord.ui.Button(label="◀ 前へ", disabled=self.page == 0, row=1)
            next_btn = discord.ui.Button(label="次へ ▶", disabled=self.page >= self.pages - 1, row=1)
            prev_btn.callback = self._make_move(-1)
            next_btn.callback = self._make_move(1)
            self.add_item(prev_btn)
            self.add_item(next_btn)

    def _make_move(self, delta):
        async def callback(interaction: discord.Interaction):
            self.page += delta
            self._build()
            await interaction.response.edit_message(content=self.header(), view=self)
        return callback


class ReviewItemDropdown(Select):
    def __init__(self, options):
        super().__init__(placeholder='問題を選択...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        item = review_logic.get_item(self.values[0])
        if item is None:
            await interaction.response.send_message("その問題は見つかりませんでした。", ephemeral=True)
            return
        await interaction.response.send_message(
            review_logic.format_item(item), view=ReviewItemActionView(item), ephemeral=True)


class ReviewItemActionView(View):
    """選んだ問題への操作（状態を進める／キーワード編集／また間違えた／削除）"""
    def __init__(self, item):
        super().__init__(timeout=120)
        self.item_id = item['id']
        if item['status'] < review_logic.STATUS_DONE:
            btn = discord.ui.Button(
                label=review_logic.ADVANCE_LABELS[item['status']], style=discord.ButtonStyle.primary)
            btn.callback = self.on_advance
            self.add_item(btn)

    async def on_advance(self, interaction: discord.Interaction):
        item = review_logic.advance(self.item_id)
        if item is None:
            await interaction.response.send_message("その問題は見つかりませんでした。", ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ 更新しました。\n" + review_logic.format_item(item), ephemeral=True)

    @discord.ui.button(label="🔑 キーワード編集", style=discord.ButtonStyle.secondary)
    async def keyword_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        item = review_logic.get_item(self.item_id)
        if item is None:
            await interaction.response.send_message("その問題は見つかりませんでした。", ephemeral=True)
            return
        await interaction.response.send_modal(ReviewKeywordModal(item))

    @discord.ui.button(label="また間違えた", style=discord.ButtonStyle.secondary)
    async def wrong_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        item = review_logic.mark_wrong_again(self.item_id)
        if item is None:
            await interaction.response.send_message("その問題は見つかりませんでした。", ephemeral=True)
            return
        await interaction.response.send_message(
            "未学習に戻しました。\n" + review_logic.format_item(item), ephemeral=True)

    @discord.ui.button(label="削除", style=discord.ButtonStyle.danger)
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = review_logic.delete_item(self.item_id)
        await interaction.response.send_message("🗑️ 削除しました。" if ok else "その問題は見つかりませんでした。", ephemeral=True)


# ====================================================
# 過去問道場のCSVからの一括登録（/review_import）
# ====================================================
@tree.command(name="review_import", description="過去問道場の成績CSVから、間違えた問題を復習ノートに一括登録します")
@app_commands.describe(file="過去問道場からエクスポートしたCSVファイル")
async def review_import_command(interaction: discord.Interaction, file: discord.Attachment):
    if file.size > review_logic.MAX_CSV_BYTES:
        await interaction.response.send_message("❌ ファイルが大きすぎます（1MBまで）。", ephemeral=True)
        return
    raw = await file.read()
    msg = review_logic.add_items_from_csv(raw)
    await interaction.response.send_message(msg, ephemeral=True)
