# AMeDAS station data: a one-off manual pull

JMA's download portal caps each request, so this is a chunked manual pull (no scheduled scraping).
Licence: JMA Public Data License; the site credits 出典：気象庁ホームページ.

Stations (snow-depth reporting; Niseko has no snow station):

| Station | 日本語 | AMeDAS no. |
|---|---|---|
| Kutchan | 倶知安 | 16917 |
| Rankoshi | 蘭越 | 16915 |
| Otaru | 小樽 | 16903 |
| Sapporo | 札幌 | 14913 |
| Asahikawa | 旭川 | 12927 |

Steps at https://www.data.jma.go.jp/risk/obsdl/index.php:

1. 地点を選ぶ: 北海道 → 後志 (Kutchan, Rankoshi, Otaru) / 石狩 (Sapporo) / 上川 (Asahikawa).
2. 項目を選ぶ: データの種類 = 日別値; tick 降雪量合計, 最深積雪, 降水量の合計, 平均気温.
3. 期間を選ぶ: one winter at a time (1 Nov → 30 Apr) to stay under the request cap; 2004/05 → 2025/26.
4. 表示オプション: keep defaults (CSV, Shift-JIS, 品質情報 columns are fine; the parser skips them).
5. Download and save each file as `state/amedas/<winter>_<group>.csv` (any name; all CSVs in the folder are read).

Then `python -c "from dokayuki.fetch.amedas import load_amedas_dir; print(load_amedas_dir('state/amedas').groupby(['station','element']).size())"`.
The analysis script joins the weekly station snowfall to SNOW-W (correlation, tercile agreement) and
uses the stations as the second scoring target.
