"""API rute nastavničkog panela: pregled korisnika, rezultata i evaluacije sustava."""

from fastapi import APIRouter, Depends

from auth import require_teacher
from database import get_connection
from schemas import get_schema

router = APIRouter(prefix="/api/admin", tags=["nastavnički panel"])


@router.get("/overview")
async def pregled(user: dict = Depends(require_teacher)):
    """Zbirni pokazatelji korištenja sustava."""
    conn = get_connection()

    brojevi = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM users WHERE role = 'student')  AS studenata,
             (SELECT COUNT(*) FROM tasks)                          AS zadataka,
             (SELECT COUNT(*) FROM tasks WHERE ai_generated = 1)   AS ai_zadataka,
             (SELECT COUNT(*) FROM submissions)                    AS predaja,
             (SELECT COUNT(*) FROM submissions WHERE is_correct=1) AS tocnih,
             (SELECT COUNT(*) FROM chat_logs WHERE role='user')    AS pitanja_tutoru,
             (SELECT COUNT(*) FROM survey)                         AS anketa"""
    ).fetchone()

    conn.close()

    predaja = brojevi["predaja"] or 0
    tocnih = brojevi["tocnih"] or 0

    return {
        "studenata": brojevi["studenata"],
        "zadataka": brojevi["zadataka"],
        "ai_zadataka": brojevi["ai_zadataka"],
        "predaja": predaja,
        "tocnih": tocnih,
        "postotak_tocnosti": round(tocnih / predaja * 100, 1) if predaja else 0.0,
        "pitanja_tutoru": brojevi["pitanja_tutoru"],
        "ispunjenih_anketa": brojevi["anketa"],
    }


@router.get("/students")
async def studenti(user: dict = Depends(require_teacher)):
    """Popis studenata s njihovim rezultatima."""
    conn = get_connection()
    redci = conn.execute(
        """SELECT u.id, u.username, u.created_at,
                  COUNT(s.id)                     AS predaja,
                  COALESCE(SUM(s.is_correct), 0)  AS tocnih,
                  COUNT(DISTINCT CASE WHEN s.is_correct = 1 THEN s.task_id END)
                                                  AS rijesenih_zadataka,
                  MAX(s.submitted_at)             AS zadnja_aktivnost
           FROM users u
           LEFT JOIN submissions s ON s.user_id = u.id
           WHERE u.role = 'student'
           GROUP BY u.id
           ORDER BY rijesenih_zadataka DESC, u.username"""
    ).fetchall()
    conn.close()

    studenti_lista = []
    for red in redci:
        stavka = dict(red)
        stavka["postotak_tocnosti"] = (
            round(red["tocnih"] / red["predaja"] * 100, 1) if red["predaja"] else 0.0
        )
        studenti_lista.append(stavka)

    return {"students": studenti_lista}


@router.get("/task-stats")
async def statistika_zadataka(user: dict = Depends(require_teacher)):
    """Uspješnost po zadatku - pokazuje koji su zadaci prezahtjevni."""
    conn = get_connection()
    redci = conn.execute(
        """SELECT t.id, t.title, t.difficulty, t.schema_id, t.ai_generated,
                  COUNT(s.id)                    AS pokusaja,
                  COALESCE(SUM(s.is_correct), 0) AS tocnih,
                  COUNT(DISTINCT s.user_id)      AS studenata
           FROM tasks t
           LEFT JOIN submissions s ON s.task_id = t.id
           GROUP BY t.id
           ORDER BY pokusaja DESC, t.id"""
    ).fetchall()
    conn.close()

    zadaci = []
    for red in redci:
        stavka = dict(red)
        stavka["schema_naziv"] = get_schema(red["schema_id"])["naziv"]
        stavka["postotak_tocnosti"] = (
            round(red["tocnih"] / red["pokusaja"] * 100, 1) if red["pokusaja"] else None
        )
        zadaci.append(stavka)

    return {"tasks": zadaci}


@router.get("/survey-results")
async def rezultati_ankete(user: dict = Depends(require_teacher)):
    """Zbirni rezultati ankete za evaluaciju sustava."""
    conn = get_connection()

    prosjeci = conn.execute(
        """SELECT COUNT(*)            AS n,
                  AVG(korisnost)      AS korisnost,
                  AVG(jasnoca)        AS jasnoca,
                  AVG(kvaliteta_ai)   AS kvaliteta_ai,
                  AVG(sucelje)        AS sucelje,
                  AVG(preporuka)      AS preporuka
           FROM survey"""
    ).fetchone()

    komentari = conn.execute(
        """SELECT komentar, created_at
           FROM survey
           WHERE komentar IS NOT NULL AND TRIM(komentar) <> ''
           ORDER BY id DESC LIMIT 50"""
    ).fetchall()

    raspodjela = conn.execute(
        """SELECT preporuka AS ocjena, COUNT(*) AS broj
           FROM survey GROUP BY preporuka ORDER BY preporuka"""
    ).fetchall()

    conn.close()

    n = prosjeci["n"] or 0

    return {
        "broj_odgovora": n,
        "prosjeci": {
            "korisnost": round(prosjeci["korisnost"], 2) if n else None,
            "jasnoca": round(prosjeci["jasnoca"], 2) if n else None,
            "kvaliteta_ai": round(prosjeci["kvaliteta_ai"], 2) if n else None,
            "sucelje": round(prosjeci["sucelje"], 2) if n else None,
            "preporuka": round(prosjeci["preporuka"], 2) if n else None,
        },
        "raspodjela_preporuke": [dict(r) for r in raspodjela],
        "komentari": [dict(r) for r in komentari],
    }
