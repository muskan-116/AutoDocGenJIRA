# app/utils/crypto.py
import os
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import base64
import hashlib

# Use AES-256-CBC like Node version
KEY = os.getenv("ENCRYPTION_KEY", "dev-encryption-key-please-change")
# Ensure 32 bytes key for AES-256
key = hashlib.sha256(KEY.encode("utf-8")).digest()

def pad(s: bytes) -> bytes:
    # PKCS7 padding
    pad_len = AES.block_size - (len(s) % AES.block_size)
    return s + bytes([pad_len] * pad_len)

def unpad(s: bytes) -> bytes:
    pad_len = s[-1]
    return s[:-pad_len]

def encrypt(plain: str) -> str:
    iv = get_random_bytes(AES.block_size)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    enc = cipher.encrypt(pad(plain.encode("utf-8")))
    return base64.b64encode(iv).decode() + ":" + base64.b64encode(enc).decode()

def decrypt(enc_str: str) -> str:
    try:
        iv_b64, data_b64 = enc_str.split(":")
        iv = base64.b64decode(iv_b64)
        data = base64.b64decode(data_b64)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        dec = unpad(cipher.decrypt(data))
        return dec.decode("utf-8")
    except Exception:
        return None
