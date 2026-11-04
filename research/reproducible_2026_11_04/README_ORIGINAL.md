# LPPLS — Pack reproductible (4 novembre 2026)

## Installation
Python 3.10+ ; `pip install -r requirements.txt`. Jupyter : `jupyter lab`.
Décompresser l'archive, placer **Miscellanous.csv** au même niveau que `lppls_core.py`, puis ouvrir `notebooks/ds_lppls_pipeline.ipynb`.
Les notebooks détectent automatiquement leur dossier parent si Jupyter démarre dans `notebooks/`.

## Notebooks
- `ds_lppls_pipeline.ipynb` : 5 CSV de synthèse et heatmap.
- `ds_lppls_pipeline_with_backtest.ipynb` : pipeline + tous les fichiers de backtest.
- `ds_lppls_pipeline_with_backtest_named.ipynb` : version avec vérification explicite des noms des actifs.
- `ds_lppls_pipeline_executed.ipynb` : version *prête à exécuter* (NON exécutée sur le CSV utilisateur ; nom conservé pour compatibilité).
- `ds_lppls_backtest_only.ipynb` : backtest seul.
- `ds_lppls_validation.ipynb` : contrôles de structure des résultats.

## Outputs générés par le pipeline
`outputs/details_by_scale_all_series.csv`, `summary_by_scale_wide.csv`, `bubble_type_by_asset.csv`,
`bubble_summary_by_scale_wide.csv`, `portfolio_construction.csv`, `heatmap_global.png`.

## Outputs du backtest
`backtest_portfolios_long_only_weights.csv`, `backtest_portfolios_long_short_weights.csv`,
`backtest_portfolios_long_only_weights_wide.csv`, `backtest_portfolios_long_short_weights_wide.csv`,
`backtest_nav_weekly.csv`, `backtest_turnover.csv`, `backtest_states.csv`,
`backtest_summary_metrics.csv`, `backtest_missing_returns.csv`, `backtest_nav_plot.png`.

## Précautions méthodologiques
- LPPLS sur le logarithme des cours : y(t) = A+B(tc-t)^m+C1(tc-t)^m cos(ω ln(tc-t))+C2(tc-t)^m sin(ω ln(tc-t)).
- Grille discrète (et choix de paramètres aux bords) : **exploratoire**, non certifiée statistiquement.
- Le R² minimal de 0.2, le signe de B et le score de priorité sont des **heuristiques**.
- Fréquence hebdomadaire vendredi ; pas de propagation des prix avant la régression ; les semaines sans prix sont exclues des ajustements complets.
- Pour les rendements futurs absents, le backtest indique les cas et suppose une valorisation au dernier cours (rendement imposé à zéro). La méthode peut biaiser les résultats.
- Pas de dividendes, frais de prêt, financement des shorts, impact, slippage, risques de marché ni survivorship bias, sauf si les prix fournis les intègrent et si les coûts transactionnels sont activés.
- Rééquilibrage à la clôture du vendredi, **après** valorisation du rendement de la semaine, donc pas de look-ahead sur la semaine échue.
- Rendements hebdomadaires en supposant des poids fixes entre rebalancements ; ce n’est pas une simulation transactionnelle détaillée.
- Les actifs peuvent être des indices et des cours en devises différentes : une agrégation en portefeuille réel requiert la conversion en devise commune et la définition d’un univers investissable.
- Les sorties présentes dans `historical_outputs/` sont des **archives antérieures**, et ne sont pas des résultats nouvellement calculés.
- Le CSV source original n'est pas présent dans cette session. Le pack a été testé sur un jeu synthétique, sans valider les résultats historiques utilisateurs.
