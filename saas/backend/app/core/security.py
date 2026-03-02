"""
Sécurité — JWT, hachage mot de passe, API Keys
"""
import hashlib
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Mots de passe ─────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(subject), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """Lève JWTError si invalide ou expiré."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ── API Keys ──────────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """
    Retourne (clé_complète, préfixe, hash_sha256).
    La clé complète n'est montrée qu'une seule fois à l'utilisateur.
    """
    prefix = "gc_live_"
    alphabet = string.ascii_letters + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(40))
    full_key = prefix + raw
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


# ── Upload sécurisé ────────────────────────────────────────────────────────────

MAGIC_BYTES: dict[str, bytes] = {
    "zip":     b"PK\x03\x04",
    "gpkg":    b"SQLite format 3",
    "geojson": b"{",       # Approximation — compléter avec validation JSON
    "kml":     b"<?xml",
    "dxf":     None,       # Texte — vérification par contenu
}


def validate_file_magic(content: bytes, extension: str) -> bool:
    """Vérifie les magic bytes du fichier uploadé pour contrer les uploads malveillants."""
    ext = extension.lower().lstrip(".")
    magic = MAGIC_BYTES.get(ext)
    if magic is None:
        return True  # Pas de magic bytes connus → on laisse passer (Shapefile, CSV…)
    return content[:len(magic)] == magic
