#!/usr/bin/env python3
"""MAVLink TCP 릴레이 — MAVProxy 없이 ArduCopter ↔ 다중 클라이언트 중계.

ArduCopter TCP 포트에 직접 접속하고, 지정한 포트들을 열어 클라이언트 연결을 대기한다.
ArduCopter에서 온 바이트를 모든 클라이언트에 브로드캐스트하고,
클라이언트에서 온 바이트를 ArduCopter로 전달한다.

ArduCopter 연결이 끊기면(크래시·재시작 등) 클라이언트 리스너는 유지한 채
자동으로 재접속을 계속 시도한다 — 프로세스가 종료되지 않는다.

사용법:
  python3 scripts/mavlink_tcp_relay.py --ardu-port 5760 --listen 15760 25760
"""
import argparse
import select
import socket
import sys
import time

BUF = 65536
ARDU_RECONNECT_DELAY = 2.0


def connect_ardu(ardu_host: str, ardu_port: int) -> socket.socket:
    """ArduCopter에 연결될 때까지 무한 재시도한다."""
    attempt = 0
    while True:
        attempt += 1
        try:
            ardu = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ardu.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            ardu.settimeout(5.0)
            ardu.connect((ardu_host, ardu_port))
            ardu.setblocking(False)
            print(f"[RELAY] ✔ ArduCopter 연결: {ardu_host}:{ardu_port} (시도 {attempt})", flush=True)
            return ardu
        except Exception as e:
            print(f"[RELAY] ✗ ArduCopter 연결 실패 (시도 {attempt}): {e} "
                  f"— {ARDU_RECONNECT_DELAY}s 후 재시도", flush=True)
            time.sleep(ARDU_RECONNECT_DELAY)


def bind_listeners(listen_ports: list[int]) -> list[socket.socket]:
    listeners = []
    for port in listen_ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        s.setblocking(False)
        listeners.append(s)
        print(f"[RELAY] ✔ 대기 중: 0.0.0.0:{port}", flush=True)
    return listeners


def pump(ardu: socket.socket, listeners: list[socket.socket],
         clients: list[socket.socket]) -> None:
    """ArduCopter가 연결되어 있는 동안 중계를 수행한다.

    ArduCopter 연결이 끊기거나 select 오류가 발생하면 리턴한다
    (호출측이 재접속 후 다시 호출) — 프로세스는 종료하지 않는다.
    """
    print("[RELAY] 중계 시작. 클라이언트 연결 대기...", flush=True)

    while True:
        rlist = [ardu] + listeners + clients
        try:
            readable, _, exceptional = select.select(rlist, [], rlist, 1.0)
        except Exception as e:
            print(f"[RELAY] select 오류: {e} — ArduCopter 재접속", flush=True)
            return

        for s in readable:
            # ── ArduCopter → 모든 클라이언트 브로드캐스트 ──────────────────
            if s is ardu:
                try:
                    data = ardu.recv(BUF)
                except Exception:
                    data = b""
                if not data:
                    print("[RELAY] ArduCopter 연결 끊김 — 재접속 시도", flush=True)
                    return
                dead = []
                for c in clients:
                    try:
                        c.sendall(data)
                    except Exception:
                        dead.append(c)
                for c in dead:
                    clients.remove(c)
                    c.close()

            # ── 신규 클라이언트 접속 ────────────────────────────────────────
            elif s in listeners:
                try:
                    conn, addr = s.accept()
                    conn.setblocking(False)
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    clients.append(conn)
                    print(f"[RELAY] 클라이언트 접속: {addr[0]}:{addr[1]}", flush=True)
                except Exception:
                    pass

            # ── 클라이언트 → ArduCopter 전달 ───────────────────────────────
            elif s in clients:
                try:
                    data = s.recv(BUF)
                except Exception:
                    data = b""
                if not data:
                    clients.remove(s)
                    s.close()
                else:
                    try:
                        ardu.sendall(data)
                    except Exception as e:
                        print(f"[RELAY] ArduCopter 전송 오류: {e}", flush=True)

        for s in exceptional:
            if s in clients:
                clients.remove(s)
            try:
                s.close()
            except Exception:
                pass


def run(ardu_host: str, ardu_port: int, listen_ports: list[int]) -> None:
    listeners = bind_listeners(listen_ports)
    clients: list[socket.socket] = []

    while True:
        ardu = connect_ardu(ardu_host, ardu_port)
        try:
            pump(ardu, listeners, clients)
        finally:
            try:
                ardu.close()
            except Exception:
                pass
            # ArduCopter가 끊긴 뒤 남은 클라이언트도 정리한다.
            # 클라이언트(FastAPI SITLConnector 등)는 자체 재접속 로직을 갖고 있으므로
            # 깨끗하게 연결을 닫아 즉시 재접속을 유도한다.
            for c in clients:
                try:
                    c.close()
                except Exception:
                    pass
            clients.clear()


def main() -> None:
    ap = argparse.ArgumentParser(description="MAVLink TCP 릴레이 (MAVProxy 대체)")
    ap.add_argument("--ardu-host", default="127.0.0.1", help="ArduCopter 호스트")
    ap.add_argument("--ardu-port", type=int, required=True, help="ArduCopter TCP 포트")
    ap.add_argument("--listen",    type=int, nargs="+", required=True,
                    metavar="PORT", help="클라이언트 수신 포트 (여러 개)")
    args = ap.parse_args()

    print(f"[RELAY] 시작: ArduCopter={args.ardu_host}:{args.ardu_port} "
          f"릴레이포트={args.listen}", flush=True)
    try:
        run(args.ardu_host, args.ardu_port, args.listen)
    except KeyboardInterrupt:
        print("[RELAY] 종료", flush=True)
    except Exception as e:
        print(f"[RELAY] 치명적 오류로 종료: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
