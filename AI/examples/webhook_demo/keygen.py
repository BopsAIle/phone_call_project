"""Bước 0: tạo cặp khóa Ed25519 giả lập cặp khóa Telnyx cấp cho bạn.

Ngoài đời bạn KHÔNG chạy file này: Telnyx giữ private key, còn public key thì
bạn copy từ portal về bỏ vào TELNYX_PUBLIC_KEY. Ở đây ta đóng cả hai vai nên
phải tự sinh ra cặp khóa đó.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from nacl.signing import SigningKey

KEYFILE = Path(__file__).with_name("demo_keys.json")


def main() -> None:
    signing_key = SigningKey.generate()
    keys = {
        # Telnyx giữ cái này để KÝ webhook.
        "private_key": base64.b64encode(bytes(signing_key)).decode(),
        # Bạn giữ cái này để KIỂM chữ ký. Chỉ cái này mới nằm trong .env.
        "public_key": base64.b64encode(bytes(signing_key.verify_key)).decode(),
    }
    KEYFILE.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    print(f"Đã ghi {KEYFILE.name}")
    print(f"  public_key  (= TELNYX_PUBLIC_KEY) : {keys['public_key']}")
    print(f"  private_key (Telnyx giữ, đừng lộ) : {keys['private_key'][:16]}...")


if __name__ == "__main__":
    main()
