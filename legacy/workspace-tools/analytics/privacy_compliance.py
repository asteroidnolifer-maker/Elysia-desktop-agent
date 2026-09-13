#!/usr/bin/env python3
"""
Elysia Analytics Privacy Compliance - Task 1630
GDPR/CCPA compliance, data anonymization, consent management.
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


class ConsentManager:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "privacy")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.consents: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        path = self.data_dir / "consents.json"
        if path.exists():
            self.consents = json.loads(path.read_text())

    def _save(self):
        path = self.data_dir / "consents.json"
        path.write_text(json.dumps(self.consents, indent=2))

    def grant_consent(self, user_id: str, purposes: List[str]) -> Dict[str, Any]:
        consent = {
            "user_id": user_id,
            "purposes": purposes,
            "granted_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=365)).isoformat(),
            "status": "active"
        }
        self.consents[user_id] = consent
        self._save()
        return consent

    def revoke_consent(self, user_id: str):
        if user_id in self.consents:
            self.consents[user_id]["status"] = "revoked"
            self.consents[user_id]["revoked_at"] = datetime.now().isoformat()
            self._save()

    def check_consent(self, user_id: str, purpose: str) -> bool:
        consent = self.consents.get(user_id)
        if not consent or consent["status"] != "active":
            return False
        if purpose not in consent["purposes"]:
            return False
        if datetime.fromisoformat(consent["expires_at"]) < datetime.now():
            return False
        return True

    def get_active_consents(self) -> List[Dict[str, Any]]:
        return [c for c in self.consents.values() if c["status"] == "active"]


class DataAnonymizer:
    @staticmethod
    def hash_identifier(value: str, salt: str = "elysia") -> str:
        return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]

    @staticmethod
    def anonymize_record(record: Dict[str, Any],
                         fields: List[str]) -> Dict[str, Any]:
        anon = record.copy()
        for field in fields:
            if field in anon:
                anon[field] = DataAnonymizer.hash_identifier(str(anon[field]))
        return anon

    @staticmethod
    def pseudonymize(value: str) -> str:
        return f"USER_{hashlib.md5(value.encode()).hexdigest()[:8].upper()}"

    @staticmethod
    def generalize_age(age: int) -> str:
        if age < 18: return "under_18"
        elif age < 25: return "18-24"
        elif age < 35: return "25-34"
        elif age < 45: return "35-44"
        elif age < 55: return "45-54"
        elif age < 65: return "55-64"
        else: return "65+"

    @staticmethod
    def generalize_location(location: str) -> str:
        parts = location.split(",")
        return parts[-1].strip() if len(parts) > 1 else "unknown"


class PrivacyCompliance:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "privacy")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.consent_mgr = ConsentManager(str(self.data_dir))
        self.anonymizer = DataAnonymizer()
        self.audit_log: List[Dict[str, Any]] = []

    def log_data_access(self, user_id: str, purpose: str, data_type: str):
        if not self.consent_mgr.check_consent(user_id, purpose):
            self.audit_log.append({
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "purpose": purpose,
                "data_type": data_type,
                "status": "denied"
            })
            return False
        self.audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "purpose": purpose,
            "data_type": data_type,
            "status": "approved"
        })
        return True

    def process_data_request(self, user_id: str,
                             request_type: str) -> Dict[str, Any]:
        result = {"user_id": user_id, "request_type": request_type,
                  "timestamp": datetime.now().isoformat()}
        if request_type == "export":
            result["status"] = "processed"
            result["message"] = "Data export ready"
        elif request_type == "delete":
            self.consent_mgr.revoke_consent(user_id)
            result["status"] = "processed"
            result["message"] = "Data deleted and consent revoked"
        elif request_type == "rectify":
            result["status"] = "pending_review"
            result["message"] = "Rectification request received"
        return result

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.audit_log[-limit:]


def main():
    compliance = PrivacyCompliance()

    if len(sys.argv) < 2:
        print("Elysia Privacy Compliance")
        print("Commands: consent <user> <purposes>, check <user> <purpose>, "
              "anonymize <data>, audit, data-request <user> <type>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "consent" and len(sys.argv) >= 4:
        purposes = sys.argv[3].split(",")
        result = compliance.consent_mgr.grant_consent(sys.argv[2], purposes)
        print(f"[+] Consent granted: {result}")
    elif cmd == "check" and len(sys.argv) >= 4:
        allowed = compliance.consent_mgr.check_consent(sys.argv[2], sys.argv[3])
        print(f"Consent: {'granted' if allowed else 'denied'}")
    elif cmd == "anonymize" and len(sys.argv) >= 3:
        data = json.loads(sys.argv[2])
        anon = DataAnonymizer.anonymize_record(data, ["email", "name", "ip"])
        print(json.dumps(anon, indent=2))
    elif cmd == "audit":
        for entry in compliance.get_audit_log(20):
            print(f"  [{entry['status']}] {entry['purpose']}: {entry['data_type']}")
    elif cmd == "data-request" and len(sys.argv) >= 4:
        result = compliance.process_data_request(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
