# CSAW ESC 2026 — Challenges (résolus + en cours)

Chaque dossier est **autonome** : son **firmware**, ses **scripts de solve**, sa
**doc de reproduction** (Windows + Linux) et ses **références**.

> **Boîte noire.** On ne *reverse* jamais le flag depuis le binaire (interdit par
> le règlement). Toute la résolution se fait **en live** via l'interface réelle
> (UART, Wi-Fi, BLE).

| # | Challenge | Pts | Type | État | Flag |
|---|---|---|---|---|---|
| 1 | [Serial Gateway](ch1_serial_gateway/) | — | UART (agent) | ✅ | `esc_2026{Challenge_1_UART_cli_...}` |
| 3 | [Airwave Template](ch3_airwave_template/) | 200 | Wi-Fi/UDP SSTI (agent) | ✅ | `esc_2026{ss7i_udp_pivot_...}` |
| 4 | [Hidden Portal](ch4_hidden_portal/) | 250 | web + stego + Gray code | ✅ | `esc_2026{50_shades_of_grey_...}` |
| 5 | [Minions Lockout](ch5_minions_lockout/) | 350 | UART + I2C hardware | ⏸️ recon | — |
| 7 | [Gateway Escape](ch7_gateway_escape/) | 400 | BLE + AES + Wi-Fi CSI | ✅ | `esc_2026{Challenge_7_WiFi_MotionDetection_...}` |

(Les flags hexadécimaux changent par boot ; seul le motif est garanti.)

## Deux familles de solve
- **Agent LLM** (ch1, ch3) : utilisent le **harnais partagé à la racine du dépôt**
  (`esc_agent/`, `run_challenge1.py`, `run_challenge3.py`, `ch1_web.py`,
  `ch3_web.py`). Lancer **depuis la racine**.
- **Solve manuel** (ch4, ch7) : scripts **autonomes** dans `chX/solve/`
  (stdlib + quelques libs pip), lançables depuis le dossier du challenge.

## Prérequis communs
- Pilote USB-série (CH340 / CP210x).
- `esptool` pour flasher : `pip install esptool`.
- Voir le `README.md` de chaque challenge pour les libs et les étapes exactes
  (Windows et Linux).

## Branches git
Chaque challenge **résolu** a sa branche (`challenge-1`, `challenge-3`,
`challenge-4`, `challenge-7`) = snapshot complet et reproductible du dépôt.
