# mt5-trader-skill

**Darija:** 12 skills l Claude bach tkhdem m3a MetaTrader 5: t7allel l symbols, tfilter
l watchlist, tsawb l lots mn spec dyal l broker, t7mi rassek b risk gate, w tsift order
ghir mn be3d ma tgoul "yes" l dak l order b3ino. Paper/demo l'owwel, w bla API key.

**English:** 12 Claude skills that drive MetaTrader 5 from Python: analyse your symbols,
screen your watchlist, size lots from the broker's own contract spec, gate every trade
through hard risk limits, and place nothing until you say yes to that exact order.
Paper first, no API key, standard library only.

Had l'pack howa port dyal [trader-skill](https://github.com/Jakeschincariol/trader-skill)
mn les actions US (SEC 13F, Congress, Alpaca) l MT5: forex, gold, indices, crypto CFDs,
ay symbol 3nd broker dyalek.

---

## Chno kayn fih / What is in it

| skill | English | Darija |
| --- | --- | --- |
| `/mt5-core` | MT5 Link: connection, specs, quotes, positions, doctor | l'wassla l MT5 + doctor |
| `/mt5-analyst` | ATR, ADR, RSI, trend, spread, swaps, suggested stop | chno kaydir l symbol b l'ar9am |
| `/mt5-screener` | screens your universe against your rules, ranks it | tfilter l watchlist |
| `/mt5-copycat` | copies a statement/portfolio into target weights | tcopy portfolio dyal chi 7ed |
| `/mt5-budget` | weights → lots, SL/TP, risk budget, margin | 9addech mn lot w fin l stop |
| `/mt5-risk` | PASS/BLOCK every order against your limits | l'babbas: PASS wla BLOCK |
| `/mt5-broker` | the only one that can send, one order, one yes | li kay-sift l'order |
| `/mt5-journal` | win rate, profit factor, expectancy, drawdown | chno 3mlt bssa7 |
| `/mt5-alerts` | price/spread/session alerts + market clock | alertes w l'wa9t dyal l'sessions |
| `/mt5-exposure` | currency tilt, drift, rebalance proposals | ch7al m3arred l'USD |
| `/mt5-calendar` | economic calendar + news blackout windows | l'agenda w blackout dyal news |
| `/mt5-news` | headlines that touch your pairs | l'akhbar li tqiss l pairs dyalek |

---

## L'chain / The chain

```
analyst -> screener -> budget -> risk -> broker      (pick your own)
copycat -------------> budget -> risk -> broker      (copy a book)
exposure / rebalance -> budget -> risk -> broker     (maintain)
news / calendar / alerts / journal                    (watch, on a schedule)
```

Kol skill kayqra f `trader/` w kaykteb f `trader/`. L'order ma t9der tji ghir mn
`mt5-broker`, w ghir ila `mt5-risk` 3tat PASS liha hiya b3inha lyoum.

---

## Install (5 dqayq) / Install (5 minutes)

```bash
git clone https://github.com/Mehdi097/Mehdi097.git
cp -r Mehdi097/mt5-trader-skill/mt5-* ~/.claude/skills/
```

Wla project-local / or project-local:

```bash
cp -r Mehdi097/mt5-trader-skill/mt5-* your-project/.claude/skills/
```

Wla as a plugin / or as a plugin, in Claude Code:

```
/plugin marketplace add Mehdi097/Mehdi097
/plugin install mt5-trader-skill@mt5-trader-skill
```

Mn be3d, f l'machine li fiha MT5 (Windows):

```bash
pip install MetaTrader5
python mt5-core/doctor.py --init
python mt5-core/doctor.py                # khass koulchi OK
```

L'khatwat b tafsil (env vars, AutoTrading, terminal path, errors): **[SETUP.md](SETUP.md)**.

Bghit ghir tjerreb bla MT5 (offline snapshot):

```bash
python mt5-core/doctor.py --init --offline
python mt5-analyst/analyst.py --offline --write
```

---

## Exe: bla Python / standalone .exe

Bghit bla Python f l'PC? Kayn `mt5trader.exe`: fichier wa7ed fih l'pack kamel, b menu
ila dert double-click, w b commandes ila khdemti mn `cmd`.

```powershell
mt5trader.exe setup
mt5trader.exe doctor
mt5trader.exe analyze --write
mt5trader.exe screen --show-fails --write-targets
mt5trader.exe plan --write
mt5trader.exe check
mt5trader.exe tickets
```

Kifach tjibo (t-tlata khedmin):

1. **b yeddik, 2 dqayq 3la Windows**: doubli klik 3la `mt5-app/build_exe.bat`
   → kaytle3 `mt5-app/dist/mt5trader.exe`
2. **GitHub Actions**: copier `ci/build-exe.yml` l `.github/workflows/build-exe.yml`
   (Add file → Create new file f l web UI), mn be3d **Actions → build-exe** → artifact,
   wla **Releases → `exe-latest`**
3. bla exe 7etta: `python mt5-app/runner.py` — nefs l'menu, nefs l'commandes

Koulchi mfesser f **[BUILD-EXE.md](BUILD-EXE.md)**.

L'exe ma kayghnich 3la MetaTrader: **l'terminal khass ykoun installé w mfto7**, w
AutoTrading khass ykoun ON. Machi daemon: jadwal → Task Scheduler.

---

## Copy-paste prompt

Fichier **[PROMPT.md](PROMPT.md)** fih l'bloc li kat-ls9o f Claude bach yinstalli l'skills w
y9ra l'chain. L'bloc l'qssir:

```
https://github.com/Mehdi097/Mehdi097/tree/main/mt5-trader-skill

install skill
```

Wla bla Claude Code: ls9 ay `SKILL.md` f l'awwel dyal l'chat, kaykhdem b7al mode.

---

## L'commandes / The commands

```bash
python3 mt5-core/doctor.py --init                      # trader/ + checklist
python3 mt5-core/bridge.py symbols --search XAU        # smiya s7i7a dyal l'symbol
python3 mt5-core/bridge.py snapshot --write            # offline copy

python3 mt5-analyst/analyst.py --write                 # -> trader/metrics.json
python3 mt5-screener/screen.py --show-fails --write-targets
python3 mt5-copycat/copy.py statement source.csv --top 5 --write
python3 mt5-budget/size.py --write                     # -> trader/orders.json
python3 mt5-risk/check.py                              # PASS / BLOCK
python3 mt5-broker/execute.py show                     # READY wla BLOCKED
python3 mt5-broker/execute.py approve --id ID --reply "yes"
python3 mt5-broker/execute.py send --id ID --dry-run
python3 mt5-broker/execute.py send --id ID

python3 mt5-journal/journal.py --days 30
python3 mt5-alerts/alerts.py ; python3 mt5-alerts/alerts.py clock
python3 mt5-exposure/rebalance.py --band 5
python3 mt5-calendar/econ.py --mine --write
python3 mt5-news/news.py --hours 12
```

---

## Kifach kay7seb l'lot / How the lot is computed

Machi `1 lot = 100,000` hard-coded. Kayqra l'spec dyal l'symbol:

```
risk_money   = equity x risk_pct / 100
loss_per_lot = (SL_distance / point) x value_per_point
volume       = risk_money / loss_per_lot        (rounded DOWN to the lot step)
```

Mn be3d kaychecki `volume_min`, `volume_max`, `max_lots_per_order`, `max_total_lots`,
`trade_stops_level`, w l'margin l'7or. Ila `volume_min` bo7dha bghat risk kbar mn li
sme7ti bih → l'trade **kaytskip** b l'ar9am, machi kaytqaddem l fo9.

**English:** the lot comes from the symbol's own spec, never from an assumed pip value.
Wider stop, smaller lot, same money at risk. If the broker's minimum lot would risk more
than your cap, the trade is skipped with the numbers printed, not rounded up.

---

## La sécurité / Safety

- **Bla yes, bla order.** `mt5-broker` kay9bel ghir yes wa7ed 3la order wa7ed. "yes to
  all", "ok", "sure", w kol kelma fiha chouk → mardouda.
- **Risk gate 9bel koulchi.** Kill switch (`trader/state/KILL`), daily loss limit,
  drawdown limit, margin level floor, spread cap, news blackout, max lots, SL obligatoire.
- **Compte real m7bous b default.** `allow_live: false` + `--live` bach t7ello b yeddik.
- **Credentials f environment.** `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`.
  3emrek ma tketbhom f JSON wla f chat.
- **Demo l'owwel.** Khdem b demo chher kamel 9bel ma tfekker f real.
- **Koulchi mkteb.** `trader/state/broker.json`, `journal.jsonl`, `risk.json` — records,
  machi souvenirs.

---

## Files

```
mt5-trader-skill/
  README.md  SETUP.md  PROMPT.md  LICENSE
  .claude-plugin/        plugin.json, marketplace.json
  mt5-core/              bridge.py, sizing.py, doctor.py, config.example.json, symbols.example.json
  mt5-analyst/           SKILL.md, analyst.py
  mt5-screener/          SKILL.md, screen.py, rules.example.json
  mt5-copycat/           SKILL.md, copy.py
  mt5-budget/            SKILL.md, size.py
  mt5-risk/              SKILL.md, check.py
  mt5-broker/            SKILL.md, execute.py
  mt5-journal/           SKILL.md, journal.py
  mt5-alerts/            SKILL.md, alerts.py, alerts.example.json
  mt5-exposure/          SKILL.md, rebalance.py
  mt5-calendar/          SKILL.md, econ.py
  mt5-news/              SKILL.md, news.py
  mt5-app/               runner.py, mt5trader.spec, build_exe.py, build_exe.bat
  tests/                 unittest suite + an offline snapshot fixture
```

Tests:

```bash
cd mt5-trader-skill
python3 -m unittest discover -s tests -t tests -v
```

Kaykhedmo offline, bla MT5, bla internet: 139 tests 3la l'arithmetic dyal l'lot, l'risk
gate, l'fingerprints, l'executor, l'stats, w l'spec dyal l'symbols.

---

## Fine print

**Machi nas7a maliya.** Hada software kayqra data 3amma w kaydir hisab. Ma ya3refch
l'wad3iya dyalek, ma y3refch l'mustaqbal, w l'leverage t9der tkhessek b sor3a.
**Not financial advice.** This is software that reads market data and does arithmetic.
Leverage can lose you more than you expect. Demo first, size small, and talk to a
licensed professional if you need advice.

**L'data katji mn l'terminal dyalek.** Il suffit que l'broker ybeddel l'smeya dyal
l'symbol, l'filling mode, wla `stops_level`, bach l'orders ytbeddlo: doctor w l'spec
kayqrawha mn l'terminal kol mrra, machi mn l'memory.

**Offline mode machi trading.** `trader/data/snapshot.json` howa copie dyal chi wa9t;
`send` fih kayrje3 `SIMULATED`, w kaykteb f `sim_fills.json`. Ma kaytsift walo.

**MetaTrader5 package Windows-only.** 3la Mac/Linux khdem b `--offline` l l'analyse w
l'sizing, w khelli l'sending l chi Windows machine wla VPS.

MIT. Port dyal l'idée dyal [Jake Schincariol](https://opusjake.ai) (trader-skill) l MT5.
