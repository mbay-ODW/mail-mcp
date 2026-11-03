"""Minimal in-process IMAP4rev1 server for flag regression tests.

Speaks real IMAP over TCP so the production ``imaplib`` code is exercised
end-to-end. It implements just enough of RFC 3501 for this project and – the
point of the exercise – its ``\\Seen`` semantics:

* ``FETCH BODY[...]`` / ``RFC822`` / ``RFC822.TEXT`` set ``\\Seen`` implicitly,
* ``BODY.PEEK[...]``, ``RFC822.HEADER``, ``FLAGS``, ``UID`` do not,
* a mailbox opened with ``EXAMINE`` is read-only: no implicit ``\\Seen`` and
  ``STORE`` is rejected.

Every command is recorded in ``server.log`` so tests can also assert on the
wire protocol (e.g. "no non-PEEK body fetch was ever sent").
"""

from __future__ import annotations

import email
import re
import socketserver
import threading
from dataclasses import dataclass, field
from email.policy import default as default_policy


@dataclass
class Message:
    uid: int
    raw: bytes
    flags: set[str] = field(default_factory=set)


class Mailbox:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.next_uid = 1

    def append(self, raw: bytes, flags: set[str] | None = None) -> int:
        uid = self.next_uid
        self.next_uid += 1
        self.messages.append(Message(uid, raw, set(flags or ())))
        return uid


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\((?:[^()]|\([^()]*\))*\)|\[[^\]]*\]|[^\s()]+')


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == tok[-1] == '"':
        return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return tok


def _parse_set(spec: str, max_value: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":", 1)
            lo = max_value if a == "*" else int(a)
            hi = max_value if b == "*" else int(b)
            lo, hi = min(lo, hi), max(lo, hi)
            out.update(range(lo, hi + 1))
        else:
            out.add(max_value if part == "*" else int(part))
    return out


def _fetch_items(spec: str) -> list[str]:
    spec = spec.strip()
    if spec.startswith("(") and spec.endswith(")"):
        spec = spec[1:-1]
    items: list[str] = []
    i = 0
    while i < len(spec):
        if spec[i] == " ":
            i += 1
            continue
        j = i
        depth = 0
        while j < len(spec) and (spec[j] != " " or depth):
            if spec[j] in "[(":
                depth += 1
            elif spec[j] in "])":
                depth -= 1
            j += 1
        items.append(spec[i:j])
        i = j
    return items


def _section(raw: bytes, section: str) -> bytes:
    section = section.upper()
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        head, sep, body = raw.partition(b"\n\n")
    if section == "":
        return raw
    if section == "HEADER":
        return head + sep
    if section == "TEXT":
        return body
    m = re.match(r"HEADER\.FIELDS \((.*)\)", section)
    if m:
        wanted = {f.upper() for f in m.group(1).split()}
        msg = email.message_from_bytes(raw, policy=default_policy)
        lines = [f"{k}: {v}" for k, v in msg.items() if k.upper() in wanted]
        return ("\r\n".join(lines) + "\r\n\r\n").encode()
    raise ValueError(f"unsupported section {section}")


class _Handler(socketserver.StreamRequestHandler):
    server: TestIMAPServer

    def _send(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()

    def handle(self) -> None:  # noqa: C901 - protocol dispatcher
        self.selected: str | None = None
        self.readonly = False
        self._send(b"* OK IMAP4rev1 test server ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            with self.server.lock:
                self.server.log.append(text)
            tag, _, rest = text.partition(" ")
            cmd, _, args = rest.partition(" ")
            cmd = cmd.upper()
            uid_mode = False
            if cmd == "UID":
                uid_mode = True
                cmd, _, args = args.partition(" ")
                cmd = cmd.upper()
            try:
                with self.server.lock:
                    done = self._dispatch(tag, cmd, args, uid_mode)
            except Exception as exc:  # pragma: no cover - debugging aid
                self._send(f"{tag} BAD {exc}\r\n".encode())
                continue
            if done:
                return

    # -- commands -----------------------------------------------------------

    def _dispatch(self, tag: str, cmd: str, args: str, uid_mode: bool) -> bool:
        srv = self.server
        if cmd == "CAPABILITY":
            self._send(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n")
        elif cmd == "LOGIN":
            pass
        elif cmd == "NOOP":
            pass
        elif cmd == "LOGOUT":
            self._send(b"* BYE bye\r\n")
            self._send(f"{tag} OK LOGOUT completed\r\n".encode())
            return True
        elif cmd == "LIST":
            for name in srv.mailboxes:
                self._send(f'* LIST (\\HasNoChildren) "/" {name}\r\n'.encode())
        elif cmd in ("SELECT", "EXAMINE"):
            name = _unquote(args.strip())
            if name not in srv.mailboxes:
                self._send(f"{tag} NO no such mailbox\r\n".encode())
                return False
            self.selected = name
            self.readonly = cmd == "EXAMINE"
            box = srv.mailboxes[name]
            self._send(f"* {len(box.messages)} EXISTS\r\n* 0 RECENT\r\n".encode())
            self._send(f"* OK [UIDNEXT {box.next_uid}] next uid\r\n".encode())
            mode = "READ-ONLY" if self.readonly else "READ-WRITE"
            self._send(f"{tag} OK [{mode}] {cmd} completed\r\n".encode())
            return False
        elif cmd == "SEARCH":
            self._search(tag, args, uid_mode)
            return False
        elif cmd == "FETCH":
            self._fetch(args, uid_mode)
        elif cmd == "STORE":
            if self.readonly:
                self._send(f"{tag} NO mailbox is read-only\r\n".encode())
                return False
            self._store(args, uid_mode)
        else:
            self._send(f"{tag} BAD unsupported {cmd}\r\n".encode())
            return False
        self._send(f"{tag} OK {cmd} completed\r\n".encode())
        return False

    def _box(self) -> Mailbox:
        assert self.selected is not None, "no mailbox selected"
        return self.server.mailboxes[self.selected]

    def _targets(self, spec: str, uid_mode: bool) -> list[tuple[int, Message]]:
        box = self._box()
        if not box.messages:
            return []
        if uid_mode:
            wanted = _parse_set(spec, box.messages[-1].uid)
            return [(i + 1, m) for i, m in enumerate(box.messages) if m.uid in wanted]
        wanted = _parse_set(spec, len(box.messages))
        return [(i + 1, m) for i, m in enumerate(box.messages) if (i + 1) in wanted]

    def _search(self, tag: str, args: str, uid_mode: bool) -> None:
        tokens = _TOKEN.findall(args)
        if tokens and tokens[0].upper() == "CHARSET":
            tokens = tokens[2:]
        box = self._box()
        hits = []
        for seq, msg in enumerate(box.messages, start=1):
            if self._matches(msg, seq, tokens):
                hits.append(msg.uid if uid_mode else seq)
        self._send(("* SEARCH " + " ".join(map(str, hits))).rstrip().encode() + b"\r\n")
        self._send(f"{tag} OK SEARCH completed\r\n".encode())

    def _matches(self, msg: Message, seq: int, tokens: list[str]) -> bool:
        parsed = email.message_from_bytes(msg.raw, policy=default_policy)
        i = 0
        while i < len(tokens):
            key = tokens[i].upper()
            if key == "ALL":
                i += 1
            elif key in ("SEEN", "UNSEEN"):
                if ("\\Seen" in msg.flags) != (key == "SEEN"):
                    return False
                i += 1
            elif key == "UID":
                last = self._box().messages[-1].uid
                if msg.uid not in _parse_set(tokens[i + 1], last):
                    return False
                i += 2
            elif key in ("FROM", "TO", "SUBJECT"):
                needle = _unquote(tokens[i + 1]).lower()
                if needle not in str(parsed.get(key, "")).lower():
                    return False
                i += 2
            elif key in ("SINCE", "BEFORE", "ON"):
                i += 2  # date filtering is irrelevant for these tests
            else:
                raise ValueError(f"unsupported search key {key}")
        return True

    def _fetch(self, args: str, uid_mode: bool) -> None:
        spec, _, items_spec = args.partition(" ")
        items = _fetch_items(items_spec)
        for seq, msg in self._targets(spec, uid_mode):
            parts: list[bytes] = []
            literals: list[tuple[bytes, bytes]] = []
            if uid_mode and not any(it.upper() == "UID" for it in items):
                parts.append(f"UID {msg.uid}".encode())
            for item in items:
                up = item.upper()
                if up == "UID":
                    parts.append(f"UID {msg.uid}".encode())
                elif up == "FLAGS":
                    continue  # emitted last, after any implicit \Seen
                elif up.startswith("BODY.PEEK[") or up.startswith("BODY["):
                    peek = up.startswith("BODY.PEEK[")
                    section = item[item.index("[") + 1 : item.rindex("]")]
                    data = _section(msg.raw, section)
                    if not peek and not self.readonly:
                        msg.flags.add("\\Seen")
                    literals.append((f"BODY[{section}]".encode(), data))
                elif up in ("RFC822", "RFC822.TEXT"):
                    if not self.readonly:
                        msg.flags.add("\\Seen")
                    data = msg.raw if up == "RFC822" else _section(msg.raw, "TEXT")
                    literals.append((up.encode(), data))
                elif up == "RFC822.HEADER":
                    literals.append((b"RFC822.HEADER", _section(msg.raw, "HEADER")))
                elif up == "RFC822.SIZE":
                    parts.append(f"RFC822.SIZE {len(msg.raw)}".encode())
                else:
                    raise ValueError(f"unsupported fetch item {item}")
            if any(it.upper() == "FLAGS" for it in items):
                parts.append(f"FLAGS ({' '.join(sorted(msg.flags))})".encode())
            out = f"* {seq} FETCH (".encode() + b" ".join(parts)
            for name, data in literals:
                sep = b" " if out[-1:] != b"(" else b""
                out += sep + name + f" {{{len(data)}}}\r\n".encode() + data
            self._send(out + b")\r\n")

    def _store(self, args: str, uid_mode: bool) -> None:
        spec, _, rest = args.partition(" ")
        mode, _, flags_spec = rest.partition(" ")
        flags = set(flags_spec.strip("()").split())
        silent = mode.upper().endswith(".SILENT")
        for seq, msg in self._targets(spec, uid_mode):
            if mode.startswith("+"):
                msg.flags |= flags
            elif mode.startswith("-"):
                msg.flags -= flags
            else:
                msg.flags = set(flags)
            if not silent:
                flag_str = " ".join(sorted(msg.flags))
                self._send(f"* {seq} FETCH (UID {msg.uid} FLAGS ({flag_str}))\r\n".encode())


class TestIMAPServer(socketserver.ThreadingTCPServer):
    __test__ = False  # not a pytest test class
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.RLock()
        self.log: list[str] = []
        self.mailboxes: dict[str, Mailbox] = {"INBOX": Mailbox(), "Sent": Mailbox()}
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def start(self) -> TestIMAPServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def add(self, raw: bytes, folder: str = "INBOX", flags: set[str] | None = None) -> int:
        with self.lock:
            return self.mailboxes[folder].append(raw, flags)

    def flags(self, uid: int, folder: str = "INBOX") -> set[str]:
        with self.lock:
            for msg in self.mailboxes[folder].messages:
                if msg.uid == uid:
                    return set(msg.flags)
        raise KeyError(uid)
