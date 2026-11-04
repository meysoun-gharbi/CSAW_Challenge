# Challenge 2 — EEPROM Secrets (200 pts) — write-up

> CSAW Embedded Security Challenge (ESC) 2026 — **SET 1**.
> Résolu **100 % en live** (UART + manipulation RFID). **Aucun désassemblage / patch de binaire.**

> ## ✅ RÉSOLU
> **`esc_2026{eeprom_master_e83c871649f13221}`**

---

## 1. L'énoncé

Thème *Star Wars* : *« Wondering how to get in? Just tap your card. But beware! This Imperial
garrison strictly obeys High Command. The guards won't unlock the blast doors unless your
identity chip proves you've received clearance from their Master. Unfortunately, the Master
(aka the Lord Commander) is away aboard his Star Destroyer, so you can't ask nicely. Your only
option is to **trick the security system into believing you've already earned his blessing**.
To pull off a deception of this magnitude, **you'll need to dig deep into the gateway's
non-volatile memory first**. »*

→ Il faut **forger, sur la carte RFID, une « visite du gateway Master » accordée**, en
s'appuyant sur ce que révèle l'**EEPROM**.

---

## 2. Matériel & setup

- **ESP32** (Ideaspark, écran ST7789) — firmware `2-eeprom_merged.bin`.
- **RC522 (MFRC522)** RFID sur SPI, **AT24C256** EEPROM sur I2C.
- Carte S50 + porte-clés fournis.
- Console UART **115200 8N1** (`/dev/ttyUSB0`).

Câblage (réf. setup officiel) :
- RC522 : SDA→D5, SCK→D18, MOSI→D23, MISO→D19, **RST→D17 (TX2 = GPIO17)**, 3.3V (splitter), GND.
- EEPROM : SDA→D21, SCL→D22, VCC (splitter), GND. (WP géré par jumper masse, adresse `0x50`.)

> ⚠️ **INSIGHT RFID CAPITAL — le « tap frais »** : le firmware **ignore une carte tenue
> immobile** ; il déclenche la lecture sur une **transition absente→présente**. Il faut donc
> *taper* la carte (l'approcher jusqu'à toucher l'antenne puis la retirer), pas la poser et la
> laisser. C'est ce qui débloque *toutes* les commandes carte (on a perdu des heures à « tenir »
> la carte avant de comprendre ça).

---

## 3. Reconnaissance (commandes UART)

`help` révèle :
```
dump_eeprom                 - Dump config database (protected by an exclusive key repeating over identity)
get_mac                     - Output ESP32 eFuse hardware MAC address
read_block [block]          - Read 16-byte block from card
write_block [block] [data]  - Write 16-byte block (hex)   (padding '0' auto)
dump_card                   - Dump all blocks from card
clear_card                  - Zero out all writable card data blocks
provision_user_status       - Reset card session logs and roaming history
```
Au boot : `Initializing and XOR-encoding gateway database in EEPROM`.
Un tap carte vierge → audit :
`Gateway MAC Suffix: C1:F6:50 Response: 0xFF (Access Denied)` +
`Access Denied: No master gateway visit on record. You should visit the master first.`

---

## 4. La mécanique

1. **EEPROM = base de gateways XOR-encodée** avec une *« clé exclusive répétée sur l'identité »*
   = une **MAC de 6 octets répétée** (XOR). Chaque enregistrement = **16 octets** :
   `nom (ASCII, null-padded)` + **4 octets de credential = [suffix MAC 3o][niveau 1o]**.
2. La **carte** stocke la **dernière visite** en **block 5 (secteur 1)** au format
   **`[suffix MAC gateway 3o][réponse 1o]`** — ex. `C1 F6 50 FF` (ce gateway, refusé).
3. La gateway (blast door) n'ouvre que si la carte a une **visite du gateway Master** avec une
   **réponse « accordée »**. Le Master étant « absent », on **forge** cette visite.

---

## 5. L'attaque (pas à pas)

### 5.1 Décoder l'EEPROM → trouver le Master

`dump_eeprom` donne un hex-dump XOR-encodé. On retrouve la clé (MAC répétée) via un
**plaintext connu** : les enregistrements finissent par `_GW`. Décodage (clé
`EC C9 FF 76 94 68`, phase 2 sur notre carte) → **base claire** :

| Gateway | credential (`[suffix][niveau]`) |
|---|---|
| Lobby_GW | `10 20 30 01` |
| Office_GW | `76 94 68 02` |
| Floor1_GW | `44 55 66 03` |
| Floor2_GW | `77 88 99 03` |
| Server_GW | `88 99 AA 05` |
| Storage_GW | `11 22 33 01` |
| **Master_GW** | **`54 F2 A5 99`** ← cible (niveau `0x99`, le + élevé) |
| Garage_GW | `DE AD BE 02` |
| Garden_GW | `55 66 77 01` |
| Vault_GW | `FE ED FA 10` |

> La clé XOR est l'« identité » (MAC). Si l'EEPROM a été ré-encodée avec une autre MAC, adapter
> la clé : le solveur la retrouve automatiquement en imposant la présence de `Master_GW` dans le
> décodage.

### 5.2 Confirmer le format de visite

`dump_card` (tap frais) → **block 5 = `C1 F6 50 FF`** = `[suffix C1:F6:50][réponse FF=refusé]`.

### 5.3 Forger la visite Master

On écrit, dans l'enregistrement de visite, le credential Master **`54 F2 A5 99`**
(suffix `54 F2 A5` + réponse `99` = clairance accordée par le Master) :
```
write_block 5 54F2A599      (tap frais)
```

### 5.4 Déclencher la vérif

Un **tap** relit la carte → le firmware voit la visite Master accordée :
```
[AUDIT] Last visit status : Gateway MAC Suffix: C1:F6:50 Response: 0x99 (Access Granted)
[ACCESS-CTL] Primary gateway authorization verified! Access Granted.
esc_2026{eeprom_master_e83c871649f13221}
```
(L'écran passe aussi à **« unlocked »**.)

---

## 6. Flag

```
esc_2026{eeprom_master_e83c871649f13221}
```

---

## 7. Reproduction

1. **Flash** : `python -m esptool --chip esp32 --port /dev/ttyUSB0 --baud 460800 write-flash 0x0 "<repo>/challenges/SET 1/firmware/2-eeprom/2-eeprom_merged.bin"`
   (esptool v5 = `write-flash` ; esptool v4 système = `write_flash`.)
2. **Câbler** RC522 + EEPROM (voir §2). Reset (bouton EN).
3. **Automatique** : `python3 ch2_solve.py`
   → il décode l'EEPROM, trouve `Master_GW`, forge block 5, écoute le flag.
   Il te demande de **taper la carte (tap frais)** aux deux moments (write + vérif).
4. **Manuel** (équivalent) :
   - `dump_eeprom` → décoder (XOR clé MAC) → `Master_GW = 54 F2 A5 99`.
   - `dump_card` → voir block 5 = `[suffix][réponse]`.
   - `write_block 5 54F2A599` (tap frais).
   - taper la carte → `Access Granted` + flag.

> Dépannage : commande carte en `timeout` → **TAP FRAIS** (ne pas tenir la carte).
> `busy/pending` → une commande carte est déjà en attente, laisser finir / re-taper.

---

## 8. Script

Solveur déterministe : **`ch2_solve.py`** (ce dossier). Aucune IA requise pour la
reproduction — la logique est entièrement déterministe.

## 9. Idées clés (pour le rapport)

- **Known-plaintext sur l'EEPROM** : la clé XOR (identité/MAC) se récupère gratuitement via les
  suffixes `_GW` des noms de gateways.
- **Forge d'enregistrement de visite** : le contrôle d'accès fait confiance au contenu réécrivable
  de la carte (block 5) → on injecte une visite Master accordée (`54 F2 A5 99`).
- **Tap frais** : subtilité d'interaction RFID (edge absente→présente) indispensable.
- Conforme au règlement : **aucun reverse de binaire**, tout obtenu en sollicitant la cible.
