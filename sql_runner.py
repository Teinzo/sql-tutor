"""Sigurno izvršavanje i determinističko ocjenjivanje studentskih SQL upita.

Upit se izvršava nad privremenom bazom u memoriji koja se gradi iz odabrane
vježbovne sheme. Glavna baza aplikacije time je nedostupna studentovom upitu.

Dodatna ograničenja:
  * dopušten je samo jedan SELECT (ili WITH ... SELECT) izraz,
  * zabranjene su ključne riječi koje mijenjaju podatke ili shemu,
  * zabranjen je pristup datotečnom sustavu (ATTACH) i internim tablicama,
  * izvršavanje se prekida nakon isteka vremenskog ograničenja.
"""

import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from config import QUERY_MAX_ROWS, QUERY_TIMEOUT
from schemas import get_ddl

# Ključne riječi koje ne smiju postojati u studentovom upitu.
ZABRANJENE_RIJECI = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "truncate",
    "grant", "revoke", "begin", "commit", "rollback", "savepoint",
    "load_extension",
}

# Zabranjeni pristup internim tablicama SQLite-a.
ZABRANJENI_OBJEKTI = {"sqlite_master", "sqlite_schema", "sqlite_temp_master"}


class QueryError(Exception):
    """Upit je odbijen prije izvršavanja ili je izbacio grešku."""


def _ukloni_komentare(sql: str) -> str:
    """Uklanja -- i /* */ komentare kako se zabranjene riječi ne bi sakrile."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def _tokeni_izvan_literala(sql: str) -> List[str]:
    """Vraća riječi iz upita, zanemarujući sadržaj tekstualnih literala."""
    bez_literala = re.sub(r"'(?:[^']|'')*'", " ", sql)
    bez_literala = re.sub(r'"(?:[^"]|"")*"', " ", bez_literala)
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", bez_literala.lower())


def validate_query(sql: str) -> None:
    """Provjerava je li upit dopušten. Baca QueryError ako nije."""
    if not sql or not sql.strip():
        raise QueryError("Upit je prazan.")

    ocisceno = _ukloni_komentare(sql).strip()

    if not ocisceno:
        raise QueryError("Upit ne sadrži nijednu naredbu.")

    # Više naredbi odvojenih točkom-zarezom nije dopušteno.
    bez_literala = re.sub(r"'(?:[^']|'')*'", "''", ocisceno)
    naredbe = [d for d in bez_literala.split(";") if d.strip()]
    if len(naredbe) > 1:
        raise QueryError("Dopušten je samo jedan SQL izraz po predaji.")

    tokeni = _tokeni_izvan_literala(ocisceno)
    if not tokeni:
        raise QueryError("Upit ne sadrži nijednu naredbu.")

    if tokeni[0] not in ("select", "with"):
        raise QueryError("Dopušteni su samo SELECT upiti.")

    zabranjeni = ZABRANJENE_RIJECI.intersection(tokeni)
    if zabranjeni:
        raise QueryError(
            f"Upit sadrži zabranjenu naredbu: {', '.join(sorted(zabranjeni)).upper()}. "
            "Dopušteno je samo dohvaćanje podataka."
        )

    objekti = ZABRANJENI_OBJEKTI.intersection(tokeni)
    if objekti:
        raise QueryError("Pristup internim tablicama baze nije dopušten.")


def build_sandbox(schema_id: str) -> sqlite3.Connection:
    """Kreira privremenu bazu u memoriji prema odabranoj shemi."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(get_ddl(schema_id))
    conn.commit()
    return conn


def _postavi_ogranicenje(conn: sqlite3.Connection, sekunde: int) -> None:
    """Prekida izvršavanje upita nakon isteka vremena."""
    pocetak = time.monotonic()

    def prekidac() -> int:
        return 1 if time.monotonic() - pocetak > sekunde else 0

    conn.set_progress_handler(prekidac, 10_000)


def run_query(
    schema_id: str,
    sql: str,
    conn: Optional[sqlite3.Connection] = None,
    validate: bool = True,
) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """Izvršava upit i vraća (nazivi stupaca, redci).

    Ako je `conn` predan, koristi se postojeća veza; inače se gradi nova.
    """
    if validate:
        validate_query(sql)

    vlastita_veza = conn is None
    if conn is None:
        conn = build_sandbox(schema_id)

    try:
        _postavi_ogranicenje(conn, QUERY_TIMEOUT)
        cursor = conn.cursor()
        cursor.execute(sql)
        stupci = [o[0] for o in cursor.description] if cursor.description else []
        redci = cursor.fetchall()
        return stupci, redci
    except sqlite3.OperationalError as exc:
        poruka = str(exc)
        if "interrupted" in poruka.lower():
            raise QueryError(
                f"Upit se izvršavao dulje od {QUERY_TIMEOUT} s i prekinut je."
            ) from exc
        raise QueryError(_prevedi_gresku(poruka)) from exc
    except sqlite3.Error as exc:
        raise QueryError(_prevedi_gresku(str(exc))) from exc
    finally:
        conn.set_progress_handler(None, 0)
        if vlastita_veza:
            conn.close()


def _prevedi_gresku(poruka: str) -> str:
    """Prevodi najčešće SQLite greške na razumljiviji hrvatski."""
    p = poruka.lower()
    if "no such table" in p:
        tablica = poruka.split(":")[-1].strip()
        return f"Tablica '{tablica}' ne postoji u ovoj shemi."
    if "no such column" in p:
        stupac = poruka.split(":")[-1].strip()
        return f"Stupac '{stupac}' ne postoji. Provjerite nazive stupaca u shemi."
    if "syntax error" in p:
        return f"Sintaksna greška u upitu. ({poruka})"
    if "ambiguous column name" in p:
        stupac = poruka.split(":")[-1].strip()
        return (
            f"Naziv stupca '{stupac}' je dvosmislen jer postoji u više tablica. "
            "Dodajte prefiks tablice, npr. studenti.id."
        )
    if "misuse of aggregate" in p:
        return f"Pogrešna upotreba agregatne funkcije. ({poruka})"
    return f"Greška u upitu: {poruka}"


# ---------------------------------------------------------------------------
# Ocjenjivanje
# ---------------------------------------------------------------------------
def _normaliziraj(redci: List[Tuple[Any, ...]]) -> List[Tuple[str, ...]]:
    """Pretvara vrijednosti u niz znakova radi usporedbe neovisne o tipu."""
    return [tuple("NULL" if v is None else str(v) for v in red) for red in redci]


def grade_query(
    schema_id: str, student_sql: str, solution_sql: str
) -> Dict[str, Any]:
    """Uspoređuje studentov upit s referentnim rješenjem.

    Vraća rječnik s ključevima:
        is_correct  - je li rješenje točno
        status      - 'tocno' | 'netocno' | 'greska'
        poruka      - kratko objašnjenje na hrvatskom
        stupci      - nazivi stupaca rezultata studentovog upita
        redci       - redci rezultata (ograničeno na QUERY_MAX_ROWS)
        broj_redaka - ukupan broj redaka koje je upit vratio
        ocekivano   - očekivani broj redaka
        trajanje_ms - vrijeme izvršavanja studentovog upita
    """
    rezultat: Dict[str, Any] = {
        "is_correct": False,
        "status": "greska",
        "poruka": "",
        "stupci": [],
        "redci": [],
        "broj_redaka": 0,
        "ocekivano": 0,
        "trajanje_ms": 0,
    }

    conn = build_sandbox(schema_id)
    try:
        # Referentno rješenje ne prolazi kroz validaciju jer dolazi iz sustava.
        try:
            oc_stupci, oc_redci = run_query(
                schema_id, solution_sql, conn=conn, validate=False
            )
        except QueryError as exc:
            rezultat["poruka"] = (
                "Referentno rješenje ovog zadatka nije ispravno. "
                f"Javite nastavniku. ({exc})"
            )
            return rezultat

        rezultat["ocekivano"] = len(oc_redci)

        pocetak = time.perf_counter()
        try:
            st_stupci, st_redci = run_query(schema_id, student_sql, conn=conn)
        except QueryError as exc:
            rezultat["status"] = "greska"
            rezultat["poruka"] = str(exc)
            return rezultat
        rezultat["trajanje_ms"] = int((time.perf_counter() - pocetak) * 1000)

        rezultat["stupci"] = st_stupci
        rezultat["redci"] = [list(r) for r in st_redci[:QUERY_MAX_ROWS]]
        rezultat["broj_redaka"] = len(st_redci)

        ocekivano_n = _normaliziraj(oc_redci)
        dobiveno_n = _normaliziraj(st_redci)

        if len(st_stupci) != len(oc_stupci):
            rezultat["status"] = "netocno"
            rezultat["poruka"] = (
                f"Upit vraća {_oblik(len(st_stupci), 'stupac', 'stupca', 'stupaca')}, "
                f"a očekuje se {_oblik(len(oc_stupci), 'stupac', 'stupca', 'stupaca')}. "
                "Provjerite koje stupce zadatak traži."
            )
            return rezultat

        if dobiveno_n == ocekivano_n:
            rezultat["is_correct"] = True
            rezultat["status"] = "tocno"
            rezultat["poruka"] = (
                "Točno! Upit je vratio "
                f"{_oblik(len(st_redci), 'redak', 'retka', 'redaka')}."
            )
            return rezultat

        rezultat["status"] = "netocno"

        # Ista skupina redaka, ali drugačiji redoslijed -> vjerojatno nedostaje ORDER BY.
        if sorted(dobiveno_n) == sorted(ocekivano_n):
            rezultat["poruka"] = (
                "Redci su točni, ali redoslijed nije. Provjerite ORDER BY dio upita."
            )
        elif len(st_redci) != len(oc_redci):
            rezultat["poruka"] = (
                f"Upit je vratio {_oblik(len(st_redci), 'redak', 'retka', 'redaka')}, "
                f"a očekuje se {len(oc_redci)}. Provjerite uvjet u WHERE dijelu."
            )
        else:
            rezultat["poruka"] = (
                "Broj redaka je točan, ali vrijednosti se ne podudaraju s očekivanima."
            )
        return rezultat
    finally:
        conn.close()


def _oblik(n: int, jednina: str, dvojina: str, mnozina: str) -> str:
    """Vraća broj s gramatički ispravnim oblikom imenice.

    Primjer: _oblik(1, 'redak', 'retka', 'redaka') -> '1 redak'
             _oblik(3, 'redak', 'retka', 'redaka') -> '3 retka'
             _oblik(7, 'redak', 'retka', 'redaka') -> '7 redaka'
    """
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {jednina}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {dvojina}"
    return f"{n} {mnozina}"


def tehnicki_ishod_opis(rezultat: Dict[str, Any]) -> str:
    """Sažetak determinističke provjere koji se prosljeđuje jezičnom modelu."""
    if rezultat["status"] == "tocno":
        return "Upit je TOČAN - rezultat se u potpunosti podudara s očekivanim."
    if rezultat["status"] == "greska":
        return f"Upit je izbacio GREŠKU: {rezultat['poruka']}"
    return (
        f"Upit je NETOČAN. {rezultat['poruka']} "
        f"Vratio je {rezultat['broj_redaka']} redaka, a očekuje se "
        f"{rezultat['ocekivano']}."
    )
