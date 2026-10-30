# Challenge 7 — Smart Gateway Escape (SET 3, 400 pts)

> **Ports & commandes** : remplace `<PORT>` par ton port série — **`COMx`** sous Windows, **`/dev/ttyUSBx`** (ou `/dev/ttyACMx`) sous Linux/macOS. Utilise **`python`** sous Windows, **`python3`** sous Linux/macOS. Les commandes ci-dessous sont valables pour les deux OS.

**Flag : `esc_2026{Challenge_7_WiFi_MotionDetection_1d270313}`**

Type : **BLE + crypto (AES) + analyse de signal Wi-Fi (CSI)**. Entièrement en
**boîte noire** (aucun reverse du firmware). Explication pédagogique détaillée :
voir [`EXPLICATION.md`](EXPLICATION.md). Références/sources : [`refs.md`](refs.md).

Résumé : la porte est surveillée par un gardien détecté via le Wi-Fi. On lit en
BLE une clé AES + le n° d'un log, on déchiffre ce log (enregistrement CSI d'une
journée), on y trouve les **25 s où la pièce est vide** (04:48:15), on règle
l'horloge de la carte sur cet instant, puis on tape `escape`.

---

## 0. Prérequis (une fois)

**Pilote USB** (si la carte n'apparaît pas) : CH340 (WCH) ou CP210x (Silicon Labs).
**Python 3** + librairies :
```bash
# Windows (PowerShell/cmd)           # Linux / macOS
python -m pip install bleak cryptography numpy matplotlib pyserial
```
- `bleak` : BLE ; `cryptography` : AES ; `numpy` : analyse CSI ; `pyserial` : UART.
- **Bluetooth LE requis** (quasi tous les laptops). Linux : BlueZ ≥ 5.43.

**Firmware** : `firmware/7-gateway-escape_merged.bin` (fourni ici).

**Flash** (adapter le port : `<PORT>` Windows, `<PORT>` Linux) :
```bash
python -m esptool --port <PORT> --baud 460800 write_flash 0x0 firmware/7-gateway-escape_merged.bin
```
Au boot l'UART affiche `[GATEWAY LOCKED] Connect via BLE to begin`.

> ⚠️ **Matériel** : après chaque déconnexion BLE, l'ESP32 **arrête d'émettre** →
> appuyer sur **RESET** avant chaque script BLE. Le CLI UART est **désactivé tant
> qu'aucun central BLE n'est connecté**.

---

## 1. Lire les infos en BLE
```bash
python solve/ch7_ble.py read
```
Affiche :
- l'indice : *« Analyze the Wi-Fi subcarrier signal variance over time »*,
- `{"log_id":15,"aes_key_hex":"9c9b3432…89665","drive_url":"…1hDcAnyGrbP…"}`.

(Équivalent GUI : app **nRF Connect** → connect → lire les caractéristiques en
**UTF-8** ; la write-char règle l'horloge.)

## 2. Récupérer et déchiffrer le bon log
Télécharger **uniquement `log_015.enc`** depuis le dossier Drive (≈66 Mo ;
NE PAS tout prendre = 6,6 Go). Lister le dossier sans compte :
`https://drive.google.com/embeddedfolderview?id=1hDcAnyGrbPCVt5zssnUBbFR-d9BFzHjA#list`
puis télécharger le fichier via `uc?export=download&id=<FILE_ID>`.

Déchiffrer (**AES-256-CBC, IV = 16 premiers octets, PKCS7**) :
```bash
python solve/ch7_decrypt.py log_015.enc log_015.csv 9c9b3432666fa8286a25e012e729eb97edaeedb4dd0e8c1b152c60927ad89665
```

## 3. Analyser la CSI → trouver le moment non-gardé
```bash
python solve/ch7_analyze.py log_015.csv --plot variance_24h.png
```
Sortie attendue : `MOMENT NON-GARDE : 2026-01-01 04:48:xx UTC`, `epoch ≈ 1767242895`.
(Variance ~22 presque tout le temps = gardien ; ~0.34 = gardien immobile ;
**~0.003 pendant ~25 s à 04:48 = pièce vide**. Voir `variance_24h.png`.)

## 4. S'évader
```bash
# RESET la carte d'abord, puis :
python solve/ch7_ble.py escape --epoch 1767242895 --port <PORT>
```
Le script : règle l'horloge (epoch **secondes**) → attend `GUARDED -> UNGUARDED`
→ envoie `escape` sur l'UART → `UNGUARDED -> UNLOCKED` →
`{"event":"escape","ok":true,"flag":"esc_2026{...}"}`.

### Variante **sans Python/bleak** — nRF Connect (téléphone) + console série (PC)
Méthode confirmée, pratique si le BLE du laptop pose problème :
1. **PC** : ouvre un **moniteur série** sur la carte (115200). Laisse-le ouvert.
2. **Téléphone (nRF Connect)** : **CONNECT** à `Gateway_Escape_7`, et **reste
   connecté** (ça déverrouille le CLI UART : *« connect via BLE first »*).
   - Lis les caractéristiques en **UTF-8** → `log_id` + `aes_key_hex` (déjà fait).
   - Dans la write-char (`cba1d466…`), **Write** en format **Text** la valeur
     **`1767242895`** (l'epoch en **secondes** du moment non-gardé).
3. **PC (console série)** : tape **`escape`** → le **flag s'affiche** sur la console.
   (La carte est en `UNGUARDED` tant que l'horloge est réglée sur l'instant vide ;
   le téléphone doit rester connecté pendant l'envoi de `escape`.)

> L'epoch `1767242895` est **calculé** par l'étape 3 (`ch7_analyze.py`) à partir du
> log déchiffré — ce n'est pas une valeur magique.

---

## Chaîne complète (1 ligne)
BLE (clé + log_id 15 + indice) → `log_015.enc` → déchiffrer (AES-256-CBC/IV=16/PKCS7)
→ analyser variance CSI → **04:48:15** → régler horloge BLE → `escape` UART → flag.

## Fichiers
`firmware/7-gateway-escape_merged.bin`, `solve/ch7_ble.py` (BLE read/escape),
`solve/ch7_decrypt.py` (AES), `solve/ch7_analyze.py` (variance+graphe),
`solve/ch7_recon.py` (recon HTTP/UDP/UART générique), `variance_24h.png`,
`data/` (log déchiffré — hors git). Détails : `EXPLICATION.md`, `refs.md`.
