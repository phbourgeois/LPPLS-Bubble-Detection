# Backtest LPPLS : contrat de données, chronologie et rapports (5 novembre 2026)

## Périmètre

Le moteur de référence reste `src/lppls_bubble/backtest.py`. Les stratégies historiques Long-only et Long/Short ne changent pas. Les poids acheteurs restent inversement proportionnels à la volatilité hebdomadaire des 52 semaines précédentes ; les poids vendeurs restent fondés sur le `priority_score`. Les plafonds de concentration, les quarantaines automatiques et l'activation de MIXED_SCALES restent **non arbitrés**.

Le modèle reste exploratoire, sans démonstration de pouvoir prédictif ; ses performances ne constituent pas des rendements investissables certifiés.

## 1. Qualité des séries

- La dernière semaine `W-FRI` est exclue si son dernier cours est daté **avant le vendredi de clôture**. Les semaines vides au milieu de la période restent vides, jamais comprimées.
- Aucune correction automatique de split, d'augmentation de capital, de distribution ou de radiation n'est improvisée.
- `backtest_quality_weekly_alerts.csv` enregistre **toutes les semaines** présentant une variation de prix >= 50 % en valeur absolue, ou au moins huit clôtures hebdomadaires identiques. `REVIEW` et `CRITICAL_REVIEW` sont des priorités de vérification et non des qualifications juridiques/économiques.
- Les alertes apparaissent aussi entre deux décisions de rééquilibrage, sans supprimer rétroactivement les rendements.
- `backtest_quality_asof.csv` reste l'audit de chaque date de décision. `block_documented` n'agit qu'avec un registre d'événements effectivement publié au moment de la décision.
- Les séries brutes doivent être rapprochées d'une source **ajustée des opérations sur titres** avant tout classement financier ou validation de backtest. Faute d'une telle source, les sauts importants restent visibles dans les résultats et signalés.

## 2. Calendrier sans anticipation

- Début de période : première date admissible >= date demandée, avec au moins 104 semaines historiques exploitables par titre.
- Les signaux et les poids cible à `t` sont construits uniquement avec les informations disponibles jusqu'à `t`.
- Réallocation à la clôture de `t`; rendement de la position à partir de la semaine suivante.
- La dernière période peut comporter moins que le pas nominal de rééquilibrage, mais jamais de semaine future : la NAV s'arrête à la **dernière semaine complète disponible**.
- Dans Streamlit, l'option par défaut « jusqu'à la dernière semaine complète » signifie `max_rebalances=None`. Le nombre de décisions peut toujours être limité explicitement pour des comparaisons avec les anciens résultats.
- Les dates réelles, le nombre de décisions et les frais figurent dans la synthèse et le rapport. Les anciens résultats sur 12 ou 24 décisions **ne sont pas numériquement comparables** à un backtest complet.

## 3. Attribution comptable, positions et risque

Les nouveaux CSV sont produits **par la même exécution** que les NAV.

| Livrable | Contenu |
|---|---|
| `backtest_attribution_weekly.csv` | Date, stratégie, titre, poids avant rendement, rendement, contribution brute, poids après dérive et avant décision, poids après décision, transaction absolue |
| `backtest_reconciliation.csv` | Somme des contributions brutes, contribution nette des frais (y compris interaction rendement/frais), rendement net et écart de rapprochement, expositions longues et courtes au début de chaque semaine |
| `backtest_quality_weekly_alerts.csv` | Dates et titres nécessitant un contrôle des prix ajustés, seuils, sévérité et statut non vérifié |
| `backtest_summary_metrics.csv` | Rendement et volatilité annualisés, Sharpe, performance cumulée, drawdown, turnover, plus forte concentration observée |
| `backtest_report.html` et `backtest_report.pdf` | Rapports de backtest autonomes (chronologie, méthodes, performances, NAV, contributions, qualité, limites) |

Les contributions sont définies par :

`contribution_i,t = poids_i,avant_rendement × rendement_i,t`

`rendement_net,t = somme(contributions_i,t) + contribution_des_frais,t`

Le coût est déduit après la performance brute à chaque date de décision. Si `f` est le coût relatif total des transactions, alors `contribution_des_frais = -(1 + rendement_brut) × f`. Cela est différent de `-f` lorsque le rendement brut n'est pas nul.

Les poids « après décision » permettent de distinguer la dérive naturelle du portefeuille et les transactions réellement programmées. Les fichiers contiennent les deux stratégies et des lignes à poids nuls pour permettre un rapprochement exhaustif.

## 4. Rapports, tests et limites

Le ZIP Streamlit comporte maintenant les rapports du **backtest** dans `backtest/`, en plus des rapports existants du snapshot LPPLS dans `lppls/`. Les fichiers historiques de snapshot restent autonomes et ne sont pas présentés comme des rapports de backtest.

Contrôles attendus avant recette opérationnelle : `python -m pytest -q`, cohérence des dates, absence d'anticipation, réconciliation au seuil `1e-10`, affichage correct de la NAV, validité du PDF, comparabilité aux cas de référence lorsque les paramètres sont inchangés. Une campagne GitHub Actions n'est pas nécessaire avant cette recette locale.

## Arbitrages reportés

- Certification des cours ajustés et éventuelle substitution de source ;
- Plafonds individuels, limites d'exposition ou rééquilibrage déclenché par la dérive ;
- Quarantaine statistique et éventuelle sortie hors calendrier ;
- Pondération des positions short harmonisée ou non ;
- Financement, emprunt, slippage et éventuels coûts de short ;
- Nouvelle stratégie MIXED_SCALES (comparaison indépendante, non activation automatique).

**Aucune de ces décisions n'est prise implicitement par le correctif.**
