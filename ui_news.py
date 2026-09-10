"""ニュース用語（未登録語の検出・追跡語の管理）まわりのView"""

import asyncio

import discord
from discord.ui import View, Select

import news_logic


class NewsTermsMenuView(View):
    """「ニュース用語」サブメニュー：未登録語の検出・追跡語の管理をまとめたView

    ⭕ 以前は用語のストック・検索・一覧・SRSクイズもここにあったが、使われて
       いなかったため削除した。ニュースの追跡語専用に縮小。
    """
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="🆕 ニュースの新語", style=discord.ButtonStyle.primary, row=0)
    async def unknown_terms_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # RSS取得は応答時間が読めないため、先に応答を保留してから処理する
        await interaction.response.defer(ephemeral=True)
        terms = await asyncio.to_thread(news_logic.get_unknown_terms)

        if not terms:
            await interaction.followup.send(
                "未登録の頻出語は見つかりませんでした。", ephemeral=True
            )
            return

        await interaction.followup.send(
            "ニュースで見つかった未登録の頻出語です。\n"
            "選んだ語はニュースの絞り込みに使われます：",
            view=UnknownTermSelectView(terms), ephemeral=True,
        )

    @discord.ui.button(label="📰 追跡語の管理", style=discord.ButtonStyle.secondary, row=0)
    async def news_keywords_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        keywords = news_logic.load_news_keywords()
        if not keywords:
            await interaction.response.send_message(
                "ニュース追跡語はまだ登録されていません。\n"
                "「🆕 ニュースの新語」から登録できます。",
                ephemeral=True,
            )
            return

        msg = f"📰 **【ニュース追跡語】**（{len(keywords)}件）\n\n"
        msg += "、".join(keywords)
        await interaction.response.send_message(
            msg, view=NewsKeywordRemoveView(keywords), ephemeral=True
        )


class UnknownTermSelectView(View):
    """ニュースから検出した未登録語を、ニュース追跡語として登録するView"""
    def __init__(self, terms):
        super().__init__(timeout=120)

        options = []
        for item in terms[:25]:  # セレクトメニューの上限
            count_label = f"（{item['count']}件）" if item['count'] > 1 else ""
            options.append(discord.SelectOption(
                label=f"{item['term']}{count_label}"[:100],
                description=item['title'][:100],
                value=item['term'][:100],
            ))
        self.add_item(UnknownTermDropdown(options))


class UnknownTermDropdown(Select):
    def __init__(self, options):
        super().__init__(
            placeholder='追跡したい語を選択（複数可）...',
            min_values=1,
            max_values=len(options),  # まとめて登録できるようにする
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        added, skipped = news_logic.add_news_keywords(self.values)

        lines = []
        if added:
            lines.append("📰 ニュース追跡語に登録しました: " + "、".join(added))
        if skipped:
            lines.append("（登録済みのためスキップ: " + "、".join(skipped) + "）")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class NewsKeywordRemoveView(View):
    """登録済みのニュース追跡語を削除するView"""
    def __init__(self, keywords):
        super().__init__(timeout=120)
        options = [discord.SelectOption(label=k[:100], value=k[:100]) for k in keywords[:25]]
        self.add_item(NewsKeywordRemoveDropdown(options))


class NewsKeywordRemoveDropdown(Select):
    def __init__(self, options):
        super().__init__(
            placeholder='削除する語を選択（複数可）...',
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        removed = news_logic.remove_news_keywords(self.values)
        msg = "🗑️ 削除しました: " + "、".join(removed) if removed else "削除対象が見つかりませんでした。"
        await interaction.response.send_message(msg, ephemeral=True)
