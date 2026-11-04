"""Stand-ins for reflexer and for a provider: real sockets, real TLS, made-up values. Each records what reached it.

`set(mode, ...)` says how a stand-in answers from then on, whatever is in flight. The modes:

    ok        reflexer: a served answer, with our headers. provider: its own answer.
    passed    reflexer only: a pass through, the provider's body with `answered-by: provider`.
    reply     any status, headers and body: `set("reply", status=503, headers={...}, body=...)`
    balancer  a load balancer's own answer: a 401 with none of our headers (`status=` for another)
    busy      reflexer's 503, marked its own, with `Retry-After` (`status=529` for Anthropic's)
    redirect  a 307 elsewhere, as relayed from a provider
    dead      nothing listens: connections are refused; the port stays its own, for no other case to take
    reset     accepts, records an arrival with no path, and resets: a dead stand-in whose attempts can be counted
    stall     reads the request and never answers; `Arrival.left_after` records when the client gave up
    drop      reads the request and closes with no answer
    cut       sends the headers and half a body, and closes
    garbage   answers bytes that are not HTTP
    badcert   TLS with a certificate nobody trusts

Any mode takes `delay=` (seconds before answering), `gzip=True` (compressed when the request accepts it, the SDKs'
default), `gap=` (seconds between a stream's events), `headers=` (added to the answer), `body=` (replaces it).
A request asking for a stream gets its format's events, unless the mode set a body: that is the stream mode.
"""
import gzip as gzip_module, http.server, json, select, socket, ssl, struct, threading, time
from urllib.parse import urlsplit

STALL_HOLD = 60.0  # seconds a stalled answer holds at most, past any case's limit
REQUEST_ID = "0190f0e0-0000-7000-8000-000000000000"
SERVED_COST = "12000"  # nano USD
SERVED_TEXT, STRAIGHT_TEXT = "served by reflexer", "from the provider"
SERVED_ID = "rfx-" + REQUEST_ID.replace("-", "")  # a served answer's id: the request id's hex
SERVED_MODEL = {"chat": "frontier-x-reflexer", "responses": "frontier-x-reflexer", "messages": "frontier-y-reflexer",
                "gemini": "frontier-z-reflexer"}
OURS = {"Reflexer-Request-Id": REQUEST_ID, "Reflexer-Answered-By": "reflexer", "Reflexer-Cost": SERVED_COST,
        "Reflexer-Status-Origin": "reflexer"}
PROVIDERS_THROUGH_US = {"Reflexer-Request-Id": REQUEST_ID, "Reflexer-Answered-By": "provider", "Reflexer-Cost": "0",
                        "Reflexer-Status-Origin": "provider"}
JSON = "application/json"
SSE = "text/event-stream"
REDIRECT_TARGET = "https://elsewhere.example/moved"
PRESETS = {"busy": {"status": 503, "headers": {"Reflexer-Status-Origin": "reflexer", "Retry-After": "0"}},
           "redirect": {"status": 307, "headers": PROVIDERS_THROUGH_US | {"location": REDIRECT_TARGET}, "body": b""}}


def wire_of(path):
    """Which format a request's path speaks; the same under reflexer's prefix."""
    path = urlsplit(path).path
    for ending, wire in (("/chat/completions", "chat"), ("/responses", "responses"), ("/messages", "messages"),
                         ("enerateContent", "gemini"), ("/v2/ask", "acme"), ("/models", "models")):
        if ending in path:
            return wire
    return "other"


def body_for(path, text, extra_usage=None):
    wire, usage = wire_of(path), extra_usage or {}
    if wire == "chat":
        return {"id": "chatcmpl-made-up", "object": "chat.completion", "created": 1, "model": "frontier-x",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4} | usage}
    if wire == "responses":
        return {"id": "resp_made_up", "object": "response", "created_at": 1, "model": "frontier-x", "status": "completed",
                "tool_choice": "auto", "tools": [], "parallel_tool_calls": False,
                "output": [{"type": "message", "id": "m", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": text, "annotations": []}]}],
                "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}} | usage}
    if wire == "messages":
        return {"id": "msg_made_up", "type": "message", "role": "assistant", "model": "frontier-y", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": text}], "usage": {"input_tokens": 3, "output_tokens": 1} | usage}
    if wire == "gemini":
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1, "totalTokenCount": 4} | usage}
    if wire == "acme":
        return {"text": text, "usage": {"in": 3, "out": 1} | usage}
    if wire == "models":
        return {"object": "list", "data": [], "models": [], "has_more": False, "first_id": None, "last_id": None}
    return {"ok": text}


def as_served(path, body):
    """A body, as reflexer writes a served answer: its id and model reflexer's, its price at `usage.cost`; on gemini, whose
    objects hold no price, the format's own names, the price in the headers."""
    wire = wire_of(path)
    if wire == "gemini":
        return body | {"responseId": SERVED_ID, "modelVersion": SERVED_MODEL["gemini"]}
    if wire in SERVED_MODEL:
        body = body | {"id": SERVED_ID, "model": SERVED_MODEL[wire]}
    if isinstance(body.get("usage"), dict):
        body = body | {"usage": body["usage"] | {"cost": int(SERVED_COST) / 10**9}}
    return body


def events_for(path, text, served=False):
    """A stream's events, in the request's format, as bytes each."""
    wire = wire_of(path)
    made = (lambda body: as_served(path, body)) if served else (lambda body: body)
    if wire == "messages":
        steps = [("message_start", {"type": "message_start", "message": made(body_for(path, "")) | {"content": [], "stop_reason": None}}),
                 ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                 ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
                 ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                 ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                                    "usage": made(body_for(path, ""))["usage"]}),
                 ("message_stop", {"type": "message_stop"})]
        return [f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in steps]
    if wire == "gemini":
        return [f"data: {json.dumps(made(body_for(path, part)))}\n\n".encode() for part in (text[:4], text[4:])]
    if wire == "responses":
        whole = made(body_for(path, text))
        steps = [("response.created", {"type": "response.created", "sequence_number": 0,
                                       "response": whole | {"status": "in_progress", "output": []}}),
                 ("response.output_text.delta", {"type": "response.output_text.delta", "sequence_number": 1, "item_id": "m",
                                                 "output_index": 0, "content_index": 0, "delta": text, "logprobs": []}),
                 ("response.completed", {"type": "response.completed", "sequence_number": 2, "response": whole})]
        return [f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in steps]
    whole = made(body_for("/chat/completions", ""))
    first, second = [{"id": whole["id"], "object": "chat.completion.chunk", "created": 1, "model": whole["model"],
                      "choices": [{"index": 0, "delta": {"role": "assistant", "content": part}, "finish_reason": None}]}
                     for part in (text[:4], text[4:])]
    second["usage"] = whole["usage"]  # sent unasked: whether reflexer heeds a client's `include_usage` is reflexer's to say
    return [f"data: {json.dumps(first)}\n\n".encode(), f"data: {json.dumps(second)}\n\n".encode(), b"data: [DONE]\n\n"]


def asks_stream(path, body):
    if "streamGenerateContent" in path:
        return True
    try:
        return json.loads(body or b"{}").get("stream") is True
    except (ValueError, AttributeError):
        return False


class Arrival:
    """One request as it reached a stand-in."""

    def __init__(self, host, method, path, headers, body):
        self.host, self.method, self.path, self.headers, self.body = host, method, path, headers, body
        self.at, self.left_after, self.gzipped = time.monotonic(), None, False

    def __repr__(self):
        return f"{self.method} {self.host}{self.path}"


def bound(port):
    """A socket on this port of the loopback. Bound beside its listener, one that never listens holds the port while the
    stand-in is dead: a call is refused, and no bind(0) is handed it, so no other case's stand-in takes its calls.
    `SO_REUSEPORT` lets the two share it for the moment one replaces the other, so the port is never free."""
    made = socket.socket()
    made.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    made.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    made.bind(("127.0.0.1", port))
    return made


class Standin:
    def __init__(self, name, context=None, untrusted=None, is_reflexer=False):
        self.name, self.context, self.untrusted, self.is_reflexer = name, context, untrusted, is_reflexer
        self.seen, self.connections = [], set()
        self.mode, self.params = "ok", {}
        self.listener = None
        self._listen(0)

    def set(self, mode="ok", **params):
        """A mode for every request from now on; the old connections are cut when nothing may answer on them."""
        was_dead = self.mode == "dead"
        if mode in PRESETS:
            mode, params = "reply", PRESETS[mode] | params
        self.mode, self.params = mode, params
        if mode in ("dead", "reset", "badcert"):
            self._cut_connections()
        if mode == "dead" and not was_dead:
            self.holder = bound(self.port)  # the port stays this stand-in's: a port let go, another case's bind(0) gets
            self._close()
        if mode != "dead" and was_dead:
            self._listen(self.port)
            self.holder.close()

    def message_arrivals(self):
        """The message calls that reached it, and the attempts `reset` counted; not a listing of models."""
        return [a for a in self.seen if a.path is None or wire_of(a.path) in ("chat", "responses", "messages", "gemini", "acme")]

    def _listen(self, port):
        self.listener = bound(port)
        self.listener.listen(256)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, args=(self.listener,), daemon=True).start()

    def _close(self):
        try:
            self.listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.listener.close()

    def _cut_connections(self):
        for connection in list(self.connections):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _accept(self, listener):
        while True:
            try:
                connection, address = listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(connection, address), daemon=True).start()

    def _serve(self, connection, address):
        self.connections.add(connection)
        try:
            if self.mode == "reset":
                self.seen.append(Arrival(self.name, "CONNECT", None, {}, b""))
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                return
            if self.context is not None:
                self.connections.discard(connection)
                context = self.untrusted if self.mode == "badcert" else self.context
                connection = context.wrap_socket(connection, server_side=True)  # detaches the plain socket
                self.connections.add(connection)
            Handler(connection, address, self)
        except (OSError, ssl.SSLError, ValueError):
            pass
        finally:
            self.connections.discard(connection)
            try:
                connection.close()
            except OSError:
                pass

    def answer(self, handler, arrival):
        mode, params = self.mode, self.params
        if mode in ("dead", "reset", "badcert"):  # on a connection opened before: nothing answers on it
            handler.close_connection = True
            return None
        if params.get("delay"):
            time.sleep(params["delay"])
        if mode == "stall":
            return self._hold(handler, arrival)
        if mode == "drop":
            handler.close_connection = True
            return None
        if mode == "garbage":
            handler.wfile.write(b"this is not http\r\n\r\n")
            handler.close_connection = True
            return None
        status, headers, body = self._made(arrival, mode, params)
        wants_stream = asks_stream(arrival.path, arrival.body)
        if wants_stream and status < 300 and "body" not in params:
            return handler.stream(status, headers, events_for(arrival.path, self._text(mode), self.is_served(mode)), params)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        if mode == "cut":
            return handler.cut(status, headers, data)
        return handler.reply(status, headers, data, params)

    def is_served(self, mode):
        return self.is_reflexer and mode == "ok"

    def _text(self, mode):
        return SERVED_TEXT if self.is_reflexer and mode != "passed" else STRAIGHT_TEXT

    def _made(self, arrival, mode, params):
        status = params.get("status", 200)
        ours = {}
        if self.is_reflexer and mode != "reply":
            ours = PROVIDERS_THROUGH_US if mode == "passed" else OURS
        headers = dict(ours) | params.get("headers", {})
        body = params["body"] if "body" in params else body_for(arrival.path, self._text(mode), params.get("usage"))
        if self.is_served(mode) and "body" not in params:
            body = as_served(arrival.path, body)
        return status, headers, body

    def _hold(self, handler, arrival):
        """Reads nothing more and answers nothing, until the client leaves."""
        connection = handler.connection
        started = time.monotonic()
        while time.monotonic() - started < STALL_HOLD:
            readable, _, _ = select.select([connection], [], [], 0.02)
            if readable:
                try:
                    if not connection.recv(1):
                        break
                except (OSError, ssl.SSLError):
                    break
            if self.mode != "stall":  # the outage is over: a call still waiting is cut
                break
        arrival.left_after = time.monotonic() - started
        handler.close_connection = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True  # or each answer's head and body wait on a delayed ACK

    def __init__(self, sock, address, standin):
        self.standin = standin
        super().__init__(sock, address, None)

    def _read_body(self):
        if "chunked" in self.headers.get("transfer-encoding", "").lower():
            parts = []
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                parts.append(self.rfile.read(size))
                self.rfile.readline()
                if size == 0:
                    return b"".join(parts)
        return self.rfile.read(int(self.headers.get("content-length", 0)))

    def _any(self):
        body = self._read_body()
        headers = {name.lower(): value for name, value in self.headers.items()}
        self.arrival = arrival = Arrival(headers.get("host", ""), self.command, self.path, headers, body)
        self.standin.seen.append(arrival)
        self.standin.answer(self, arrival)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _any

    def _head(self, status, headers, content_type, length=None):
        self.send_response(status)
        self.send_header("content-type", headers.pop("content-type", content_type))
        if length is not None:
            self.send_header("content-length", str(length))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()

    def _accepts_gzip(self):
        return "gzip" in self.headers.get("accept-encoding", "")

    def reply(self, status, headers, data, params=None):
        headers = dict(headers)
        if (params or {}).get("gzip") and self._accepts_gzip():
            data = gzip_module.compress(data)
            headers["content-encoding"] = "gzip"
            self.arrival.gzipped = True
        self._head(status, headers, JSON, len(data))
        self.wfile.write(data)
        self.wfile.flush()

    def stream(self, status, headers, events, params):
        self._head(status, dict(headers), SSE)
        self.close_connection = True  # a stream ends with its connection
        for event in events:
            self.wfile.write(event)
            self.wfile.flush()
            if params.get("gap"):
                time.sleep(params["gap"])

    def cut(self, status, headers, data):
        self._head(status, dict(headers), JSON, len(data))
        self.wfile.write(data[:len(data) // 2])
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, *args):
        pass


class Proxy:
    """A forward proxy the client may point at: CONNECT tunnels to the harness's names; a plain request it answers
    itself, as one on the far side of a network would: it cannot reach this machine's loopback."""

    def __init__(self):
        self.tunnels, self.plain = [], []
        proxy = self

        class ProxyHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_CONNECT(self):
                proxy.tunnels.append(self.path.split(":")[0])
                host, port = self.path.rsplit(":", 1)
                try:
                    far = socket.create_connection((host, int(port)))
                except OSError:
                    self.send_error(502)
                    return
                self.send_response(200)
                self.end_headers()
                self.close_connection = True
                pump(self.connection, far)

            def _plain(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                headers = {name.lower(): value for name, value in self.headers.items()}
                proxy.plain.append(Arrival(urlsplit(self.path).hostname, self.command, self.path, headers, body))
                on_this_machine = urlsplit(self.path).hostname in ("127.0.0.1", "localhost", "::1")
                data = b'{"error": "the proxy cannot reach it"}' if on_this_machine else json.dumps(body_for(self.path, "through the proxy")).encode()
                self.send_response(502 if on_this_machine else 200)
                self.send_header("content-type", JSON)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _plain

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def pump(one, other):
    def copy(source, target):
        try:
            while data := source.recv(65536):
                target.sendall(data)
        except OSError:
            pass
        for end in (source, target):
            try:
                end.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    threading.Thread(target=copy, args=(other, one), daemon=True).start()
    copy(one, other)
