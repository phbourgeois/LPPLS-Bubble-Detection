# Audit des notebooks de backtest (4 novembre 2026)

Archives : `notebooks/` ; source : `lppls_notebooks_3_versions.zip` fourni dans le projet. **Contenu des notebooks conserve octet pour octet**.

| Fichier | Octets | SHA-256 | Cellules | Sorties |
|---|---:|---|---:|---:|
| `ds_lppls_pipeline_executed.ipynb` | 20038 | `fa9cde54ea79252a6916f8f85aa65b404732ca4514127d67a0f07180dca7242e` | 24 | 0 |
| `ds_lppls_pipeline_with_backtest.ipynb` | 20385 | `a329dae86a4438970f194c4a012c2d7d6cf9265aa98f5ddcbecfa378e486f414` | 24 | 0 |
| `ds_lppls_pipeline_with_backtest_named.ipynb` | 39232 | `6f29c87ba85241c694f93afd1948a15c62bbaae28d2bbc4156fa78065d0bf79a` | 25 | 0 |

## Diagnostic
- `ds_lppls_pipeline_executed.ipynb` : reconstruction, aucune sortie ; son nom ne prouve aucune execution.
- `ds_lppls_pipeline_with_backtest.ipynb` : code de snapshot et annexe narrative uniquement, absence de boucle autonome de backtest.
- `ds_lppls_pipeline_with_backtest_named.ipynb` : cellule de calcul de NAV, poids, turnover et metriques ; c'est la seule version avec moteur de backtest historique.
- **Biais d'anticipation** : dans la cellule finale, l'eligibilite utilise `weekly.loc[forward_dates]` (cours des 4 semaines futures).
- **Poids historiques** : rebalancement uniquement si changement de statut, sans renormaliser les autres poids ; la masse investie peut varier.
- **Rendements manquants** : `fillna(0)` dans le calcul de NAV peut maquiller des trous de prix.
- L'estimation LPPLS est une recherche sur une grille reduite et ne constitue pas un protocole statistique certifie.

## Integration technique
- `src/lppls_bubble/backtest.py` : reprise de la petite grille d'estimation et des familles de signaux du notebook named ; interface de calcul **distinguable des originaux**.
- A chaque date t, selection des actifs uniquement sur historique observe jusqu'a t ; aucun cours futur consulte pour decider l'eligibilite ou les poids.
- Rebalancement periodique a la cloture ; poids driftent avec les rendements entre decisions ; transactions comparees aux poids courants.
- Les cours manquants sur positions ouvertes causent une erreur explicite et non un retour zero silencieux.
- Les rapports sur les performances restent exploratoires, avec frais optionnels ; aucune comparaison numerique aux resultats historiques tant que les CSV d'origine sont absents.
- Les 15 variantes long-only discutees dans les chats ne sont **pas implementees**.

## Verification requise
- Relancer le backtest avec le vrai `SBF120.csv` et comparer les series aux anciennes archives si elles reapparaissent.
- Tester la tenue des signaux, le traitement des delistings et des dates, les donnees point-in-time, les couts de transactions.
- Etudier la validite LPPLS et la calibration statistique avant emploi a des decisions financieres.
