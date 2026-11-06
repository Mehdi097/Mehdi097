# Passerelle REST MetaTrader 5 — adresse + clé API

TraderDesk ne se connecte pas directement au protocole propriétaire de MT5 depuis
une machine distante : il parle à une **passerelle REST** que vous lancez sur le
PC Windows où le terminal MetaTrader 5 est installé. C'est cette passerelle que
vous désignez par **adresse** et **clé API** dans l'onglet « Connexion MT5 ».

```
┌────────────────────┐   http(s) + X-API-Key   ┌──────────────────────────┐
│  TraderDesk (.exe) │ ───────────────────────▶ │  TraderDesk --bridge      │
│  11 agents         │ ◀─────────────────────── │  Windows + terminal MT5   │
└────────────────────┘    JSON                  └────────────┬─────────────┘
                                                             │ package MetaTrader5
                                                             ▼
                                                   compte démo / réel MT5
```

## 1. Démarrer la passerelle

```bat
pip install MetaTrader5            :: package officiel, Windows uniquement
dist\TraderDesk.exe --bridge --api-key MA_CLE_SECRETE --port 8765 --host 0.0.0.0
```

Depuis les sources :

```bash
python run.py --bridge --api-key MA_CLE_SECRETE --port 8765 --host 0.0.0.0 \
  --login 12345678 --password MOT_DE_PASSE --server Exness-Real
```

Variables d'environnement équivalentes : `TRADERDESK_API_KEY`, `MT5_LOGIN`,
`MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`.

Si le package `MetaTrader5` ou le terminal sont absents, la passerelle démarre
quand même **en simulation** et l'indique dans `/api/v1/ping` : vous pouvez donc
valider toute la chaîne adresse + clé API + ordres sans compte réel.

## 2. Côté dashboard

Onglet **Connexion MT5** :

| Champ | Valeur |
|---|---|
| Mode | `Passerelle REST (adresse + clé API)` |
| Adresse | `http://127.0.0.1:8765` (même machine) ou `http://192.168.1.50:8765` (réseau local) |
| Clé API | `MA_CLE_SECRETE` — identique à celle du `--bridge` |
| Reconnexion automatique | ✅ |
| Exécution automatique | ✅ |
| Autoriser le trading RÉEL | à cocher **uniquement** pour un vrai compte |

« ⚡ Tester la connexion » appelle `/ping` + `/account` et affiche serveur, compte
et latence. « 💾 Enregistrer & reconnecter » sauvegarde puis reconnecte
automatiquement ; si la passerelle tombe, le moteur réessaie toutes les 15 s.

> Si la passerelle est sur une autre machine, utilisez HTTPS + un reverse proxy
> et une clé longue aléatoire : en HTTP clair sur un réseau non fiable, la clé
> circule en clair. Ne l'exposez jamais directement sur Internet.

## 3. Contrat de l'API

Toutes les requêtes (sauf `/`) exigent l'en-tête `X-API-Key: MA_CLE_SECRETE`
ou `Authorization: Bearer MA_CLE_SECRETE`. Réponses JSON.

| Méthode | Chemin | Corps | Réponse |
|---|---|---|---|
| GET | `/` | — | informations de service |
| GET | `/api/v1/ping` | — | `{ok, server, account, mode, message}` |
| GET | `/api/v1/account` | — | `{login, server, currency, balance, equity, margin, free_margin, profit, leverage}` |
| GET | `/api/v1/positions` | — | `{positions:[{ticket, symbol, side, volume, price_open, price_current, sl, tp, profit, time, comment}]}` |
| GET | `/api/v1/symbols` | — | `{symbols:[{symbol, bid, ask, volume_min, volume_step}]}` |
| GET | `/api/v1/history` | — | `{orders:[…]}` |
| POST | `/api/v1/order` | `{symbol, side:"buy"\|"sell", volume, price?, sl?, tp?, comment?, magic?, deviation?}` | `{ok:true, ticket, retcode, price, status:"placed"\|"filled", …}` |
| POST | `/api/v1/close` | `{ticket}` | `{ok:true, ticket, status:"closed"}` |

Erreur métier : `{ "ok": false, "error": "…", "status": "rejected" }` (HTTP 200),
afin que TraderDesk enregistre l'échec dans `trader/state/broker.json` via
`ticket.py result --status failed`.

### Correspondance des symboles

Les agents du pack produisent des tickers d'actions US (`AAPL`, `GOOGL`…). Sur
un compte MT5 de CFD, le symbole peut être `AAPL.a`, `AAPL#`, `US500.cash`…
Le champ **« Correspondance des symboles »** (JSON) ou **préfixe/suffixe** fait
la traduction :

```json
{"AAPL":"AAPL.a", "AXP":"AXP.a", "GOOGL":"GOOGL.a", "KO":"KO.a", "BAC":"BAC.a"}
```

Le volume envoyé vaut `notional ($) / prix`, arrondi au pas de 0.01, borné par
`max_lot`. Les SL/TP sont calculés depuis `default_sl_pct` / `default_tp_pct`.

## 4. Sécurité côté application

1. `trader-risk` doit avoir rendu **PASS pour cet ordre exact aujourd'hui**
   (fingerprint SHA-256 des champs de l'ordre) ;
2. `trader-broker` enregistre un `yes` explicite pour **un seul** ordre ;
3. TraderDesk vérifie : kill switch, `auto_execute`, approbation manuelle
   éventuelle, `live_trading` hors simulation, connexion, plafonds journaliers
   et volume max ;
4. l'ordre part à la passerelle, puis le ticket MT5 et le fill sont journalisés
   (et ajoutés comme lot fiscal dans `trader/portfolio.json`).

Les secrets sont stockés dans `settings.json` local (chmod 600), ne sont jamais
renvoyés en clair par `/api/state` (masqués `••••••••abcd`) et ne sont jamais
écrits dans le journal.
