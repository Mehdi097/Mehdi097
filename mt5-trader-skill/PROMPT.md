# PROMPT - l'bloc li kat-ls9o / the block you paste

## A. Install (Claude Code wla Claude b skills)

```
https://github.com/Mehdi097/Mehdi097/tree/main/mt5-trader-skill

install skill
```

Wla f Claude Code:

```
/plugin marketplace add Mehdi097/Mehdi097
/plugin install mt5-trader-skill@mt5-trader-skill
```

Wla copy dyal l'folders:

```bash
git clone https://github.com/Mehdi097/Mehdi097.git
cp -r Mehdi097/mt5-trader-skill/mt5-* ~/.claude/skills/
```

---

## B. L'awwel message: 3ref l'machine

Ls9 hada f chat jdid (m3a l'skills installés):

```
Khdem b mt5-core.

1. dir doctor --init (bash), w 3tini l'checklist kamla.
2. ila chi symbol ma kaynch, 9addeh b bridge.py symbols --search.
3. ila AutoTrading m7bous wla l'terminal ma connectach, goul liha kifach t7ellha
   w 7bess.
4. mn be3d, 3tini summary: compte demo wla real, currency, equity, leverage,
   spread dyal koul symbol f l'universe, w volume_min.

Ma tsift walo, ma tbeddel walo f config bla ma nssewlek.
```

Claude should answer with the doctor table and stop. No orders.

---

## C. Job dyal koul nhar (routine)

```
Routine dyal l'youm 3la MT5, b had l'tartib, w goul liya l'ar9am:

1. analyst.py --write  : ATR, ADR, spread, trend dyal l'universe.
2. econ.py --mine --write : chi blackout l'youm?
3. screen.py --show-fails --write-targets : chkoun PASS w 3lach l'okhrin FAIL.
4. size.py --write : l'volume w SL/TP li bghat l'equity.
5. check.py : PASS wla BLOCK, b l'sabab.

Ma tsiftch 7ta order. 3tini ghir jadwal: symbol, side, lots, SL, TP, risk %,
w l'BLOCK b l'sabab dyalou.
```

W mn be3d, order b order:

```
execute.py show
```
```
yes l order <ID> ghir. 3tini l'ticket qbel ma tsift.
```
```
execute.py send --id <ID>
```

Claude khass yrefed ay "yes" jam3i, w khass ygoul l'ticket w l'retcode b l'kelmat
(10009 done = filled, 10019 = ma kaynch flous, 10027 = AutoTrading, 10030 = filling).

---

## D. Ila l'user bgha yt3ellem / review

```
journal.py --days 30 : win rate, profit factor, expectancy, max drawdown.
9arn l'expectancy m3a l'commission w l'swap. Goul liya b sara7a wach had
l'approche katkhdem, wla l'sizing kbar bzzaf.
```

```
rebalance.py --band 5 : ch7al m3arred l USD, w wach l'drift ystahl rebalance
wla l'spread ghadi yakol l'far9.
```

---

## E. L'qawa3id li khass Claude y7fazhom (ls9 hada f l'system prompt wla f CLAUDE.md)

```
MT5 trading rules, no exceptions:

1. No order without: mt5-risk PASS on THAT order today, AND the user's explicit
   yes for THAT order id. Never approve in batch. Never send without approval.
2. Credentials never in chat, never in JSON. Environment variables only.
3. Real account needs allow_live:true AND --live. Otherwise refuse and say why.
4. Kill switch trader/state/KILL stops everything. If it exists, do not send,
   and do not delete it without being asked.
5. Never invent a price, a spread, a lot size or a tick value. Read the symbol
   spec and the live tick, or say you cannot.
6. If the broker refuses (retcode), report the retcode and its meaning, do not
   retry blindly, do not "fix" it by sending a bigger order.
7. Demo first. Suggest the smaller size when unsure.
8. Say the numbers. "It should be fine" is not a report.
9. This is not financial advice: say it when the user asks for a prediction,
   and never promise a result.
10. Report what the files recorded, not what you remember.
```

---

## F. Bla Claude Code (mode "paste a SKILL.md")

Ls9 l'contenu dyal `mt5-risk/SKILL.md` (wla `mt5-broker/SKILL.md`) f l'awwel dyal l'chat,
w Claude kaykhdem b7al dak l'mode. Kaytlef l'scripts Python (khass tkhdem bihom b yeddik f
PowerShell), walakin l'methode w l'qawa3id kayb9aw.
