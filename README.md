# CSAW ESC 2026 — LLM Agent Solver

Automated solver for **CSAW Embedded Security Challenge 2026** using
Gemini LLM + ESP32 serial interaction.

## Setup

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your_key"
```

## Flash firmware

```bash
esptool --chip esp32 --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 <firmware>.bin
```

Firmware binaries: `csaw_esc_2026/challenges/SET 1/firmware/`

## Solve

```bash
# Challenge 1 — Serial Gateway
python3 solve.py --challenge 1 --port /dev/ttyUSB0

# Challenge 2 — EEPROM Secrets
python3 solve.py --challenge 2 --port /dev/ttyUSB0

# Use a specific model
python3 solve.py --challenge 1 --port /dev/ttyUSB0 --model gemini-2.5-pro
```

## List available models

```bash
python3 list_models.py
```

## Architecture

```
solve.py                  # single entry point (--challenge 1|2)
list_models.py            # list Gemini models
esc_agent/
  llm.py                  # Gemini backend (tool calling, retry)
  serial.py               # pyserial UART backend
  wifi.py                 # Wi-Fi scanner (nmcli/netsh)
  agent.py                # core agent loop
  challenge1.py           # Serial Gateway tools + prompts
  challenge2.py           # EEPROM Secrets tools + prompts
```
