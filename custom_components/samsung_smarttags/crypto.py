"""
Cryptographic helpers for Samsung Account authentication.

Implements the encryption/decryption flows matching the uTag source:
https://github.com/KieronQuinn/uTag
"""

import base64
import hashlib
import json
import os
import secrets
import string
from urllib.parse import quote

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import pad


def random_string(length: int) -> str:
    """Generate a random alphanumeric string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_code_challenge() -> tuple[str, str]:
    """Generate code verifier and its SHA-256 base64url challenge (PKCE S256)."""
    verifier = random_string(43)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def generate_state() -> str:
    """Generate a random 20-character state string."""
    return random_string(20)


def generate_android_id() -> str:
    """Generate a random hex string to use as Android ID."""
    return secrets.token_hex(8)


def _hash_data(input_str: str) -> str:
    """SHA-256 hash then base64 encode."""
    digest = hashlib.sha256(input_str.encode("UTF-8")).digest()
    return base64.b64encode(digest).decode("UTF-8")


def _pbkdf2_derive(password_chars: str, salt: bytes, iterations: int) -> bytes:
    """PBKDF2 key derivation — 128-bit output."""
    return PBKDF2(
        password_chars.encode("UTF-8"),
        salt,
        dkLen=16,
        count=iterations,
    )


def _get_key(chk_do_num_str: str, chk_do_num: int) -> bytes:
    """Generate the AES key via PBKDF2."""
    hashed = _hash_data(chk_do_num_str)
    salt = os.urandom(16)
    return _pbkdf2_derive(hashed, salt, chk_do_num)


def _get_encrypted_key(aes_key: bytes, public_key) -> str:
    """RSA-encrypt the AES key."""
    cipher_rsa = PKCS1_v1_5.new(public_key)
    key_b64 = base64.b64encode(aes_key)
    encrypted = cipher_rsa.encrypt(key_b64)
    return base64.b64encode(encrypted).decode("UTF-8")


def _get_encrypted_value(aes_key: bytes, iv: bytes, plaintext: str) -> str:
    """AES/CBC/PKCS5Padding encrypt."""
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    padded = pad(plaintext.encode("UTF-8"), AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("UTF-8")


def encrypt_svc_param(svc_param_json: str, pki_public_key_b64: str, chk_do_num_str: str) -> str:
    """Encrypt the SVC param and return the full svcParam query value."""
    chk_do_num = int(chk_do_num_str)

    pki_key_der = base64.b64decode(pki_public_key_b64)
    rsa_key = RSA.import_key(pki_key_der)

    aes_key = _get_key(chk_do_num_str, chk_do_num)
    svc_enc_ky = _get_encrypted_key(aes_key, rsa_key)

    iv = os.urandom(16)
    svc_enc_param = _get_encrypted_value(aes_key, iv, svc_param_json)
    svc_enc_iv = iv.hex()

    payload = json.dumps(
        {
            "chkDoNum": chk_do_num_str,
            "svcEncParam": svc_enc_param,
            "svcEncKY": svc_enc_ky,
            "svcEncIV": svc_enc_iv,
        },
        separators=(",", ":"),
    )

    b64_payload = base64.b64encode(payload.encode("UTF-8")).decode("UTF-8")
    return quote(b64_payload, safe="")


def decrypt_login_response(encrypted_value: str, state: str) -> str:
    """Decrypt the 'state' field from the login redirect using AES/ECB."""
    key_bytes = state.encode("UTF-8")[:16]
    if len(key_bytes) < 16:
        key_bytes = key_bytes + b"\x00" * (16 - len(key_bytes))
    key_spec = key_bytes[:16]

    cipher = AES.new(key_spec, AES.MODE_ECB)
    if all(c in "0123456789abcdefABCDEF" for c in encrypted_value):
        data = bytes.fromhex(encrypted_value)
    else:
        data = base64.b64decode(encrypted_value)
    decrypted = cipher.decrypt(data)

    pad_len = decrypted[-1]
    if 0 < pad_len <= 16 and all(b == pad_len for b in decrypted[-pad_len:]):
        decrypted = decrypted[:-pad_len]
    return decrypted.decode("UTF-8")


def decrypt_with_state(encrypted_value: str, decrypted_state: str) -> str:
    """Decrypt auth code, auth server URL, or email using the decrypted state."""
    return decrypt_login_response(encrypted_value, decrypted_state)


def build_svc_param(
    code_challenge_b64: str,
    country_code: str,
    android_id: str,
    state: str,
) -> dict:
    """Build the SVC Param dict for Samsung login."""
    return {
        "clientId": "yfrtglt53o",
        "code_challenge": code_challenge_b64,
        "code_challenge_method": "S256",
        "competitorDeviceYNFlag": "Y",
        "countryCode": country_code.lower(),
        "deviceInfo": "Microsoft|com.android.chrome",
        "deviceModelID": "Windows PC",
        "deviceName": "Microsoft Windows PC",
        "deviceOSVersion": "35",
        "devicePhysicalAddressText": f"ANID:{android_id}",
        "deviceType": "APP",
        "deviceUniqueID": android_id,
        "redirect_uri": (
            "ms-app://s-1-15-2-4027708247-2189610-1983755848-"
            "2937435718-1578786913-2158692839-1974417358"
        ),
        "replaceableClientConnectYN": "N",
        "replaceableClientId": "",
        "replaceableDevicePhysicalAddressText": "",
        "responseEncryptionType": "1",
        "responseEncryptionYNFlag": "Y",
        "scope": "",
        "state": state,
        "svcIptLgnID": "",
        "iosYNFlag": "Y",
    }


def build_login_url(
    sign_in_uri: str,
    pki_public_key_b64: str,
    chk_do_num: str,
    country_code: str = "us",
    language: str = "en",
) -> dict:
    """Build the full Samsung login URL.

    Returns dict with url, code_verifier, state, android_id.
    """
    code_verifier, code_challenge = generate_code_challenge()
    state = generate_state()
    android_id = generate_android_id()

    svc_param = build_svc_param(code_challenge, country_code, android_id, state)
    svc_param_json = json.dumps(svc_param, separators=(",", ":"))

    svc_param_encoded = encrypt_svc_param(
        svc_param_json, pki_public_key_b64, str(chk_do_num)
    )

    full_url = f"{sign_in_uri}?locale={quote(language)}&svcParam={svc_param_encoded}&mode=C"

    return {
        "url": full_url,
        "code_verifier": code_verifier,
        "state": state,
        "android_id": android_id,
    }


def decrypt_e2e_location(
    lat_enc: str, lon_enc: str, private_key_b64: str, iv_b64: str,
    pin: str, user_id: str,
) -> tuple[float, float]:
    """Decrypt E2E-encrypted tag location coordinates.

    Returns (latitude, longitude) as floats.
    """
    is_v2 = private_key_b64.endswith("_v2")
    if is_v2:
        private_key_b64 = private_key_b64[:-3]

    key_material = (pin + user_id) if is_v2 else pin

    key_hash = hashlib.sha256(key_material.encode()).digest()
    iv = base64.b64decode(iv_b64)
    encrypted_privkey = base64.b64decode(private_key_b64)
    cipher = AES.new(key_hash, AES.MODE_CBC, iv)

    from Crypto.Util.Padding import unpad

    decrypted_privkey = unpad(cipher.decrypt(encrypted_privkey), AES.block_size)

    import ecies

    dec_lat = ecies.decrypt(decrypted_privkey, base64.b64decode(lat_enc))
    dec_lon = ecies.decrypt(decrypted_privkey, base64.b64decode(lon_enc))
    return float(dec_lat.decode()), float(dec_lon.decode())
