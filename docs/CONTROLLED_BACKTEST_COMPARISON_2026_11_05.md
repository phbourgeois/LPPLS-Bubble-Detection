# LPPLS — comparaison contrôlée des backtests et transparence des exclusions
Date : 5 novembre 2026

## Pourquoi cette intervention ?

Le ZIP de référence sur SBF 120 conserve 120 titres pour le snapshot, mais seulement 117 pour les rendements historiques, après exclusions rétrospectives d'ATOS, ABIVAX et Eutelsat. Les règles LPPLS de classification et de pondération ne changent **pas**. Les titres exclus doivent apparaître dans le rapport de backtest : nom, portée, dates d'anomalies et justification. Les conclusions doivent être étiquetées **RETROSPECTIVE_SENSITIVITY**, jamais « investissables sans anticipation ».

## Base commune imposée

- Même fichier `audit/backtest_prices.csv` (après décisions de qualité).
- Même historique, fréquence hebdomadaire W-FRI, dernière semaine complète, dates de décision, horizon de détention et frais de transaction pour **cinq** stratégies.
- Même grille canonique LPPLS 7×7×7 = 343 candidats, et **mêmes signaux estimés à chaque décision** : aucun refit pour favoriser un scénario.
- Même capital initial de 1, dérive des poids entre décisions, transactions après rendement à la clôture de rééquilibrage.
- Benchmark équipondéré sur **les titres éligibles à la date de décision selon l'historique de 104 semaines et le blocage éventuel**. Il utilise exactement les actifs de l'univers de backtest retenu et est rebalancé au même rythme. **Ce n'est pas le SBF 120 officiel, ni un indice de rendement total**.

## Cinq scénarios comparables

| Scénario | Achat | Vente | Poids |
|---|---|---|---|
| `original_long_only` | Tous sauf COHERENT_MULTI_UP | Aucun | Inverse-volatilité 52 semaines |
| `original_long_short` | Tous sauf COHERENT_MULTI_UP | COHERENT_MULTI_UP | Achats inverse-volatilité, shorts score LPPLS |
| `benchmark_equal_weight` | Tous les titres éligibles | Aucun | Équipondération |
| `mixed_long_only` | COHERENT_MULTI_DOWN, NO_BUBBLE et MIXED si court UP / long DOWN | Aucun | **Même inverse-volatilité** |
| `mixed_long_short` | Même poche acheteuse que ci-dessus | COHERENT_MULTI_UP et MIXED si court DOWN / long UP | **Même inverse-volatilité à l'achat**, **même score LPPLS à la vente** |

Les MIXED dont le signal court ou long est NONE/MIXED ne sont pas introduits par force dans les nouvelles poches. La poche L/S utilise les mêmes objectifs que l'original (50 % long et −50 % short lorsqu'il existe des titres vendeurs ; sinon 100 % long). Aucune volatilité cible, aucun plafond, aucun coût de prêt ni filtre statistique nouveau n'est ajouté.

**Important :** le benchmark 100 % long et le Long/Short proche de zéro net ne portent pas le même risque de marché. Cette comparaison contextualise les rendements ; elle ne permet pas d'attribuer les écarts uniquement à la qualité des signaux sans tests complémentaires de neutralisation du bêta.

## Vérification du moteur et trace

`run_strategy_comparison` reçoit les poids cibles **originaux déjà calculés** par le moteur de backtest, leurs mêmes états LPPLS et leurs dates. Il rejoue les deux stratégies historiques et **interrompt l'analyse** si une seule NAV diffère de celle publiée de plus de `1e-10`. Il n'existe donc pas de second modèle de comptabilité autonome libre de dériver silencieusement.

La comparaison exporte :

- `backtest_comparison_nav.csv` : cinq NAV et leurs rendements hebdomadaires.
- `backtest_comparison_metrics.csv` : performance, rendement et volatilité annualisés, Sharpe rf=0, drawdown, turnover, poids maximal, écart de rendement annualisé et tracking error vis-à-vis du benchmark.
- `backtest_comparison_targets.csv` : chaque cible par date, stratégie et titre.
- `backtest_comparison_exposures.csv` : long, short, net, concentration et coûts.
- `backtest_comparison_turnover.csv` : transactions et montant brut.
- `backtest_comparison_gaps.csv` : écart de NAV et de rendement à l'équipondéré.
- `backtest_comparison_signal_counts.csv` : nombre d'actions par catégorie de signal lors de chaque décision.
- `backtest_comparison_annual.csv` : rendement composé par année civile.
- `backtest_comparison_nav.png` : graphique des cinq NAV.

Les rapports **HTML et PDF** intègrent dès leur début l'univers effectivement analysé, le statut de sensibilité et la liste motivée des exclusions. Ils ajoutent ensuite les cinq scénarios, les règles exactes et la courbe comparée. Le ZIP Streamlit conserve tous les anciens fichiers et les nouveaux exports automatiquement.

## Première simulation indépendante sur le ZIP du 5 novembre 2026

117 titres, 36 décisions et 143 semaines de rendement, du 02/02/2024 au 30/10/2026, 0 point de base de frais :

| Scénario | Performance cumulée |
|---|---:|
| Original Long-only | +9,61 % |
| Original Long/Short | −2,71 % |
| Benchmark équipondéré (même univers) | +19,41 % |
| Mixed Long-only | +0,65 % |
| Mixed Long/Short | −9,12 % |

Les deux stratégies originales sont reproduites par le rejeu indépendant au seuil `2e-15`. Ce premier essai confirme **qu'aucun gain systématique ne doit être présumé** des règles mixtes directionnelles ; il n'est pas une démonstration de robustesse, et les titres ont été exclus rétrospectivement.

## Réserves et tests

Tests de régression dans `tests/test_backtest_comparison.py` : sélection explicite des oppositions, pondération short par score, replay de la NAV, contrôle des dates et du coût, présence des rapports et du tableau d'exclusion. Pour la recette, lancer `python -m pytest -q` puis une seule exécution Streamlit sur le CSV de référence ; vérifier les cinq courbes, la réconciliation des deux originales et le ZIP complet.

Les prix ne sont pas certifiés ajustés des opérations sur titres, le SBF 120 est reconstruit à partir de l'univers fourni et non d'une composition historique datée, le financement du short reste ignoré et la couche statistique LPPLS ne prouve aucune prédictibilité. Les résultats sont exploratoires. Aucune GitHub Actions n'est nécessaire pour préparer cette recette.
