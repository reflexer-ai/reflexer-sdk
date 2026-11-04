"""A certificate authority and a server certificate for every name of the suite, made at run time, never kept."""
import datetime, ipaddress, os, ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _name(text):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])


def _issue(subject, issuer, public, signer, is_ca, names=()):
    """As strict verifiers require: identifier and usage extensions present."""
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer)).public_key(public)
               .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(hours=1))
               .not_valid_after(now + datetime.timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(public), critical=False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), critical=False)
               .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=is_ca, crl_sign=is_ca, content_commitment=False,
                                            key_encipherment=False, data_encipherment=False, key_agreement=False,
                                            encipher_only=False, decipher_only=False), critical=True))
    if names:
        alt = [x509.DNSName(name) for name in names] + [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        builder = builder.add_extension(x509.SubjectAlternativeName(alt), critical=False)
    return builder.sign(signer, hashes.SHA256())


def _authority(folder, label, names):
    authority = ec.generate_private_key(ec.SECP256R1())
    root = _issue(f"acceptance {label}", f"acceptance {label}", authority.public_key(), authority, True)
    key = ec.generate_private_key(ec.SECP256R1())
    server = _issue("acceptance server", f"acceptance {label}", key.public_key(), authority, False, names)
    ca, chain = os.path.join(folder, f"{label}-ca.pem"), os.path.join(folder, f"{label}-server.pem")
    with open(ca, "wb") as out:
        out.write(root.public_bytes(serialization.Encoding.PEM))
    with open(chain, "wb") as out:
        out.write(server.public_bytes(serialization.Encoding.PEM)
                  + key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca, chain


class Certs:
    """`ca`: the file every client under test trusts. `context()`: a server's. `untrusted()`: a server's nobody trusts."""

    def __init__(self, folder, names):
        everything = [*names, "localhost"]
        self.ca, self.chain = _authority(folder, "trusted", everything)
        _, self.bad_chain = _authority(folder, "untrusted", everything)

    def context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.chain)
        return context

    def untrusted(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.bad_chain)
        return context
