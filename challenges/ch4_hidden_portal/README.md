# Challenge 4 — Hidden Portal (SET 2, 250 pts)

**Flag : `esc_2026{50_shades_of_grey_7685f0ebd0f4df28}`**

Type : **web + stéganographie + Gray code → pivot UART**. Boîte noire (aucun
reverse firmware). Références/sources détaillées : [`refs.md`](refs.md).

Chaîne : endpoint caché `/api/admin` (forced browsing) → négociation de contenu
→ PNG stego → **PIN en LSB du canal Rouge** → `/api/verify-pin` ouvre le vault →
payload « encoded at rest » = **Gray code** → `diag_dump <token>` sur l'UART.

---

## 0. Prérequis + flash
Pilote USB (CH340/CP210x). Python 3 + `pip install pyserial`.
Firmware fourni : `firmware/4-web_merged.bin`.
```bash
# Windows
python  -m esptool --port COM12 --baud 460800 write_flash 0x0 firmware\4-web_merged.bin
# Linux / macOS
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 firmware/4-web_merged.bin
```
Au boot : un **SoftAP** `SmartHomeGW_xxxxxx` apparaît (mot de passe affiché sur
l'UART / dans le firmware). **Connecte ton Wi-Fi à ce SoftAP** (le dashboard est
sur `http://192.168.4.1`). Garde le câble USB branché (pour l'UART du pivot final).

## 1. Recon (optionnel, pédagogique)
```bash
python solve/ch4_recon.py --out ch4_loot      # python3 sous Linux
```
Montre les endpoints + la **négociation de contenu** de `/api/admin`
(`Accept:text/html` → page HTML cachée ; sinon → la **PNG stego**), et télécharge
la PNG.

## 2. Solveur complet (automatique)
```bash
# Windows                              # Linux / macOS
python  solve/ch4_solve.py --port COM12
python3 solve/ch4_solve.py --port /dev/ttyUSB0
```
Le script enchaîne tout :
1. `GET /api/admin` → PNG (épée dans la pierre).
2. **Stego** : LSB du **canal Rouge**, row-major, MSB-first → `PIN:9573`.
3. `POST /api/verify-pin {"sequence":[9,5,7,3]}` → vault déverrouillé.
4. `GET /vault` → payload hex « encoded at rest ».
5. **Gray code** (`g^=g>>4; g^=g>>2; g^=g>>1`) → `"...diag_dump <token>"`.
6. UART `diag_dump <token>` → **flag**.

> 💡 Le PIN et le token **changent à chaque boot** — le script les recalcule à
> chaque exécution (rien n'est codé en dur).

## Vérif manuelle de la stego (outil standard)
```bash
zsteg firmware_dumped_asset.png         # -> b1,r,lsb,xy  text: "PIN:9573"
```
(On a extrait la PNG via `/api/admin` ; `zsteg` confirme la config LSB.)

## Vérif manuelle du Gray code
CyberChef : `From Hex` → `From Gray Code` sur le payload du vault → le message en
clair apparaît.

---

## Fichiers
`firmware/4-web_merged.bin`, `solve/ch4_recon.py`, `solve/ch4_solve.py`,
`refs.md`.
