#!/usr/bin/env python3
"""
Password Tool for Elysia Pentesting
Password strength testing and hash cracking.
"""
import hashlib
import hmac
import os
import sys
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from itertools import product
import string


class PasswordStrengthTester:
    """Test password strength and estimate crack time."""

    def __init__(self):
        self.common_passwords = [
            "password", "123456", "12345678", "qwerty", "abc123",
            "monkey", "master", "dragon", "login", "princess",
            "football", "shadow", "sunshine", "trustno1", "iloveyou"
        ]

    def test_strength(self, password: str) -> Dict[str, Any]:
        """Test password strength."""
        score = 0
        feedback = []

        # Length check
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if len(password) >= 16:
            score += 1
        else:
            feedback.append("Use at least 12 characters")

        # Character variety
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in string.punctuation for c in password)

        if has_upper:
            score += 1
        if has_lower:
            score += 1
        if has_digit:
            score += 1
        if has_special:
            score += 1

        if not has_upper:
            feedback.append("Add uppercase letters")
        if not has_lower:
            feedback.append("Add lowercase letters")
        if not has_digit:
            feedback.append("Add numbers")
        if not has_special:
            feedback.append("Add special characters")

        # Common password check
        if password.lower() in self.common_passwords:
            score = 0
            feedback.append("This is a commonly used password - avoid it!")

        # Sequential/repeated characters
        sequential = sum(1 for i in range(len(password)-1) if ord(password[i+1]) - ord(password[i]) == 1)
        if sequential > 2:
            score -= 1
            feedback.append("Avoid sequential characters (abc, 123)")

        repeated = len(password) - len(set(password))
        if repeated > len(password) * 0.3:
            score -= 1
            feedback.append("Too many repeated characters")

        # Calculate entropy
        charset_size = 0
        if has_upper:
            charset_size += 26
        if has_lower:
            charset_size += 26
        if has_digit:
            charset_size += 10
        if has_special:
            charset_size += 32
        if charset_size == 0:
            charset_size = 26

        entropy = len(password) * (charset_size.bit_length())

        # Estimate crack time
        guesses_per_second = 1e10  # 10 billion guesses/sec (modern GPU)
        total_combinations = charset_size ** len(password)
        seconds_to_crack = total_combinations / guesses_per_second / 2

        strength_levels = ["Very Weak", "Weak", "Fair", "Strong", "Very Strong"]
        strength_index = min(score // 2, len(strength_levels) - 1)

        return {
            "password_length": len(password),
            "score": max(0, min(score, 8)),
            "strength": strength_levels[strength_index],
            "entropy": entropy,
            "estimated_crack_time": self._format_time(seconds_to_crack),
            "feedback": feedback,
            "checks": {
                "length_8": len(password) >= 8,
                "length_12": len(password) >= 12,
                "has_uppercase": has_upper,
                "has_lowercase": has_lower,
                "has_digit": has_digit,
                "has_special": has_special,
                "not_common": password.lower() not in self.common_passwords
            }
        }

    def _format_time(self, seconds: float) -> str:
        """Format seconds into human-readable time."""
        if seconds < 1:
            return "Instantly"
        elif seconds < 60:
            return f"{seconds:.0f} seconds"
        elif seconds < 3600:
            return f"{seconds/60:.0f} minutes"
        elif seconds < 86400:
            return f"{seconds/3600:.0f} hours"
        elif seconds < 86400 * 365:
            return f"{seconds/86400:.0f} days"
        else:
            return f"{seconds/86400/365:.0e} years"


class HashCracker:
    """Hash cracker for pentesting (educational purposes)."""

    def __init__(self):
        self.supported_hashes = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
            "sha512": hashlib.sha512
        }

    def crack_dict_attack(self, hash_value: str, hash_type: str,
                          wordlist_path: str) -> Optional[str]:
        """Dictionary attack using a wordlist."""
        if hash_type not in self.supported_hashes:
            print(f"[-] Unsupported hash type: {hash_type}")
            return None

        hash_func = self.supported_hashes[hash_type]
        print(f"[*] Starting dictionary attack ({hash_type})...")

        try:
            with open(wordlist_path, "r", encoding="utf-8", errors="ignore") as f:
                for i, word in enumerate(f):
                    word = word.strip()
                    if hash_func(word.encode()).hexdigest() == hash_value:
                        print(f"[+] Found! Password: {word}")
                        print(f"    Attempts: {i + 1}")
                        return word

                    if i % 100000 == 0 and i > 0:
                        print(f"    Attempted {i} passwords...")

        except FileNotFoundError:
            print(f"[-] Wordlist not found: {wordlist_path}")
            return None

        print("[-] Password not found in wordlist")
        return None

    def crack_bruteforce(self, hash_value: str, hash_type: str,
                         max_length: int = 6) -> Optional[str]:
        """Brute force attack (for short passwords only)."""
        if hash_type not in self.supported_hashes:
            print(f"[-] Unsupported hash type: {hash_type}")
            return None

        hash_func = self.supported_hashes[hash_type]
        charset = string.ascii_lowercase + string.digits
        print(f"[*] Starting brute force attack (max length: {max_length})...")

        attempts = 0
        for length in range(1, max_length + 1):
            print(f"    Trying length {length}...")
            for combo in product(charset, repeat=length):
                password = "".join(combo)
                attempts += 1

                if hash_func(password.encode()).hexdigest() == hash_value:
                    print(f"[+] Found! Password: {password}")
                    print(f"    Attempts: {attempts}")
                    return password

        print(f"[-] Not found after {attempts} attempts")
        return None

    def generate_hash(self, text: str, hash_type: str) -> str:
        """Generate hash for text."""
        if hash_type not in self.supported_hashes:
            return f"Unsupported hash type: {hash_type}"

        return self.supported_hashes[hash_type](text.encode()).hexdigest()

    def verify_hash(self, text: str, hash_value: str, hash_type: str) -> bool:
        """Verify text matches hash."""
        return self.generate_hash(text, hash_type) == hash_value


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Password Tool for Pentesting")
        print("=" * 40)
        print("\nCommands:")
        print("  test <password>           - Test password strength")
        print("  hash <text> <type>        - Generate hash")
        print("  verify <text> <hash> <type> - Verify hash")
        print("  crack <hash> <type> <wordlist> - Dictionary attack")
        print("\nHash types: md5, sha1, sha256, sha512")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "test" and len(sys.argv) >= 3:
        tester = PasswordStrengthTester()
        result = tester.test_strength(sys.argv[2])
        print(f"\nPassword Strength Analysis:")
        print(f"  Length: {result['password_length']}")
        print(f"  Score: {result['score']}/8")
        print(f"  Strength: {result['strength']}")
        print(f"  Entropy: {result['entropy']} bits")
        print(f"  Crack Time: {result['estimated_crack_time']}")
        if result["feedback"]:
            print(f"\n  Feedback:")
            for f in result["feedback"]:
                print(f"    - {f}")

    elif cmd == "hash" and len(sys.argv) >= 4:
        cracker = HashCracker()
        h = cracker.generate_hash(sys.argv[2], sys.argv[3])
        print(f"\n{sys.argv[3].upper()}: {h}")

    elif cmd == "verify" and len(sys.argv) >= 5:
        cracker = HashCracker()
        match = cracker.verify_hash(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"\nMatch: {'YES' if match else 'NO'}")

    elif cmd == "crack" and len(sys.argv) >= 5:
        cracker = HashCracker()
        cracker.crack_dict_attack(sys.argv[2], sys.argv[3], sys.argv[4])

    else:
        print("Unknown command. Run without args for help.")


if __name__ == "__main__":
    main()
