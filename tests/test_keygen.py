import os
import sys
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import generate_keypair, generate_psk


class TestGenerateKeypair:
    def test_returns_private_and_public(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, str)
        assert isinstance(pub, str)

    def test_keys_are_base64_44_chars(self):
        priv, pub = generate_keypair()
        assert len(priv) == 44
        assert len(pub) == 44
        base64.b64decode(priv)
        base64.b64decode(pub)

    def test_keypairs_are_unique(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestGeneratePsk:
    def test_returns_base64_string(self):
        psk = generate_psk()
        assert len(psk) == 44
        base64.b64decode(psk)

    def test_psks_are_unique(self):
        psk1 = generate_psk()
        psk2 = generate_psk()
        assert psk1 != psk2
