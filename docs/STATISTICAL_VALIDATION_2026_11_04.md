# Validation statistique LPPLS : expérience rétrospective sur prix de marché réels

**Date : 4 novembre 2026. Statut : EXPÉRIMENTAL, validation prédictive NON acquise.**

## Objectif et principes

Le filtre historique `R² ≥ 0,2` classait comme valides 40/40 marches aléatoires sur une expérience antérieure. Nous ajoutons une **couche d'inférence séparée** ; elle ne modifie pas automatiquement le portefeuille ni la classification historique dans Streamlit. Le critère vérifie une amélioration oscillatoire de LPPLS **par rapport à une tendance en loi de puissance non oscillatoire**, pas l'existence économique d'une bulle.

La statistique est `gain = max(0, (SSE_smooth - SSE_LPPLS)/SSE_smooth)`, les deux SSE étant obtenues par optimisation sur les grilles fixées à l'avance. Les valeurs-p proviennent de la **réestimation intégrale** du modèle sur des rendements simulés : (1) bootstrap circulaire par blocs de 4 semaines des seuls rendements passés, (2) marche aléatoire gaussienne calibrée sur moyenne et variance des seuls rendements passés. Pour être accepté, un ajustement doit franchir **les deux familles nulles** (`p_joint=max(p_block,p_gaussian)`), afficher au moins 1,5 cycle et survivre au contrôle FDR de Benjamini–Hochberg entre tous les actifs et fenêtres **à chaque date de décision** (alpha 10 %).

**Précision** : ni la correction BH entre dates de décision, ni les dépendances longitudinales, ni les déformations de la distribution dues à l'ajustement du modèle nul ne sont intégralement maîtrisées ; cette valeur-p est un diagnostic bootstrap de recherche, **pas une probabilité certifiée de bulle**.

## Source authentique et transformations

- Source externe : [Plotly Datasets – stockdata.csv](https://github.com/plotly/datasets/blob/master/stockdata.csv), dépôt sous licence MIT ; historique du **3 janvier 2007 au 1er mars 2016** ; capture figée jusqu'au **26 février 2016** pour l'exercice.
- Actifs : actions MSFT, IBM, SBUX, AAPL ; **GSPC est un indice et n'entre pas dans l'agrégat actions**.
- Source enregistrée dans GitHub : `data/external/plotly_stockdata_weekly_2007_2016.csv` (`03438a45582bf9b48fc724f9f60d0a0f0c5754808187aa62fda3e58287a9cce2`, SHA-256). 478 vendredis, dernière clôture observée de la semaine, **cours arrondis au centime** ; aucune interpolation. Les prix ne sont pas certifiés ajustés des dividendes et opérations sur titres.
- Le véritable `SBF120.csv` de février 2026 n'a pas été retrouvé : **il n'a pas été simulé ni remplacé en prétendant qu'il s'agissait de la même source**.

## Décisions figées (évaluation hors de la fenêtre de calibration)

- Première date test : **4 janvier 2013** ; 20 décisions espacées de 8 semaines, dernière date **4 décembre 2015**. Le résultat de la dernière décision est évalué grâce aux prix disponibles jusqu'au 26 février 2016.
- Ajustements par actif à **52 et 104 semaines**, 199 simulations par null et par fit, `alpha=0,10`. Famille BH = 5 actifs × 2 fenêtres = 10 tests **à chaque date**.
- La sortie prédite à `t` est enregistrée sans consulter `t+1` à `t+8`. Une UP-bubble alerte sur un futur creux de rendement **≤ −10 %** ; une DOWN-bubble alerte sur un futur pic de rendement **≥ +10 %**, relativement au cours à `t`.
- Comparateur élémentaire : momentum 26 semaines ≥ +20 % (risque futur de baisse), ou ≤ −20 % (risque futur de hausse), avec la même définition d'événement et le même calendrier.
- **Les paramètres sont fixés dans le script avant l'évaluation automatisée, mais ce travail reste rétrospectif : il ne s'agit pas d'un protocole préenregistré par un tiers ni d'un test aveugle sur une nouvelle source.**

## Résultats calculés

| Mesure | Résultat |
|---|---:|
| Décisions / lignes actif-date | 20 / 100 |
| Fits LPPLS (5 actifs × 2 fenêtres) | 200 |
| Ajustements significatifs après BH | **0** |
| Plus petite valeur-p non corrigée | **0.015** |
| Plus petite q-value à la même date | **0.150** |
| Événements futurs de baisse ≥ 10 %, quatre actions | **8 / 80** |
| Événements futurs de hausse ≥ 10 %, quatre actions | **13 / 80** |
| Alertes LPPLS UP / DOWN (actions) | **0 / 0** |
| Alertes momentum UP / DOWN (actions) | **24 / 2** |
| Alertes correctes momentum UP / DOWN | **2 / 0** |

**Aucune précision (precision), lift ou performance prédictive n'est calculable pour LPPLS sans alertes.** La sensibilité sur les épisodes observés est 0, mais cette expérience ne fournit aucune preuve positive de capacité prédictive. Les chevauchements entre actions et fenêtres réduisent fortement le nombre effectif d'événements indépendants ; le panneau est petit et les tests ont peu de puissance pour de rares alertes.

## Contrôles synthétiques séparés

| Contrôle | Acceptations au seuil non corrigé de 10 % | IC de Wilson descriptif 95 % |
|---|---:|---:|
| Marches aléatoires i.i.d. gaussiennes | **2 / 100** | 0.6%–7.0% |
| LPPLS synthétiques « implantées » sur la grille du modèle | **80 / 80** | 95.4%–100.0% |

Ces mesures évaluent un filtre sur des cas synthétiques prédéfinis : elles ne sont **pas un taux de faux positifs en conditions financières réelles**, ni une preuve de sensibilité pour les bulles réelles. Le contrôle positif est artificiellement favorable au modèle (il appartient à la famille ajustée). Les simulations ne corrigent pas ici les tests multiples entre dates.

## Interprétation et décision

**Succès informatique limité :** le contrôle négatif semble plus sélectif que l'ancienne règle `R²`, sous ces hypothèses nulles, et les tests restent causaux. **Pas de validation économique positive :** zéro signal sur le jeu réel, donc aucune amélioration hors échantillon démontrée. Les prix de source publique ne sont pas un substitut au SBF120 initial et ne reflètent ni survivance, ni frais, ni dividendes ; la taille du panel (4 titres) interdit les conclusions fortes.

Pour continuer scientifiquement : (i) obtenir historiques point-in-time ajustés avec univers et dates de composition, (ii) réserver un **nouvel** échantillon géographique/chronologique non examiné pour validation prospective, (iii) tester d'autres modèles nuls (GARCH, rendements à queues épaisses, régimes), (iv) bootstrap des performances conditionnelles et intervalle de confiance, (v) comparer à un benchmark par momentum et à des indicateurs de drawdown, (vi) décider **avant** ces validations du coût des faux signaux et du seuil de décision. Les signaux statistiquement non significatifs doivent rester « exploration » sans usage en trading.

## Reproduction locale sans crédit GitHub Actions

`PYTHONPATH=src python -m pytest -q`

`PYTHONPATH=src python scripts/validate_lppls_oos.py --input data/external/plotly_stockdata_weekly_2007_2016.csv`

La sortie `docs/statistical_validation/` conserve les 200 fits, 100 décisions, résultats des contrôles, statistiques et graphique. Pas de workflow CI déclenché.
