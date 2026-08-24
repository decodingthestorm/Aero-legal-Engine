from legal_engine.api.security import hash_password, verify_password


class TestPasswordHashing:
    def test_roundtrips(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed) is True

    def test_wrong_password_is_rejected(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password("wrong password", hashed) is False

    def test_hash_is_not_the_plaintext_password(self):
        hashed = hash_password("correct horse battery staple")
        assert "correct horse battery staple" not in hashed

    def test_two_hashes_of_the_same_password_differ(self):
        """Random per-call salt — otherwise identical passwords would
        produce identical hashes, leaking which users share a password."""
        first = hash_password("same password")
        second = hash_password("same password")
        assert first != second
        assert verify_password("same password", first) is True
        assert verify_password("same password", second) is True

    def test_hash_is_self_describing(self):
        hashed = hash_password("correct horse battery staple")
        algorithm, iterations, salt_hex, digest_hex = hashed.split("$")
        assert algorithm == "pbkdf2_sha256"
        assert int(iterations) > 0
        bytes.fromhex(salt_hex)
        bytes.fromhex(digest_hex)

    def test_malformed_hash_is_rejected_not_raised(self):
        assert verify_password("anything", "not-a-real-hash") is False
        assert verify_password("anything", "pbkdf2_sha256$notanumber$aa$bb") is False
        assert verify_password("anything", "bcrypt$12$salt$hash") is False
