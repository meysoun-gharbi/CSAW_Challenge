# Challenge 1 — Serial Gateway (SET 1)

**Flag : `esc_2026{Challenge_1_UART_cli_4909cc5dda95299f}`** (par boot — le vôtre
différera sur la partie hexadécimale, l'important est le format `esc_2026{...}`).

Type : **filaire (UART)** — oracle de préfixe sur la console série → mode
développeur → `claim`. Résolu **par l'agent LLM** (harnais `esc_agent/`) et
reproductible manuellement.

> **Harnais partagé.** Les challenges 1 et 3 utilisent le harnais d'agent qui vit
> **à la racine du dépôt** (`esc_agent/`, `run.py`, `run_challenge1.py`,
> `ch1_web.py`). Lance donc les commandes **depuis la racine du dépôt**, pas
> depuis ce dossier. Le firmware du challenge est ici : `firmware/`.

---

## 0. Prérequis + flash
Pilote USB (CP210x/CH340). Python 3. Pour l'agent : `pip install -r requirements.txt`
(à la racine) + une clé LLM dans `.env` (voir `.env.example`).
Firmware fourni : `firmware/1-serial_merged.bin`.
```bash
# Windows
python  -m esptool --port COM4 --baud 460800 write_flash 0x0 challenges\ch1_serial_gateway\firmware\1-serial_merged.bin
# Linux / macOS
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 challenges/ch1_serial_gateway/firmware/1-serial_merged.bin
```

## 1. Résolution par l'agent (depuis la racine du dépôt)
```bash
# Windows
python  run_challenge1.py --port COM4 --backend gemini --model gemini-2.5-flash
# Linux / macOS
python3 run_challenge1.py --port /dev/ttyUSB0 --backend gemini --model gemini-flash-latest
```
L'agent fait tout seul : scan Wi-Fi (recon) → oracle UART (découverte caractère
par caractère) → mode développeur → `claim` → flag.

## 2. Console web « mission control » (optionnel, pour la démo)
```bash
python ch1_web.py --port COM4        # defaut: gemini-2.5-flash via Vertex, cle depuis .env
# puis ouvrir http://127.0.0.1:8011/ et cliquer "Launch agent"
```

## Méthode (pour reproduire à la main)
1. Oracle de préfixe UART : répond `one or more commands start with X` /
   `no command starts with X`. Charset : `a-z`, espace, `! @ - _`.
2. Seuls `h` et `m` démarrent des commandes ; commande cachée
   `mode developer --help`.
3. Elle demande un suffixe MAC 6 hexa = l'identité de la carte, lue par recon
   Wi-Fi (SSID `SmartHomeGW_xxxxxx`).
4. En mode dev : `log1`..`log100` ; `log37` indique de lancer `claim_flag_uart_s1`.
5. `claim_flag_uart_s1` → le flag.

> Note : pénalité de rate-limit qui double à chaque échec (plafond 2000 ms) ;
> `reboot` (pulse EN/RTS) la remet à zéro.

## Fichiers
`firmware/1-serial_merged.bin`. Harnais : `../../run_challenge1.py`,
`../../ch1_web.py`, `../../esc_agent/`.
