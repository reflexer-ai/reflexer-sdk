"""Real-looking names on this machine's loopback, and nothing beyond it, in the suite's process and its forks.

`socket.getaddrinfo` answers a name of the suite with an address in VIRTUAL that spells its stand-in's port, and
`socket.socket.connect` turns that address into the stand-in's. Any other name fails to resolve, and a connection to
anything off this machine raises: nothing here can reach a real provider. No SDK or HTTP library is touched.
"""
import errno, ipaddress, socket

VIRTUAL = "127.77."  # the first half of the address a name resolves to; the rest is the port

hosts = {}
real_getaddrinfo, real_connect, real_connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex


def is_literal(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    name = host.decode() if isinstance(host, bytes) else host
    if name is None or name == "localhost" or is_literal(name):
        return real_getaddrinfo(host, port, family, type, proto, flags)
    target = hosts.get(name.lower().rstrip("."))
    if target is None or family not in (0, socket.AF_INET):
        raise socket.gaierror(socket.EAI_NONAME, f"offline: {name} is not a name of the suite")
    address = f"{VIRTUAL}{target >> 8}.{target & 255}"
    number = port if isinstance(port, int) else 443
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, number))]


def real_address(sock, address):
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return address
    host, port = address[0], address[1]
    if not is_literal(host):
        host, port = getaddrinfo(host, port)[0][4]
    if host.startswith(VIRTUAL):
        high, low = host[len(VIRTUAL):].split(".")
        return ("127.0.0.1", int(high) << 8 | int(low))
    if not ipaddress.ip_address(host).is_loopback:
        raise OSError(errno.ENETUNREACH, f"offline: {host} is not on this machine")
    return (host, port) + tuple(address[2:])


def connect(self, address):
    return real_connect(self, real_address(self, address))


def connect_ex(self, address):
    return real_connect_ex(self, real_address(self, address))


def add(name, port):
    hosts[name.lower()] = port


def install():
    """Turns the resolver on. Twice is once."""
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = getaddrinfo, connect, connect_ex
