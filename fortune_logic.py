"""馬みくじ（競馬テーマのお遊びおみくじ）モジュール

⭕ これは実在のレース予想やkeiba-app-newの予測とは一切関係ない、Bot単体で完結する
   お遊び機能です。馬券の買い方や実在の馬を示唆するような文言は入れず、あくまで
   「今日の気分」的な運試しに留めています。
"""

import random

# 出現率の合計は100。大吉が一番レアになるよう、実際のおみくじの体感に寄せた配分。
FORTUNES = [
    {
        "rank": "大吉",
        "weight": 8,
        "gate_flavor": "絶好の枠",
        "message": "絶好調！今日は思い切って前に出ていく日。",
    },
    {
        "rank": "中吉",
        "weight": 20,
        "gate_flavor": "内枠",
        "message": "波に乗れそう。焦らず自分のペースを守れば結果はついてくる。",
    },
    {
        "rank": "吉",
        "weight": 30,
        "gate_flavor": "中団",
        "message": "まずまずの手応え。地道な積み重ねが効いてくる日。",
    },
    {
        "rank": "末吉",
        "weight": 27,
        "gate_flavor": "外枠",
        "message": "派手さはないけれど堅実。無理せずいつも通りが吉。",
    },
    {
        "rank": "凶",
        "weight": 15,
        "gate_flavor": "大外枠",
        "message": "今日は無理せず休養日。仕切り直せば次はきっと走れる。",
    },
]

GATE_NUMBERS = list(range(1, 19))  # 実際の競馬の枠番(1〜18頭立て想定)を模した演出


def draw_fortune(rng=None):
    """馬みくじを1回引きます。

    Args:
        rng (random.Random, optional): 乱数源（テスト用の注入口）。省略時はrandomモジュール。

    Returns:
        dict: {"rank", "gate_flavor", "message", "gate_number"}
    """
    rng = rng or random
    ranks = [f["rank"] for f in FORTUNES]
    weights = [f["weight"] for f in FORTUNES]
    chosen_rank = rng.choices(ranks, weights=weights, k=1)[0]
    entry = next(f for f in FORTUNES if f["rank"] == chosen_rank)

    return {
        "rank": entry["rank"],
        "gate_flavor": entry["gate_flavor"],
        "message": entry["message"],
        "gate_number": rng.choice(GATE_NUMBERS),
    }


def format_fortune_message(fortune, display_name):
    """馬みくじの結果をDiscord向けのメッセージ文字列に整形します。"""
    return (
        f"🏇 **【馬みくじ】{display_name}さんの結果**\n"
        f"# {fortune['rank']}\n"
        f"枠番 {fortune['gate_number']}番（{fortune['gate_flavor']}）\n"
        f"{fortune['message']}"
    )
