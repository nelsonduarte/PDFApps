"""PDFApps single-instance enforcement via QLocalServer.

When a second invocation happens (e.g., user clicks a PDF in Explorer
while PDFApps is already running), the new process connects to the
running instance, sends the PDF paths via a length-prefixed UTF-8
message, and exits immediately. The running instance loads each path
as a new tab and brings its window to the front.

Wire format
-----------
``[4-byte big-endian length] [UTF-8 payload]``

Payload is NUL-separated (``\\0``) absolute paths. NUL is illegal in
every mainstream filesystem (POSIX + Windows NTFS/exFAT), so it is a
safer delimiter than newline — paths can legitimately contain ``\\n``
on macOS and Linux, which would have been silently split with the
previous newline separator. The 4-byte length lets the server frame
the message correctly even when ``readyRead`` arrives in multiple
chunks. A 64 KB cap prevents a hostile or buggy peer from forcing the
server to allocate unbounded memory.

Socket naming
-------------
The socket name is suffixed with the first 12 hex chars of
``sha256(username)`` so concurrent sessions on a shared machine (e.g.,
Windows fast-user-switching or a multi-user Linux box) each get their
own instance — they should not steal each other's PDF tabs.
"""

import getpass
import hashlib
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_log = logging.getLogger(__name__)

# Connect/wait timeout for the second-invocation handshake. 1 s is
# generous on local sockets/named pipes (typical RTT < 5 ms) while
# still capping the worst-case startup delay if the running instance
# is wedged.
_SOCKET_TIMEOUT_MS = 1000

# Cap on a single payload. 64 KB easily fits hundreds of absolute paths
# (a typical Windows MAX_PATH is 260 chars) and bounds memory pressure
# from a malformed or hostile peer.
_MAX_PAYLOAD_BYTES = 64 * 1024


def _socket_name() -> str:
    """Stable per-user socket name.

    Suffixed with a hash of the username so simultaneous sessions for
    different users on the same machine don't collide (and don't
    accidentally hand each other's PDFs across user boundaries).
    """
    try:
        user = getpass.getuser()
    except Exception:
        # getuser() raises on minimal Windows services with no USERNAME
        # env var; fall back to a stable literal so the socket is at
        # least reachable from sibling processes of the same user.
        user = "default"
    digest = hashlib.sha256(user.encode("utf-8")).hexdigest()[:12]
    return f"pdfapps-single-instance-{digest}"


def send_to_existing(paths: list[str]) -> bool:
    """Try to forward ``paths`` to a running PDFApps instance.

    Returns ``True`` if the connection succeeded and the message was
    written (the caller — a second invocation — should now exit).
    Returns ``False`` if no instance is running (caller should start
    the main window itself).
    """
    sock = QLocalSocket()
    sock.connectToServer(_socket_name())
    if not sock.waitForConnected(_SOCKET_TIMEOUT_MS):
        return False
    try:
        # NUL separator: paths can contain newlines on macOS/Linux but
        # NUL is forbidden in every mainstream filesystem, so it is the
        # only fully unambiguous delimiter for absolute paths.
        payload = "\0".join(paths).encode("utf-8")
        if len(payload) > _MAX_PAYLOAD_BYTES:
            # Refuse to send a payload the server would just reject;
            # better to fall back to a normal second instance than
            # silently drop half the files.
            _log.warning(
                "single-instance: payload too large (%d > %d), "
                "falling back to second instance",
                len(payload), _MAX_PAYLOAD_BYTES,
            )
            return False
        header = len(payload).to_bytes(4, "big")
        sock.write(header + payload)
        sock.flush()
        sock.waitForBytesWritten(_SOCKET_TIMEOUT_MS)
    finally:
        sock.disconnectFromServer()
        sock.close()
    return True


class SingleInstanceServer(QObject):
    """Listens for second-invocation connections and emits paths.

    Connect the ``new_paths`` signal to the main window's load handler.
    Construction is no-op-safe if the server fails to bind (a warning
    is logged and the signal simply never fires), so the running
    instance keeps working even without single-instance forwarding.
    """

    new_paths = Signal(list)  # list[str]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        # Clean up any stale socket file from a previous crash. On
        # Linux QLocalServer leaves an orphan file behind if the
        # process is killed; removeServer() unlinks it so listen()
        # can succeed. On Windows this is a no-op.
        QLocalServer.removeServer(_socket_name())
        if not self._server.listen(_socket_name()):
            _log.warning(
                "single-instance: failed to bind socket %s: %s",
                _socket_name(), self._server.errorString(),
            )
            return
        self._server.newConnection.connect(self._on_new_connection)
        _log.info("single-instance: listening on %s", _socket_name())

    def _on_new_connection(self):
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        # Bind sock into the lambda so the slot has a stable reference
        # even if more peers connect before we finish reading this one.
        sock.readyRead.connect(lambda s=sock: self._read_payload(s))
        # Defensive cleanup: if the peer drops without sending anything
        # the QLocalSocket would otherwise leak until the server dies.
        sock.disconnected.connect(sock.deleteLater)

    def _read_payload(self, sock):
        # Wait for the 4-byte length header to be fully buffered.
        if sock.bytesAvailable() < 4:
            return  # readyRead will fire again
        header = bytes(sock.read(4))
        length = int.from_bytes(header, "big")
        if length <= 0 or length > _MAX_PAYLOAD_BYTES:
            _log.warning(
                "single-instance: invalid payload length %d", length,
            )
            sock.disconnectFromServer()
            return
        # Payload may not have arrived yet — wait once, then read
        # whatever's available. We tolerate a short read rather than
        # blocking the GUI for a full second on a wedged peer.
        if sock.bytesAvailable() < length:
            sock.waitForReadyRead(_SOCKET_TIMEOUT_MS)
        data = bytes(sock.read(length))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            _log.warning("single-instance: payload not valid UTF-8")
            sock.disconnectFromServer()
            return
        paths = [p for p in text.split("\0") if p.strip()]
        if paths:
            _log.info(
                "single-instance: received %d path(s) from second instance",
                len(paths),
            )
            self.new_paths.emit(paths)
        sock.disconnectFromServer()
