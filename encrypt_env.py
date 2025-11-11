#!/usr/bin/env python3
import argparse, getpass, os, sys
from secrets import token_bytes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'ENV1'           # file marker
SALT_LEN = 16
NONCE_LEN = 12

def derive_key(passphrase: bytes, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    return kdf.derive(passphrase)

def main():
    ap = argparse.ArgumentParser(description="Encrypt a .env file with AES-256-GCM using scrypt key derivation.")
    ap.add_argument("--in", dest="src", default=".env", help="Input file (default: .env)")
    ap.add_argument("--out", dest="dst", default=".env.enc", help="Output file (default: .env.enc)")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        print(f"ERROR: input file not found: {args.src}", file=sys.stderr)
        sys.exit(1)

    pw = getpass.getpass("Enter passphrase: ").encode("utf-8")
    pw2 = getpass.getpass("Re-enter passphrase: ").encode("utf-8")
    if pw != pw2:
        print("ERROR: passphrases do not match.", file=sys.stderr)
        sys.exit(2)

    salt = token_bytes(SALT_LEN)
    key = derive_key(pw, salt)
    aes = AESGCM(key)
    nonce = token_bytes(NONCE_LEN)

    data = open(args.src, "rb").read()
    ct = aes.encrypt(nonce, data, associated_data=None)

    with open(args.dst, "wb") as f:
        f.write(MAGIC + salt + nonce + ct)

    print(f"Encrypted -> {args.dst}")
    print("Share the passphrase out-of-band (phone/Teams).")

if __name__ == "__main__":
    main()
