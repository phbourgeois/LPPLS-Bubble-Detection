# Grille LPPLS unique et approfondie — décision du 5 novembre 2026

## Arbitrage retenu

**Une seule grille est désormais autorisée pour le snapshot et les estimations historiques du backtest.** Elle utilise exactement les 343 combinaisons de la grille approfondie initiale : 7 valeurs de l'exposant `m` entre 0,1 et 0,9, 7 fréquences `omega` entre 6 et 13, et 7 horizons candidats pour `t_c` entre 1 semaine et 1,5 fois la longueur de la fenêtre.

- Version immuable : `legacy_full_7x7x7_v1`
- Implémentation canonique : `src/lppls_bubble/lppls_fit.py`
- Entrée identique : logarithmes des prix hebdomadaires observés sur la fenêtre de longueur fixée.
- Choix du modèle : minimum de la somme des carrés des résidus (SSE) parmi les 343 régressions.
- Validité : filtres LPPLS hérités, notamment `R² >= 0,2`, et même classification UP lorsque `B < 0`, DOWN sinon.
- Les paramètres complets `A,B,C,m,omega,phi,t_c,R²,RMSE` sont calculés dans le composant commun ; le backtest n'exploite que ceux nécessaires à ses décisions.
- Le backtest garde ses règles de pondération et ses deux stratégies existantes ; aucune sélection entre grille rapide et approfondie n'est proposée dans Streamlit.

## Optimisation sans approximation

Les 343 matrices de régression et leurs pseudo-inverses sont précalculées une seule fois **par longueur de fenêtre**, puis réutilisées. Les 343 SSE exactes sont calculées de façon vectorisée sur chaque vecteur de cours. Aucun candidat de la grille approfondie n'est supprimé.

Il ne s'agit **pas** d'une recherche continue de paramètres et la grille peut laisser des solutions sur ses bornes. L'identification des bulles, la stabilité des paramètres et les performances prédictives restent à démontrer séparément.

## Comparabilité et bascule

Les performances historiques déjà exportées avec la grille à 27 combinaisons **ne doivent pas être comparées directement** à des backtests utilisant les 343 combinaisons : des signaux, positions et performances vont changer. Les résultats antérieurs sont une archive et doivent être recalculés sur les mêmes cours, dates et hypothèses.

Le manifeste ZIP Streamlit enregistre `lppls_grid_version` et `lppls_grid_candidates_per_fit`. Le CSV `backtest_summary_metrics.csv` reprend ces références. L'alias `fit_tiny` reste exporté seulement pour compatibilité de code tiers ; il exécute maintenant **la grille de 343 points**.

## Recette et vérification

1. Comparer les 343 combinaisons au solveur en boucle historique (7 fenêtres).
2. Comparer signaux court/long terme, état multi-échelles et priorité entre snapshot et backtest **à la même date**.
3. Comparer le calcul avec et sans modifications des cours postérieurs à la date de décision : les sorties à cette date doivent être identiques.
4. Exécuter les tests locaux et un backtest représentatif ; vérifier le ZIP, ses dates, la réconciliation des NAV et la grille déclarée.
5. Effectuer une unique recette de déploiement Streamlit ; ne pas multiplier les campagnes GitHub Actions.

Les tests de comparaison du solveur ont été exécutés localement sur 28 estimations synthétiques et 42 estimations réelles de six titres de l'archive SBF : résultats identiques à la grille originale aux tolérances numériques près. Les tests d'intégration ajoutés au dépôt restent à exécuter sur l'application entière.
