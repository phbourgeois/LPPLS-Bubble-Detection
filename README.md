# LPPLS-Bubble-Detection

Application Streamlit de detection exploratoire de bulles financieres par ajustement LPPLS multi-echelles.

## Etat du projet (bootstrap 2026-11-04)

- **Code historique retrouve** : notebook Colab `notebooks/ds_lppls_pipeline.ipynb` (27 fevrier 2026).
- **Moteur migre** : `src/lppls_bubble/legacy_engine.py` encapsule **sans remplacer les calculs** des cellules du notebook pour fournir les estimations aux 7 horizons hebdomadaires 13, 26, 39, 52, 65, 78, 104.
- **Interface initiale** : chargement du CSV SBF120 historique, selection des fenetres, tableaux, heatmap, graphique des cours, exports CSV/PNG/HTML/PDF.
- **Notebooks du backtest recuperes** depuis l'archive du projet : 3 versions sous `notebooks/`, dont une reconstruction NON EXECUTEE et une version `named` avec code de backtest. Voir `docs/BACKTEST_AUDIT.md`.
- **Backtest experimental integre** : moteur `src/lppls_bubble/backtest.py` avec selection causale et suivi des portefeuilles. Ce moteur corrige des biais du notebook source ; les resultats historiques ne sont PAS reproduits a l'identique.
- **Non valide scientifiquement** : signaux LPPLS heuristiques du notebook ; aucune inference de probabilite ni signal de trading certifie.

## Execution locale

```bash
python -m venv .venv
# Activer .venv, puis :
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Le CSV est lu selon la convention d'origine (`;`, decimales `,`, trois lignes d'en-tete de metadonnees puis `Name;...`). Historique minimal : **104 semaines** par actif avec les fenetres par defaut.

## Tests, credits GitHub Actions

```bash
python -m pytest -q
```

Les tests s'executent localement. **Aucun workflow GitHub Actions n'est fourni** dans cette version : aucune execution facturable ne doit etre declenchee par la migration. Le futur CI sera manuel (`workflow_dispatch`) et declenche uniquement apres verification locale.

## Provenance et limites

Voir [docs/RECOVERY.md](docs/RECOVERY.md) et [docs/BACKTEST_AUDIT.md](docs/BACKTEST_AUDIT.md). Les notebooks historiques sont maintenant archives, mais leurs sorties d'execution ne sont pas verifiees ; aucune validite predictive n'est etablie.

## Archives complémentaires (4 novembre 2026)

- [Audit des deux ZIP et limites](docs/ARCHIVE_AUDIT_2026_11_04.md).
- [Pack de recherche autonome](research/reproducible_2026_11_04/README.md) : nouveau moteur `lppls_core.py`, 6 notebooks (dont 2 nouveaux usages), exemple synthétique, source d'origine et copie corrigée ; **pas branché automatiquement sur Streamlit**.
- [Six résultats historiques dédupliqués](artifacts/historical_2026_02_27/README.md) : 15 actifs, 105 estimations, sans prix bruts ni backtests NAV.

La version de production reste `src/lppls_bubble/`. Les nouvelles variantes sont publiées isolément pour éviter de modifier les estimations et performances de la V0 sans une recette comparative.


## Moteur de référence (comparaison contrôlée du 4 novembre 2026)

**Référence opérationnelle : `src/lppls_bubble`** pour l'interface Streamlit (snapshots et backtests). Sur les échantillons synthétiques contrôlés, les deux moteurs concordent sur **56/56 ajustements LPPLS**, **8/8 classifications** et les pondérations instantanées sur séries complètes. Le moteur historique a été sécurisé sur la **continuité des fenêtres de prix**, sur l'exclusion des actifs incomplets des portefeuilles et sur les **formats CSV standard / Datastream**. En backtest, la variante retenue dérive réellement les positions et rapproche les rendements nets de la NAV ; la variante de recherche a des écarts comptables avec frais.

**Avertissement scientifique essentiel :** 40/40 marches aléatoires indépendantes passent le filtre heuristique `R² >= 0,2` dans un test de simulation. L'application est un **outil de recherche exploratoire**, pas un détecteur de retournements validé ni un service de conseil en investissement.

- [Protocole, résultats et décision scientifique](docs/SCIENTIFIC_ENGINE_COMPARISON_2026_11_04.md)
- [Données et tableaux reproductibles de comparaison](docs/engine_comparison_data/summary.json)
- Commande de reproduction locale : `python scripts/compare_engines.py`
- **Aucune migration automatique du moteur `research/` vers Streamlit** et aucun workflow Actions ajouté.

## Validation statistique séparée (2026-11-04)

La règle historique R² ne permet pas d'identifier une bulle avec fiabilité. Le module expérimental `src/lppls_bubble/statistical.py` calcule des scores calibrés par bootstrap de blocs et marche aléatoire gaussienne, avec réestimation complète des modèles et correction BH entre actifs/fenêtres à chaque date. **Cette couche ne modifie pas automatiquement le backtest ou les ordres.**

Premier test sur prix publics réels 2007–2016, quatre actions et le S&P 500 : 200 fits sur 20 dates de décision (2013–2015), **0 signal significatif**, alors que 8 épisodes de forte baisse et 13 de forte hausse sont observés parmi les actions au cours des 8 semaines suivantes. **Aucune capacité prédictive démontrée.** Voir [rapport](docs/STATISTICAL_VALIDATION_2026_11_04.md) et [résultats](docs/statistical_validation/summary.json).

Reproduction locale : `PYTHONPATH=src python scripts/validate_lppls_oos.py --input data/external/plotly_stockdata_weekly_2007_2016.csv` ; `PYTHONPATH=src pytest -q`. Aucun workflow Actions ajouté.

## Contrôle qualité causal et pondération (proposition du 4 novembre 2026)

Le backtest peut maintenant exporter un audit de qualité par actif et date de décision (`backtest_quality_asof.csv`) et la convention de pondération (`backtest_weighting_policy.csv`). Le mode `audit` est le défaut : **aucun titre n'est exclu sur la seule base d'une variation extrême**, et les poids historiques restent inchangés. Le mode optionnel `block_documented` accepte un registre CSV de décisions publiées datées, sans anticiper les événements futurs. Cette mise à jour ne déploie pas les variantes `MIXED_SCALES` par défaut.

Voir [règles, limites et décisions en suspens](docs/QUALITY_FILTER_AND_WEIGHTING.md).

## Téléchargement unique depuis Streamlit (4 novembre 2026)

Après une exécution réussie de l'analyse LPPLS, l'interface présente **un seul bouton** `Télécharger les livrables LPPLS (ZIP)`. L'archive `lppls_livrables_complets.zip` est organisée en dossiers :

- `donnees/source.csv` : copie du fichier d'entrée réellement analysé ;
- `donnees/quality_events.csv` : registre des événements si fourni pour le backtest ;
- `lppls/` : tous les exports des estimations, synthèses et rapports HTML/PDF ;
- `backtest/` : poids, états, qualité, turnover, NAV et performances, si demandé et réussi ;
- `statistique/` : CSV du diagnostic expérimental, s'il a été calculé ;
- `manifest.json` et `README.md` : paramètres d'exécution, statut de chaque calcul, empreintes SHA-256 des fichiers et guide de lecture.

Un backtest en erreur n'est **jamais présenté comme réussi** : le ZIP conserve les autres résultats et le manifeste mentionne explicitement l'échec. Les fichiers CSV, PNG, HTML, PDF conservent leurs octets originaux dans l'archive. Ce regroupement est destiné à faciliter un audit des résultats en partageant un seul fichier, sans modification des calculs ou règles de trading.

## Backtest auditable et période complète (5 novembre 2026)

- Les estimations LPPLS et le backtest écartent désormais la dernière semaine `W-FRI` inachevée : le dernier cours du mardi n'est pas présenté comme la clôture du vendredi futur.
- Dans Streamlit, par défaut, le backtest couvre **jusqu'à la dernière semaine complète** ; la limitation du nombre de rééquilibrages est devenue facultative.
- `backtest_quality_weekly_alerts.csv` relève toutes les alertes de variation extrême et cours stagnants, **y compris entre deux rééquilibrages**, sans suppression arbitraire des rendements.
- `backtest_attribution_weekly.csv` fournit contributions par actif, poids avant/après rendement et transactions ; `backtest_reconciliation.csv` rapproche sommes des contributions, frais et NAV.
- `backtest_report.html` et `backtest_report.pdf` sont des **rapports de backtest autonomes**, inclus dans le ZIP en plus des rapports du modèle LPPLS.
- Frais, périodes réelles, volatilités, rendements annualisés, Sharpe et concentrations sont désormais exportés ; stratégies, règles de pondération et statut de validation scientifique inchangés.

Voir [protocole et limites de cette mise à jour](docs/BACKTEST_DATA_QUALITY_REPORTS_2026_11_05.md). Les cours de marché historiques ne sont pas certifiés ajustés ; les mouvements atypiques doivent être vérifiés auprès du fournisseur.

## Grille approfondie unique (5 novembre 2026)

Les deux moteurs opérationnels (photographie LPPLS et historique du backtest) utilisent désormais **exactement la même grille approfondie de 343 combinaisons**. Le calcul est mutualisé et vectorisé avec mise en cache des matrices, sans retour à une grille simplifiée. Le fichier `manifest.json` du ZIP et `backtest_summary_metrics.csv` identifient la version de la grille. Les anciens backtests calculés sur 27 combinaisons ne sont pas comparables sans recalcul.

Voir [méthode et tests de concordance](docs/UNIFIED_FULL_GRID_2026_11_05.md).
