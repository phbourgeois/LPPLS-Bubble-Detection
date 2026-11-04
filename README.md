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
