# Challenge 6 — Silicon Badge — FLOW de reproduction

> Flag : **`esc_2026{silicon_badge_35ab0259}`** — 100 % live, aucun reverse.

## ⚠️ Règles d'or
- **TAP FRAIS** : approche le badge jusqu'à toucher l'antenne puis retire — ne le tiens pas.
- **UN SEUL BOOT** : le keystream et la **passkey BLE changent à chaque reset**. Ne resette
  PAS entre l'`enroll_master` et la soumission du nom.
- `clarke_gate` normalise casse + espaces (`Richard Clarke` = `richardclarke`) **mais pas le
  point** → ne tape pas `Richard A. Clarke`.

---

## 0. Flash (une fois)
```bash
python -m esptool --chip esp32 --port /dev/ttyUSB0 --baud 460800 \
    write-flash 0x0 "../csaw_esc_2026/challenges/SET 3/firmware/6-badge/6-badge_merged.bin"
```
Reset (bouton EN) → au boot : `OLED challenge display started (Silicon Badge)`.

---

## A. VERSION SCRIPTÉE (recommandée)
```bash
python3 ch6_solve.py
```
Le script :
1. `enroll_master` + `read_block 8` (il te demande **2 taps frais**) → calcule le **keystream**.
2. `my_keys` → déchiffre le coffre → affiche les codes, dont la **passkey BLE (6 chiffres)**.
3. **Pause** : tu fais le bonding BLE sur nRF Connect avec cette passkey, tu lis l'énigme,
   tu identifies l'auteur de la citation.
4. Entrée → il tape le nom (`Richard Clarke`) → **flag affiché** + écrit dans `ch6_FLAG.txt`.

> Si tu as déjà l'auteur et un boot encore valide :
> `python3 ch6_solve.py --flag-only`  (soumet juste le nom)

---

## B. VERSION MANUELLE (minicom + nRF Connect)

### B.1 Ouvrir la console
```bash
minicom -D /dev/ttyUSB0 -b 115200
```
Options minicom : `Ctrl-A Z` (menu), `E` = echo local ON (pour voir ce que tu tapes),
`U`/`W` = ajout CR/wrap. Quitter : `Ctrl-A X`.

### B.2 Dériver le keystream
```
enroll_master           ← TAP FRAIS ; note le plaintext affiché "00000000LEVEL999"
read_block 8            ← TAP FRAIS ; note les 16 octets (32 hex) = block8
```
`keystream = block8 XOR "00000000LEVEL999"` (XOR octet par octet, ASCII de la chaîne).

### B.3 Déchiffrer le coffre
```
my_keys                 ← renvoie vault_hex (80 o = 5 blocs de 16 o)
```
Chaque bloc XOR keystream → un code en clair :

| bloc | rôle | valeur (exemple de notre run) |
|---|---|---|
| access code | accès | `965333` |
| gym lock | — | `9631` |
| **ble key** | **passkey BLE** | **`994096`** |
| sim pin | — | `5476` |
| laptop | — | `38798524` |

> Décodage rapide en Python :
> ```python
> ks   = bytes.fromhex("<keystream hex>")
> v    = bytes.fromhex("<vault_hex>")
> for i in range(0,len(v),16):
>     print("".join(chr(b^ks[j]) if 32<=(b^ks[j])<127 else "." for j,b in enumerate(v[i:i+16])))
> ```

### B.4 BLE — bonding + énigme (nRF Connect)
1. nRF Connect → **SCAN** → `Silicon_Badge_6` (`BC:DD:C2:C1:F6:52`) → **CONNECT**.
2. Lire la caractéristique (service `4bf0ff…`, carac `4bf0ff03…`) → demande de **BOND**.
3. Entrer la **passkey = `994096`** (celle du coffre, ce boot).
4. Relire la caractéristique → **l'énigme** (une citation) s'affiche.

> En CLI à la place de nRF :
> ```bash
> bluetoothctl
> agent KeyboardDisplay
> default-agent
> pair BC:DD:C2:C1:F6:52      # entrer la passkey 994096 quand demandé
> # puis lire la carac (gatttool / bleak)
> ```

### B.5 Identifier l'Architecte
Énigme : *« If you spend more on coffee than on IT security, you will be hacked. What's more,
you deserve to be hacked. »* → citation de **Richard Clarke** = **« the Architect »**.

### B.6 Libérer le flag
Dans minicom, taper simplement le nom :
```
Richard Clarke
```
→
```
==============================================================
            QUOTE AUTHOR CONFIRMED — FLAG RELEASED
==============================================================
  esc_2026{silicon_badge_35ab0259}
==============================================================
```
(s'affiche aussi sur l'écran OLED).

---

## Dépannage
- Commande carte en `timeout` → **TAP FRAIS** (ne pas tenir).
- `busy/pending` → une commande carte attend déjà, laisse finir / re-tape.
- nRF `auth failed 0x51` / `reason 0x51` → mauvaise passkey → la board a probablement reset,
  **re-dérive** le keystream (étapes B.2–B.3) et réutilise la nouvelle passkey.
- `unknown_command` sur le nom → tu as mis un point/initiale ; tape `Richard Clarke` tout court.
