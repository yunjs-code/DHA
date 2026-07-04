#!/usr/bin/env python3
"""MAVLink v2 서명 키 생성 유틸리티.

생성된 32바이트 키를 파일로 저장한다.
GCS(정상 측)와 공격자가 이 키를 공유하는지 여부가 실험의 핵심 변수다.
"""
import argparse
import os
import sys


def generate_key(path: str, force: bool = False) -> None:
    if os.path.exists(path) and not force:
        print(f"[ERROR] 파일이 이미 존재합니다: {path}")
        print(f"        덮어쓰려면 --force 옵션을 사용하세요.")
        sys.exit(1)

    key = os.urandom(32)

    with open(path, "wb") as f:
        f.write(key)

    print(f"[OK]    32바이트 서명 키 생성 완료: {path}")
    print(f"[KEY]   {key.hex()}")
    print()
    print(f"[사용법]")
    print(f"  방어 적용:  python scripts/defense_signing.py --drone drone-01 --key-file {path}")
    print(f"  서명 공격:  python scripts/inject_attack.py   --drone drone-01 --cmd ARM --sign --key-file {path}")
    print(f"  무서명 공격: python scripts/inject_attack.py  --drone drone-01 --cmd ARM --no-sign")


def main() -> None:
    ap = argparse.ArgumentParser(description="MAVLink v2 서명 키 생성")
    ap.add_argument("--key-file", default="signing.key", help="저장할 키 파일 경로 (기본: signing.key)")
    ap.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기")
    args = ap.parse_args()

    generate_key(args.key_file, args.force)


if __name__ == "__main__":
    main()
