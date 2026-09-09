"""実データの分布からライバル馬プール（架空馬）を生成する。

このスクリプトは **discord-task-bot の実行環境では動かない**（duckdb が必要）。
keiba_score_search 側の venv で実行し、成果物の JSON だけをこのリポジトリにコミットする。

    PYTHONIOENCODING=utf-8 ../keiba_score_search/.venv/Scripts/python.exe \
        race_sim/tools/build_rivals.py

出力: race_sim/data/rivals.json

## 生成の方針

実在の馬名・血統名は一切持ち出さない。使うのは分布と相関だけ。

⭕ 能力・脚質・適性をそれぞれ独立に抽選すると、「ダート短距離の追込馬でスタミナが高い」
   のような実在しない組み合わせが量産される。そこで**実在馬の「プロフィールの形」
   （どの馬場・距離を、どの位置取りで、どのクラスで走ったか）をテンプレートとして
   抽出し、そこに架空の名前と能力値を与える**。個体は特定できない（同じプロフィールの
   馬が何千頭もいる）一方、条件どうしの相関は実データのまま保たれる。
"""

import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
RACE_SIM = os.path.dirname(HERE)
REPO = os.path.dirname(RACE_SIM)
SRC_CSV = os.path.join(os.path.dirname(REPO), 'keiba_score_search', 'data', 'all_utf8.csv')
OUT_JSON = os.path.join(RACE_SIM, 'data', 'rivals.json')

sys.path.insert(0, REPO)
from race_sim import engine  # noqa: E402

SEED = 20260910
MIN_STARTS = 5          # これ未満の出走数の馬はテンプレートにしない（傾向が読めない）
TARGET_POOL = 1700      # 生成する頭数（実データの構成比で配分する分）
# ⭕ 下限を26にしていたとき、テンプレートの少ないG2は各区分がちょうど26頭になり、
#    16頭立てを組むと適性の合わない馬まで動員されて勝ち時計が0.43秒遅くなった。
#    16頭立てを無理なく組めるだけの余裕を持たせる。
MIN_PER_BUCKET = 38     # クラス×主戦場×距離区分ごとの最低頭数
MIN_TEMPLATES = 10      # テンプレートがこれ未満の組み合わせは実在しないとみなす

# 能力zの水準とばらつきの補正。
# ⭕ engine.CLASS_MEAN_Z / FIELD_Z_SD をそのまま使うと、出走メンバー内の実効的な
#    能力SDが0.401（較正時の想定は0.34）まで広がった。適性グレードの差と能力配分の
#    傾きが上乗せされるためで、結果として能力最上位の勝率が0.39（目標0.327）、
#    勝ち時計が0.22秒遅くなった。ばらつきを絞り、水準をその分だけ上げて相殺する。
#    tools/calibrate.py --pool で確認できる。
POOL_Z_SHIFT = 0.26
POOL_Z_SCALE = 0.80

CLASS_MAP = {
    '7': '未勝利', '15': '未勝利', '23': '1勝', '43': '2勝', '67': '3勝',
    '115': 'OP', '131': 'OP', '147': 'OP', '163': 'G3', '179': 'G2', '195': 'G1',
}

# 芝の出走比率 → (芝適性, ダート適性)
SURFACE_GRADES = [
    (0.90, 'A', 'D'), (0.60, 'A', 'C'), (0.40, 'B', 'B'), (0.10, 'C', 'A'), (0.00, 'D', 'A'),
]
BANDS = ('sprint', 'mile', 'middle', 'long')

# 個体の能力の内訳につける傾き。位置取りの傾向・適性から、それらしい配分にする。
# ⭕ 平均は動かさず配分だけ変える。ability_z の重み付き平均が条件によって
#    上下することで、「ダートのパワー型」「終い勝負の切れ者」が自然に生まれる。
#
# ⭕ 前に行く馬ほど FRONT_TILT をそのまま、後ろから行く馬ほど符号を反転して掛ける。
#    脚質を4つに区切って傾きを選ぶ形も試したが、キャリア平均位置は0.483付近に密集する
#    ため大半が「差し」に分類され、ほぼ全馬が同じ配分になってしまった。
FRONT_TILT = {'speed': 45, 'dash': -45, 'guts': 15, 'wit': -15}
DIRT_TILT = {'power': 60, 'dash': -35, 'speed': -20}
TURF_TILT = {'dash': 25, 'speed': 20, 'power': -45}
LONG_TILT = {'stamina': 55, 'guts': 20, 'dash': -35, 'speed': -35}
SPRINT_TILT = {'speed': 40, 'dash': 30, 'stamina': -55, 'guts': -10}


# ====================================================
# 実データからテンプレートを取り出す
# ====================================================
def load_templates(con):
    """5走以上の実在馬について、走った条件の分布を集計する。"""
    con.execute(
        "CREATE OR REPLACE VIEW raw AS SELECT * FROM read_csv('"
        + SRC_CSV.replace('\\', '/') + "', header=false, skip=1, all_varchar=true, ignore_errors=true)"
    )
    names = [d[0] for d in con.execute("SELECT * FROM raw LIMIT 0").description]

    def c(i):
        return names[i]

    class_case = ' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in CLASS_MAP.items())
    con.execute(f"""
        CREATE OR REPLACE VIEW starts AS
        SELECT
            trim({c(13)})                    AS horse,
            {c(14)}                          AS sex,
            TRY_CAST({c(15)} AS INT)         AS age,
            {c(9)}                           AS surface,
            TRY_CAST({c(11)} AS INT)         AS distance,
            CASE {c(8)} {class_case} ELSE NULL END AS cls,
            TRY_CAST({c(31)} AS INT)         AS pass4,
            TRY_CAST({c(18)} AS INT)         AS field_size,
            TRY_CAST({c(20)} AS INT)         AS finish_pos
        FROM raw
        WHERE {c(10)} NOT IN ('2', '3')
          AND {c(22)} = '0'
          AND TRY_CAST({c(20)} AS INT) >= 1
          AND trim({c(13)}) <> ''
    """)

    rows = con.execute(f"""
        WITH per AS (
          SELECT horse,
                 count(*)                                              AS starts,
                 any_value(sex)                                        AS sex,
                 max(age)                                              AS age,
                 avg(CASE WHEN surface = '芝' THEN 1.0 ELSE 0.0 END)   AS turf_share,
                 avg(CASE WHEN distance <= 1400 THEN 1.0 ELSE 0.0 END) AS sprint,
                 avg(CASE WHEN distance BETWEEN 1401 AND 1800 THEN 1.0 ELSE 0.0 END) AS mile,
                 avg(CASE WHEN distance BETWEEN 1801 AND 2400 THEN 1.0 ELSE 0.0 END) AS middle,
                 avg(CASE WHEN distance > 2400 THEN 1.0 ELSE 0.0 END)  AS long,
                 avg(CASE WHEN pass4 IS NOT NULL AND field_size > 0
                          THEN pass4 * 1.0 / field_size END)           AS pos_mean,
                 stddev_samp(CASE WHEN pass4 IS NOT NULL AND field_size > 0
                          THEN pass4 * 1.0 / field_size END)           AS pos_sd,
                 mode(cls)                                             AS main_class
          FROM starts
          GROUP BY horse
          HAVING count(*) >= {MIN_STARTS}
        )
        SELECT * FROM per WHERE main_class IS NOT NULL AND pos_mean IS NOT NULL
    """).fetchall()

    templates = []
    for (horse, starts, sex, age, turf_share, sprint, mile, middle, long_,
         pos_mean, pos_sd, main_class) in rows:
        templates.append({
            'starts': starts, 'sex': sex, 'age': age,
            'turf_share': turf_share,
            'bands': {'sprint': sprint, 'mile': mile, 'middle': middle, 'long': long_},
            'pos_mean': pos_mean,
            'pos_sd': pos_sd if pos_sd is not None else 0.22,
            'cls': main_class,
        })
    return templates


def real_name_sets(con):
    """架空名が実在名と衝突しないよう、実在の馬名・種牡馬名・母父名を集める。"""
    used = set()
    for col in (13, 43, 45):
        names = [d[0] for d in con.execute("SELECT * FROM raw LIMIT 0").description]
        rows = con.execute(f"SELECT DISTINCT trim({names[col]}) FROM raw").fetchall()
        used.update(x[0] for x in rows if x[0])
    return used


# ====================================================
# 架空の馬名をつくる
# ====================================================
class NameMaker:
    """実在馬名の字面から2次のマルコフ連鎖を学習し、架空名を生成する。

    ⭕ 音の並びの傾向（「サン〜」「〜ロード」など）を引き継ぐので、無作為な
       カタカナの羅列よりずっと競走馬らしい名前になる。生成後に実在名と
       突き合わせ、衝突したものは捨てる。
    """

    KATAKANA = set('ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトド'
                   'ナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴー')

    @classmethod
    def is_katakana(cls, name):
        return bool(name) and all(ch in cls.KATAKANA for ch in name)

    def __init__(self, source_names, rng):
        self.rng = rng
        self.chain = defaultdict(Counter)
        self.lengths = Counter()
        for name in source_names:
            # ⭕ カタカナ名だけを学習する。母父名には外国産種牡馬のラテン文字表記が
            #    混ざっており、これを学習させたら「Maxiolfhd」「A. P. J」のような
            #    名前が23件生成された。
            if not (2 <= len(name) <= 9) or not self.is_katakana(name):
                continue
            self.lengths[len(name)] += 1
            seq = ('^', '^') + tuple(name) + ('$',)
            for i in range(len(seq) - 2):
                self.chain[(seq[i], seq[i + 1])][seq[i + 2]] += 1
        self.length_choices = list(self.lengths.keys())
        self.length_weights = [self.lengths[k] for k in self.length_choices]

    MIN_LEN = 4

    def _draw(self, key, allow_end=True):
        counter = self.chain.get(key)
        if not counter:
            return '$'
        items = [(c, n) for c, n in counter.items() if allow_end or c != '$']
        if not items:
            return '$'
        return self.rng.choices([c for c, _ in items], [n for _, n in items])[0]

    def make(self, banned, attempts=200):
        for _ in range(attempts):
            target = self.rng.choices(self.length_choices, self.length_weights)[0]
            target = max(self.MIN_LEN, target)
            prev, cur = '^', '^'
            out = []
            while len(out) < target:
                # ⭕ 目標長に届く前に終端が出たら引き直す。素直に打ち切ると
                #    「ロノコ」「スピー」のような2〜3文字ばかりになった（実データでは
                #    3文字以下は全体の2%しかない）。
                nxt = self._draw((prev, cur), allow_end=False)
                if nxt == '$':
                    break
                out.append(nxt)
                prev, cur = cur, nxt
            name = ''.join(out)
            if len(name) >= self.MIN_LEN and name not in banned and self.is_katakana(name):
                banned.add(name)
                return name
        return None


# ====================================================
# テンプレート → 架空馬
# ====================================================
def grade_surface(turf_share):
    for threshold, turf, dirt in SURFACE_GRADES:
        if turf_share >= threshold:
            return turf, dirt
    return 'B', 'B'


def grade_bands(bands):
    """距離区分ごとの出走比率を適性グレードに変換する。"""
    top = max(bands, key=lambda k: bands[k])
    grades = {}
    for band, share in bands.items():
        if band == top:
            grades[band] = 'A'
        elif share >= 0.20:
            grades[band] = 'B'
        elif share >= 0.05:
            grades[band] = 'C'
        else:
            grades[band] = 'D'
    return grades, top


def style_from_position(pos):
    """4コーナーの相対位置を脚質に変換する。build_baseline.py の区切りと揃える。"""
    if pos <= 0.08:
        return '逃げ'
    if pos <= 0.33:
        return '先行'
    if pos <= 0.66:
        return '差し'
    return '追込'


def build_params(rng, level, pos_mean, aptitude, top_band):
    """能力の内訳をつくる。平均は level のまま、配分だけ傾ける。"""
    params = {k: level for k in engine.JST_PARAMS}

    # 前に行く馬ほど +1、後ろから行く馬ほど -1
    front_ness = max(-1.0, min(1.0, (0.483 - pos_mean) / 0.34))
    for key, delta in FRONT_TILT.items():
        params[key] += delta * front_ness

    tilts = [DIRT_TILT if aptitude['dirt'] == 'A' else TURF_TILT if aptitude['turf'] == 'A' else {}]
    if top_band == 'long':
        tilts.append(LONG_TILT)
    elif top_band == 'sprint':
        tilts.append(SPRINT_TILT)

    for tilt in tilts:
        for key, delta in tilt.items():
            params[key] += delta

    # 個体差
    for key in params:
        params[key] += rng.gauss(0, 28)

    # 平均を level に戻す（傾けただけで底上げはしない）
    shift = level - sum(params.values()) / len(params)
    return {k: int(round(max(1, v + shift))) for k, v in params.items()}


def make_rival(rng, template, name_maker, banned, sire_pool):
    aptitude = {}
    turf, dirt = grade_surface(template['turf_share'])
    aptitude['turf'], aptitude['dirt'] = turf, dirt
    band_grades, top_band = grade_bands(template['bands'])
    aptitude.update(band_grades)

    name = name_maker.make(banned)
    if name is None:
        return None

    cls = template['cls']
    z = rng.gauss(engine.CLASS_MEAN_Z[cls] + POOL_Z_SHIFT, engine.FIELD_Z_SD * POOL_Z_SCALE)

    # ⭕ 得意条件で走ったときに ability_z が z になるよう、適性ぶんを差し引いた水準を
    #    パラメータの中心にする。これをしないと、得意条件のボーナスが丸ごと上乗せに
    #    なり、クラスごとの平均能力（＝勝ちタイム）が較正値から外れる。
    apt_bonus = (engine.APTITUDE_BONUS[turf if turf == 'A' or dirt != 'A' else dirt]
                 + engine.APTITUDE_BONUS['A'])
    level = 500 + 200 * (z - apt_bonus)

    style_seed = min(0.98, max(0.02, template['pos_mean']))
    return {
        'name': name,
        'sex': template['sex'],
        'age': template['age'],
        'class': cls,
        'z': round(z, 3),
        'params': build_params(rng, level, style_seed, aptitude, top_band),
        'pos_mean': round(style_seed, 3),
        'pos_sd': round(min(0.35, max(0.05, template['pos_sd'])), 3),
        'aptitude': aptitude,
        'sire': rng.choice(sire_pool),
        'bms': rng.choice(sire_pool),
    }


def template_bucket(t):
    """テンプレートを クラス×主戦場×距離区分 に振り分ける。"""
    surface = '芝' if t['turf_share'] >= 0.5 else 'ダ'
    if t['bands']['long'] >= 0.25:
        band = 'long'
    else:
        band = max(('sprint', 'mile', 'middle'), key=lambda b: t['bands'][b])
    return f"{t['cls']}|{surface}|{band}"


def bucket_of(rival):
    """クラス×主戦場。ダート適性がAならダート馬とみなす。"""
    return f"{rival['class']}|{'ダ' if rival['aptitude']['dirt'] == 'A' else '芝'}"


def field_size_distribution(con):
    """クラス別の出走頭数分布。出走表を組むときの頭数はここから引く。"""
    class_case = ' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in CLASS_MAP.items())
    names = [d[0] for d in con.execute("SELECT * FROM raw LIMIT 0").description]
    rows = con.execute(f"""
        WITH races AS (
          SELECT DISTINCT substr({names[40]}, 1, length({names[40]}) - 2) AS race_key,
                 CASE {names[8]} {class_case} ELSE NULL END AS cls,
                 TRY_CAST({names[18]} AS INT) AS field_size
          FROM raw
          WHERE {names[10]} NOT IN ('2', '3')
        )
        SELECT cls, field_size, count(*) FROM races
        WHERE cls IS NOT NULL AND field_size BETWEEN 5 AND 18
        GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()

    out = defaultdict(dict)
    for cls, size, n in rows:
        out[cls][str(size)] = n
    return dict(out)


def main():
    if not os.path.exists(SRC_CSV):
        sys.exit(f"元データが見つかりません: {SRC_CSV}")

    rng = random.Random(SEED)
    con = duckdb.connect()

    templates = load_templates(con)
    print(f"テンプレート: {len(templates):,}頭（{MIN_STARTS}走以上の実在馬）")

    banned = real_name_sets(con)
    print(f"実在名: {len(banned):,}件（衝突チェック用）")

    name_maker = NameMaker([n for n in banned if 2 <= len(n) <= 9], rng)

    # 種牡馬名も架空にする。実在の血統名を持ち出さないため。
    sire_pool = []
    for _ in range(160):
        s = name_maker.make(banned)
        if s:
            sire_pool.append(s)
    print(f"架空の種牡馬名: {len(sire_pool)}件")

    # クラス×主戦場×距離区分ごとに最低頭数を確保しつつ、全体の分布は実データに従う
    # ⭕ 距離区分を入れずに芝ダだけで切っていたときは、長距離適性を持つ馬が
    #    クラスごとに1〜2頭しか生成されず、3000m戦を組もうとすると距離適性Dの馬で
    #    過半数が埋まった。実際の長距離戦は中距離主戦の馬が中心なので、
    #    「long のシェアが25%以上」を長距離対応とみなして確保する。
    by_bucket = defaultdict(list)
    for t in templates:
        by_bucket[template_bucket(t)].append(t)

    by_bucket = {k: v for k, v in by_bucket.items() if len(v) >= MIN_TEMPLATES}
    total = sum(len(v) for v in by_bucket.values())
    quota = {}
    for key, items in by_bucket.items():
        quota[key] = max(MIN_PER_BUCKET, round(TARGET_POOL * len(items) / total))

    rivals = []
    for key, items in sorted(by_bucket.items()):
        for _ in range(quota[key]):
            r = make_rival(rng, rng.choice(items), name_maker, banned, sire_pool)
            if r:
                rivals.append(r)
    rng.shuffle(rivals)

    result = {
        'meta': {
            'source': os.path.basename(SRC_CSV),
            'templates': len(templates),
            'min_starts': MIN_STARTS,
            'seed': SEED,
            'count': len(rivals),
            'generated_at': datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
            'note': '実データの分布から生成した架空馬。実在の馬名・血統名は含まない。',
        },
        'field_size': field_size_distribution(con),
        'horses': rivals,
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

    print(f"書き出し: {OUT_JSON} ({os.path.getsize(OUT_JSON):,} bytes)")
    print(f"  頭数: {len(rivals):,}")
    counts = Counter(bucket_of(r) for r in rivals)
    print("  クラス×主戦場:", dict(sorted(counts.items())))
    long_ok = Counter(r['class'] for r in rivals if r['aptitude']['long'] in 'AB')
    print("  長距離をこなす馬:", dict(sorted(long_ok.items())))
    # ⭕ 脚質はレースごとに出走メンバー内で順位づけして決まる（rivals.build_field）。
    #    ここでは個体の位置取り傾向の散らばりだけを確認する。
    tendency = Counter('前' if r['pos_mean'] < 0.38 else ('後' if r['pos_mean'] > 0.6 else '中')
                       for r in rivals)
    print("  位置取り傾向:", dict(tendency))
    print("  名前の長さ:", dict(sorted(Counter(len(r['name']) for r in rivals).items())))
    print("  名前サンプル:", [r['name'] for r in rivals[:10]])
    print("  種牡馬サンプル:", sire_pool[:6])


if __name__ == '__main__':
    main()
