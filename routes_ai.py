"""API rute za AI funkcionalnosti: chatbot tutor i generiranje zadataka."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_service import AIError, chat_with_tutor, generate_sql_tasks
from auth import get_current_user, require_teacher
from config import is_llm_configured
from database import get_connection
from schemas import SCHEMAS
from sql_runner import QueryError, run_query

router = APIRouter(prefix="/api", tags=["umjetna inteligencija"])


class ChatPoruka(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: List[Dict[str, str]] = []
    schema_id: Optional[str] = None


class ZahtjevGeneriranja(BaseModel):
    difficulty: str = "početnik"
    topic: str = "osnovni upiti"
    schema_id: str = "fakultet"
    count: int = Field(default=3, ge=1, le=5)


class SpremiZadatak(BaseModel):
    schema_id: str = "fakultet"
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    difficulty: str
    topic: Optional[str] = None
    solution_sql: str = Field(min_length=1, max_length=5000)
    hint: Optional[str] = None


def _normaliziraj_sql(sql: str) -> str:
    """Svodi upit na oblik pogodan za usporedbu (za prepoznavanje duplikata)."""
    return " ".join(sql.lower().replace(";", " ").split())


def _postojeci_zadaci(schema_id: str) -> tuple:
    """Vraća (naslovi, normalizirana rješenja) postojećih zadataka za shemu."""
    conn = get_connection()
    redci = conn.execute(
        """SELECT title, solution_sql FROM tasks
           WHERE schema_id = ? ORDER BY id DESC LIMIT 60""",
        (schema_id,),
    ).fetchall()
    conn.close()

    naslovi = [r["title"] for r in redci]
    rjesenja = {_normaliziraj_sql(r["solution_sql"]) for r in redci}
    return naslovi, rjesenja


def _provjeri_ai() -> None:
    if not is_llm_configured():
        raise HTTPException(
            status_code=503,
            detail="AI funkcionalnosti nisu dostupne jer OPENAI_API_KEY "
                   "nije postavljen u .env datoteci.",
        )


# Napomena: rute koje pozivaju jezični model namjerno su definirane kao obični
# `def`, a ne `async def`. Poziv modela je blokirajući (requests), pa bi ga
# unutar korutine blokirao cijeli event loop i aplikacija se ne bi odazivala
# dok traje generiranje. FastAPI sinkrone rute izvodi u zasebnoj dretvi.
@router.post("/chat")
def razgovor(podaci: ChatPoruka, user: dict = Depends(get_current_user)):
    """Šalje poruku AI tutoru i vraća njegov odgovor."""
    _provjeri_ai()

    try:
        odgovor = chat_with_tutor(podaci.history, podaci.message, podaci.schema_id)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Razgovor se bilježi radi kasnije evaluacije sustava.
    conn = get_connection()
    conn.executemany(
        "INSERT INTO chat_logs (user_id, role, content) VALUES (?, ?, ?)",
        [
            (user["id"], "user", podaci.message),
            (user["id"], "assistant", odgovor),
        ],
    )
    conn.commit()
    conn.close()

    return {"response": odgovor}


@router.post("/generate-tasks")
def generiraj_zadatke(
    podaci: ZahtjevGeneriranja, user: dict = Depends(get_current_user)
):
    """Generira zadatke jezičnim modelom i provjerava izvršivost rješenja.

    Svako generirano rješenje izvršava se nad vježbovnom shemom kako bi se
    odbacili zadaci s neispravnim SQL-om - to je ključan korak jer jezični
    model povremeno generira upite koji se ne mogu izvršiti.
    """
    _provjeri_ai()

    if podaci.schema_id not in SCHEMAS:
        raise HTTPException(status_code=400, detail="Nepoznata shema baze.")

    # Naslovi postojećih zadataka šalju se modelu kako ne bi ponovio isti zadatak.
    naslovi, postojeca_rjesenja = _postojeci_zadaci(podaci.schema_id)

    try:
        zadaci = generate_sql_tasks(
            podaci.difficulty,
            podaci.topic,
            podaci.schema_id,
            podaci.count,
            izbjegni=naslovi,
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    provjereni: List[Dict[str, Any]] = []
    neizvrsivi = 0
    duplikati = 0
    vidjena_rjesenja = set()

    for zadatak in zadaci:
        kljuc = _normaliziraj_sql(zadatak["solution_sql"])

        # Duplikat postojećeg zadatka ili ponavljanje unutar iste serije.
        if kljuc in postojeca_rjesenja or kljuc in vidjena_rjesenja:
            duplikati += 1
            print(f"[generiranje] Duplikat preskočen: '{zadatak['title']}'")
            continue

        try:
            stupci, redci = run_query(
                zadatak["schema_id"], zadatak["solution_sql"], validate=False
            )
        except QueryError as exc:
            neizvrsivi += 1
            print(f"[generiranje] Odbačen zadatak '{zadatak['title']}': {exc}")
            continue

        vidjena_rjesenja.add(kljuc)
        zadatak["broj_redaka"] = len(redci)
        zadatak["stupci"] = stupci
        zadatak["primjer_redaka"] = [list(r) for r in redci[:5]]
        provjereni.append(zadatak)

    if not provjereni:
        if duplikati and not neizvrsivi:
            raise HTTPException(
                status_code=409,
                detail="Model je vratio samo zadatke koji već postoje. "
                       "Pokušajte ponovno, promijenite temu ili razinu težine.",
            )
        raise HTTPException(
            status_code=502,
            detail="Model je generirao zadatke, ali nijedno rješenje nije bilo "
                   "izvršivo. Pokušajte ponovno ili odaberite drugu temu.",
        )

    return {
        "tasks": provjereni,
        "odbaceno": neizvrsivi,
        "duplikata": duplikati,
    }


@router.post("/save-task")
async def spremi_zadatak(
    podaci: SpremiZadatak, user: dict = Depends(get_current_user)
):
    """Sprema zadatak u bazu nakon provjere da je rješenje izvršivo."""
    if podaci.schema_id not in SCHEMAS:
        raise HTTPException(status_code=400, detail="Nepoznata shema baze.")

    try:
        run_query(podaci.schema_id, podaci.solution_sql, validate=False)
    except QueryError as exc:
        raise HTTPException(
            status_code=400, detail=f"Rješenje nije izvršivo: {exc}"
        ) from exc

    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO tasks
           (schema_id, title, description, difficulty, topic,
            solution_sql, hint, ai_generated, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            podaci.schema_id,
            podaci.title,
            podaci.description,
            podaci.difficulty,
            podaci.topic,
            podaci.solution_sql,
            podaci.hint,
            user["id"],
        ),
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {"message": "Zadatak je spremljen.", "task_id": task_id}


@router.delete("/tasks/{task_id}")
async def obrisi_zadatak(task_id: int, user: dict = Depends(require_teacher)):
    """Briše zadatak i pripadajuće pokušaje (samo nastavnik)."""
    conn = get_connection()
    postoji = conn.execute(
        "SELECT id FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()

    if not postoji:
        conn.close()
        raise HTTPException(status_code=404, detail="Zadatak nije pronađen.")

    conn.execute("DELETE FROM submissions WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

    return {"message": "Zadatak je obrisan."}
