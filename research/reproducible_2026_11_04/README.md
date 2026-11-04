# LPPLS — Pack expérimental reproductible (4 novembre 2026)

Code récupéré **sans écraser** la chaîne Streamlit dans `src/lppls_bubble/`. Ce dossier forme une expérimentation autonome et explicite.

## Origine et versions

- `lppls_core_source.py` : contenu **strictement inchangé** de `lppls_core.py` fourni dans `lppls_complete_notebooks_and_outputs.zip`. Ne pas l'importer dans les notebooks : il est conservé comme référence documentaire.
- `lppls_core.py` : **copie corrigée et testée localement**, dont les seuls ajustements sont :
  1. remplacement de `DataFrame.std(min_count=13)` (argument pandas non accepté) par `std().where(count() >= 13)` ;
  2. `valid_frac` rapporté à **7 fenêtres prévues** plutôt qu'au nombre de fenêtres disponibles ;
  3. correction du message d'erreur si aucun actif n'a de fenêtre complète ;
  4. `max_rebalances` borne aussi la période de valorisation à la dernière période de détention.
- `README_ORIGINAL.md` et les six notebooks `notebooks/` : repris **tels quels** du ZIP. Un notebook appelé `executed` est en réalité **non exécuté** (tous les `outputs` sont vides), comme indiqué dans la source.
- `examples/synthetic_example.csv` : jeu de données entièrement synthétique, **pas de prix réels**.

Les noms des quatre notebooks déjà présents dans le dépôt coïncident avec certains de ce pack mais leur **contenu diffère**. Ils restent dans leur dossier d'archive historique `notebooks/`; les nouvelles variantes sont sous `research/reproducible_2026_11_04/notebooks/`.

## Exécution autonome (hors Streamlit)

Depuis la racine de ce dossier :

```bash
python -m pip install -r requirements.txt
# Déposer un CSV autorisé et nommé Miscellanous.csv à ce niveau
jupyter lab
# Ouvrir notebooks/ds_lppls_pipeline_with_backtest_named.ipynb
```

Pour un smoke test sur le CSV synthétique sans notebook :

```python
from pathlib import Path
from lppls_core import load_prices, to_weekly, write_snapshot_outputs, run_backtest
weekly = to_weekly(load_prices('examples/synthetic_example.csv'))
write_snapshot_outputs(weekly, Path('outputs'), grid='tiny')
run_backtest(weekly, Path('outputs'), start_date='2024-02-01',
             rebalance_weeks=4, grid='tiny', max_rebalances=3)
```

Le mode `tiny` permet la recette rapide. Le mode `full` explore une grille plus large et est plus coûteux. Les sorties `outputs/` ne doivent pas être versionnées ; les livrables historiques sont dans [`../../artifacts/historical_2026_02_27/`](../../artifacts/historical_2026_02_27/).

## Réserves scientifiques

Le moteur est **exploratoire**, et sa recherche discrète des paramètres ne constitue pas une estimation LPPLS certifiée. Le backtest présente une convention de **valorisation à prix inchangé quand un rendement observé manque**, avec export `backtest_missing_returns.csv` ; ce n'est pas un rendement observé de 0 % et le résultat peut être biaisé. Le modèle de portefeuille est simplifié (poids fixes entre rééquilibrages, contraintes et frais incomplets). Le benchmark équipondéré ne démontre aucune supériorité de la stratégie. La comparaison avec le moteur `src/lppls_bubble/backtest.py` demande des données réelles et un protocole commun. Aucune équivalence entre performances historiques et nouvelles performances n'est revendiquée.
