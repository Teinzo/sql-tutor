"""API rute za statistiku napretka i anketu za evaluaciju sustava."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import get_current_user
from database import get_connection
from schemas import get_schema

router = APIRouter(prefix="/api", tags=["napredak i evaluacija"])


class AnketaOdgovor(BaseModel):
    korisnost: int = Field(ge=1, le=5)
    jasnoca: int = Field(ge=1, le=5)
    kvaliteta_ai: int = Field(ge=1, le=5)
    sucelje: int = Field(ge=1, le=5)
    preporuka: int = Field(ge=1, le=5)
    komentar: Optional[str] = Field(default=None, max_length=2000)


@router.get("/progress")
async def napredak(user: dict = Depends(get_current_user)):
    """Sažetak napretka trenutnog korisnika."""
    conn = get_connection()

    ukupno_zadataka = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]

    sazetak = conn.execute(
        """SELECT COUNT(*)                       AS ukupno_predaja,
                  SUM(is_correct)                AS tocnih_predaja,
                  COUNT(DISTINCT task_id)        AS pokusanih_zadataka,
                  COUNT(DISTINCT CASE WHEN is_correct = 1 THEN task_id END)
                                                 AS rijesenih_zadataka,
                  AVG(duration_ms)               AS prosjecno_trajanje
           FROM submissions WHERE user_id = ?""",
        (user["id"],),
    ).fetchone()

    po_tezini = conn.execute(
        """SELECT t.difficulty,
                  COUNT(DISTINCT t.id) AS ukupno,
                  COUNT(DISTINCT CASE WHEN s.is_correct = 1 THEN t.id END) AS rijeseno
           FROM tasks t
           LEFT JOIN submissions s ON s.task_id = t.id AND s.user_id = ?
           GROUP BY t.difficulty""",
        (user["id"],),
    ).fetchall()

    po_shemi = conn.execute(
        """SELECT t.schema_id,
                  COUNT(DISTINCT t.id) AS ukupno,
                  COUNT(DISTINCT CASE WHEN s.is_correct = 1 THEN t.id END) AS rijeseno
           FROM tasks t
           LEFT JOIN submissions s ON s.task_id = t.id AND s.user_id = ?
           GROUP BY t.schema_id""",
        (user["id"],),
    ).fetchall()

    po_temi = conn.execute(
        """SELECT COALESCE(t.topic, 'ostalo') AS tema,
                  COUNT(s.id)                 AS pokusaja,
                  SUM(s.is_correct)           AS tocnih
           FROM submissions s
           JOIN tasks t ON t.id = s.task_id
           WHERE s.user_id = ?
           GROUP BY tema
           ORDER BY pokusaja DESC""",
        (user["id"],),
    ).fetchall()

    kroz_vrijeme = conn.execute(
        """SELECT DATE(submitted_at) AS dan,
                  COUNT(*)           AS pokusaja,
                  SUM(is_correct)    AS tocnih
           FROM submissions
           WHERE user_id = ?
           GROUP BY dan
           ORDER BY dan DESC
           LIMIT 14""",
        (user["id"],),
    ).fetchall()

    zadnji = conn.execute(
        """SELECT s.id, s.query, s.is_correct, s.feedback, s.submitted_at,
                  t.title, t.difficulty, t.schema_id
           FROM submissions s
           JOIN tasks t ON t.id = s.task_id
           WHERE s.user_id = ?
           ORDER BY s.submitted_at DESC
           LIMIT 10""",
        (user["id"],),
    ).fetchall()

    conn.close()

    ukupno_predaja = sazetak["ukupno_predaja"] or 0
    tocnih_predaja = sazetak["tocnih_predaja"] or 0
    rijesenih = sazetak["rijesenih_zadataka"] or 0

    return {
        "sazetak": {
            "ukupno_zadataka": ukupno_zadataka,
            "rijeseno_zadataka": rijesenih,
            "pokusano_zadataka": sazetak["pokusanih_zadataka"] or 0,
            "ukupno_predaja": ukupno_predaja,
            "tocnih_predaja": tocnih_predaja,
            "postotak_tocnosti": round(tocnih_predaja / ukupno_predaja * 100, 1)
            if ukupno_predaja
            else 0.0,
            "postotak_rijesenih": round(rijesenih / ukupno_zadataka * 100, 1)
            if ukupno_zadataka
            else 0.0,
            "prosjecno_trajanje_ms": round(sazetak["prosjecno_trajanje"] or 0),
        },
        "po_tezini": [dict(r) for r in po_tezini],
        "po_shemi": [
            {**dict(r), "naziv": get_schema(r["schema_id"])["naziv"]} for r in po_shemi
        ],
        "po_temi": [dict(r) for r in po_temi],
        "kroz_vrijeme": [dict(r) for r in reversed(kroz_vrijeme)],
        "zadnje_predaje": [dict(r) for r in zadnji],
    }


@router.post("/survey")
async def posalji_anketu(
    odgovor: AnketaOdgovor, user: dict = Depends(get_current_user)
):
    """Sprema odgovor na anketu o zadovoljstvu sustavom.

    Tablica ima UNIQUE(user_id), pa ponovno slanje azurira postojeci odgovor
    umjesto da stvori duplikat. Time jedan ispitanik doprinosi tocno jednim
    zapisom, sto je preduvjet za valjanu obradu rezultata.
    """
    conn = get_connection()
    conn.execute(
        """INSERT INTO survey
           (user_id, korisnost, jasnoca, kvaliteta_ai, sucelje, preporuka, komentar)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               korisnost    = excluded.korisnost,
               jasnoca      = excluded.jasnoca,
               kvaliteta_ai = excluded.kvaliteta_ai,
               sucelje      = excluded.sucelje,
               preporuka    = excluded.preporuka,
               komentar     = excluded.komentar,
               created_at   = CURRENT_TIMESTAMP""",
        (
            user["id"],
            odgovor.korisnost,
            odgovor.jasnoca,
            odgovor.kvaliteta_ai,
            odgovor.sucelje,
            odgovor.preporuka,
            odgovor.komentar,
        ),
    )
    conn.commit()
    conn.close()

    return {"message": "Hvala na ispunjenoj anketi!"}


@router.get("/survey/mine")
async def moja_anketa(user: dict = Depends(get_current_user)):
    """Provjerava je li korisnik već ispunio anketu."""
    conn = get_connection()
    red = conn.execute(
        "SELECT created_at FROM survey WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user["id"],),
    ).fetchone()
    conn.close()

    return {"ispunjena": red is not None, "datum": red["created_at"] if red else None}
