"""Autentikacija i upravljanje sesijama.

Lozinke se pohranjuju kao PBKDF2-HMAC-SHA256 sažetak sa slučajnom soli, čime se
izbjegava ranjivost običnog SHA-256 sažetka na napade unaprijed izračunatim
tablicama (rainbow tables).

Prijava se ne čuva u localStorageu nego u HttpOnly kolačiću koji sadrži slučajni
token sesije pohranjen u bazi.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Response

from config import PBKDF2_ITERATIONS, SESSION_HOURS
from database import get_connection

COOKIE_NAME = "sql_tutor_session"


# ---------------------------------------------------------------------------
# Lozinke
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Vraća zapis oblika 'pbkdf2_sha256$iteracije$sol$sažetak'."""
    sol = os.urandom(16)
    sazetak = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), sol, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${sol.hex()}${sazetak.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Provjerava lozinku uz usporedbu otpornu na vremenske napade."""
    try:
        algoritam, iteracije, sol_hex, sazetak_hex = stored.split("$")
    except ValueError:
        return False

    if algoritam != "pbkdf2_sha256":
        return False

    izracunato = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(sol_hex),
        int(iteracije),
    )
    return hmac.compare_digest(izracunato.hex(), sazetak_hex)


# ---------------------------------------------------------------------------
# Sesije
# ---------------------------------------------------------------------------
def create_session(user_id: int, response: Response) -> str:
    """Stvara novu sesiju i postavlja kolačić na odgovoru."""
    token = secrets.token_urlsafe(32)
    istek = datetime.now() + timedelta(hours=SESSION_HOURS)

    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, istek.isoformat()),
    )
    conn.commit()
    conn.close()

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )
    return token


def destroy_session(token: Optional[str], response: Response) -> None:
    if token:
        conn = get_connection()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    response.delete_cookie(COOKIE_NAME, path="/")


def purge_expired_sessions() -> None:
    conn = get_connection()
    conn.execute(
        "DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# FastAPI ovisnosti
# ---------------------------------------------------------------------------
def get_current_user_optional(
    sql_tutor_session: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    """Vraća podatke prijavljenog korisnika ili None ako nije prijavljen."""
    if not sql_tutor_session:
        return None

    conn = get_connection()
    red = conn.execute(
        """SELECT u.id, u.username, u.role, s.expires_at
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = ?""",
        (sql_tutor_session,),
    ).fetchone()
    conn.close()

    if not red:
        return None

    if datetime.fromisoformat(red["expires_at"]) < datetime.now():
        return None

    return {"id": red["id"], "username": red["username"], "role": red["role"]}


def get_current_user(
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    """Zahtijeva prijavljenog korisnika, inače vraća 401."""
    if not user:
        raise HTTPException(status_code=401, detail="Niste prijavljeni.")
    return user


def require_teacher(user: dict = Depends(get_current_user)) -> dict:
    """Zahtijeva ulogu nastavnika."""
    if user["role"] != "nastavnik":
        raise HTTPException(
            status_code=403, detail="Ova radnja dostupna je samo nastavnicima."
        )
    return user
