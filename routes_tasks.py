"""API rute za zadatke, izvršavanje upita i predaju rješenja."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_service import AIError, evaluate_query
from auth import get_current_user
from config import is_llm_configured
from database import get_connection
from schemas import SCHEMAS, get_schema
from sql_runner import (
    QueryError,
    build_sandbox,
    grade_query,
    run_query,
    tehnicki_ishod_opis,
)

router = APIRouter(prefix="/api", tags=["zadaci"])


class IzvrsiUpit(BaseModel):
    schema_id: str = "fakultet"
    query: str = Field(min_length=1, max_length=5000)


class PredajaRjesenja(BaseModel):
    task_id: int
    query: str = Field(min_length=1, max_length=5000)
    trazi_ai_povratnu: bool = True


def _zadatak_u_rjecnik(red, otkrij_rjesenje: bool = False) -> Dict[str, Any]:
    podaci = {
        "id": red["id"],
        "schema_id": red["schema_id"],
        "title": red["title"],
        "description": red["description"],
        "difficulty": red["difficulty"],
        "topic": red["topic"],
        "hint": red["hint"],
        "ai_generated": bool(red["ai_generated"]),
        "created_at": red["created_at"],
        "schema_naziv": get_schema(red["schema_id"])["naziv"],
    }
    if otkrij_rjesenje:
        podaci["solution_sql"] = red["solution_sql"]
    return podaci


@router.get("/tasks")
async def popis_zadataka(
    schema_id: Optional[str] = None,
    difficulty: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Popis zadataka s podatkom je li ih trenutni korisnik već riješio."""
    uvjeti: List[str] = []
    parametri: List[Any] = []

    if schema_id:
        uvjeti.append("t.schema_id = ?")
        parametri.append(schema_id)
    if difficulty:
        uvjeti.append("t.difficulty = ?")
        parametri.append(difficulty)

    where = f"WHERE {' AND '.join(uvjeti)}" if uvjeti else ""

    conn = get_connection()
    redci = conn.execute(
        f"""SELECT t.*,
                   COALESCE(MAX(s.is_correct), 0) AS rijesen,
                   COUNT(s.id)                    AS broj_pokusaja
            FROM tasks t
            LEFT JOIN submissions s
                   ON s.task_id = t.id AND s.user_id = ?
            {where}
            GROUP BY t.id
            ORDER BY t.id""",
        [user["id"], *parametri],
    ).fetchall()
    conn.close()

    zadaci = []
    for red in redci:
        zadatak = _zadatak_u_rjecnik(red)
        zadatak["rijesen"] = bool(red["rijesen"])
        zadatak["broj_pokusaja"] = red["broj_pokusaja"]
        zadaci.append(zadatak)

    return {"tasks": zadaci}


@router.get("/tasks/{task_id}")
async def dohvati_zadatak(task_id: int, user: dict = Depends(get_current_user)):
    """Detalji zadatka zajedno s prethodnim pokušajima korisnika."""
    conn = get_connection()
    red = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    if not red:
        conn.close()
        raise HTTPException(status_code=404, detail="Zadatak nije pronađen.")

    pokusaji = conn.execute(
        """SELECT query, is_correct, feedback, ai_feedback, submitted_at
           FROM submissions
           WHERE user_id = ? AND task_id = ?
           ORDER BY submitted_at DESC LIMIT 10""",
        (user["id"], task_id),
    ).fetchall()
    conn.close()

    # Nastavnik smije vidjeti referentno rješenje.
    zadatak = _zadatak_u_rjecnik(red, otkrij_rjesenje=user["role"] == "nastavnik")
    shema = get_schema(red["schema_id"])

    return {
        "task": zadatak,
        "schema": {
            "id": shema["id"],
            "naziv": shema["naziv"],
            "opis": shema["opis"],
            "ikona": shema["ikona"],
            "tablice": shema["tablice"],
        },
        "attempts": [dict(p) for p in pokusaji],
    }


@router.post("/run")
async def izvrsi_upit(podaci: IzvrsiUpit, user: dict = Depends(get_current_user)):
    """Izvršava upit nad vježbovnom shemom bez ocjenjivanja i spremanja."""
    if podaci.schema_id not in SCHEMAS:
        raise HTTPException(status_code=400, detail="Nepoznata shema baze.")

    try:
        stupci, redci = run_query(podaci.schema_id, podaci.query)
    except QueryError as exc:
        return {"uspjeh": False, "greska": str(exc)}

    return {
        "uspjeh": True,
        "stupci": stupci,
        "redci": [list(r) for r in redci[:200]],
        "broj_redaka": len(redci),
    }


@router.get("/schema-preview/{schema_id}")
async def pregled_sheme(schema_id: str, user: dict = Depends(get_current_user)):
    """Vraća prvih nekoliko redaka svake tablice u shemi radi prikaza u sučelju."""
    if schema_id not in SCHEMAS:
        raise HTTPException(status_code=404, detail="Nepoznata shema baze.")

    shema = get_schema(schema_id)
    conn = build_sandbox(schema_id)
    pregled: Dict[str, Any] = {}

    try:
        for tablica in shema["tablice"]:
            stupci, redci = run_query(
                schema_id, f"SELECT * FROM {tablica} LIMIT 5", conn=conn, validate=False
            )
            ukupno = run_query(
                schema_id,
                f"SELECT COUNT(*) FROM {tablica}",
                conn=conn,
                validate=False,
            )[1][0][0]
            pregled[tablica] = {
                "stupci": stupci,
                "redci": [list(r) for r in redci],
                "ukupno": ukupno,
            }
    finally:
        conn.close()

    return {"schema": shema["naziv"], "tablice": pregled}


@router.post("/submit")
def predaj_rjesenje(  # sinkrono: evaluate_query blokirajuće zove jezični model
    podaci: PredajaRjesenja, user: dict = Depends(get_current_user)
):
    """Ocjenjuje rješenje, sprema pokušaj i vraća povratnu informaciju.

    Ocjenjivanje je dvoslojno:
      1. deterministička usporedba rezultata s referentnim rješenjem,
      2. kvalitativno objašnjenje jezičnog modela (ako je dostupan).
    """
    conn = get_connection()
    zadatak = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (podaci.task_id,)
    ).fetchone()

    if not zadatak:
        conn.close()
        raise HTTPException(status_code=404, detail="Zadatak nije pronađen.")

    rezultat = grade_query(
        zadatak["schema_id"], podaci.query, zadatak["solution_sql"]
    )

    ai_povratna: Optional[str] = None
    ai_greska: Optional[str] = None

    if podaci.trazi_ai_povratnu and is_llm_configured():
        try:
            ai_povratna = evaluate_query(
                task_description=zadatak["description"],
                solution_sql=zadatak["solution_sql"],
                student_sql=podaci.query,
                schema_id=zadatak["schema_id"],
                tehnicki_ishod=tehnicki_ishod_opis(rezultat),
            )
        except AIError as exc:
            ai_greska = str(exc)

    conn.execute(
        """INSERT INTO submissions
           (user_id, task_id, query, is_correct, feedback, ai_feedback, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            user["id"],
            podaci.task_id,
            podaci.query,
            int(rezultat["is_correct"]),
            rezultat["poruka"],
            ai_povratna,
            rezultat["trajanje_ms"],
        ),
    )
    conn.commit()
    conn.close()

    return {
        "is_correct": rezultat["is_correct"],
        "status": rezultat["status"],
        "feedback": rezultat["poruka"],
        "ai_feedback": ai_povratna,
        "ai_greska": ai_greska,
        "stupci": rezultat["stupci"],
        "redci": rezultat["redci"],
        "broj_redaka": rezultat["broj_redaka"],
        "ocekivano": rezultat["ocekivano"],
        "trajanje_ms": rezultat["trajanje_ms"],
    }


@router.get("/tasks/{task_id}/hint")
async def dohvati_uputu(task_id: int, user: dict = Depends(get_current_user)):
    """Vraća unaprijed pripremljenu uputu za zadatak."""
    conn = get_connection()
    red = conn.execute(
        "SELECT hint FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    conn.close()

    if not red:
        raise HTTPException(status_code=404, detail="Zadatak nije pronađen.")

    return {"hint": red["hint"] or "Za ovaj zadatak nije pripremljena uputa."}
