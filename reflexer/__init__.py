"""Reflexer's SDK: which calls go to reflexer, and what happens when it fails. It changes no answer.

Standard library only. Every decision is here, on plain values (a URL, headers, a status), with no I/O;
`transport.setup_http_client` plugs it into the HTTP client the client already has, so every dependency is the client's,
none is ours.

Where can my key go? `Reflexer.route`, then `transport.Through`. What happens when reflexer fails? `transport.Through`.
"""
import base64, hashlib, ipaddress, json, logging, random, re, time
from importlib.metadata import version as installed  # its one function the SDK reads: no other loads a module
from urllib.parse import urlsplit

BASE = "https://api.reflexer.ai"
SKIP = "reflexer-skip"  # a header the client sets on one call: "true" skips reflexer, "false" does not; it never leaves
NOT_A_SKIP = "the Reflexer-Skip header must be true or false: true sends the call directly to the provider, false lets the call go through reflexer"
OURS = "reflexer-"  # what starts each header of ours: none leaves for a provider
NAMESPACE = "reflexer-namespace"  # the one header of ours a client may give reflexer

log = logging.getLogger("reflexer")


class Reflexer:
    """One client's way to reflexer, for one wire format, from a provider file's data: `reflexer_path`, reflexer's path
    for the format; `provider`, the provider's own address, to which no upstream is named; `calls`, the path
    of the calls that return a model's message, the only ones that go to reflexer; `routers`, optional, by host, the wire
    of a router with a route of its own at reflexer, taken for the calls it lists."""

    def __init__(self, key, wire, base=BASE, sample=1.0, clock=time.monotonic, namespace=None):
        check(key)
        if namespace is not None and not (isinstance(namespace, str) and re.fullmatch(r"[!-~]+(?: [!-~]+)*", namespace)):
            raise ValueError("a namespace may contain only ASCII letters, digits and signs, and single spaces between them, because the SDK sends it in a header")
        if isinstance(sample, bool) or not isinstance(sample, (int, float)) or not 0 <= sample <= 1:  # nan is neither
            raise ValueError("sample must be a number from 0 to 1: the share of calls that the SDK sends to reflexer")
        self.key, self.base, self.sample, self.namespace = key, checked_base(base), sample, namespace
        self.way = way(wire)  # a typo in a provider file raises here, as the client is made, never on a call
        self.routers = {host: way(router) for host, router in wire.get("routers", {}).items()}
        self.breaker = Breaker(clock)

    def route(self, url, headers, replay=False):
        """The call as it goes to reflexer, (url, headers); or None, and it goes straight to the provider.
        It carries all the client's headers, its provider's key among them, and its query: reflexer passes them on,
        and stores no key. A replay has nowhere else to go, so neither sampling nor the breaker turns it away."""
        turned_away = random.random() >= self.sample or self.breaker.is_open()  # noqa: S311 a share of calls, no secret
        if skips(headers.get(SKIP)) or (turned_away and not replay):
            return None
        address = urlsplit(url)
        router = self.routers.get(address.hostname)
        reflexer_path, provider, calls = router if router and re.search(router[2], address.path) else self.way
        call = re.search(calls, address.path)
        if not call or not reachable(address):
            return None
        host = address.netloc.rpartition("@")[2]  # no user or password of the URL's goes to reflexer
        upstream = f"{address.scheme}://{host}{address.path[:call.start()]}"  # its provider, a router, a runner
        ours = {"reflexer-key": self.key}
        if upstream != provider:
            ours["reflexer-upstream"] = upstream
        theirs = {name: value for name, value in headers.items()
                  if name != "host" and (name == NAMESPACE or not name.startswith(OURS))}  # no header of a client's steers us
        to = f"{self.base}{reflexer_path}{address.path[call.start():]}"
        if address.query:
            to += f"?{address.query}"
        given = {NAMESPACE: self.namespace} if self.namespace else {}  # a call's own namespace header wins
        return to, given | theirs | ours

    def goes_straight(self, status, headers):
        """Whether the call goes straight to the provider, given reflexer's response."""
        straight_for = whole(headers.get("reflexer-straight"))
        meaning = read(status, headers.get("reflexer-status-origin"), straight_for)
        self.breaker.note(meaning, straight_for)
        if meaning == GRACE:
            log.warning("the reflexer key is revoked; the SDK sends calls directly to the provider until the key's grace period ends")
        return meaning != ANSWER

    def failed(self, failure):
        """The call to reflexer raised: it goes straight. Only the kind of failure is logged, never its text."""
        log.warning("the call to reflexer failed (%s); the SDK sends the call directly to the provider", type(failure).__name__)
        self.breaker.note(FAILED, None)


def skips(value):
    """Whether the client's `Reflexer-Skip` header skips reflexer for this call, by its value in any case and without the
    whitespace around it, which is not part of a header's value (RFC 9110 5.5): "true" does, "false" does not, and no
    header does not. Any other value raises, before anything is sent (fail loud)."""
    if value is None:
        return False
    value = (value.decode() if isinstance(value, bytes) else value).strip(" \t").lower()
    if value not in ("true", "false"):
        raise ValueError(NOT_A_SKIP)
    return value == "true"


def way(wire):
    """A wire's (reflexer_path, provider, calls)."""
    return wire["reflexer_path"], wire.get("provider"), wire["calls"]


REPLAY = "replay_response"  # a body's field: the caller's answer takes the provider's place


class ReplayNotTaken(Exception):
    """A replay bypasses the provider: when reflexer cannot take it, it fails, and goes nowhere else."""


def is_replay(body):
    """Whether a request's body holds the field at its top. Only a body that may name it, plainly or escaped, is parsed."""
    if REPLAY.encode() not in body and b"\\u" not in body:
        return False
    try:
        data = json.loads(body)
    except ValueError:
        return False
    return isinstance(data, dict) and REPLAY in data


# What reflexer's response to a call means
ANSWER = "an answer"  # for the client
FAILED = "failed"  # straight, and counted by the breaker
ASKED = "asked"  # straight, not counted
GRACE = "grace"  # straight, not counted, with a warning


def read(status, origin, straight_for):
    """What a response means: its status, whose doing it is, and whether it says to go straight."""
    overloaded = status == 429 or status >= 500
    if origin is None:  # none of our headers: the load balancer's own
        return FAILED
    if origin == "connection" or 300 <= status < 400:  # reflexer could not reach the provider, or a redirect to follow
        return ASKED
    if origin != "reflexer" or status < 400:  # served, passed through, or the provider's own error
        return ANSWER
    if straight_for is None:  # reflexer's "not now", or an error the client's SDK raises, naming our key
        return FAILED if overloaded else ANSWER
    return ASKED if overloaded else GRACE  # reflexer's "not now, for this long", or a key revoked less than a day ago


# The breaker, provisional values: a minute or so at most, in exponential backoff with jitter
BACKOFF = 1.0  # seconds after a first failure of reflexer's; doubled at each one in a row
BACKOFF_CAP = 60.0
JITTER = 0.2  # each wait stretched by up to this share of it, at most of the cap, so clients do not come back together
OBEYED_AFTER = 2  # responses in a row carrying `Reflexer-Straight`: one server alone sends no one away


class Breaker:
    """When every call goes straight, whatever it is: after reflexer's failures, or when told to.
    No lock: threads racing here cost a wait a little off, nothing else."""

    def __init__(self, clock):
        self.clock = clock
        self.backoff = BACKOFF
        self.told_in_a_row = 0
        self.open_until = 0.0

    def is_open(self):
        return self.clock() < self.open_until

    def note(self, meaning, straight_for):
        self.told_in_a_row = 0 if straight_for is None else self.told_in_a_row + 1
        if self.told_in_a_row >= OBEYED_AFTER:
            self.open_for(straight_for)
        if meaning == ANSWER:
            self.backoff = BACKOFF
        if meaning == FAILED and not self.is_open():  # calls already in flight when it failed count once
            self.open_for(self.backoff)
            self.backoff = min(BACKOFF_CAP, self.backoff * 2)

    def open_for(self, seconds):
        wait = seconds + random.uniform(0, JITTER * min(seconds, BACKOFF_CAP))  # noqa: S311 a spread of waits, no secret
        self.open_until = max(self.open_until, self.clock() + wait)


def whole(value):
    """A header's whole number, or None for a value reflexer did not send, and so ignored."""
    return int(value) if re.fullmatch("[0-9]{1,18}", value or "") else None


def reachable(address):
    """Whether reflexer can pass through to this split URL: public https only."""
    host = address.hostname.rstrip(".")
    if address.scheme != "https" or host == "localhost":
        return False
    try:
        return ipaddress.ip_address(numeric(host)).is_global
    except ValueError:  # a name: reflexer resolves and checks it
        return True


def numeric(host):
    """The host as the system's resolver reads it: an IPv4 address in any notation inet_aton takes (`10.1`, `167772161`,
    `0x0a000001`, `0300.0250.0.1`) as its number; anything else (a name, IPv6) as it is."""
    forms = [re.fullmatch("(0[xX][0-9a-fA-F]+)|(0[0-7]*)|([1-9][0-9]*)", part) for part in host.split(".")]
    if len(forms) > 4 or not all(forms):
        return host
    *high, low = [int(form[0], (16, 8, 10)[form.lastindex - 1]) for form in forms]
    if any(part > 255 for part in high) or low >= 256 ** (4 - len(high)):
        return host
    return sum(part << 8 * (3 - at) for at, part in enumerate(high)) + low


def checked_base(base):
    """Reflexer's address, which gets the key: https, or plain http on this machine for a stand-in."""
    address = urlsplit(base)
    if address.scheme != "https" and address.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError(f"reflexer's address must use https, to protect the key: {base}")
    return base.rstrip("/")


def check(key):
    """A key not of the form raises before anything is sent."""
    form = re.fullmatch(r"(rfx1_[a-z2-7]{7}_[a-z2-7]{52})_([a-z2-7]{7})", key or "")
    if not form or form[2] != checksum(form[1]):
        raise ValueError("this is not a reflexer key: a reflexer key has the form rfx1_CLIENT_SECRET_CHECK, as given at onboarding")


def checksum(text):
    return base64.b32encode(hashlib.sha256(text.encode()).digest()[:4]).decode().lower().rstrip("=")


def supported(package, majors):
    """A provider file runs only on the majors of its SDK it was tested on: a new major raises at import, never misroutes."""
    version = installed(package)
    if int(version.split(".")[0]) not in majors:
        raise ImportError(f"reflexer is tested on {package} {majors}, not {version}")
