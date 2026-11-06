# SETUP - mn zéro l order 3la demo / from zero to an order on demo

Had l'fichier kaywesslek mn machine khawya l chain kamla khedma 3la compte **demo**.
L'compte real kayji mn be3d, w b yeddik.

This file takes a fresh Windows machine to the full chain running on a **demo**
account. Real money comes later, and on purpose.

---

## 0. Chnou khassek / What you need

- Windows 10/11 (l'package `MetaTrader5` Windows-only / Windows only)
- MetaTrader 5 mn l'broker dyalek (machi ghir MetaQuotes demo ila bghit l'broker dyalek)
- Python 3.8 – 3.13, **64-bit** (b7al l'terminal)
- Compte demo mfto7 f l'terminal

> VPS Windows rkhis (2 GB RAM) howa l'7all ila bghit l'bot ykhdem 24/7. L'terminal
> khass ykoun mfto7, w l'machine ma tn3ssch.

---

## 1. MT5: 7ell l'compte demo w 7ell AutoTrading

1. 7ell MetaTrader 5 → `File → Open an Account` → `Demo` → 3emmer l'form → `Next`.
2. Klik 3la l'boton **AutoTrading** f l' toolbar bach ywelli khder.
3. `Tools → Options → Expert Advisors` → ✅ `Allow algorithmic trading`.
4. Khelli l'terminal mfto7. Ila tsedd, l'Python ma yl9ach l'connection.

English: open a demo account, turn AutoTrading on in the toolbar, allow algorithmic
trading in Options, and leave the terminal running.

---

## 2. Python + package

```powershell
python --version                 # 3.8 wla kter, khass ykoun 64-bit
pip install MetaTrader5
```

Ila `pip` ma kaynch: 3awed installi Python mn python.org w 3ellem ✅ `Add python.exe to PATH`.

Jarreb:

```powershell
python -c "import MetaTrader5 as m; print(m.__version__, m.initialize()); m.shutdown()"
```

Ila tle3 `True` → mzyan. Ila `False` → chouf l'jadwal dyal l'errors f l'akhir.

---

## 3. L'pack

```powershell
git clone https://github.com/Mehdi097/Mehdi097.git
cd Mehdi097\mt5-trader-skill
```

Wla copy dyal l'folders l `~/.claude/skills/` bach Claude yel9ahom f kol projet.

---

## 4. `doctor.py` - l'checklist

```powershell
python mt5-core\doctor.py --init
```

Kaycreyi `trader\`:

```
trader\config.json      # l'limites + terminal path + magic
trader\symbols.json     # l'universe dyalek
trader\state\           # records
trader\data\            # snapshots (offline / calendar / news)
```

3emmer `trader\config.json`:

```json
{
  "terminal_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
  "login": 51234567,
  "server": "MetaQuotes-Demo",
  "symbol_suffix": "",
  "portfolio_risk_pct": 3.0,
  "risk_pct_per_trade": 0.5,
  "max_risk_pct_per_trade": 1.0,
  "max_lots_per_order": 0.5,
  "max_total_lots": 1.5,
  "max_open_positions": 4,
  "max_daily_loss_pct": 2.0,
  "max_drawdown_pct": 10.0,
  "min_margin_level_pct": 300,
  "max_spread_points": 25,
  "require_sl": true,
  "allow_live": false
}
```

Mn be3d:

```powershell
python mt5-core\doctor.py
```

Khass tchouf `OK` f koulchi. Ila symbol ma kaynch → sift smiya s7i7a:

```powershell
python mt5-core\bridge.py symbols --search XAU
python mt5-core\bridge.py symbols --search EUR
```

Ba3d 9ad `trader\symbols.json` b l'smiyat li l9iti. Ila broker kayzid suffix (`.raw`, `m`,
`.pro`) → 7ello f `"symbol_suffix"` wla kteb l'smiyat kamla f symbols.json.

---

## 5. Credentials: environment variables, machi JSON

```powershell
setx MT5_LOGIN "51234567"
setx MT5_PASSWORD "your-demo-password"
setx MT5_SERVER "MetaQuotes-Demo"
setx MT5_PATH "C:\Program Files\MetaTrader 5\terminal64.exe"
```

Sedd w 7ell PowerShell mn be3d `setx`. Ila ma 7ettitich password, l'Python kaykhedem
b l'compte li deja mfto7 f l'terminal — hadi hiya l'as'hal w l'akthar amana.

**3emrek** ma tketb l'password f `config.json`, f chat, wla f screenshot.

---

## 6. L'awwel chain kamla (demo)

```powershell
python mt5-analyst\analyst.py --write
# chouf: trader\metrics.json
```

```powershell
copy mt5-screener\rules.example.json trader\rules.json
python mt5-screener\screen.py --show-fails --write-targets
# chouf: trader\targets.json
```

```powershell
python mt5-budget\size.py --write
# chouf: trader\orders.json  (volume, SL, TP, risk %)
```

```powershell
python mt5-risk\check.py
# PASS / BLOCK + l'sabab
```

```powershell
python mt5-broker\execute.py show
python mt5-broker\execute.py approve --id <ID> --reply "yes"
python mt5-broker\execute.py send --id <ID> --dry-run
python mt5-broker\execute.py send --id <ID>
```

L'order l'owwel 3la demo. 7ello f l'terminal w chouf SL/TP, w 9arn l'volume m3a li
7sebti.

---

## 7. Routine / Schedule

| wa9t | commande |
| --- | --- |
| kol sba7 | `analyst.py --write` → `screen.py --write-targets` → `size.py --write` → `check.py` |
| kol 5 dqayq | `alerts.py` |
| kol nhar 7:30 UTC | `econ.py --mine --write` (blackout l'lyoum) |
| kol joumou3a | `journal.py --days 7` |
| kol chher | `journal.py --days 30 --write` + `rebalance.py --band 5` |

Task Scheduler: `Action → Start a program → python.exe` + arguments, "Run whether user
is logged on or not", w 3ellem `Start in` 3la folder dyal l'pack.

---

## 8. Jdwal l'errors / Error table

| 3lama / symptom | chno kay3ni | l'7all |
| --- | --- | --- |
| `import MetaTrader5` fail | package ma msayebch wla Python 32-bit | `pip install MetaTrader5` b Python 64-bit |
| `initialize() = False`, `-10005` | IPC timeout: terminal msdoud wla path ghalat | 7ell l'terminal, 3emmer `MT5_PATH` |
| `-6 Authorization failed` | login/password/server ghalat | `setx` 3awed, wla khelli l'terminal mfto7 |
| `10027 autotrading disabled` | AutoTrading m7bous | klik l'boton AutoTrading |
| `10030 invalid filling` | filling mode ma kaynch l had symbol | l'executor kay3awed bo7do; ila b9a, 7ett `"type_filling"` f l'order |
| `10016 invalid stops` | SL/TP 9rab bzzaf | `stops_level_points` f l'spec; `size.py` kaywessa3 bo7do |
| `10019 not enough money` | margin ma kfach | n9es `max_total_lots` wla `portfolio_risk_pct` |
| `10018 market closed` | weekend wla session msdouda | `alerts.py clock` |
| `symbol not in Market Watch` | smiya ghalta wla suffix | `bridge.py symbols --search XXX` |
| `CANNOT SET TRADING` / read-only | compte investor password | 3awed b l'master password |
| offline mode bgha snapshot | ma kaynch `trader\data\snapshot.json` | `bridge.py snapshot --write` wla `--live` |

---

## 9. Mn demo l real (b yeddik, machi b default)

1. Demo chher kamel, `journal.py --days 30` w chouf: PF > 1.2, drawdown < li planiti.
2. `"allow_live": true` f config, **w** `--live` f kol send.
3. N9es l'risk l nos (`risk_pct_per_trade: 0.25`, `max_lots_per_order: 0.1`).
4. Khdem b `--dry-run` f l'awwel, 9arn m3a l'terminal.
5. `execute.py kill on` wa9t ay 7aja ma mfhmtich — kaywe9ef koulchi b fichier wa7ed.

`allow_live` howa l'far9 li kayn bin "demo b default" w "real b l'3a9el". Ma tbeddlohch
b zerba.
