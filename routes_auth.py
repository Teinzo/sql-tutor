"""API rute za registraciju, prijavu i odjavu."""

import re
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from auth import (
    create_session,
    destroy_session,
    get_current_user,
    hash_password,
    verify_password,
)
from database import get_connection

router = APIRouter(prefix="/api", tags=["autentikacija"])

KORISNICKO_IME_UZORAK = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


class Registracija(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=6, max_length=128)


class Prijava(BaseModel):
    username: str
    password: str


@router.post("/register")
async def registracija(podaci: Registracija, response: Response):
    if not KORISNICKO_IME_UZORAK.match(podaci.username):
        raise HTTPException(
            status_code=400,
            detail="Korisničko ime smije sadržavati 3-30 slova, brojeva, "
                   "točku, crticu ili podvlaku.",
        )

    conn = get_connection()
    postoji = conn.execute(
        "SELECT id FROM users WHERE username = ?", (podaci.username,)
    ).fetchone()

    if postoji:
        conn.close()
        raise HTTPException(status_code=400, detail="Korisničko ime već postoji.")

    cursor = conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'student')",
        (podaci.username, hash_password(podaci.password)),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    create_session(user_id, response)

    return {
        "message": "Registracija uspješna.",
        "user": {"id": user_id, "username": podaci.username, "role": "student"},
    }


@router.post("/login")
async def prijava(podaci: Prijava, response: Response):
    conn = get_connection()
    korisnik = conn.execute(
        "SELECT id, username, password_hash, role FROM users WHERE username = ?",
        (podaci.username,),
    ).fetchone()
    conn.close()

    if not korisnik or not verify_password(podaci.password, korisnik["password_hash"]):
        raise HTTPException(
            status_code=401, detail="Pogrešno korisničko ime ili lozinka."
        )

    create_session(korisnik["id"], response)

    return {
        "message": "Prijava uspješna.",
        "user": {
            "id": korisnik["id"],
            "username": korisnik["username"],
            "role": korisnik["role"],
        },
    }


@router.post("/logout")
async def odjava(
    response: Response, sql_tutor_session: Optional[str] = Cookie(default=None)
):
    destroy_session(sql_tutor_session, response)
    return {"message": "Odjava uspješna."}


@router.get("/me")
async def trenutni_korisnik(user: dict = Depends(get_current_user)):
    return {"user": user}
