# LPPLS — moteur de référence, 4 novembre 2026

**Décision : `src/lppls_bubble` reste le moteur de référence Streamlit** après sécurisation des CSV, des fenêtres hebdomadaires et de l'éligibilité. `research/reproducible_2026_11_04/lppls_core.py` reste une alternative archivée, sans remplacement automatique.

## Expériences identiques

Deux échantillons synthétiques : 2 actifs × 164 semaines (CSV d'exemple fourni) et 6 actifs × 156 semaines (trajectoires LPPLS simulées, deux marches aléatoires, tendance et série quasi plate). Chaque actif a été ajusté sur sept fenêtres : 13, 26, 39, 52, 65, 78 et 104 semaines. Les séries hebdomadaires d'entrée sont identiques dans les deux moteurs.

| Mesure | Exemple | Contrôle |
|---|---:|---:|
| Ajustements comparés | 14 | 42 |
| Coefficients B et R² concordants | 14 | 42 |
| Signaux concordants | 14 | 42 |
| Classifications finales concordantes | 2/2 | 6/6 |

Les pondérations instantanées concordent à la précision machine. `phi` n'a pas la même convention de phase et ne doit pas être comparé directement.

## Backtests sur les mêmes cours

4 rééquilibrages de 4 semaines du 2 février au 24 mai 2024 ; coûts de 15 points de base.

| NAV finale | Streamlit | Recherche |
|---|---:|---:|
| Long-only | 0,917934 | 0,915987 |
| Long/short | 0,892400 | 0,892026 |

Poids cibles long-only identiques ; écart maximal des poids cibles long/short 0,040214. Le moteur Streamlit fait dériver les poids avec les prix, rééquilibre et déduit les frais des rendements nets. Le moteur de recherche applique des poids fixes sans expliciter les transactions nécessaires, et ses rendements déclarés diffèrent des variations de NAV **3 semaines** au cours de ce test avec frais. Les grilles LPPLS réduites (`tiny`) diffèrent entre les deux codes.

## Tests négatifs et réserve scientifique

Sur **40 marches aléatoires indépendantes**, 40 fits satisfont le filtre heuristique LPPLS : 23 signaux UP, 17 DOWN, R² médian 0,8154. Le filtre actuel n'est **pas un test statistique fiable de bulle**. Une série à tendance simple est également classée comme bulle cohérente. Le temps critique est mal identifié même dans certaines trajectoires LPPLS simulées.

Avant correction, le code Colab pouvait compresser les dates d'une fenêtre de 104 semaines en supprimant les valeurs manquantes. Le moteur retenu conserve maintenant les semaines calendaires et refuse ces estimations incomplètes ; les deux moteurs n'acceptent ici que les fenêtres [13,26,39] après suppression d'une observation. Les actifs dont 104 semaines ne sont pas disponibles ne sont plus pondérés.

**Limites :** uniquement données synthétiques, absence de reproduction sur SBF120.csv et Miscellanous.csv, prix ajustés/dividendes non vérifiés, biais de survivance, coût des shorts non modélisé, risques de calibration et de surajustement. Cette décision porte sur la qualité logicielle et comptable du moteur, pas sur une capacité prédictive certifiée. Aucun workflow GitHub Actions créé.
