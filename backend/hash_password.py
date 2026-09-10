"""
Turn a plaintext password into a `scrypt:<salt>:<hash>` value you can put in
DASH_USERS so the plaintext never leaves your machine.

    python hash_password.py
    python hash_password.py "my long passphrase"

Then in Railway → Variables:
    DASH_USERS = sashakhoo:scrypt:<salt>:<hash>:director,accounts:scrypt:<salt>:<hash>:admin
"""
import contextlib
import getpass
import io
import sys

with contextlib.redirect_stdout(io.StringIO()):
    from auth import _to_record  # reuses the exact same scrypt parameters


def main():
    pw = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Password: ")
    if not pw:
        raise SystemExit("empty password")
    salt_hex, hash_hex = _to_record(pw)
    print(f"scrypt:{salt_hex}:{hash_hex}")


if __name__ == "__main__":
    main()
