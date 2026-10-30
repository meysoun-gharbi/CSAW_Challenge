# Challenge 7 — Smart Gateway Escape · Explication pour le rapport

**Flag : `esc_2026{Challenge_7_WiFi_MotionDetection_1d270313}`**
(Version pédagogique, du débutant à la solution complète. Le détail technique +
les sources sont dans `refs/challenge7.md`.)

---

## 1. L'histoire (l'analogie)

On est enfermé dans un bâtiment ; une **porte de sortie** est surveillée par un
**gardien**. Il faut s'évader **au moment exact où le gardien s'absente**. Le
cerveau du bâtiment est une carte ESP32 (la *gateway*) : au démarrage elle dit
`[GATEWAY LOCKED] Connect via BLE to begin` → « parle-moi d'abord en Bluetooth ».

---

## 2. Parler à la carte en Bluetooth (BLE)

On scanne, on trouve `Gateway_Escape_7`, on **se connecte**. La carte expose des
« cases mémoire » (*caractéristiques* GATT) **non protégées** (outil : `bleak` en
Python, ou l'app **nRF Connect** sur téléphone — penser à lire les valeurs en
**UTF-8**, sinon on voit de l'hexa). On y lit **3 cadeaux** :
1. un message : *« Analyze the Wi-Fi subcarrier signal variance over time »* (l'indice),
2. des infos : **`log_id = 15`** + une **clé AES** (64 hexa) + l'URL d'un Drive,
3. une case en écriture = **l'horloge de la carte** (`CLOCK_SET_CHAR`).

> ⚠️ Deux pièges matériels : le BLE **arrête d'émettre après chaque déconnexion**
> (→ appuyer sur RESET avant chaque reconnexion) ; et le **CLI UART est verrouillé
> tant qu'une connexion BLE n'est pas active**.

---

## 3. Récupérer et déchiffrer la bonne « note »

Sur le Drive : **100 fichiers `log_001.enc` … log_100.enc`**, ~66 Mo chacun,
**chiffrés** (illisibles). La carte a dit « prends le **n°15** » et a donné la clé.
- Astuce pour lister un dossier Drive public sans compte :
  `https://drive.google.com/embeddedfolderview?id=<ID>#list`.
- On télécharge **seulement `log_015.enc`** (pas les 6,6 Go !).

**Déchiffrement — c'est de l'AES-256-CBC, IV = 16 premiers octets, padding PKCS7.**
- *Clé* : les 64 hexa = 32 octets = **AES-256**.
- *Mode* : trouvé en raisonnant — taille multiple de 16 → mode par blocs ; aucun
  bloc répété → pas ECB ; on teste → seul **CBC** donne du texte lisible
  (entropie basse). Preuve : avec un IV faux, seul le **1er bloc** est cassé, le
  reste reste lisible = **signature du CBC**.
- *IV* : les **16 premiers octets** du fichier (convention : IV collé devant).
- Script : `ch7_decrypt.py <in.enc> <out.csv> <cle_hex>`.

Résultat : un **CSV** → `timestamp_ms, rssi, subcarrier_count, amplitudes[64]`,
une mesure **toutes les 0,5 s pendant tout le 1ᵉʳ janvier 2026** (172 800 lignes).
(C'est le clin d'œil « New Year's Eve » de l'énoncé.)

---

## 4. Le Wi-Fi qui « voit » — CSI et sous-porteuses

- Une **porteuse** = une fréquence radio. Le Wi-Fi n'en utilise pas une mais
  **découpe son canal en 64 fines tranches** = les **sous-porteuses** (technique
  OFDM). D'où **64 nombres par ligne**.
- Les ondes **rebondissent** sur tout (murs, meubles, **personnes**). La force
  (amplitude) reçue sur chaque sous-porteuse forme une **empreinte de la pièce**.
  C'est la **CSI** (*Channel State Information*).
- **Analogie** : 64 lampes de couleurs différentes traversant la pièce ; on mesure
  la luminosité de chacune. Pièce vide → luminosités stables ; quelqu'un passe →
  elles changent. → **détection de présence par Wi-Fi** (= le nom du flag).

---

## 5. La variance = un détecteur de mouvement

La **variance** mesure si des nombres sont **stables** (petite variance) ou
**sautent** (grande variance).

Calcul (4 étapes) sur une suite de valeurs :
1. moyenne ; 2. écart de chaque valeur à la moyenne ; 3. on met au carré ;
4. moyenne des carrés = la variance. (Le carré sert à rendre tout positif et à
faire « exploser » la variance dès que ça bouge fort.)

Exemple réel (une sous-porteuse, 4 instants) :
- **pièce vide** `15.0,15.1,15.0,14.9` → moyenne 15.0, écarts ~0 → **var ≈ 0.005** 🟢
- **gardien** `11,18,13,18` → même moyenne 15.0, gros écarts → **var ≈ 9.5** 🔴

> La **moyenne est la même** dans les deux cas ! Seule la **variance** distingue
> « stable » de « ça saute ». C'est pour ça qu'on l'utilise.

Données réelles du log (4 mesures consécutives, 12 premières sous-porteuses) :
```
PIECE VIDE  04:48:15 : toutes ~15.0, ne bougent pas   -> variance moyenne 0.004
GARDIEN     12:00:00 : sautent 10↔18 dans tous les sens -> variance moyenne 3.7
                                                          (~22 sur une minute entiere)
```

---

## 6. Comment le script trouve le « trou » (fenêtre glissante)

La variance se calcule sur un **GROUPE de lignes** (pas une seule — un seul
instant ne dit pas si « ça bouge »).

1. On prend une **fenêtre de 40 lignes** (~20 s).
2. Pour chacune des 64 sous-porteuses : variance sur ces 40 lignes → 64 variances ;
   on en fait la **moyenne** = **un score** pour ce moment.
3. On **glisse** la fenêtre (de 10 lignes = 5 s) et on recommence, **jusqu'au bout**.
4. On obtient **~17 000 scores** (un par position) → on prend **le MINIMUM**.

```
172 800 lignes ─(fenêtre de 40, glisse de 10)→ ~17 000 scores ─(min)→ 04:48:15
```

Script : `ch7_analyze.py <csv>` (option `--plot` pour le graphique).

**Important (anti-triche) :** le script ne contient **aucune réponse en dur** (ni
« 04:48 », ni l'epoch). Preuve : appliqué à un autre fichier, il donne un **autre**
résultat — et sur `log_001` (chiffré avec une **autre clé**) il ne déchiffre même
pas → le script **plante** faute de vraies données, au lieu de « réciter » 04:48.
Le « 04:48 » sort **uniquement** des mesures réelles de log_015.

---

## 7. Le résultat de l'analyse

- Presque toute la journée : variance **~22** (gardien qui patrouille).
- Un « sol » à **~0.34** : gardien présent mais **immobile** (micro-mouvements /
  respiration).
- **UN SEUL** creux **~0.0036** (≈ 100× sous le sol), large de **~25 s**, centré sur
  **04:48:15 UTC** = **pièce totalement vide = gardien absent**. Étroit → d'où le
  message « j'ai essayé de trouver ce moment mais j'ai échoué ».

Graphique : `ch7_fw/variance_24h.png` (le creux n'est visible qu'en **échelle
logarithmique**, car en échelle normale il se confond avec les creux à 0.34).

---

## 8. L'évasion

1. `CLOCK_SET_CHAR` attend l'epoch en **SECONDES** (texte ASCII) — ex. `1767242895`
   (= 04:48:15 UTC). (En millisecondes → année 57971 = faux.) Limité à 1 écriture / 10 s.
2. Après l'écriture, la carte met ~3-5 s à « settler » (`System initialising`) puis
   passe `GUARDED -> UNGUARDED`.
3. **Pendant que le BLE est connecté**, on envoie `escape` sur l'**UART** →
   `UNGUARDED -> UNLOCKED` → `{"event":"escape","ok":true,"flag":"esc_2026{…}"}`.

---

## 9. Chaîne complète (une ligne)

BLE (lire clé + log_id 15 + indice) → télécharger `log_015.enc` → déchiffrer
(AES-256-CBC / IV=16 premiers octets / PKCS7) → analyser la variance CSI → trouver
les 25 s vides **04:48:15** → régler l'horloge BLE sur `1767242895` → `escape` sur
l'UART → **`esc_2026{Challenge_7_WiFi_MotionDetection_1d270313}`**.

## Outils / fichiers du projet
`ch7_recon.py` (recon), `ch7_decrypt.py` (déchiffrement), `ch7_analyze.py`
(variance + creux, `--plot`), `ch7_fw/variance_24h.png` (graphe),
`ch7_fw/logs/log_015.csv` (log déchiffré). Libs : `bleak`, `cryptography`, `numpy`,
`matplotlib`.
