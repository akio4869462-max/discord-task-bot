# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

就活・応用情報の学習・筋トレ・タイピング訓練を1つに束ねた、個人利用のDiscord Bot。EC2上でDockerコンテナとして常時稼働している。

記録した活動は**競走馬の育成**に変換される。作業時間が能力になり、土曜と水曜に開催されるレースへ出走して着順を競う。設計と数字の根拠は `docs/RACE_DESIGN.md` にある。

## コマンド

```bash
# 依存インストール（テスト用ライブラリを含む）
pip install -r requirements-dev.txt

# テスト全実行
pytest -v

# 単一ファイル / 単一テスト / 名前で絞り込み
pytest tests/test_news_logic.py -v
pytest tests/test_news_logic.py::test_detect_unknown_terms_sorts_by_frequency
pytest -k "streak" -v

# ローカル起動（Discordへ実接続する。後述の「テスト用Bot」を使うこと）
python main.py

# Dockerで起動
docker compose up -d --build
```

**Windowsで日本語出力が `UnicodeEncodeError: 'cp932'` で落ちる場合は `PYTHONIOENCODING=utf-8` を付ける。** ログ・テスト出力ともに日本語を含むため頻発する。

```bash
PYTHONIOENCODING=utf-8 python -m pytest -q
```

## アーキテクチャ

### モジュール分割の原則

`main.py` が Discord とのやり取り（イベント、スラッシュコマンド、View/Modal）を一手に引き受け、`*_logic.py` は **Discord に一切依存しない**。ロジック側に `import discord` は存在せず、文字列とプリミティブだけを返す。この境界のおかげでロジックはネットワーク無しでユニットテストできる。

| モジュール | 責務 | データファイル |
|---|---|---|
| `task_logic.py` | タスクCRUD・優先度/期限ソート | `data/todo.json` |
| `horse_logic.py` | 競走馬の育成（成長・調子・出走・昇級・世代交代） | `data/stable.json`（移行元: `data/player_data.json`） |
| `race_sim/engine.py` | レースシミュレーション（Discord非依存・標準ライブラリのみ） | `race_sim/data/course_baseline.json` |
| `race_sim/rivals.py` | ライバル馬プールから出走表を組む | `race_sim/data/rivals.json` |
| `race_sim/calendar.py` | 番組表（土曜・水曜の開催） | — |
| `news_logic.py` | RSS取得・既知語フィルタ・未知語検出 | `data/news_keywords.json`（読み: `data/glossary.json` も） |
| `exam_logic.py` | 応用情報の分野別演習記録 | `data/exam_data.json` |
| `training_logic.py` | 筋トレの曜日別メニュー・記録 | `data/training_data.json` |
| `typing_logic.py` | タイピング訓練のドリル進行・計測 | `data/typing_data.json` |
| `calendar_logic.py` | Googleカレンダーへの期限同期（任意） | `data/service_account.json` |

`main.py` は約1,100行あり、機能追加のたびに UI クラスとコマンド定義が積み上がる構造になっている。分割は未着手。

### ニュース照合に使う2つのファイル

`news_logic.load_stock_keywords()` は `glossary.json`（学習用語）と `news_keywords.json`（ニュース追跡専用の語の配列）を結合してニュース記事とのマッチングに使う。

⭕ かつては `glossary.json` が用語のストック・検索・SRSクイズ機能の主データでもあったが、使われていなかったため2026年9月にUI・ロジック・テストごと削除した。`glossary.json` は今もニュース照合の入力source（読み取り専用）として`news_logic.py`から参照されるが、UIから新規追加する手段は無い。追跡語を増やしたい場合は「🆕 ニュースの新語」から `news_keywords.json` へ登録する。

### データ形式の移行は「読み込み時」に行う

スキーマを変える際、既存 JSON の手作業移行や移行スクリプトは書かない。**読み込み関数の中で旧形式を検出して補完する**のがこのリポジトリの流儀。

- `horse_logic.load_stable()` … 厩舎データが無ければ旧 `player_data.json` を読み、初代馬の成長へ読み替える
- `task_logic.list_tasks()` … `id` を持たない古いタスクに UUID を採番して保存

新しいフィールドを足すときはこのパターンに従うこと。

### Discord まわりの制約

**`interaction.response.*` は受信から約3秒以内**に呼ぶ必要がある。ネットワークI/Oを挟む場合は次のいずれか。

- 先に `interaction.response.defer(ephemeral=True)` してから `followup.send()`（例: ニュース取得）
- 先に結果を返し、時間のかかる処理は後追いで `followup.send()`（例: タスク登録→カレンダー同期）

**同期的なブロッキングI/Oは必ず `asyncio.to_thread` で逃がす。** RSS取得と Google Calendar API がこれに該当する。直接呼ぶと Bot 全体が固まる。

**モーダル（`discord.ui.Modal`）には `TextInput` しか置けない。** 選択肢を選ばせたい項目はモーダルの前後にボタン/セレクトのステップを挟む（例: タスク追加は「カテゴリ選択 → 内容入力モーダル → 優先度選択」の3段）。

### 定期配信

`@tasks.loop(time=DELIVERY_TIMES)` は**1つだけ**で、8:00 と 20:00 の両方を担当する。関数内で `now_jst.hour` を見て分岐しているので、新しい定期処理を足すときはループを増やさずこの分岐に相乗りさせる。月曜朝の週間サマリーも同じ関数内にある。

`/test_reminder`（朝の処理）と `/test_typing_notify`（夜の処理）で、時刻を待たずに動作確認できる。

### 環境変数の読み込み順序

`main.py` の冒頭で、**自作モジュールを import するより前に** `load_dotenv()` を呼んでいる。`calendar_logic.py` がモジュール読み込み時に `os.getenv('GOOGLE_CALENDAR_ID')` を評価するため、順序を入れ替えると環境変数が空になる。import 文を整理する際に壊しやすいので注意。

## テスト

`conftest.py` がリポジトリ直下に置かれており、これによって `tests/` から `main.py` などを直接 import できる。

### ファイルパスの差し替えが必須

各モジュールはデータファイルのパスを**モジュールレベル定数**として持つ。テストでは `monkeypatch.setattr` で一時ディレクトリに差し替えること。差し替えないと本物の `data/` を読み書きしてしまう。

```python
@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, 'TRAINING_DATA_FILE', str(tmp_path / 'training_data.json'))
```

**ある関数が複数のファイルを読む場合、そのすべてを差し替える。** 特に `news_logic.load_stock_keywords()` は `GLOSSARY_FILE` と `NEWS_KEYWORDS_FILE` の両方を読むため、片方だけ差し替えるとテストが実データを巻き込んで不安定になる（過去に実際に起きている）。

### 時刻に依存する関数はテスト用の引数を持つ

`today` / `now` を省略可能な引数として受け取り、省略時のみ現在時刻を使う設計にしている。テストではこれを注入して固定日で検証する。

```python
def log_session(note=None, now=None):
    now = now or datetime.now(JST)
```

新しく日付ロジックを書くときも同じ形にすること。

### ネットワークを叩かない

`news_logic` のテストは `fetch_rss` を monkeypatch で差し替える。`fetch_rss(url=None)` は引数を取るシグネチャなので、モックも `lambda url=None: SAMPLE_RSS` の形にする。

## デプロイ

`main` への push で `.github/workflows/deploy.yml` が動く。**`deploy` ジョブは `needs: test` で `test` ジョブに依存**しており、テストが落ちると本番へ反映されない。`test.yml` は PR のみを対象にして二重実行を避けている。

デプロイは EC2 に SSH して `git pull && docker compose up -d --build` を実行する。`data/` はホスト側にバインドマウントされており、コンテナを作り直しても残る（Git 管理外）。

### 本番と開発の分離

**このリポジトリの `.env` は開発用Bot（`task-bot-dev`）のもの。** 本番の認証情報は EC2 側の `.env` にしか無い。

| | 読む設定 | 接続先Bot | チャンネル |
|---|---|---|---|
| ローカル | このリポジトリの `.env` | `task-bot-dev` | テストサーバー |
| EC2（本番） | EC2上の `.env` | `TaskManagerBot` | 本番サーバー |

したがって**ローカルでは `python main.py` をそのまま実行してよい**。本番との二重ログインは起こらない。

⭕ ここを「`.env` は本番のもの」と誤解すると、`.env.dev` を作って切り替える仕組みや、
   本番トークンとの一致を検出するガードといった、この構成では意味の無いものを足してしまう
   （実際に一度作って捨てた）。データも `data/` がローカルとEC2で別々なので混ざらない。

## 実装上の注意

**外部フィードは総合フィードを使わない。** `news_logic.RSS_FEEDS` は ITmedia AI+ / エンタープライズ / @IT の3本。総合フィード（`itmedia_all.xml`）はスマホ販売ランキングや飲食チェーンの話題まで含み、用語抽出をかけると製品名ばかりになるため意図的に外している。

**日本語テキストの正規表現で `\b` は使えない。** Python の `\w` は Unicode 文字を含むため、`OpenAIの` のような箇所に単語境界が生じない。英字トークンの切り出しには ASCII 英数字だけを見る先読み/後読み（`(?<![A-Za-z0-9])...(?![A-Za-z0-9])`）を使っている。

**モーダル入力の数値変換に `str.isdigit()` を使わない。** `²` のような文字に `True` を返す一方で `int()` は失敗し、Bot が無応答になる。`main.parse_positive_int()` / `parse_float()` を使うこと（全角数字も受け付ける）。
