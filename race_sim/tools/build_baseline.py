"""実データ（keiba_score_search）からレースシミュレーションの較正基準値を抽出する。

このスクリプトは **discord-task-bot の実行環境では動かない**（duckdb が必要）。
keiba_score_search 側の venv で実行し、成果物の JSON だけをこのリポジトリにコミットする。

    PYTHONIOENCODING=utf-8 ../keiba_score_search/.venv/Scripts/python.exe \
        race_sim/tools/build_baseline.py

出力: race_sim/data/course_baseline.json

⭕ 元CSVはヘッダに空列・重複名があり、`前走`系の列を持つファイルでは列数も異なる。
   そのため列名ではなく「位置」で読む（header=false, skip=1）。列順は
   keiba_score_search/analysis/common.py の COLUMNS と同一。
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import duckdb

# ====================================================
# 入力・出力パス
# ====================================================
HERE = os.path.dirname(os.path.abspath(__file__))
RACE_SIM = os.path.dirname(HERE)
REPO = os.path.dirname(RACE_SIM)
SRC_CSV = os.path.join(os.path.dirname(REPO), 'keiba_score_search', 'data', 'all_utf8.csv')
OUT_JSON = os.path.join(RACE_SIM, 'data', 'course_baseline.json')

# 元CSVの列位置（0始まり）。common.py の COLUMNS と対応する。
COL = {
    'nen': 0, 'tsuki': 1, 'hi': 2, 'basho': 4, 'race_no': 6, 'race_name': 7,
    'class_code': 8, 'surface': 9, 'course_code': 10, 'distance': 11, 'track_cond': 12,
    'horse_name': 13, 'sex': 14, 'age': 15, 'field_size': 18, 'horse_no': 19,
    'finish_pos': 20, 'abnormal_code': 22, 'pop_rank': 24, 'race_time': 25,
    'pass1': 28, 'pass2': 29, 'pass3': 30, 'pass4': 31, 'last3f': 32,
    'race_id': 40, 'sire': 43, 'broodmare_sire': 45, 'win_odds': 48, 'pci': 51,
}

# クラスコード → ゲーム内クラス。
# ⭕ 15(新馬)は108行しかなく統計が取れないため未勝利に含める。
CLASS_MAP = {
    '7': '未勝利', '15': '未勝利',
    '23': '1勝', '43': '2勝', '67': '3勝',
    '115': 'OP', '131': 'OP', '147': 'OP',
    '163': 'G3', '179': 'G2', '195': 'G1',
}
BASE_CLASS = '1勝'   # オフセットの基準クラス（最も行数が多く安定している）
BASE_COND = '良'

# ⭕ 障害レースは course_code '2'(芝) / '3'(ダ)。'8' は芝の外回りで平地。
#    keiba_score_search/analysis/dataset.py は '8' を障害としており、そちらは誤り。
JUMP_COURSE_CODES = ('2', '3')

MIN_CELL_RACES = 20      # この本数に満たないセルは基準値として採用しない


def build_view(con, csv_path):
    """位置指定でCSVを読み、意味のある列名を付けたクリーニング済みビューを作る。"""
    con.execute(
        "CREATE OR REPLACE VIEW raw AS "
        "SELECT * FROM read_csv('" + csv_path + "', header=false, skip=1, "
        "all_varchar=true, ignore_errors=true)"
    )
    names = [d[0] for d in con.execute("SELECT * FROM raw LIMIT 0").description]

    def c(key):
        return names[COL[key]]

    jump = ', '.join("'" + x + "'" for x in JUMP_COURSE_CODES)
    con.execute(f"""
        CREATE OR REPLACE VIEW runners AS
        SELECT
            substr({c('race_id')}, 1, length({c('race_id')}) - 2) AS race_key,
            {c('basho')}                         AS basho,
            {c('surface')}                       AS surface,
            {c('course_code')}                   AS course_code,
            {c('class_code')}                    AS class_code,
            {c('track_cond')}                    AS track_cond,
            TRY_CAST({c('distance')} AS INT)     AS distance,
            TRY_CAST({c('finish_pos')} AS INT)   AS finish_pos,
            {c('abnormal_code')}                 AS abnormal_code,
            TRY_CAST({c('race_time')} AS DOUBLE) AS race_time,
            TRY_CAST({c('last3f')} AS DOUBLE)    AS last3f,
            TRY_CAST({c('pop_rank')} AS INT)     AS pop_rank,
            TRY_CAST({c('field_size')} AS INT)   AS field_size,
            TRY_CAST({c('pass1')} AS INT)        AS pass1,
            TRY_CAST({c('pass4')} AS INT)        AS pass4,
            TRY_CAST({c('pci')} AS DOUBLE)       AS pci,
            TRY_CAST({c('nen')} AS INT)          AS nen
        FROM raw
        WHERE {c('course_code')} NOT IN ({jump})
          AND {c('abnormal_code')} = '0'
          AND TRY_CAST({c('finish_pos')} AS INT) >= 1
          AND TRY_CAST({c('race_time')} AS DOUBLE) > 0
          AND TRY_CAST({c('distance')} AS INT) IS NOT NULL
    """)

    class_case = ' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in CLASS_MAP.items())
    con.execute(f"""
        CREATE OR REPLACE VIEW runners2 AS
        SELECT *,
          race_time - min(race_time) OVER (PARTITION BY race_key) AS margin,
          count(*)  OVER (PARTITION BY race_key)                  AS n_finish,
          CASE class_code {class_case} ELSE NULL END               AS cls
        FROM runners
    """)


def q(con, sql):
    return con.execute(sql).fetchall()


def fit_additive(con, iterations=30):
    """走破タイムを「コース基準 ＋ クラス補正 ＋ 馬場補正」の加法モデルに分解する。

        勝ちタイム ≈ base[場所|芝ダ|距離] + class_offset[クラス] + cond_offset[芝ダ|馬場]

    ⭕ セルごとの平均を直接比べる方法（同一コース内のペア比較）を最初に試したが、
       群によって含まれるコースの構成比が違うため、G3が3勝クラスより遅いという
       非単調が出た。さらに G2 と不良馬場はセル本数が閾値に届かず欠落した。
       ここでは3つの効果を交互に最小二乗で当てはめる。各パラメータは全データを
       使って推定されるので、出走の少ない群にも値が付き、構成比の偏りも吸収される。

    Returns:
        tuple: (base, class_offset, cond_offset, fit_stats)
    """
    winners = q(con, """
        SELECT basho, surface, distance, cls, track_cond, race_time, last3f, field_size
        FROM runners2
        WHERE finish_pos = 1 AND cls IS NOT NULL AND last3f > 0
    """)

    rows = [
        (f"{b}|{s}|{d}", cls, f"{s}|{tc}", t, l3, fs)
        for b, s, d, cls, tc, t, l3, fs in winners
    ]

    course_keys = {r[0] for r in rows}
    class_keys = {r[1] for r in rows}
    cond_keys = {r[2] for r in rows}

    base = {k: 0.0 for k in course_keys}
    class_off = {k: 0.0 for k in class_keys}
    cond_off = {k: 0.0 for k in cond_keys}

    def mean_residual_by(index, current):
        """指定した次元でグループ化し、他の効果を差し引いた残差の平均を返す。"""
        acc = {k: [0.0, 0] for k in current}
        for r in rows:
            key = r[index]
            resid = r[3] - base[r[0]] - class_off[r[1]] - cond_off[r[2]] + current[key]
            acc[key][0] += resid
            acc[key][1] += 1
        return {k: (s / n if n else 0.0) for k, (s, n) in acc.items()}

    for _ in range(iterations):
        base = mean_residual_by(0, base)
        class_off = mean_residual_by(1, class_off)
        cond_off = mean_residual_by(2, cond_off)
        # 定数項の重複を防ぐため、基準クラス・基準馬場を0に固定してコース側へ寄せる
        anchor_c = class_off[BASE_CLASS]
        for k in class_off:
            class_off[k] -= anchor_c
        for s in {c.split('|')[0] for c in cond_keys}:
            anchor_t = cond_off.get(f"{s}|{BASE_COND}", 0.0)
            for k in cond_off:
                if k.startswith(s + '|'):
                    cond_off[k] -= anchor_t
        for k in base:
            base[k] += anchor_c

    # 当てはまりの確認とコース別のばらつき
    per_course = {k: [0, 0.0, 0.0, 0.0, 0.0] for k in course_keys}  # n, Σresid, Σresid², Σl3f, Σfield
    sse = 0.0
    for course, cls, cond, t, l3, fs in rows:
        resid = t - base[course] - class_off[cls] - cond_off[cond]
        sse += resid * resid
        p = per_course[course]
        p[0] += 1
        p[1] += resid
        p[2] += resid * resid
        p[3] += l3 or 0.0
        p[4] += fs or 0.0

    base_out = {}
    for k, (n, s1, s2, sl, sf) in per_course.items():
        if n < MIN_CELL_RACES:
            continue
        var = max(0.0, s2 / n - (s1 / n) ** 2)
        base_out[k] = {
            'n': n,
            'win_time': round(base[k], 2),
            'win_time_sd': round(var ** 0.5, 2),
            'last3f': round(sl / n, 2),
            'field': round(sf / n, 1),
        }

    n_rows = len(rows)
    dropped = sum(v[0] for k, v in per_course.items() if k not in base_out)
    stats = {
        'winners': n_rows,
        'rmse': round((sse / n_rows) ** 0.5, 3),
        'courses_kept': len(base_out),
        'courses_dropped': len(course_keys) - len(base_out),
        'rows_dropped': dropped,
    }

    class_out = {k: {'offset': round(v, 3)} for k, v in sorted(class_off.items())}
    cond_out = {k: {'offset': round(v, 3)} for k, v in sorted(cond_off.items())}
    for k, cnt in count_by(rows, 1).items():
        class_out[k]['n'] = cnt
    for k, cnt in count_by(rows, 2).items():
        cond_out[k]['n'] = cnt

    return base_out, class_out, cond_out, stats


def count_by(rows, index):
    acc = {}
    for r in rows:
        acc[r[index]] = acc.get(r[index], 0) + 1
    return acc


def collect_last3f_class(con):
    """上がり3Fのクラス別の差。同一コース内のペア比較で基準クラスとの差を取る。

    ⭕ コース平均の上がり3Fだけを基準にすると、上のクラスほど速いという当然の傾向が
       誤差に見えてしまい、較正の判定が甘くなる。
    """
    rows = q(con, f"""
        WITH win AS (
          SELECT basho, surface, distance, cls, last3f
          FROM runners2
          WHERE finish_pos = 1 AND cls IS NOT NULL AND last3f > 0 AND track_cond = '{BASE_COND}'
        ),
        cell AS (
          SELECT basho, surface, distance, cls, count(*) n, avg(last3f) l
          FROM win GROUP BY 1,2,3,4 HAVING count(*) >= {MIN_CELL_RACES}
        ),
        ref AS (
          SELECT basho, surface, distance, l AS l_ref FROM cell WHERE cls = '{BASE_CLASS}'
        )
        SELECT c.cls, sum(c.n) n, sum((c.l - r.l_ref) * c.n) / sum(c.n) AS offset_sec
        FROM cell c JOIN ref r
          ON c.basho = r.basho AND c.surface = r.surface AND c.distance = r.distance
        GROUP BY 1 ORDER BY 1
    """)
    return {cls: {'n': n, 'offset': round(off, 3)} for cls, n, off in rows}


def collect_margins(con):
    """着差（勝ち馬との秒差）の分布。シミュレータの「ばらつき」の較正目標になる。"""
    out = {}
    for pos in range(2, 6):
        n, q10, q25, q50, q75, q90, mean = q(con, f"""
            SELECT count(*) n,
                   quantile_cont(margin, 0.10) q10,
                   quantile_cont(margin, 0.25) q25,
                   quantile_cont(margin, 0.50) q50,
                   quantile_cont(margin, 0.75) q75,
                   quantile_cont(margin, 0.90) q90,
                   avg(margin) mean
            FROM runners2 WHERE finish_pos = {pos} AND margin >= 0 AND margin < 30
        """)[0]
        out[str(pos)] = {
            'n': n, 'mean': round(mean, 3),
            'q10': round(q10, 2), 'q25': round(q25, 2), 'q50': round(q50, 2),
            'q75': round(q75, 2), 'q90': round(q90, 2),
        }
    return out


def collect_style(con):
    """脚質分布と脚質別の勝率。4コーナー通過順を頭数で正規化して分類する。"""
    rows = q(con, """
        WITH t AS (
          SELECT surface,
            CASE
              WHEN pass4 IS NULL OR n_finish < 5 THEN NULL
              WHEN pass4 <= 1                    THEN '逃げ'
              WHEN pass4 <= n_finish * 0.33      THEN '先行'
              WHEN pass4 <= n_finish * 0.66      THEN '差し'
              ELSE '追込'
            END AS style,
            finish_pos
          FROM runners2
        )
        SELECT surface, style, count(*) n,
               avg(CASE WHEN finish_pos = 1 THEN 1.0 ELSE 0.0 END) win_rate
        FROM t WHERE style IS NOT NULL GROUP BY 1,2 ORDER BY 1,2
    """)
    return {f"{s}|{st}": {'n': n, 'win_rate': round(wr, 4)} for s, st, n, wr in rows}


def collect_favorite_hit(con):
    """人気順ごとの勝率・複勝率。「順当すぎないか」を測る較正目標。"""
    rows = q(con, """
        SELECT pop_rank, count(*) n,
               avg(CASE WHEN finish_pos = 1 THEN 1.0 ELSE 0.0 END) win_rate,
               avg(CASE WHEN finish_pos <= 3 THEN 1.0 ELSE 0.0 END) show_rate
        FROM runners2
        WHERE pop_rank BETWEEN 1 AND 18 AND n_finish >= 8
        GROUP BY 1 ORDER BY 1
    """)
    return {str(p): {'n': n, 'win_rate': round(w, 4), 'show_rate': round(s, 4)}
            for p, n, w, s in rows}


def main():
    if not os.path.exists(SRC_CSV):
        sys.exit(f"元データが見つかりません: {SRC_CSV}")

    con = duckdb.connect()
    build_view(con, SRC_CSV.replace('\\', '/'))

    total, races, y0, y1 = q(con, """
        SELECT count(*), count(DISTINCT race_key), min(nen), max(nen) FROM runners2
    """)[0]
    print(f"対象: {total:,}行 / {races:,}レース (20{y0}-20{y1})")

    base, class_off, cond_off, fit = fit_additive(con)

    result = {
        'meta': {
            'source': os.path.basename(SRC_CSV),
            'rows': total, 'races': races,
            'years': f"20{y0}-20{y1}",
            'base_class': BASE_CLASS, 'base_cond': BASE_COND,
            'min_cell_races': MIN_CELL_RACES,
            'fit': fit,
            'generated_at': datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
        },
        'base': base,
        'class_offset': class_off,
        'cond_offset': cond_off,
        'last3f_class_offset': collect_last3f_class(con),
        'margin': collect_margins(con),
        'style': collect_style(con),
        'favorite': collect_favorite_hit(con),
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"書き出し: {OUT_JSON} ({os.path.getsize(OUT_JSON):,} bytes)")
    print(f"  当てはまり: RMSE {fit['rmse']}秒 / 勝ち馬{fit['winners']:,}行")
    print(f"  基準コース: {fit['courses_kept']}件（本数不足で不採用 {fit['courses_dropped']}件 = {fit['rows_dropped']}行）")
    print("  クラス補正(秒):", {k: v['offset'] for k, v in class_off.items()})
    print("  馬場補正(秒):", {k: v['offset'] for k, v in cond_off.items()})
    print("  上がり3Fのクラス差(秒):", {k: v['offset'] for k, v in result['last3f_class_offset'].items()})
    print("  着差(2着):", result['margin']['2'])
    print("  脚質別勝率:", {k: v['win_rate'] for k, v in result['style'].items()})

    # クラスが上がるほど速くなっているか（ゲームの手触りに直結するので必ず確認する）
    order = ['未勝利', '1勝', '2勝', '3勝', 'OP', 'G3', 'G2', 'G1']
    seq = [(c, class_off[c]['offset']) for c in order if c in class_off]
    bad = [(a, b) for (a, va), (b, vb) in zip(seq, seq[1:]) if vb > va]
    print("  クラス単調性:", "OK" if not bad else f"NG {bad}")
    for name in ('東京|芝|1600', '中山|芝|2000', '東京|ダ|1400'):
        if name in base:
            print(f"  参考 {name} 1勝クラス良: {base[name]['win_time']}秒 (n={base[name]['n']})")


if __name__ == '__main__':
    main()
