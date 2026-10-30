# Challenge 4 — Hidden Portal · References

CSAW ESC 2026, Set 2 (250 pts), the "web" challenge. ESP32 SoftAP
`SmartHomeGW_xxxxxx` @ `192.168.4.1`, HTTP dashboard on port 80.

**Scope note:** firmware reverse engineering is forbidden by the rules (and
`strings`/binary analysis counts). Every step below is **black box**: it uses
only what the live device serves (HTTP responses, the dashboard HTML/JS, the
on-device TFT image, the UART CLI). All techniques are public and predate the
challenge.

README hint (verbatim): *"…the developers relied too much on vibe coding and
left things in places they shouldn't. You can capture the secrets of Gru with
the right skillset. When in doubt, search, inspect, or listen. Some things hide
more than they show. Be careful not to get locked out. Also remember… A house
that starts over does not keep its old locks."*

---

## 1. Finding the hidden endpoint — forced browsing / unreferenced resources

The dashboard JS advertises an **"unlinked diagnostic asset endpoint"**
(`/api/admin`) via a `<meta name="diag-asset-endpoint">` breadcrumb. Reaching
an endpoint the UI does not link to is the classic *forced browsing* technique.

- **OWASP — Forced browsing** (a.k.a. Predictable Resource Location / Resource
  Enumeration: accessing resources not referenced but still reachable).
  - https://owasp.org/www-community/attacks/Forced_browsing
- **OWASP WSTG — Enumerate Infrastructure and Application Admin Interfaces**
  (finding admin/diagnostic interfaces not linked from the app).
  - https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management_Testing/05-Enumerate_Infrastructure_and_Application_Admin_Interfaces
- **OWASP WSTG — Review Old, Backup and Unreferenced Files for Sensitive Info.**
  - https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management_Testing/04-Review_Old_Backup_and_Unreferenced_Files_for_Sensitive_Information
- **CWE-425 — Direct Request ("Forced Browsing")**.
  - https://cwe.mitre.org/data/definitions/425.html
- **CAPEC-87 — Forceful Browsing**.
  - https://capec.mitre.org/data/definitions/87.html
- **"Inspect the client" is a documented first step** — read the served
  HTML/JS/comments (here the breadcrumb + the `/api/*` fetches). This is black
  box, not reversing: OWASP WSTG "Map Application Architecture" / review of
  client-side code.
  - https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/05-Review_Webpage_Content_for_Information_Leakage

---

## 2. The hidden secret — image steganography

README: *"Some things hide more than they show."* The 4-digit PIN is expected
to be concealed in an image/asset (served by `/api/admin` and/or shown on the
TFT), recovered by inspecting the file rather than brute-forcing the PIN.

- **CTF stego methodology** (metadata → appended data → LSB bit-planes → tools).
  - https://skills.sh/ramzxy/ctf/ctf-stego
  - https://www.charlesreid1.com/wiki/Steganography/LSB
- **zsteg** — automatic LSB scanner for PNG/BMP (`zsteg -a file.png`).
  - https://github.com/zed-0xff/zsteg
- **Stegsolve** — GUI to step through individual bit planes (visible content
  like a QR/text in one channel).
  - https://github.com/zardus/wiki/blob/master/toolkits.md (Stegsolve JAR)
  - https://www.charlesreid1.com/wiki/Stegsolve
- **steghide** — passphrase-based embedding for JPEG/BMP/WAV/AU
  (`steghide extract -sf img.jpg -p ""`); **Stegseek** cracks the passphrase.
  - https://github.com/StefanoDeVuono/steghide
  - https://github.com/RickdeJager/stegseek
- **ExifTool / binwalk / strings** — metadata + appended/embedded data (first
  pass before pixel-level analysis).
  - https://exiftool.org/
  - https://github.com/ReFirmLabs/binwalk
- **stego-toolkit** — bundled reference of the above.
  - https://github.com/DominicBreuker/stego-toolkit
- **Fallback: Pillow + numpy** to pull LSBs directly from pixel data (useful
  when the asset is a non-standard/raw image, e.g. a 1-bit or small bitmap).
  - https://pillow.readthedocs.io/en/stable/
- **CWE-311/CWE-312 — security-by-obscurity of stored data** (why "encoded at
  rest" is not protection).
  - https://cwe.mitre.org/data/definitions/312.html

---

## 3. The PIN pad — MNIST handwritten-digit classifier

The PIN pad is a canvas posting a 28×28 grayscale matrix (784 bytes) to
`/api/classify`, which returns a digit + confidence — i.e. an **MNIST** model
on-device. Relevant when we must *submit* the recovered PIN by producing
digit images, or reason about the classifier.

- **MNIST database of handwritten digits** (28×28 grayscale, the canonical set).
  - http://yann.lecun.com/exdb/mnist/
- **MNIST preprocessing — centre-of-mass alignment** (the JS comment matches the
  official centering by centre of mass, not bounding box).
  - http://yann.lecun.com/exdb/mnist/ (preprocessing notes)
- **TensorFlow Lite for Microcontrollers** (typical way an ESP32 runs such a
  model; context for the on-device classifier).
  - https://www.tensorflow.org/lite/microcontrollers

---

## 3b. Attacks on the classifier (adversarial ML / evasion)

The PIN pad is an on-device classifier, so the adversarial-ML family applies: an
attacker controls the raw 28×28 `matrix` posted to `/api/classify` (not just
the drawing), so they can craft an input that the model reads as a *chosen*
digit — a **targeted evasion / adversarial-example** attack. Useful to reliably
feed the recovered PIN digits (bypassing imperfect handwriting recognition), to
probe confidence behaviour, or if the intended bug is classifier-side.

- **Goodfellow, Shlens, Szegedy (2015) — "Explaining and Harnessing Adversarial
  Examples"** (introduces FGSM; targeted or untargeted, white-box).
  - https://arxiv.org/abs/1412.6572
- **Biggio et al. (2013) — "Evasion attacks against machine learning at test
  time"** (the foundational test-time evasion paper).
  - https://arxiv.org/abs/1708.06131
- **Szegedy et al. (2014) — "Intriguing properties of neural networks"**
  (the original adversarial-examples observation).
  - https://arxiv.org/abs/1312.6199
- **Carlini & Wagner (2017) — "Towards Evaluating the Robustness of Neural
  Networks"** (the strong C&W attack; evaluated on MNIST).
  - https://arxiv.org/abs/1608.04644
- **Madry et al. (2018) — "Towards Deep Learning Models Resistant to Adversarial
  Attacks"** (PGD; the canonical robustness baseline).
  - https://arxiv.org/abs/1706.06083
- **MITRE ATLAS** — adversarial-ML threat matrix (ATT&CK-style; evasion, model
  extraction, inference). Note AML.T0043 "Craft Adversarial Data".
  - https://atlas.mitre.org/
- **OWASP Machine Learning Security Top 10** — ML01:2023 *Input Manipulation
  Attack* (evasion) at the top of the list.
  - https://owasp.org/www-project-machine-learning-security-top-10/
- **OWASP Top 10 for LLM Applications** (if any input is interpreted by an LLM —
  prompt injection etc.; kept for completeness, the pad here is an image model).
  - https://owasp.org/www-project-top-10-for-large-language-model-applications/
- **CleverHans / Foolbox / ART** — reference libraries implementing the attacks
  above (FGSM/PGD/C&W) against MNIST-style models.
  - https://github.com/cleverhans-lab/cleverhans
  - https://github.com/bethgelab/foolbox
  - https://github.com/Trusted-AI/adversarial-robustness-toolbox

---

## 3c. Decoding the vault payload — Gray code  ✅ (the actual mechanism)

The `/vault` "encoded at rest" payload is **Gray code** (binary reflected Gray
code). The hint "50 shades of **grey**? 256 would've been better..." is a pun on
*grey/Gray* (8-bit Gray code spans 256 values). Decode each byte Gray→binary:
`g ^= g>>4; g ^= g>>2; g ^= g>>1; g &= 0xff` → the plaintext
`"run this command in uart to get the flag: diag_dump <token>"`. The flag itself
confirmed it: `esc_2026{50_shades_of_grey_7685f0ebd0f4df28}`.

### Decode recipe (what to run)

```python
# payload bytes = From Hex of the /vault string
def gray_to_bin(g):          # binary reflected Gray -> binary, per byte
    g ^= g >> 4
    g ^= g >> 2
    g ^= g >> 1
    return g & 0xff
plain = bytes(gray_to_bin(c) for c in payload)
# -> "run this command in uart to get the flag: diag_dump <token>"
```
Worked example (1st byte): `0x4b -> ^>>4 =0x4f -> ^>>2 =0x5c -> ^>>1 =0x72 = 'r'` ("run...").

**Fast path — CyberChef:** `From Hex` → `From Gray Code` outputs the plaintext in
two operations. Reach for it whenever an "encoded" blob resists XOR/Vigenère and a
hint mentions *grey/gray*.

### How we actually found it (method, incl. the dead-ends)
1. hex → 58 bytes; noticed a **reduced alphabet** (~25 distinct values), mostly
   uppercase, frequent `0x30`.
2. brute phase that ALL failed (recorded so we don't repeat): single-byte XOR,
   keyword XOR, Vigenère XOR/ADD/SUB (all lengths, charsets incl. hex/base64),
   **image OTP** (every channel/greyscale formula/order/offset — fuzzy dist 45 ⇒
   not the image), base-26, rank/freq substitution, ramps, affine, hash keystreams.
3. the unlock was the **exact hint** ("**50** shades of **grey**") → *grey* = a pun
   on **Gray code**, not grayscale; "256 would've been better" = 8-bit Gray = 256
   values. One `gray_to_bin` pass then revealed the plaintext.
> Lesson: when XOR/Vigenère/OTP all fail on a short "encoded" blob, suspect a
> *representation* change (Gray code, endianness, bit-order, base-N) before a key.

### References
- **Gray code (binary reflected) — definition + binary⇄Gray conversion.**
  - https://en.wikipedia.org/wiki/Gray_code
- **Gray↔binary bit-twiddling (the `g ^= g>>k` trick).**
  - https://graphics.stanford.edu/~seander/bithacks.html#GrayCode
- **CyberChef — "From Gray Code" operation** (point-and-click decode).
  - https://gchq.github.io/CyberChef/

---

## 4. Rate limiting / lockout — do NOT brute-force the PIN

`/api/verify-pin` limits attempts (`attempts_left`, `retry_after`,
`rate_limited`) and the firmware can disable the SoftAP ("lockdown, power-cycle
to restore"). README: *"Be careful not to get locked out."* The intended path
is to *recover* the PIN (stego), not guess 10000 combos.

- **OWASP — Blocking Brute Force Attacks / account-lockout rationale.**
  - https://owasp.org/www-community/controls/Blocking_Brute_Force_Attacks
- **CWE-307 — Improper Restriction of Excessive Authentication Attempts.**
  - https://cwe.mitre.org/data/definitions/307.html
- **"A house that starts over does not keep its old locks"** = the PIN
  regenerates every boot (per-boot secret, like ch3's token) — so a recovered
  PIN is only valid until the next reboot.

---

## 5. The pivot — UART to disclose the flag

After the vault is unlatched, the flag is read over the UART CLI (same board /
serial setup as ch3).

- **pySerial** (UART console; open with `dtr=rts=False` to avoid resetting a
  CH340).
  - https://pyserial.readthedocs.io/en/stable/pyserial_api.html
- **ESP32 auto-reset (DTR/RTS = EN/BOOT)**.
  - https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html
- See [[challenge3-airwave-template-solved]] — same board, same SoftAP +
  WSL/python.exe UART pattern.

---

## 6. Transport & platform

- **ESP32 SoftAP default `192.168.4.1`** (Espressif).
  - https://docs.espressif.com/projects/esp-at/en/latest/esp32/AT_Command_Examples/TCP-IP_AT_Examples.html
- **Python `urllib` / HTTP client** (black-box requests).
  - https://docs.python.org/3/library/urllib.request.html
- **gzip-compressed assets on embedded web servers** (the dashboard HTML is
  served gzipped to save flash — decompress client-side to inspect).
  - https://docs.python.org/3/library/gzip.html

---

## 7. Step → reference map

| Solve step | Reference |
|---|---|
| Read served HTML/JS, find breadcrumb | OWASP WSTG "Review Webpage Content" |
| Reach unlinked `/api/admin` | Forced browsing (OWASP, CWE-425, CAPEC-87) |
| Pull hidden PIN from the asset | CTF stego methodology, zsteg/Stegsolve/steghide |
| Avoid lockout, don't brute the PIN | OWASP brute-force controls, CWE-307 |
| (If needed) feed digits to classifier | MNIST + preprocessing notes |
| Craft inputs the classifier accepts as chosen digits | Adversarial ML: FGSM/C&W/PGD, MITRE ATLAS, OWASP ML Top 10 |
| Submit PIN → vault unlatched (POST /api/verify-pin) | §4, CWE-307 |
| Decode vault "encoded at rest" payload | **Gray code** (§3c) — Wikipedia, bithacks, CyberChef "From Gray Code" |
| Pivot: `diag_dump <token>` on UART → flag | pySerial + ESP32 auto-reset |

**Confirmed solve chain:** breadcrumb `/api/admin` (forced browsing) → content-neg
PNG → stego `b1,r,lsb,xy` → `PIN:9573` → POST /api/verify-pin `[9,5,7,3]` → vault
open → **Gray-code** payload → `diag_dump FBSuDb` (UART) →
`esc_2026{50_shades_of_grey_7685f0ebd0f4df28}`.

---

*Living document — extended as each black-box step is confirmed on the device.*
