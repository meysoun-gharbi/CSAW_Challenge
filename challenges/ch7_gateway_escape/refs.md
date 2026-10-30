# Challenge 7 — Smart Gateway Escape · References

CSAW ESC 2026, Set 3 (400 pts). ESP32 device, **BLE-gated** ("[GATEWAY LOCKED]
Connect via BLE to begin"). Black box (no firmware reverse).

**Flag:** `esc_2026{Challenge_7_WiFi_MotionDetection_1d270313}`

Theme: the exit is watched by a guard detected via **Wi-Fi CSI motion sensing**.
Find the one ~25 s window where the room is truly empty (guard absent), set the
gateway clock to that instant, then `escape`.

---

## 1. BLE recon — read the unprotected GATT characteristics

Device `Gateway_Escape_7` @ `80:64:6F:F0:63:16`, custom service
`4fafc201-1fb5-459e-8fcc-c5c9c331914b` (the Arduino/Espressif BLE_server example
UUID) with 3 characteristics, left readable/writable:
- `beb5483e-…` (read) — hint: *"Analyze the Wi-Fi subcarrier signal variance over time."*
- `d0e12345-…` (read) — `{"log_id":15,"drive_url":"…","aes_key_hex":"9c9b3432…89665"}`
- `cba1d466-…` (write) — **CLOCK_SET_CHAR** (set the gateway's clock).

- **bleak** — cross-platform Python BLE (scan / connect / read_gatt_char /
  write_gatt_char). `pip install bleak`.
  - https://bleak.readthedocs.io/
- **GATT basics** (services, characteristics, properties, UUIDs).
  - https://www.bluetooth.com/specifications/specs/ (Core; GATT)
  - https://learn.adafruit.com/introduction-to-bluetooth-low-energy/gatt
- **nRF Connect** (phone app to browse GATT; read values as UTF-8, write the
  clock as Text) — the GUI equivalent of the bleak recon.
  - https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile
- **Arduino `BLE_server` example** (origin of the `4fafc201…` / `beb5483e…` UUIDs).
  - https://github.com/espressif/arduino-esp32/tree/master/libraries/BLE/examples/BLE_server
- Note: this ESP32 firmware **stops advertising after any disconnect** → press
  EN/RESET before each fresh connect. The UART CLI is **disabled until a BLE
  central is connected** ("connect via BLE first").

---

## 2. Getting the data — list a public Google Drive folder without auth

The notes are 100 files `log_001.enc`…`log_100.enc` (~66 MB each, AES-encrypted).
Only `log_015.enc` matters (log_id from BLE). Do NOT bulk-download 6.6 GB.

- **`embeddedfolderview`** returns a static HTML listing (no JS, no auth):
  `https://drive.google.com/embeddedfolderview?id=<FOLDER_ID>#list`
  then parse `flip-entry-title">NAME` and `flip-entry" id="entry-<FILE_ID>"`;
  download one with `https://drive.google.com/uc?export=download&id=<FILE_ID>`.
  - https://stackoverflow.com/questions/custom (embeddedfolderview trick — community)

---

## 3. Decryption — AES-256-CBC, IV = first 16 bytes, PKCS7  ✅ (record this!)

The `.enc` file is **AES-256-CBC**. **The 16-byte IV is PREPENDED (= the first 16
bytes of the file)**; the rest is the ciphertext; plaintext ends with **PKCS7**
padding. Key = `aes_key_hex` from the BLE char (32 bytes = AES-256).

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
raw = open("log_015.enc","rb").read()
iv, ct = raw[:16], raw[16:]                       # IV = FIRST 16 BYTES
pt = (lambda d: d.update(ct)+d.finalize())(
        Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor())
pad = pt[-1]; pt = pt[:-pad] if 1<=pad<=16 and pt[-pad:]==bytes([pad])*pad else pt
```

### How the mode was determined (not guessed)
1. key = 32 bytes → **AES-256**.
2. file size is a **multiple of 16** → a *block* mode (CBC/ECB), not a stream
   mode (CTR/GCM, which keep arbitrary length).
3. **no repeated 16-byte block** → **not ECB** (ECB leaks identical blocks).
4. decrypt a small chunk under each candidate and let **entropy / readability**
   decide: CBC(iv=first16) → entropy ~3.5, text `timestamp_ms,rssi,...`; CTR → ~8.0
   (garbage). → **CBC**.
5. confirmation: with a WRONG IV (zeros), CBC still decrypts everything **after the
   first 16 bytes** correctly — the "only the first block is corrupted" behaviour
   is the signature of CBC and proves both the mode and that the IV is at the front.

- **NIST SP 800-38A** — block cipher modes (CBC definition; IV requirements).
  - https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38a.pdf
- **`cryptography` — symmetric encryption (AES / CBC / CTR).**
  - https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/
- **PKCS#7 padding** (RFC 5652 §6.3).
  - https://datatracker.ietf.org/doc/html/rfc5652#section-6.3
- **Block cipher modes & the "ECB penguin"** (why identical blocks reveal ECB).
  - https://en.wikipedia.org/wiki/Block_cipher_mode_of_operation#Electronic_codebook_(ECB)
- **Convention: prepend the IV to the ciphertext** (store IV in the clear with CT).
  - https://crypto.stackexchange.com/questions/5185/does-the-iv-need-to-be-secret

Project helper: `ch7_decrypt.py <in.enc> <out.csv> <aes_key_hex>`.

---

## 4. The payload — Wi-Fi CSI motion detection

Decrypted CSV: `timestamp_ms,rssi,subcarrier_count,amplitudes[64]`, one row every
0.5 s for the whole of **2026-01-01** (172 800 rows). The 64 **subcarrier
amplitudes** are Wi-Fi **Channel State Information (CSI)**: a moving body perturbs
multipath → high per-subcarrier **variance over time**; an empty, static room →
near-zero variance.

- **Wi-Fi CSI sensing / device-free motion detection** (background).
  - Yang et al., *From RSSI to CSI: Indoor Localization via Channel Response* (ACM
    CSUR 2013): https://dl.acm.org/doi/10.1145/2543581.2543592
  - Wang et al., *A Survey on Behavior Recognition Using WiFi CSI* (IEEE Comm. Mag.
    2017): https://ieeexplore.ieee.org/document/8067693
  - Nexmon CSI / ESP32-CSI-Tool (how CSI is captured on commodity hardware):
    https://github.com/StevenMHernandez/ESP32-CSI-Tool

### The analysis
- Compute, over a sliding time window, the mean across subcarriers of each
  subcarrier's **temporal variance**.
- Most of the day var ≈ 22 (guard patrolling); a 0.34 "floor" = guard present but
  **still** (micro-motion / breathing). **One ~25 s window** has var ≈ **0.003**
  (~100× below the floor) = **truly empty = guard absent**, centred
  **04:48:15 UTC** (`epoch 1767242895 s`). Narrow → "I failed to find it".
- Tools: `numpy` for the variance scan.

---

## 5. The escape — set the clock, then `escape`

- `CLOCK_SET_CHAR` expects the epoch in **SECONDS** as an ASCII string (ms → year
  57971 = wrong). Rate-limited to 1 write / 10 s.
- After a valid write the monitor takes a few seconds to settle
  ("System initialising - wait") then `[StateMachine] GUARDED -> UNGUARDED`.
- While the **BLE link is still up**, send `escape` on the **UART** CLI →
  `[StateMachine] UNGUARDED -> UNLOCKED` →
  `{"event":"escape","ok":true,"flag":"esc_2026{...}"}`.
- **Unix epoch / time conversion.**
  - https://docs.python.org/3/library/datetime.html

---

## 6. Step → reference map

| Solve step | Reference |
|---|---|
| Connect BLE, read GATT chars (key, log_id, hint) | bleak / nRF Connect / GATT |
| List Drive folder, fetch only log_015 | embeddedfolderview trick |
| Decrypt log — **AES-256-CBC, IV = first 16 bytes, PKCS7** | NIST SP 800-38A, cryptography, RFC 5652 |
| Identify mode (size %16, no ECB repeats, entropy, CBC IV test) | block-cipher-modes, ECB penguin |
| CSI variance → find the empty 25 s window (04:48:15) | Wi-Fi CSI sensing papers, numpy |
| Set CLOCK_SET_CHAR (epoch seconds) → UART `escape` → flag | bleak write + UART CLI |

**Confirmed chain:** BLE read (key `9c9b3432…`, log_id 15, hint) → decrypt
`log_015.enc` (AES-256-CBC / IV=first-16 / PKCS7) → CSI variance scan → empty
window **04:48:15 UTC = 1767242895** → CLOCK_SET_CHAR → UART `escape` →
`esc_2026{Challenge_7_WiFi_MotionDetection_1d270313}`.
