# Qualité des prix et règles de pondération (2026-11-04)

## Comportement confirmé et conservé

Le moteur opérationnel reste `src/lppls_bubble/backtest.py` ; les archives notebook et les moteurs de recherche restent inchangés.

- **Long-only, achats** : poids proportionnels à `1 / sigma`, avec `sigma` = écart-type des rendements hebdomadaires des 52 dernières semaines. Au moins 13 rendements valides sont nécessaires.
- **Long/Short, achats** : même règle inverse-volatilité. **Ventes** : poids proportionnels au score de priorité LPPLS, pas à l'inverse-volatilité.
- **Expositions** : long +50 % et short -50 % si deux poches existent ; sans short, long +100 %.
- Les titres sans historique complet sur 104 semaines sont inéligibles ; les positions dérivent entre décisions espacées de quatre semaines. Les poids sont réestimés à chaque décision. Il s'agit du comportement du moteur courant, **pas** d'une reproduction exacte du notebook historique.
- Aucun plafond de concentration ou changement de pondération des shorts n'est activé.

## Audit qualité historique sans anticipation

L'export `backtest_quality_asof.csv` donne, à chaque date de décision et pour chaque titre :

| Colonne | Description |
|---|---|
| `history_complete` | Les 104 derniers prix hebdomadaires sont disponibles et strictement positifs |
| `stale_weeks`, `stale_alert` | Nombre de clôtures hebdomadaires identiques consécutives, alerte à 8 |
| `last_return`, `extreme_return_alert` | Rendement de la dernière semaine ; alerte si valeur absolue >= 50 % |
| `event_block`, `event_source` | Dernier état publié du registre d'événements, avec sa référence |
| `block_applied` | Si la politique a réellement supprimé le titre des allocations |
| `quality_alert`, `quality_policy` | Diagnostics et politique appliquée |

L'export `backtest_weighting_policy.csv` documente les trois poches et leurs pondérations.

**Mode par défaut : `audit`**. Les variations extrêmes et stagnations déclenchent des **alertes uniquement**. Aucune suppression rétrospective de véritables mouvements de marché.

**Mode facultatif : `block_documented`**. Il faut déposer un CSV d'événements datés, colonnes `asset,published_at,action,source` ; `effective_at` est facultative. `action` vaut `BLOCK` ou `RELEASE`. Le blocage commence à la première décision après que l'événement est publié ET effectif ; une levée de blocage doit elle-même être datée. La décision ne consulte pas les événements futurs.

Exemple de format (fictif, pas une donnée réelle) :

```csv
asset,published_at,effective_at,action,source
EXEMPLE,2025-03-12,2025-03-12,BLOCK,https://example.org/notice
EXEMPLE,2025-04-10,2025-04-10,RELEASE,https://example.org/correction
```

Ce registre **n'est pas rempli automatiquement** : aucun calendrier rétrospectif ATOS/EMEIS/VIVENDI n'est imposé. L'utilisateur doit vérifier la date, la disponibilité et la validité de chaque source.

## Limites importantes

Le traitement est effectué aux dates ordinaires de décision, et **pas** sous la forme de liquidations intra-période. Les cours doivent être contrôlés pour les dividendes, splits et distributions ; les alertes ne les corrigent pas. Les prix manquants sur une position détenue restent une erreur explicite. Un événement divulgué après la clôture le jour même nécessiterait un horodatage plus fin que la date de publication utilisée ici.

## Choix méthodologiques laissés ouverts

1. Shorts : scores LPPLS historiques ou inverse-volatilité harmonisée.
2. Plafonds par titre et traitement du capital non investi.
3. Durée et seuil d'une quarantaine statistique (aucune quarantaine active).
4. Suspension sur prix stagnants (alerte seule).
5. Liquidation entre rééquilibrages et coûts de financement des ventes.
6. Intégration par défaut des stratégies `MIXED_SCALES` (restent expérimentales).

Ce correctif ne valide ni la prédictibilité LPPLS ni les performances de la stratégie sur des séries non ajustées.
