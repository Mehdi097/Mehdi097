# TraderDesk — 11 agents de trading + MetaTrader 5

> **Salam / Bonjour 👋** — Had l'application li talbit: application **Windows `.exe`** fiha **ga3 les 11 agents** dyal [`Jakeschincariol/trader-skill`](https://github.com/Jakeschincariol/trader-skill) b dept kamlin, **dashboard** kayban fih kolchi (chno kaydir koll agent, les logs, les fichiers, les ordres, les positions, P/L), w **blassa fih tdir l'adresse w l'clé API dial MetaTrader** — w howa **kaytconnecta wahdo** w **kayexecuta les trades** wahdo (m3a les portes de sécurité).

Application de bureau (Python 100 % standard, zéro dépendance obligatoire) qui transforme le pack de 11 « Claude skills » en un **desk de trading autonome** : chaque agent est spécialisé, exécute réellement son script Python d'origine, écrit ses fichiers dans `trader/`, et le moteur envoie les ordres approuvés à **MetaTrader 5**.

---

## 1. Démarrage rapide

```bash
# Linux / macOS / aperçu
python3 run.py                                  # http://127.0.0.1:8770
bash build_linux.sh                             # aperçu sur 0.0.0.0:8770

# Windows : double-clic sur
build_windows.bat                               # -> dist\TraderDesk.exe
dist\TraderDesk.exe                             # ouvre le dashboard dans le navigateur
```

Au premier lancement, l'application :

1. crée `runtime/` (ou `%APPDATA%\TraderDesk` depuis le `.exe`) avec `trader/config.json`, `targets.json`, `metrics.json`, `prices.json`, `rules.json`, `alerts.json`, `portfolio.json` ;
2. se connecte **automatiquement** au mode par défaut (**simulation**, sans argent réel) ;
3. lance le premier cycle des 11 agents → `copycat → budget → risk → broker → MT5` : 5 ordres sont dimensionnés, contrôlés, transformés en tickets, puis **exécutés sur le compte démo** avec SL/TP ;
4. continue toutes les 90 s (réglable) : cotations qui bougent, P/L, équité, alertes, news, 13F, PTR, contrôle du risque, etc.

> ⚠️ Le mode **réel** n'envoie **jamais** un ordre sans que vous cochiez explicitement « Autoriser le trading RÉEL ». Par défaut : simulation + paper + kill switch disponible. Ce logiciel n'est **pas un conseil financier** ; le trading comporte un risque de perte.

---

## 2. Les 11 agents (repris intégralement du dépôt)

| Commande | Spécialité | Ce qu'il fait vraiment dans l'app |
|---|---|---|
| `/trader-copycat` | Ingénieur inverse | 13F-HR SEC EDGAR → `trader/targets.json` (poids, CUSIP, valeur, date du dépôt) |
| `/trader-news` | Veille actualités | Yahoo RSS + 8-K SEC → headlines, tags, items `!`, `trader/state/news.json` |
| `/trader-budget` | Budget Manager | `size.py` → buffer de cash, cap par titre, `trader/orders.json` |
| `/trader-pelosi` | Congrès | House PTR → fourchettes de montants, owner SP/JT/DC, délai de déclaration |
| `/trader-analyst` | Résultats | SEC XBRL companyfacts → `trader/metrics.json` (TTM, marges, croissance, EPS) |
| `/trader-screener` | Screener | `screen.py` → PASS/FAIL par règle + score pondéré → `trader/shortlist.json` |
| `/trader-risk` | Risque | `check.py` → PASS/BLOCK + **fingerprint** de chaque ordre → `trader/state/risk.json` |
| `/trader-broker` | Exécuteur | `ticket.py` → tickets, « yes » explicite, journal append-only, lots après fill |
| `/trader-tax` | Fiscalité | `lots.py` → lots FIFO/HIFO, court/long terme, wash sales, harvest |
| `/trader-alerts` | Prix | `alerts.py` → above/below/stop/pct_move/opening bell + calendrier NYSE 2026/2027 |
| `/trader-rebalance` | Rééquilibrage | `rebalance.py` → dérive en points, bande à 5 pts, ventes avant achats |

Chaque fiche complète (rôle, déclencheurs, commandes, fichiers lus/écrits, règles, exemple, interdictions, calendrier, `SKILL.md` d'origine) est visible dans **l'onglet « Les 11 agents »** → clic sur une carte → 4 onglets : *Fiche complète / Dernière sortie / Journal / SKILL.md*. Les scripts, les `SKILL.md`, le README et la licence MIT d'origine sont embarqués dans `traderdesk/skills/`.

### Pipelines du pack (onglet « Pipeline & fichiers »)

```
copycat ─────────────→ budget → risk → broker → MT5     (copier un investisseur)
analyst → screener ──→ budget → risk → broker → MT5     (choisir ses titres)
news / pelosi / alerts                                  (veille, jamais d'ordre)
rebalance / tax ─────→ risk → broker → MT5              (maintenance)
```

Tous les fichiers `trader/*.json` et `trader/state/*.json` sont lisibles en direct depuis le dashboard (explorateur de fichiers).

---

## 3. Connexion MetaTrader 5 — adresse + clé API

Onglet **« Connexion MT5 »**. Trois modes :

| Mode | Champs | Usage |
|---|---|---|
| **Simulation** *(défaut)* | aucun | compte démo local, remplit les ordres, P/L et prix qui bougent |
| **Passerelle REST** | **Adresse** + **Clé API** | `http://127.0.0.1:8765` (ou l'adresse de votre serveur/bridge), clé envoyée en `X-API-Key` et `Authorization: Bearer` |
| **Terminal local** | compte, mot de passe, serveur, chemin `terminal64.exe` | package officiel `MetaTrader5` (Windows) |

Dès que vous cliquez sur **« Enregistrer & reconnecter »** :

* la configuration est sauvegardée localement (`settings.json`, permissions `600`, **secrets jamais renvoyés en clair au dashboard**) ;
* `connect()` est appelée automatiquement (`/ping` puis `/account`) ;
* si la passerelle tombe, le moteur **se reconnecte tout seul** toutes les `reconnect_seconds` (15 s) ;
* l'état (serveur, compte, latence, dernière erreur, tentatives) s'affiche en direct.

### Lancer la passerelle sur le PC Windows où MT5 est installé

```bat
pip install MetaTrader5
dist\TraderDesk.exe --bridge --api-key MA_CLE --port 8765
:: ou depuis les sources :
python run.py --bridge --api-key MA_CLE --port 8765 --host 0.0.0.0
```

La passerelle détecte le package `MetaTrader5` + le terminal connecté. Si l'un des deux manque, elle démarre en **mode simulation** et le dit dans `/api/v1/ping` (pratique pour tester l'adresse + la clé API sans risque). Contrat complet : [`docs/MT5_BRIDGE.md`](docs/MT5_BRIDGE.md).

### Exécution automatique des trades

```
agent → trader/orders.json → check.py (PASS du jour + fingerprint)
      → ticket.py approve --reply "yes" → conversion notional $ / prix = volume MT5
      → POST /api/v1/order (symbol, side, volume, sl, tp, magic, comment)
      → ticket.py result --status placed --broker-id … --filled-qty … --filled-price …
      → trader/portfolio.json (lot fiscal) + dashboard (trade, position, P/L, équité)
```

Portes de sécurité vérifiées avant **chaque** ordre : `kill_switch`, `auto_execute`, `require_approval`, `live_trading` (obligatoire hors simulation), connexion active, `max_daily_orders`, `max_lot`, `max_orders_per_cycle`, et bien sûr **PASS de `trader-risk` pour cet ordre exact aujourd'hui**. Si `require_approval` est coché, les tickets restent en attente et vous cliquez sur « ✓ Exécuter » dans l'onglet *Ordres & trades*.

---

## 4. Dashboard — ce qui est visible

* **Vue d'ensemble** : 6 KPI, courbe d'équité, compte MT5 (solde/équité/marge libre), 4 pipelines, 11 agents avec statut *idle / running / OK / erreur*, journal LIVE, positions ;
* **Les 11 agents** : fiche complète + nombre d'exécutions + durée + dernier résumé + bouton « Exécuter maintenant » + activation ;
* **Pipeline & fichiers** : les 4 chaînes et le contenu JSON de chaque artefact ;
* **Ordres & trades** : portes de sécurité, tickets READY (approuver / refuser), ordres MT5 exécutés (ticket, volume, prix, SL/TP, mode), positions & P/L ;
* **Connexion MT5** : formulaire adresse + clé API, test de connexion, état live, tous les paramètres de trading, tutoriel de branchement ;
* **Journal temps réel** : tous les événements filtrables + export CSV ;
* **Documentation** : README + 11 `SKILL.md` d'origine.

---

## 5. Fabriquer le `.exe`

```bat
:: sur Windows, depuis la racine du dépôt
build_windows.bat
:: résultat : dist\TraderDesk.exe  (fichier unique, ~20-40 Mo)
```

Le workflow GitHub Actions [`.github/workflows/build-exe.yml`](.github/workflows/build-exe.yml) compile la même chose sur `windows-latest` à chaque push et dépose `TraderDesk-Windows-x64` en artefact (et en release sur un tag). Le spec PyInstaller embarque le dashboard, les 11 dossiers de skills, leurs scripts et les données de démo. En mode gelé, les scripts sont importés en processus (pas besoin de `python.exe` sur la machine cible).

```
run.py                     point d'entrée (dashboard ou --bridge)
traderdesk/
  settings.py              config + secrets masqués + chemins (PyInstaller-compatible)
  state.py                 état temps réel, journal, artefacts, persistance
  server.py                API JSON + fichiers statiques (http.server)
  agents/registry.py       fiches détaillées des 11 agents, pipelines, artefacts
  agents/engine.py         orchestration, exécution des scripts, ordres MT5, reconnexion
  mt5/connector.py         simulation | REST (adresse + clé API) | terminal local
  mt5/bridge.py            passerelle REST MT5 (--bridge)
  web/                     index.html, styles.css, app.js
  skills/                  les 11 skills d'origine (SKILL.md + .py + exemples), MIT
  data/seed/               jeu de données de démonstration issu du dépôt
docs/MT5_BRIDGE.md         contrat de la passerelle
tests/                     tests de fumée (pipeline complet, REST, API)
```

---

## 6. Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## 7. Crédits & avertissements

* Pack d'origine : [Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill) par Jake Schincariol — **MIT** (licence conservée dans `traderdesk/skills/LICENSE`). Les 11 `SKILL.md` et les outils Python sont reproduits tels quels ; TraderDesk ajoute l'orchestration, le dashboard et le connecteur MetaTrader 5.
* MetaTrader 5 n'a pas de « clé API » native : la clé API protège **la passerelle REST fournie** ; le mode « terminal local » utilise login/mot de passe/serveur du terminal. Les deux sont supportés.
* Données publiques (SEC EDGAR, House Clerk, Yahoo RSS) : delay, partielles, jamais temps réel. Le prix qui fait foi est celui du broker. Les 13F ont 45 jours de retard ; les PTR du Congrès sont publics et en retard, pas de l'info privilégiée.
* **Pas un conseil financier, pas un conseil fiscal.** Paper trading par défaut. Vous pouvez perdre de l'argent.

---

<sub>👋 À l'origine ce dépôt était le README de profil @Mehdi097 — il héberge maintenant TraderDesk.</sub>
