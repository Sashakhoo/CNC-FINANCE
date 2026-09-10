"""
Turn a plaintext password into a `scrypt:<salt>:<hash>` value for the
DASH_USERS bootstrap variable, so the plaintext never leaves your machine.

    python hash_password.py
    python hash_password.py "my long passphrase"
"""
import contextlib
import getpass
import io
import sys

with contextlib.redirect_stdout(io.StringIO()):
    from auth import hash_new


def main():
    pw = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Password: ")
    if not pw:
        raise SystemExit("empty password")
    salt_hex, hash_hex = hash_new(pw)
    print(f"scrypt:{salt_hex}:{hash_hex}")


if __name__ == "__main__":
    main()
