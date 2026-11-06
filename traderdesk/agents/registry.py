"""Fiche complète des 11 agents, fidèle au dépôt Jakeschincariol/trader-skill.

Chaque agent garde son SKILL.md d'origine (servi par /api/docs/<id>), ses
commandes, ses fichiers d'entrée/sortie, ses règles, ses limites et son rôle
dans le pipeline. Le moteur exécute réellement les scripts Python d'origine.
"""

from pathlib import Path

from ..settings import SKILLS_DIR


def spec(
    id, command, role, tagline, detail, triggers, commands, reads, writes,
    rules, example, never, stage, schedule, icon, color, tool=None,
):
    return {
        "id": id,
        "command": command,
        "role": role,
        "tagline": tagline,
        "detail": detail,
        "triggers": triggers,
        "commands": commands,
        "reads": reads,
        "writes": writes,
        "rules": rules,
        "example": example,
        "never": never,
        "stage": stage,
        "schedule": schedule,
        "icon": icon,
        "color": color,
        "tool": tool,
        "skill_md": str(SKILLS_DIR / id / "SKILL.md"),
    }


AGENTS = [
    spec(
        "trader-copycat", "/trader-copycat", "Ingénieur inverse",
        "Reconstruit le portefeuille d'un investisseur depuis son 13F-HR",
        "Lit les dépôts publics 13F-HR sur SEC EDGAR (et les Form 4 si besoin), reconstruit chaque position, sa part du fonds, ce qui a été acheté, ajouté, réduit ou vendu depuis le trimestre précédent, fait correspondre chaque CUSIP à un ticker, puis écrit trader/targets.json : les poids à copier pour les autres agents.",
        ["copy Buffett", "copy Berkshire", "que possède Ackman ?", "montre son 13F", "copy the top 5", "reverse engineer this investor"],
        [
            "edgar13f.py find buffett",
            "edgar13f.py find \"pershing square\" --sec",
            "edgar13f.py filings 1067983",
            "edgar13f.py holdings 1067983 --accession 0001193125-26-352200",
            "edgar13f.py diff 1067983",
            "edgar13f.py copy 1067983 --top 5 --out trader/targets.json",
        ],
        ["SEC EDGAR (submissions + 13F-HR information table)", "filers.json (23 investisseurs connus)", "share_classes.json", "trader/tickers.json (corrections CUSIP)", "OpenFIGI en option --figi"],
        ["trader/targets.json : {source, as_of, filed, cik, method, weights:[{ticker,name,weight,pct_of_13f,value,shares,cusips}]}", "trader/state/copycat.json (journal TraderDesk)"],
        [
            "Toujours dire l'âge des données : « positions au 2026-06-30, déposées le 2026-08-14 ».",
            "Un 13F = 45 jours de retard, positions longues US uniquement : ni shorts, ni cash, ni obligations, ni étranger, ni prix payé.",
            "C'est la FIRME qui dépose, pas la personne : Berkshire Hathaway, pas « Buffett a acheté ».",
            "Chaque nombre vient du dépôt : citer l'accession number et le lien de l'information table.",
            "Options PUT/CALL et PRN sont exclues et listées ; une classe d'actions multiple est combinée (GOOG + GOOGL).",
            "SEC exige un User-Agent « Nom email@exemple.com » sinon l'outil refuse l'appel.",
        ],
        "Berkshire Hathaway (CIK 1067983), T2 2026 : AAPL 22,04 %, AXP 17,14 %, GOOGL 12,62 %, KO 10,86 %, BAC 9,20 %. Top 5 renormalisé : 30,67 / 23,85 / 17,56 / 15,11 / 12,80 %. Nouveau : D.R. Horton ; sortie : Constellation Brands.",
        ["Ne place jamais d'ordre", "N'invente jamais un ticker (marqué * et à corriger)", "Ne dit pas « holdings today »"],
        "Source / Cibles", "À chaque nouvelle 13F (trimestriel) ou à la demande", "◈", "#7c6cff", "trader-copycat/edgar13f.py",
    ),
    spec(
        "trader-news", "/trader-news", "Veille actualités",
        "Surveille les headlines et les dépôts 8-K de chaque titre détenu",
        "Interroge le flux RSS public Yahoo Finance (un flux par ticker) et le flux Atom SEC EDGAR des 8-K. Ne remonte que le nouveau, avec les tickers touchés, les tags (earnings, analyst, legal, deal, capital, people, risk) et un marquage ! pour les items 8-K importants (2.02 résultats, 5.02 dirigeant, 2.06 dépréciation, 3.01 retrait de cote, 4.02 états financiers non fiables, 1.03 faillite, 1.05 cyber).",
        ["what's new on my stocks", "8-K", "news on AAPL", "briefing du jour", "surveille mes positions"],
        [
            "news.py",
            "news.py --tickers AAPL AXP GOOGL KO BAC --hours 24",
            "news.py --forms 8-K,10-Q --json",
            "news.py --all --dry-run",
        ],
        ["trader/portfolio.json (positions) ou trader/targets.json", "Yahoo Finance RSS public", "SEC EDGAR Atom feed (8-K)", "trader/config.json : sec_user_agent"],
        ["trader/state/news.json (items déjà vus, 30 jours)", "trader/state/news_items.json (briefing TraderDesk)"],
        [
            "Un headline est une piste, pas un fait : lire la source avant d'affirmer.",
            "Un dépôt 8-K prime sur un article : c'est ce que l'entreprise a déclaré à la SEC.",
            "Chaque item liste les tickers touchés et ses tags ; pas de prédiction.",
            "Sans sec_user_agent, la partie SEC est sautée avec une note, les headlines restent.",
            "Un item n'apparaît qu'une fois (état conservé 30 jours).",
        ],
        "Sur le portefeuille copié : un 8-K item 2.02 (résultats) pour AAPL, un article « analyst » sur BAC ; l'agent pondère l'importance par le poids de la position dans targets.json.",
        ["Ne recommande jamais d'acheter ou vendre", "Ne prédit pas le cours", "Ne résume pas un article paywall non lu"],
        "Veille", "Toutes les 15 min en séance (planifié)", "◉", "#4cc9f0", "trader-news/news.py",
    ),
    spec(
        "trader-budget", "/trader-budget", "Gestionnaire de budget",
        "Dimensionne chaque position avant tout achat",
        "Transforme des poids cibles en montants en dollars : retire le cash buffer, renormalise les poids à 100, plafonne chaque titre à max_position_pct (l'excédent est redistribué aux autres par poids, en boucle), supprime les tranches sous min_order_usd, arrondit pour utiliser chaque dollar, gère les parts fractionnaires ou entières, et écrit les propositions dans trader/orders.json au format place_stock_order (notional en chaîne).",
        ["j'ai 5 000 $", "size my trades", "garde 10 % en cash", "aucun titre au-dessus de 25 %", "set my rules"],
        [
            "size.py",
            "size.py --budget 5000 --write",
            "size.py --weights AAPL=22.04,AXP=17.14,GOOGL=12.62 --json",
            "size.py --whole-shares --prices trader/prices.json",
            "size.py --top 5 --cents --write",
        ],
        ["trader/config.json (budget, cash_buffer_pct, max_position_pct, min/max_order_usd, fractional, blocked)", "trader/targets.json", "trader/prices.json (parts entières)"],
        ["trader/orders.json : la liste d'ordres proposés + récapitulatif du dimensionnement", "trader/state/budget.json (résumé TraderDesk)"],
        [
            "cash buffer = budget × cash_buffer_pct, jamais investi.",
            "Poids renormalisés à 100 sur les titres conservés (blocked retirés, --top N garde les N plus gros).",
            "Aucune position > max_position_pct du budget ; excès redistribué jusqu'à stabilisation.",
            "Tranche < min_order_usd supprimée et son poids redistribué.",
            "Arrondi au dollar par défaut (--cents pour les centimes) ; le dollar d'arrondi va à la plus grosse position non plafonnée.",
            "--whole-shares achète des parts entières puis dépense le reste une part à la fois sur le titre le plus sous sa cible.",
            "L'argent non investissable est affiché « laissé inactif », jamais caché.",
        ],
        "Budget 5 000 $, buffer 10 %, cap 25 % : AAPL 1 250 $ (plafonné), AXP 1 119 $, GOOGL 823 $, KO 708 $, BAC 600 $, 500 $ de cash, 0 $ inactif.",
        ["Ne place rien", "Ne dépasse jamais le budget", "Ne masque jamais l'argent inutilisé"],
        "Dimensionnement", "Après copycat / screener, ou à la demande", "▤", "#f9c74f", "trader-budget/size.py",
    ),
    spec(
        "trader-pelosi", "/trader-pelosi", "Traqueur du Congrès",
        "Lit les déclarations de transactions des élus (House PTR) dès leur publication",
        "Télécharge l'index annuel du House Clerk (YEARFD.zip), repère chaque nouveau Periodic Transaction Report, convertit le PDF en lignes propres : élu, propriétaire (SP conjoint, JT, DC), titre, ticker, achat/vente, strike et échéance des options, date de trade, fourchette de montant, délai de déclaration. Alerte une seule fois par dépôt et signale les titres que vous détenez.",
        ["what is Pelosi buying", "Congress trades", "alert me when Pelosi files", "track Nancy Pelosi"],
        [
            "ptr.py index --member pelosi",
            "ptr.py index --since 2026-10-01",
            "ptr.py new --member pelosi --read",
            "ptr.py parse trader/state/ptr-pdfs/<DocID>.pdf --json",
        ],
        ["disclosures-clerk.house.gov / public_disc / financial-pdfs / YEARFD.zip", "PDF des PTR sur le site du Clerk", "pdftotext (poppler, optionnel)", "trader/portfolio.json"],
        ["trader/state/pelosi.json (DocIDs déjà annoncés)", "trader/state/ptr-pdfs/ (PDF téléchargés)", "trader/state/pelosi_trades.json (TraderDesk)"],
        [
            "Citer le PTR du Clerk, pas un tracker tiers (DocID + lien).",
            "Les montants sont des FOURCHETTES : « 1 000 001 $ – 5 000 000 $ », jamais une moyenne.",
            "Le propriétaire compte : SP = conjoint, JT = joint, DC = enfant, vide = l'élu.",
            "Dire le retard : nombre de jours entre le trade et le dépôt, > 45 jours = en retard.",
            "Une option (call avec strike/échéance) n'est pas un achat d'actions ; les exercices sont marqués.",
            "STOCK Act : déclaration sous 30/45 jours — données publiques, pas d'info privilégiée, jamais « en avance ».",
        ],
        "PTR 2026 de N. Pelosi : transactions SP (Paul Pelosi), fourchette 1 000 001 $ – 5 000 000 $, délai de 12 jours ; un titre en commun avec le portefeuille est signalé en rouge.",
        ["Ne prétend pas avoir une information privilégiée", "Ne transforme pas une fourchette en montant exact", "Ne place aucun ordre"],
        "Veille", "Dès qu'un nouveau dépôt est publié", "★", "#ff8fab", "trader-pelosi/ptr.py",
    ),
    spec(
        "trader-analyst", "/trader-analyst", "Analyste des résultats",
        "Lit les chiffres réellement déposés à la SEC (XBRL)",
        "Depuis SEC EDGAR : companyfacts XBRL (10-Q / 10-K), liste des submissions pour le dernier 10-Q/10-K et le dernier 8-K item 2.02, puis l'exhibit EX-99.1 (communiqué de résultats). Produit trimestre par trimestre : revenue, résultat net, EPS dilué, marges brute/opérationnelle/nette, croissance vs le même trimestre N-1, TTM, et un fichier de métriques pour le screener.",
        ["how did Apple's earnings look", "check the 10-Q", "compare margins", "is revenue growing"],
        [
            "facts.py AAPL",
            "facts.py AAPL AXP GOOGL KO BAC --metrics trader/metrics.json",
            "facts.py AAPL --quarters 8 --json",
            "facts.py --cik 0000320193 --json",
        ],
        ["https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json", "SEC submissions + dernier 8-K item 2.02 / EX-99.1", "sec_user_agent obligatoire"],
        ["trader/metrics.json : une ligne par société (revenue_ttm, net_income_ttm, eps_ttm, *_growth_yoy, marges, period_end, source)", "trader/state/analyst.json"],
        [
            "Les chiffres déposés d'abord : le communiqué sert au contexte (guidance, segments), en disant quelle source a fourni chaque nombre.",
            "Comparer le comparable : croissance vs même trimestre N-1 ; les variations Q/Q sont affichées mais la saisonnalité est rappelée.",
            "Dire ce qui est dérivé : pas de 10-Q pour le Q4 (10-K moins 3 trimestres), marqué « derived », EPS approximatif.",
            "Dire quand la donnée retarde : si le dernier 10-Q est plus récent que le dernier trimestre des facts, l'outil affiche un NOTE avec le lien.",
            "Signaler les one-offs (résultat net > résultat opérationnel) ; banques/assureurs n'ont pas de marge brute → vide, pas zéro.",
        ],
        "AAPL au 2026-06-27 (T3 fiscal 2026) : revenue 109,42 Md$ (+16,4 %), résultat net 29,79 Md$ (+27,1 %), EPS dilué 2,02 $ (+28,7 %), marge brute 50,1 % ; TTM 466,8 Md$ et 8,71 $/action.",
        ["Ne donne pas d'avis d'investissement", "Ne comble jamais un chiffre manquant", "N'utilise pas le communiqué comme source de chiffres"],
        "Analyse fondamentale", "À chaque saison de résultats / avant un screen", "∑", "#06d6a0", "trader-analyst/facts.py",
    ),
    spec(
        "trader-screener", "/trader-screener", "Screener",
        "Filtre les sociétés selon VOS règles et classe celles qui passent",
        "Transforme « sociétés rentables qui grandissent et pas trop chères » en règles vérifiables. Pour chaque société, indique chaque règle PASS/FAIL avec le nombre et le seuil, calcule price / P/E / earnings_yield si des prix sont fournis, puis classe les survivantes (score 0–1 par métrique, moyenne pondérée).",
        ["screen for stocks", "find me companies that", "rank these stocks", "growing companies under 30 times earnings"],
        [
            "screen.py trader/metrics.json --rules trader/rules.json",
            "screen.py trader/metrics.json --rules trader/rules.json --prices trader/prices.json --out trader/shortlist.json",
            "screen.py companies.csv --rules trader/rules.json --json",
        ],
        ["trader/metrics.json (de trader-analyst) ou tout CSV avec colonne ticker", "trader/prices.json (optionnel)", "trader/rules.json"],
        ["trader/shortlist.json : passed[{ticker,score,why,skipped}], failed[{ticker,why}], note"],
        [
            "Opérateurs : >, >=, <, <=, ==, !=, between [bas,haut], in, not in.",
            "missing: « fail » = une société sans la métrique échoue (les banques n'ont pas d'operating_margin) ; « skip » = la règle est ignorée et signalée.",
            "Ranking : score 0 à 1 par métrique, moyenne pondérée ; une métrique absente est signalée.",
            "Code de sortie 1 = aucune société ne passe → montrer les « presque ».",
            "Un screen est un filtre sur des chiffres déclarés, PAS une recommandation.",
        ],
        "Règles d'exemple (croissance ≥ 10, marge op. ≥ 25, EPS > 0, P/E ≤ 35) : 2/5 passent — GOOGL score 0,75 (croissance 24,2 ; P/E 17,8), KO 0,25. AAPL échoue (P/E 39,2 > 35), BAC et AXP : operating_margin manquante.",
        ["Ne dit jamais « acheter »", "Ne devine jamais une métrique manquante", "N'envoie rien à trader-budget de lui-même"],
        "Sélection", "Avant le dimensionnement", "⌕", "#9b5de5", "trader-screener/screen.py",
    ),
    spec(
        "trader-risk", "/trader-risk", "Gestionnaire de risque",
        "Vérifie CHAQUE ordre proposé contre vos limites",
        "Contrôle les ordres dans l'ordre du fichier comme si chaque PASS était exécuté (pour détecter un lot d'achats qui, ensemble, cassent le buffer de cash). Chaque ordre reçoit PASS ou BLOCK avec les raisons, et un fingerprint SHA-256 de l'ordre exact, afin que trader-broker n'accepte que l'ordre précis validé aujourd'hui.",
        ["check the orders", "is this trade allowed", "why was it blocked", "PASS / BLOCK"],
        [
            "check.py",
            "check.py --orders trader/orders.json --json",
            "check.py --no-write",
        ],
        ["trader/orders.json", "trader/config.json", "trader/portfolio.json", "trader/prices.json", "trader/state/broker.json (ordres déjà placés aujourd'hui)"],
        ["trader/state/risk.json : {date, results:[{index,fingerprint,verdict,reasons,warnings}], pass, block, cash_after}"],
        [
            "format : symbole/side manquant, qty et notional, notional hors ordre market/day, limit sans prix, type inconnu.",
            "asset : options (symbole OCC), crypto, tout ce qui n'est pas action/ETF ; blocked tickers.",
            "size : sous min_order_usd, au-dessus de max_order_usd, position > max_position_pct du compte.",
            "cash : un achat qui entame le cash buffer ou exige de la marge ; short : vente > détention sauf allow_short.",
            "duplicate : même symbole + même side deux fois dans le lot, ou déjà placé aujourd'hui.",
            "daily limit : plus de max_orders_per_day ordres placés dans la journée.",
            "Sortie 0 = tout passe ; 1 = au moins un BLOCK. Les ordres bloqués ne vont jamais au broker.",
        ],
        "5 propositions Berkshire (1 250 / 1 119 / 823 / 708 / 600 $) : 5 PASS, 0 BLOCK, cash après exécution 500 $ (compte paper).",
        ["Ne place jamais d'ordre", "Ne modifie jamais un ordre pour le faire passer", "Ne valide pas un ordre qui a changé depuis le check"],
        "Contrôle (gate obligatoire)", "Avant CHAQUE exécution", "⛨", "#ef476f", "trader-risk/check.py",
    ),
    spec(
        "trader-broker", "/trader-broker", "Exécuteur d'ordres",
        "Transforme un ordre approuvé en ticket exact et enregistre le « oui »",
        "C'est le SEUL agent qui peut mener à un ordre. Trois portes : (1) trader-risk a validé CET ordre exact aujourd'hui (fingerprint), (2) un « yes » explicite pour CET ordre uniquement, (3) la carte « Allow once / Deny ». Le ticket affiche la phrase en clair et le JSON exact envoyé au connecteur ; approve refuse « yes to all », « ok », « sure », un oui qui nomme une autre action ou un autre montant.",
        ["place the orders", "execute", "send it to my broker", "show me the tickets"],
        [
            "ticket.py show",
            "ticket.py show --index 1 --json",
            "ticket.py approve --index 1 --reply \"yes\"",
            "ticket.py result --index 1 --status placed --broker-id ID",
            "ticket.py fill --symbol AAPL --side buy --qty 3.6628 --price 341.27",
            "ticket.py log",
        ],
        ["trader/orders.json", "trader/state/risk.json", "trader/config.json", "trader/state/broker.json"],
        ["trader/state/broker.json (journal append-only des décisions : approved / declined / placed / denied / failed)", "trader/portfolio.json (lots fiscaux après fill)"],
        [
            "Un « oui » = un seul ordre, jamais un lot ; la réponse est enregistrée mot pour mot.",
            "Un ordre est READY seulement si le fingerprint PASS du jour correspond et qu'aucune décision n'existe déjà.",
            "result ne peut suivre que approve ; fill ajoute un lot (achat) ou consomme les lots en FIFO (vente).",
            "Paper trading par défaut ; clés API dans les variables d'environnement, jamais dans le chat.",
            "TraderDesk ajoute une 4e porte : le connecteur MetaTrader 5 (simulation / REST / local) + kill switch + plafonds.",
        ],
        "Ticket : « Buy $1,250 of AAPL, market, day » → JSON {symbol:AAPL, side:buy, notional:\"1250\", type:market, time_in_force:day}. Après « yes », TraderDesk envoie l'équivalent MT5 (volume = notional / prix) et enregistre le ticket broker + le fill.",
        ["Ne place rien par lui-même (dans le pack d'origine)", "N'accepte jamais un ordre non READY", "Ne demande jamais les clés dans le chat"],
        "Exécution", "Après risque, un ordre à la fois", "⇄", "#ff9f1c", "trader-broker/ticket.py",
    ),
    spec(
        "trader-tax", "/trader-tax", "Optimiseur fiscal",
        "Suit les lots de prix de revient, gains/pertes et wash sales",
        "Tient les lots (FIFO, HIFO ou lots spécifiques), calcule les gains latents par lot avec terme court/long et la date de passage en long terme, simule ce qu'une vente réaliserait AVANT de vendre, trouve les candidates au tax-loss harvesting au-dessus d'un seuil, vérifie la règle des 30 jours avant/après (GOOG et GOOGL = une même famille) et n'écrit que des propositions de vente.",
        ["what are my gains", "cost basis", "tax-loss harvest", "wash sale", "before selling anything"],
        [
            "lots.py report --lots",
            "lots.py sell KO 2 --price 90.11",
            "lots.py sell KO 2 --method specific --lots KO-2",
            "lots.py harvest --min-loss 100 --write",
            "lots.py wash KO",
        ],
        ["trader/portfolio.json (positions + lots {id,date,shares,cost})", "trader/prices.json", "trader/orders.json (achats planifiés = wash sale)", "trader/state/tax.json"],
        ["trader/state/tax.json (ventes réalisées)", "trader/orders.json (propositions harvest avec --write)"],
        [
            "Long terme si vente > 1 an après l'achat, sinon court terme ; report --lots donne la date de bascule.",
            "Méthodes : fifo, hifo, specific. L'ordre broker ne porte pas d'ID de lot : le choix se fait dans les paramètres du broker.",
            "Wash sale : perte disallowed si rachat du même titre (ou substantiellement identique) 30 jours avant/après ; l'outil vérifie les autres lots, les achats planifiés et les ventes enregistrées.",
            "Il ne voit ni IRA, ni compte du conjoint, ni un autre broker — le rappeler.",
            "Ce n'est PAS un conseil fiscal : pas de taux, pas d'impôt dû, pas de déclaration.",
        ],
        "Portefeuille acheté le 2026-10-13 : un lot par titre, tous court terme jusqu'au 2027-10-14. Si BAC passe sous sa base de 600 $, harvest --min-loss 25 propose BAC-1 avec la date « ne pas racheter avant » (31 jours après la vente).",
        ["Ne donne jamais de taux ou de montant d'impôt", "Ne propose jamais une vente qu'il voit comme wash sale", "Ne place aucun ordre"],
        "Maintenance", "Avant toute vente / fin d'année", "§", "#43aa8b", "trader-tax/lots.py",
    ),
    spec(
        "trader-alerts", "/trader-alerts", "Alertes de prix",
        "Sonne sur un objectif, un stop ou la cloche d'ouverture",
        "Règles above / below / stop / pct_move / opening_bell, chacune ne sonne qu'une fois (ou se réarme). Connaît les heures NYSE 9:30–16:00 avec les jours fériés 2026 et 2027 et les fermetures anticipées à 13:00, gère l'heure d'été sans fichier de timezone, récupère des cotations gratuites différées (Yahoo chart JSON, Stooq CSV) un ticker à la fois et écrit trader/prices.json pour budget, risk, tax et rebalance.",
        ["alert me when", "tell me if AAPL hits", "set a stop", "is the market open", "get me prices"],
        [
            "alerts.py clock",
            "alerts.py quote AAPL KO --write",
            "alerts.py quote --holdings --write",
            "alerts.py add --symbol AAPL --above 350",
            "alerts.py add --symbol BAC --stop 50 --note \"my stop\"",
            "alerts.py check",
            "alerts.py list",
            "alerts.py reset aapl-above-350",
        ],
        ["trader/alerts.json (règles)", "trader/prices.json", "trader/state/alerts.json (ce qui a sonné)", "Yahoo chart JSON / Stooq CSV"],
        ["trader/prices.json : {\"as_of\", \"prices\": {...}}", "trader/state/alerts.json", "trader/alerts.json"],
        [
            "above : prix ≥ price ; below/stop : prix ≤ price ; rearm ou reset pour sonner à nouveau.",
            "pct_move : mouvement de pct % depuis la clôture précédente (ou ref), au plus une fois par jour.",
            "opening_bell : une fois par jour de bourse ; calendrier NYSE 2026/2027 intégré, autre année = « liste inconnue ».",
            "Cotations GRATUITES et différées : suffisant pour alertes/tailles, jamais pour timer un ordre ; le prix broker fait foi.",
            "Une alerte est une information, JAMAIS un ordre : un stop qui sonne ne vend rien.",
        ],
        "Le 2026-10-13, AAPL clôture 341,27 $ et BAC 53,96 $ : check → « Nothing hit ». À 9:30 le lendemain, opening_bell sonne une fois.",
        ["Ne place / annule / modifie jamais un ordre", "Ne prétend pas qu'une cotation est temps réel", "Ne prédit pas le cours"],
        "Données de marché", "Toutes les 15 min en séance", "◷", "#00bbf9", "trader-alerts/alerts.py",
    ),
    spec(
        "trader-rebalance", "/trader-rebalance", "Rééquilibreur",
        "Ramène le portefeuille aux poids cibles quand il dérive",
        "Valorise chaque position au prix courant, calcule la dérive en points de pourcentage par rapport à la cible, ne propose des trades que pour les titres HORS de la bande (5 points par défaut), garde le buffer de cash et le plafond par titre, ignore les micro-trades, liste les ventes avant les achats et écrit trader/orders.json en propositions.",
        ["rebalance", "my portfolio drifted", "bring it back to the targets", "am I overweight"],
        [
            "rebalance.py",
            "rebalance.py --band 5 --write",
            "rebalance.py --sell-untracked --json",
        ],
        ["trader/portfolio.json", "trader/prices.json", "trader/targets.json", "trader/config.json (rebalance_band_pct)"],
        ["trader/orders.json (propositions, ventes d'abord)", "trader/state/rebalance.json (table de dérive TraderDesk)"],
        [
            "Valeur du compte = cash + chaque position au prix courant.",
            "Cibles renormalisées sur la poche actions (compte − buffer), aucune au-dessus de max_position_pct.",
            "Dérive = % actuel du compte − % cible ; seuls les titres à plus de « band » points sont tradés, retour complet à la cible.",
            "Ventes d'abord pour disposer du cash ; achats seulement avec le cash au-dessus du buffer, sinon tous réduits du même facteur.",
            "Trades < min_order_usd ignorés ; trade > max_order_usd coupé au max (relancer après fill).",
            "Positions hors cibles laissées tranquilles et listées, sauf --sell-untracked.",
        ],
        "Portefeuille copié valorisé aux clôtures du 2026-10-13 : chaque dérive < 0,1 point → « rien hors de la bande », aucun trade proposé.",
        ["Ne place aucun ordre", "Ne vend pas sans passer par trader-tax puis trader-risk", "Ne modifie pas les cibles"],
        "Maintenance", "Mensuel / trimestriel, après une nouvelle 13F", "⟳", "#80ed99", "trader-rebalance/rebalance.py",
    ),
]

AGENTS_BY_ID = {a["id"]: a for a in AGENTS}

PIPELINES = [
    {
        "name": "Copier un investisseur",
        "flow": ["trader-copycat", "trader-budget", "trader-risk", "trader-broker"],
        "detail": "13F-HR → poids cibles → dimensionnement en $ → contrôle des limites → tickets → exécution MT5.",
    },
    {
        "name": "Choisir ses propres titres",
        "flow": ["trader-analyst", "trader-screener", "trader-budget", "trader-risk", "trader-broker"],
        "detail": "Chiffres SEC XBRL → shortlist → dimensionnement → contrôle → tickets → exécution MT5.",
    },
    {
        "name": "Veille continue",
        "flow": ["trader-news", "trader-pelosi", "trader-alerts"],
        "detail": "Headlines + 8-K, dépôts du Congrès, prix et cloche NYSE : information seulement, jamais d'ordre.",
    },
    {
        "name": "Maintenance du portefeuille",
        "flow": ["trader-rebalance", "trader-tax", "trader-risk", "trader-broker"],
        "detail": "Dérive et lots fiscaux → propositions → contrôle → tickets → exécution MT5.",
    },
]

ARTIFACTS = [
    {"file": "trader/targets.json", "by": "trader-copycat", "used_by": "trader-budget, trader-rebalance, trader-news", "what": "Poids cibles à copier, source et date du 13F"},
    {"file": "trader/metrics.json", "by": "trader-analyst", "used_by": "trader-screener", "what": "Métriques fondamentales (TTM, croissance, marges)"},
    {"file": "trader/shortlist.json", "by": "trader-screener", "used_by": "trader-budget", "what": "Sociétés qui passent les règles + score et raisons"},
    {"file": "trader/prices.json", "by": "trader-alerts", "used_by": "trader-budget, trader-risk, trader-tax, trader-rebalance", "what": "Dernières cotations différées"},
    {"file": "trader/orders.json", "by": "trader-budget / rebalance / tax", "used_by": "trader-risk, trader-broker", "what": "Ordres proposés, jamais exécutés directement"},
    {"file": "trader/state/risk.json", "by": "trader-risk", "used_by": "trader-broker", "what": "PASS / BLOCK par ordre avec fingerprint"},
    {"file": "trader/state/broker.json", "by": "trader-broker", "used_by": "trader-risk, trader-tax", "what": "Journal append-only des oui / non / placements"},
    {"file": "trader/portfolio.json", "by": "trader-broker (fill)", "used_by": "trader-tax, trader-rebalance, trader-news, trader-risk", "what": "Cash, positions et lots de prix de revient"},
    {"file": "trader/config.json", "by": "vous (paramètres)", "used_by": "tous les agents", "what": "Budget, buffer, caps, limites, blocked, paper, SEC UA"},
    {"file": "trader/rules.json", "by": "vous (paramètres)", "used_by": "trader-screener", "what": "Règles du screen et pondération du classement"},
    {"file": "trader/alerts.json", "by": "trader-alerts", "used_by": "trader-alerts", "what": "Règles d'alerte de prix"},
    {"file": "trader/state/news.json", "by": "trader-news", "used_by": "trader-news", "what": "Items déjà vus (30 jours)"},
    {"file": "trader/state/pelosi.json", "by": "trader-pelosi", "used_by": "trader-pelosi", "what": "DocID des PTR déjà annoncés"},
    {"file": "trader/state/tax.json", "by": "trader-tax", "used_by": "trader-tax", "what": "Ventes réalisées de l'année"},
]


def skill_markdown(agent_id):
    p = Path(SKILLS_DIR) / agent_id / "SKILL.md"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return "# Documentation indisponible\n"
