# Design

**Visual system (2026-10-15):** the author's house system. Paper, ink, hairlines, mono tabular
numbers, one vermilion mark per figure (the favoured tercile or bin), IBM Plex. No cards, shadows,
pills, badges, gradients or icons. The HokkaidoWilds tie is the diamond logo, the "part of" line
and the credits. The HokkaidoWilds palette notes below are kept for provenance only.

The dashboard is a HokkaidoWilds-family page, so its tokens come from the live site
(https://hokkaidowilds.org, WordPress + Astra theme + Elementor; studied 2026-10-14: homepage,
the ski-touring listing `/skitour`, and the route page `/ski-touring/hobetsu-bozu-yama`).
Tokens are in `site/design-tokens.css`.

## Where each token came from

| Token | Value | Source on the live site |
|---|---|---|
| Body font | Lato 400, 15px / 1rem, line-height 1.65 | Astra inline CSS: `body,button,input… {font-family:'Lato',sans-serif;font-weight:400;font-size:15px;line-height:1.65em}`; Google Fonts request `css?family=Lato:400` |
| Heading/accent font | Lato 700 / 500 | Elementor kit 35601: `--e-global-typography-primary-font-weight:700`, accent 500 |
| Display font | Jaapokki (custom, a few feature titles) | `.elementor-element-ef359eb{font-family:"Jaapokki";font-weight:900}`; not a Google Font and not redistributed here → fallback Lato 900 |
| Japanese | Noto Sans JP | present in site CSS (`font-family: 'Noto Sans JP'`) |
| Link blue | #427fc1 | Astra customiser `a{color:#427fc1}`; `.transtablepagenumb{background:#427FC1}`; darkened to #2f6aa8 on white for WCAG AA |
| Link hover / CTA red | #e01c1e, hover #b90001 | `a:hover,a:focus{color:#e01c1e}`; `.elementor-button-link.elementor-button{background:#E01C1E}` / `:hover{background:#B90001}` |
| Deep heading blue | #063077 | `.accordianformian .gfield_list_header{color:#063077}` |
| Logo blues / red | #185078, #2868a0, #4078c0, #e01818 | sampled from `logo-retina-410.png` |
| Kit green | #23a455 | `--e-global-color-183ba068:#23A455` |
| Text grey | #3a3a3a (Astra global), #808285 (body) | `--ast-global-color-1:#3a3a3a`; `body{color:#808285}` |
| Border grey | #eaeaea | `.main-header-menu.submenu-with-border .sub-menu{border-color:#eaeaea}` |
| Header | white bar, menu text #0a0101 | `.main-header-bar{background-color:#fff}`; `.main-header-menu .menu-link{color:#0a0101}` |
| Footer rule | #7a7a7a | `.ast-small-footer{border-top-color:#7a7a7a}` |
| Radius | 2–6 px (cards 4 px) | most frequent `border-radius` values in the minified CSS: 2px, 3px, 6px |
| Difficulty rubric colours | A #c4201f, B #ff8f76, C #6cdc88, D #068e41 | route page `/* DIFFICULTY TABLE */ .diffA…{…}`, small-caps `.diffcellmainhead` 0.8em |
| Card style | image-topped cards, uppercase white labels over the image | `.elementor-posts--skin-cards`, `.gridddiffboo,.griddregionboo{… color:white;text-transform:uppercase;font-weight:bold;font-size:13px}` |

## Layout rules

- Mobile-first: one column at 375 px, two at 768 px, three at 1280 px; 16 px gutters; no
  horizontal scroll; tap targets ≥ 44 px.
- Photo-led hero (CSS gradient in the logo blues until a HokkaidoWilds photo is placed in
  `site/assets/photos/`), with the diamond logo, a strong headline, valid dates and freshness.
- Snow-week cards borrow the route-page difficulty rubric: a total (the tercile bar and signal
  grade) broken into contributing factors shown as small bars.
- Diverging colours: temperature blue–white–red (blue = colder = good); snow and pressure
  indices always highlight the "more snow" end in the logo blue; the HokkaidoWilds red is
  reserved for "big snow week" and strong signals.
- Dark mode via `prefers-color-scheme` plus a manual override; contrast pairs checked to AA
  (ink #3a3a3a on white 10.7:1; link #2f6aa8 on white 4.6:1; dark ink #e6e9ec on #0f1418 14:1).
- No tracking, no cookies; the Nerd/Normie mode and theme preferences use `localStorage`.

## Nerd Mode / Normie Mode (spec update 1)

Same page, two depths; **Nerd Mode is a first-class half of the product, not a footnote.**
The toggle sits at the top, Normie is the default, the choice persists per viewer in
`localStorage` (wrapped in try/catch) and `?mode=nerd` / `?mode=normie` shares a view.

**Normie Mode** is the Book-ahead signal (working name; alternative "Beat-the-crowd signal",
set in `config/site.yaml: wording.signal_name`): tercile bar, P(big week), signal grade and one
plain line per week; the ingredient chain as five friendly cards (Trigger → Outbreak → Steering →
Fuel → Delivery), each with an icon, a one-liner and a lining up / neutral / against state per
week; "what's driving things now"; the safety links. Voice: the author's house style. Dry,
terse, first person singular, conclusion first, then the evidence, then the caveat once.
Uncertainty is a number or a condition, never a hedge. Sentence case. No exclamation marks, no
emoji, no "robust", "comprehensive", "delve", "key takeaways". The running gag ("Japow. Alta pow.
Albany pow.*") sits in the header under the title; its footnote ("*Nobody has ever flown to
Albany, NY for the powder. Probably.") sits with the single disclaimer at the end of the page.
One disclaimer, at the end, in small type; nowhere else.
Normie mode also carries a "Built on published work" paragraph: the PBC paper, its predecessor,
and the sea-effect, monsoon, vortex and blocking literature as linked author–year citations. The
`cites()` helper renders a key only when it is verified in `docs/REFERENCES_CHECK.md`, so an
unverified entry silently drops out of the sentence rather than appearing unlinked.

**Copy rule:** never imply certainty. "Week 3 looks better than week 4 for a trip", never
"book Tuesday". No price data or booking links in v1.

**Nerd Mode** adds, per ingredient, the mechanism, the index definition (formula, box, levels),
why it matters at weeks 3–4, its PBC skill and **lift**, with author–year citations; and the
sections Results (lift tables with CIs, reliability, ROC area, windows of opportunity,
experiment-log summary, effective sample size), Methods, Limitations, Reproducibility (commit,
state version, one command) and a numbered References list built from `references.bib`.

**Skill badges lead with the lift** over the operationally debiased model with its 95 %
interval; a non-significant lift reads "no demonstrated improvement over the raw model".

**Citation rules (strict):** every factual or physical claim in nerd mode carries a citation;
every reference is verified (DOI resolves; title, authors, year, venue match; the cited claim
appears in the source) and logged in `docs/REFERENCES_CHECK.md`; unverified references never
appear on the site; nothing is invented. If support cannot be found the claim is softened or
removed.

### Earlier mode notes

**Normie Mode (default)** answers one question: *am I likely to get Japow in weeks 3 and 4?*
It shows the headline, the two snow-week cards reduced to a tercile bar, the "big week" chip
and the signal grade with a plain-English line, the "what's driving things" strip in words,
the safety line and credits. **Nerd Mode** keeps everything and adds: init dates and
freshness details, the factor-contribution bars, skill badges with explainers, the six
circulation-index cards with quintile bars, the maps, the season tracker, and the method links.
The toggle is in the header, keyboard-focusable, remembered per browser.

## Screenshots

Design QA renders three fixture states (strong signal, no signal, stale/not skilful) at 375,
768 and 1280 px in light and dark mode to `docs/screenshots/` (`scripts/design_qa.py`).
