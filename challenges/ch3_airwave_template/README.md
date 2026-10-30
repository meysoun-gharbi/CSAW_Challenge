# Challenge 3 — Airwave Template (SET 2, 200 pts)

**Flag : `esc_2026{ss7i_udp_pivot_cd75162250886fde}`** (token hexa par boot).

Type : **radio (Wi-Fi/UDP)** — **SSTI** (Server-Side Template Injection) sur un
service de template UDP à ports mobiles (4210-4219), puis **pivot UART**. Résolu
**par l'agent LLM** (harnais `esc_agent/`). Références : [`refs.md`](refs.md).

> **Harnais partagé.** Comme le ch1, ce challenge utilise le harnais à la
> **racine du dépôt** (`esc_agent/`, `run.py`, `run_challenge3.py`, `ch3_web.py`).
> Lance les commandes **depuis la racine**. Firmware ici : `firmware/`.

---

## 0. Prérequis + flash
Pilote USB. Python 3 + `pip install -r requirements.txt` (racine) + `pyserial`.
Pour l'agent : clé LLM dans `.env`. Firmware : `firmware/3-udp_merged.bin`.
```bash
# Windows
python  -m esptool --port COM12 --baud 460800 write_flash 0x0 challenges\ch3_airwave_template\firmware\3-udp_merged.bin
# Linux / macOS
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 challenges/ch3_airwave_template/firmware/3-udp_merged.bin
```
Au boot : SoftAP `SmartHomeGW_xxxxxx`. **Associe-toi au SoftAP** (l'agent parle
UDP à `192.168.4.1` ports 4210-4219) + garde le câble USB (UART).

> Comme être sur le SoftAP coupe internet : utiliser un **backend LLM local**
> (Ollama) *ou* un **2ᵉ lien internet** (partage USB du téléphone / Ethernet).

## 1. Résolution par l'agent (depuis la racine)
```bash
# local (Ollama, hors-ligne)
python run_challenge3.py --uart COM12 --backend local --model qwen2.5:7b-instruct
# cloud (Gemini via Vertex, necessite internet)
python run_challenge3.py --uart COM12 --backend gemini --model gemini-2.5-flash --vertex
```
L'agent découvre : télémétrie UDP → oracle de template (SSTI) → dump du contexte
→ commande secrète → pivot UART → flag.

## 2. Console web (démo)
```bash
python ch3_web.py --uart COM12 --backend gemini --model gemini-2.5-flash --vertex
# http://127.0.0.1:8010/
```

## Méthode (reproduire à la main)
1. UDP sur les ports **mobiles** 4210-4219 (le service « bouge »).
2. `{{device_id}}` rend une valeur connue → confirme le rendu de template.
3. `{{7*7}}` → `49` → **évaluation serveur = SSTI**.
4. `{{config}}` → dump du contexte (`device_id,uptime,clients,secret_cmd`).
5. `{{secret_cmd}}` → `diag_dump <token>` (token aléatoire par boot).
6. UART `diag_dump <token>` → flag.

## Fichiers
`firmware/3-udp_merged.bin`. Backend : `../../esc_agent/challenges/airwave_template.py`,
wordlist SSTI `../../esc_agent/challenges/wordlists/`. Harnais :
`../../run_challenge3.py`, `../../ch3_web.py`. Références : `refs.md`.
