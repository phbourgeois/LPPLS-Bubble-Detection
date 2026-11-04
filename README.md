# LPPLS-Bubble-Detection

Application Streamlit de detection exploratoire de bulles financieres par ajustement LPPLS multi-echelles.

## Etat du projet (bootstrap 2026-11-04)

- **Code historique retrouve** : notebook Colab `notebooks/ds_lppls_pipeline.ipynb` (27 fevrier 2026).
- **Moteur migre** : `src/lppls_bubble/legacy_engine.py` encapsule **sans remplacer les calculs** des cellules du notebook pour fournir les estimations aux 7 horizons hebdomadaires 13, 26, 39, 52, 65, 78, 104.
- **Interface initiale** : chargement du CSV SBF120 historique, selection des fenetres, tableaux, heatmap, graphique des cours, exports CSV/PNG/HTML/PDF.
- **Pas encore recuperes** : notebooks historiques du backtesting et sorties du 27/02/2026, dont `ds_lppls_pipeline_with_backtest_named.ipynb`.
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

Voir [docs/RECOVERY.md](docs/RECOVERY.md). Une application disponible ne signifie pas que le backtesting historique a ete retrouve ou que les signaux ont une validite predictive etablie.
