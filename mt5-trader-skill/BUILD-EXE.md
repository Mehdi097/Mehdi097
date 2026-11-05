# BUILD-EXE - mt5trader.exe (bla Python f l'PC)

**Darija:** l'exe howa l'pack kamel f fichier wa7ed. Kat-téléchargih, kat-doubli klik,
kat-chouf menu, khedma. Ma khassekch Python f l'machine — walakin **MetaTrader 5 khass
ykoun installé w mfto7**, 7it l'programme kayhder m3a l'terminal, machi m3a l'internet.

**English:** one file with all twelve skills inside. Double-click, pick from the menu,
done. No Python on the target machine. MetaTrader 5 still has to be installed and
running, because orders and quotes come from the terminal, not from the internet.

---

## Chnou kayn f l'exe / what is inside

| kayn / inside | makaynch / not inside |
| --- | --- |
| 12 skills + l'ar9am dyal l'lot w l'risk | walo mn l'market data dyalek |
| `trader/config.json` w `symbols.json` kaytsaybo f l'awwel run | password wla login (ghir environment variables) |
| MetaTrader5 package + l'DLL dyalha | terminal dyal MT5 (khass ykoun installé 3ndek) |

L'awwel run kaycreyi `trader\` **7da l'exe** (7it l'exe ma kay3refch `cd` dyalek), w
kayncopier fih `config.example.json` → `config.json` w `symbols.example.json` →
`symbols.json`. Ma kaybeddelch 7ta fichier kayn mn 9bel.

---

## 7all A: GitHub Actions (bla Windows dev machine)

L'fichier dyal l'workflow kayn f **`ci/build-exe.yml`**. GitHub kay9ra ghir
`.github/workflows/*.yml`, donc khass tcopier f l'blassa sa7i7a — **b yeddik**, 7it ay
token dyal app ma 3ndhach l'permission `workflows`:

1. Sir l `github.com/Mehdi097/Mehdi097` → **Add file → Create new file**.
2. Smiya: `.github/workflows/build-exe.yml`.
3. Ls9 l'contenu dyal `mt5-trader-skill/ci/build-exe.yml` → **Commit**.
4. Ba3d l'commit, l'build kaytle9 bo7do (wla: **Actions → build-exe → Run workflow**).

Mn be3d l'workflow kaybniha 3la runner Windows 7a9i9i.

1. Rfe3 l'commit (wla khdem `gh workflow run build-exe`).
2. Sir l **Actions → build-exe → l'run l'akhir**.
3. Mn be3d: **Artifacts → `mt5trader-windows-x64`** → téléchargi → fatte7 l'zip.
4. Wla dirett mn **Releases**: tag `exe-latest` fih `mt5trader.exe` (prerelease, kaytbeddel
   m3a kol build).

L'workflow kaydir 9bel l'build: l'tests (139 test offline), w mn be3d **smoke test** 3la
l'exe: `mt5trader.exe version`, `help`, w `doctor --offline` (khass yfachil b 1, machi
ycrache b 2).

---

## 7all B: build 3la Windows dyalek

```powershell
# 1. Python 3.8+ 64-bit mn python.org, ✅ Add to PATH
# 2. l'dependencies
pip install pyinstaller MetaTrader5

# 3. build
cd mt5-trader-skill\mt5-app
python build_exe.py
```

Wla ghir **doubli klik 3la `build_exe.bat`** — kaydir koulchi w kaywe9ef 3la l'resultat.

Kaytle3 `mt5-app\dist\mt5trader.exe` (~30–45 MB, onefile).

Xeyr ila `python build_exe.py --check` bach tchouf chnou n9ess bla ma ybnа.

> PyInstaller **ma kay-cross-compilich**: exe dyal Windows kaytbna ghir mn Windows.
> Mn Linux/Mac: `build_exe.py` kaywe9ef w kaygoul lik hadchi (machi kaybnih ghalat).

---

## Awwel run / first run

```powershell
mt5trader.exe setup          # trader\config.json + symbols.json
notepad trader\config.json   # terminal_path, login, limites
mt5trader.exe doctor         # khass koulchi OK
```

Mn be3d, l'chain (bla Python, koulchi b l'exe):

```powershell
mt5trader.exe analyze --write
mt5trader.exe screen --show-fails --write-targets
mt5trader.exe plan --write
mt5trader.exe check
mt5trader.exe tickets
mt5trader.exe approve --id EURUSD-buy-20261106120000 --reply "yes"
mt5trader.exe send --id EURUSD-buy-20261106120000 --dry-run
mt5trader.exe send --id EURUSD-buy-20261106120000
mt5trader.exe journal --days 30
mt5trader.exe kill on
```

Wla bla commandes: **doubli klik** 3la l'exe → menu b 13 khyar (kl 7aja mktouba b
darija w b l'anglais), w `h` bach tchouf koul l'commandes.

`mt5trader.exe help` fih l'jadwal kamel. Kol flag dyal l'scripts kaykhdem hna:

```powershell
mt5trader.exe doctor --offline
mt5trader.exe plan --risk 0.25 --write
mt5trader.exe journal --days 90 --json
mt5trader.exe send --id X --live          # compte real, b yeddik
```

---

## L'matalib / Requirements

- Windows 10/11, 64-bit
- MetaTrader 5 mfto7 + AutoTrading ON (7it l'orders kaydewzo mn l'terminal)
- `trader\config.json` m3emmer (`terminal_path`, w l'limites)
- Ila bghit **real**: `"allow_live": true` + `--live` f kol send

---

## Troubleshooting

| 3lama / symptom | sabab / cause | 7all / fix |
| --- | --- | --- |
| Windows "protected your PC" (SmartScreen) | exe machi signé | `More info → Run anyway`, wla bniha b yeddik mn l'source |
| antivirus kay7yed l'exe | PyInstaller onefile kay-extracti f temp | 7ell `dist\` f l'antivirus, wla bni **onedir** |
| `mt5-core\bridge.py ma l9itch / not found` | l'exe mabni bla l'folders | 3awed bni b `mt5trader.spec` (fih `datas`) |
| `MetaTrader5` import error dakhel l'exe | DLL ma tqell3atch | 3awed bni b `collect_all("MetaTrader5")` — kayn f l'spec |
| `initialize() = False` / `-10005` | terminal msdoud wla path ghalat | 7ell MT5, 3emmer `terminal_path` |
| `10027 autotrading disabled` | AutoTrading m7bous | klik l'boton f l'terminal |
| l'exe kaytqad b tqal f l'awwel | onefile kay-extracti f `%TEMP%` | 3adi; wla bni onedir |
| `doctor` kaygoul `symbols.json` khawi | ma dertich `setup` | `mt5trader.exe setup` |
| kaybda w kaytsed f 1 seconde | antivirus wla SmartScreen | chouf l'console mn `cmd` machi double-click |

---

## Chnou **ma** kaydirch l'exe / what it will not do

- Ma kayb9ach mkhebbi f tray: console app, kayt7ell w kayt9ed. Jadwal → **Task Scheduler**
  (`mt5trader.exe alerts` kol 5 dqayq), machi l'exe b raso.
- Ma kay-signich l'orders b rasou: risk PASS + yes dyalek. L'exe sayeb l'cadre, machi
  l'qarar.
- Ma kaykhdemch bla l'terminal: l'data kollha mn MT5. Ila bghit l'analyse bla terminal,
  `--offline` m3a `trader\data\snapshot.json`.
- Machi nas7a maliya. Demo l'owwel.
