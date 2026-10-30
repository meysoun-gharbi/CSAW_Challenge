# Challenge 3 — Airwave Template · References

CSAW ESC 2026, Set 2 (200 pts). ESP32 SoftAP `SmartHomeGW_xxxxxx` @ `192.168.4.1`.
Vulnerability class: **Server-Side Template Injection (SSTI)** over a UDP template
service (ports 4210-4219, port-hopping), then an **SSTI → UART pivot** to disclose
the flag (`esc_2026{...}`).

All techniques below are public and predate the challenge: the solve = recognise the
pattern ("Template" in the title) and apply the documented method.

---

## 1. Primary technique — SSTI (detection → enumeration → leak)

- **James Kettle — *Server-Side Template Injection: RCE for the Modern Web App*** (Black Hat 2015). Introduces the `{{7*7}}` probe and the detect → identify engine → exploit method.
  - https://portswigger.net/research/server-side-template-injection
  - PDF: https://www.blackhat.com/docs/us-15/materials/us-15-Kettle-Server-Side-Template-Injection-RCE-For-The-Modern-Web-App-wp.pdf
- **PortSwigger Web Security Academy — Server-side template injection** (step-by-step; "if the output contains `49`, the expression is evaluated server-side").
  - https://portswigger.net/web-security/server-side-template-injection
- **OWASP WSTG — Testing for Server-side Template Injection** (methodology, blind cases).
  - https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/07-Input_Validation_Testing/18-Testing_for_Server-side_Template_Injection

### Payload lists
- **payload-box / ssti-advanced-payload-list — `Intruder/all-payloads.txt`** — the wordlist the agent actually uses (bundled as `esc_agent/challenges/wordlists/ssti-all-payloads.txt`). ~295 ready-to-send payloads: detection, context dump, RCE chains.
  - https://github.com/payload-box/ssti-advanced-payload-list/blob/main/Intruder/all-payloads.txt
- **PayloadsAllTheThings — Server Side Template Injection** (per-engine syntaxes, dumps, bypasses).
  - https://github.com/swisskyrepo/payloadsallthethings
- **HackTricks — SSTI**.
  - https://book.hacktricks.xyz/pentesting-web/ssti-server-side-template-injection

### Automated tools (HTTP-oriented; need a UDP↔HTTP bridge here)
- **tplmap** — https://github.com/epinna/tplmap
- **SSTImap** (maintained Python 3 fork) — https://github.com/vladko312/SSTImap

---

## 2. "The entrance that keeps moving" — port hopping / Moving Target Defense

- Luo, Wang, Cai — *Effectiveness of Port Hopping as a Moving Target Defense* (2014): https://archive.cps-vo.org/node/19893
- *Analysis of Port Hopping for Proactive Cyber Defense* (2015): https://www.earticle.net/Article/A242063
- IPv6 variant (client must learn the current endpoint): https://arxiv.org/pdf/2105.13592

---

## 3. Transport & hardware

- **Python `socket`** (UDP `AF_INET`/`SOCK_DGRAM`, `sendto`/`recvfrom`): https://docs.python.org/3/library/socket.html
- **ESP32 SoftAP default address `192.168.4.1`** (Espressif): https://docs.espressif.com/projects/esp-at/en/release-v2.4.0.0/esp32/AT_Command_Examples/TCP-IP_AT_Examples.html
- **pySerial** (UART console; `dtr=rts=False` to avoid resetting a CH340): https://pyserial.readthedocs.io/en/stable/pyserial_api.html
- **ESP32 auto-reset / DTR-RTS = EN-BOOT**: https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html

---

## 4. Classification

- **CWE-1336 — Improper Neutralization of Template Syntax (SSTI)**: https://cwe.mitre.org/data/definitions/1336.html
- **CWE-94 — Improper Control of Generation of Code (Code Injection)**: https://cwe.mitre.org/data/definitions/94.html

---

## 5. Step → reference map

| Solve step | Reference |
|---|---|
| Join `192.168.4.1`, UDP sockets | Espressif ESP-AT + Python `socket` |
| Scan 4210-4219 (moving port) | Port Hopping / MTD (Luo et al.) |
| Confirm render with a known value | PortSwigger / OWASP WSTG |
| Prove evaluation (`{{7*7}}` → 49) | Kettle (Black Hat 2015) |
| Enumerate / dump context → leak | payload-box list, PayloadsAllTheThings, HackTricks |
| Use leaked command on UART → flag | pySerial + ESP32 auto-reset |
