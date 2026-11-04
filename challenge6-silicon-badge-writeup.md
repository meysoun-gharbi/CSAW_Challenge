# Challenge 6 — Silicon Badge (450 pts) — write-up

> CSAW Embedded Security Challenge (ESC) 2026 — **SET 3**.
> Résolu **100 % en live** (UART + RFID + BLE). **Aucun désassemblage / patch de binaire.**

> ## ✅ RÉSOLU
> **`esc_2026{silicon_badge_35ab0259}`**

---

## 1. L'énoncé (indices)

Thème *agent secret* :
- *« An Agent lost his card and his badge »* → carte + badge RFID à exploiter.
- *« this soldier doesn't have access to anything classified »* → accès limité par défaut.
- *« unlock their secret safe full of keys »* → un coffre chiffré (`my_keys`).
- *« Blue teeth are not for smiles »* → **Bluetooth / BLE**.
- **But : « Find the name of the Architect »** → la cible finale.

---

## 2. Matériel & setup

- **ESP32** (kit officiel, écran ST7789, BLE) — firmware `6-badge_merged.bin`.
- **RC522 (MFRC522)** RFID sur SPI (carte S50 + **badge** fournis).
- Console UART **115200 8N1** (`/dev/ttyUSB0`).
- BLE : `Silicon_Badge_6` @ `BC:DD:C2:C1:F6:52` (MAC board `BC:DD:C2:C1:F6:50`).

> ⚠️ **Tap frais** (comme ch2) : le firmware lit la carte/badge sur une transition
> **absente→présente**, pas sur une carte tenue. Taper, ne pas poser-et-tenir.

---

## 3. Reconnaissance (UART)

`help` / `about` révèlent :
```
about        -> fw 2.3.1, build-tag: try-harder{keystream_reuse_is_only_half_the_story}
my_keys      -> coffre chiffré (80 o)
unlock [hex] -> auth par keystream (32 hex)
enroll_master / read_block / dump_card / clear_card / write_block
```
Le **build-tag** est l'indice capital : *« keystream reuse is only half the story »*.

---

## 4. La mécanique (chaîne complète)

### 4.1 Récupérer le keystream via known-plaintext (réutilisation XOR)

`enroll_master` écrit un **badge** dans le secteur 2 :
- **block 8 = LEVEL** = la chaîne ASCII `00000000LEVEL999` **XOR keystream(16o)**.
- block 9 = card id XOR keystream.

L'enroll affiche en clair le plaintext paddé (`00000000LEVEL999`). On lit block 8 brut
(`dump_card` / `read_block 8`) → le keystream se récupère intégralement :

```
keystream = block8  XOR  b"00000000LEVEL999"
```

### 4.2 Déchiffrer le coffre `my_keys` (même keystream réutilisé)

`my_keys` = **80 o = 5 blocs de 16 o**, chacun **XOR du même keystream** (c'est « l'autre
moitié de l'histoire » : la réutilisation du keystream sur le badge ET le coffre). Décodage :

| Entrée | Valeur en clair |
|---|---|
| access code | `965333` |
| gym lock | `9631` |
| **ble key (passkey)** | **`994096`** |
| sim pin | `5476` |
| laptop | `38798524` |

### 4.3 BLE : bonding avec la passkey → lire l'énigme

Le service BLE expose une caractéristique (`4bf0ff03…`) en lecture **protégée par bonding
MITM (passkey)**. On s'appaire avec la **passkey `994096`** (issue du coffre) :
```
bluetoothctl → agent KeyboardDisplay → pair BC:DD:C2:C1:F6:52 → passkey 994096
```
Une fois *bonded*, la lecture de la caractéristique renvoie **l'énigme** :

> *« If you spend more on coffee than on IT security, you will be hacked. What's more, you
> deserve to be hacked. »* — **Who said it?**

### 4.4 L'Architecte = l'auteur de la citation

Cette citation est de **Richard Clarke** (ex-coordinateur national US pour la sécurité /
contre-terrorisme). C'est **« the Architect »** recherché.

### 4.5 Soumettre le nom → le flag s'affiche

La dernière étape n'est **ni `unlock`, ni une écriture BLE** (`unlock` répond
`try-harder{...you seem lost}` ; la caractéristique BLE est read-only). Il faut **taper le
nom de l'auteur directement au prompt UART** — c'est le *clarke_gate* caché :

```
> Richard Clarke
==============================================================
            QUOTE AUTHOR CONFIRMED — FLAG RELEASED
==============================================================
  esc_2026{silicon_badge_35ab0259}
==============================================================
{"event":"clarke_gate","ok":true,"flag":"esc_2026{silicon_badge_35ab0259}"}
```

> Le gate **normalise** l'entrée : insensible à la casse et aux espaces
> (`Richard Clarke`, `richard clarke`, `RichardClarke` marchent tous), mais **pas au point** :
> `Richard A. Clarke` est rejeté (`unknown_command`). Le flag s'affiche aussi **à l'écran**.

---

## 5. Flag

```
esc_2026{silicon_badge_35ab0259}
```

---

## 6. Reproduction (pas à pas)

> ⚠️ **Contrainte par boot** : le keystream et la passkey sont **régénérés à chaque reset**.
> Ne PAS resetter la board entre l'`enroll_master` et la fin. Tout dans une seule session.

1. **Flash** : `python -m esptool --chip esp32 --port /dev/ttyUSB0 --baud 460800 write-flash 0x0 "<repo>/challenges/SET 3/firmware/6-badge/6-badge_merged.bin"`
2. `enroll_master` (tap frais le badge) → note le plaintext `00000000LEVEL999`.
3. `read_block 8` (tap) → `keystream = block8 XOR "00000000LEVEL999"`.
4. `my_keys` → XOR keystream sur les 5 blocs → **passkey `994096`** (+ autres codes).
5. BLE : `bluetoothctl` → `pair` le badge avec passkey `994096` → lire la carac → énigme.
6. Identifier l'auteur de la citation → **Richard Clarke**.
7. Taper **`Richard Clarke`** au prompt UART → **`QUOTE AUTHOR CONFIRMED — FLAG RELEASED`** + flag.

---

## 7. Idées clés (pour le rapport)

- **Known-plaintext + réutilisation de keystream** : l'`enroll_master` divulgue le plaintext
  `00000000LEVEL999` → keystream complet, réutilisé tel quel pour chiffrer le coffre
  (« keystream reuse is only half the story » = badge **et** coffre).
- **Secret BLE derrière un bonding MITM** : la clé d'appairage n'est pas affichée (vs. ch classique)
  mais **stockée chiffrée dans le coffre** → il faut d'abord casser le XOR pour obtenir la passkey.
- **OSINT final** : l'énigme BLE pointe vers une citation attribuée → **Richard Clarke**,
  « the Architect », soumis au *clarke_gate* UART (normalisation casse/espaces).
- Conforme au règlement : **aucun reverse de binaire**, tout obtenu en sollicitant la cible.
