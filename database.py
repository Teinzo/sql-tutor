"""Pristup bazi podataka aplikacije (SQLite).

Sadrži definiciju sheme, inicijalizaciju, jednostavnu migraciju putem
PRAGMA user_version te početne (seed) podatke.
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import (
    DB_PATH,
    DEMO_LOZINKA_NASTAVNIK,
    DEMO_LOZINKA_STUDENT,
    ZADANE_DEMO_LOZINKE,
)

# Verzija sheme. Povecanjem broja pokrece se ponovna izgradnja tablica.
SCHEMA_VERSION = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'student',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_id    TEXT NOT NULL DEFAULT 'fakultet',
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    difficulty   TEXT NOT NULL,
    topic        TEXT,
    solution_sql TEXT NOT NULL,
    hint         TEXT,
    ai_generated INTEGER NOT NULL DEFAULT 0,
    created_by   INTEGER,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS submissions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    task_id      INTEGER NOT NULL,
    query        TEXT NOT NULL,
    is_correct   INTEGER NOT NULL DEFAULT 0,
    feedback     TEXT,
    ai_feedback  TEXT,
    duration_ms  INTEGER,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS chat_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- UNIQUE(user_id): jedan odgovor po korisniku. Ponovno slanje azurira
-- postojeci zapis umjesto da stvara duplikat, cime rezultati ankete ostaju
-- upotrebljivi za evaluaciju sustava.
CREATE TABLE IF NOT EXISTS survey (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER UNIQUE,
    korisnost      INTEGER NOT NULL,
    jasnoca        INTEGER NOT NULL,
    kvaliteta_ai   INTEGER NOT NULL,
    sucelje        INTEGER NOT NULL,
    preporuka      INTEGER NOT NULL,
    komentar       TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_submissions_user ON submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_submissions_task ON submissions(task_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_schema     ON tasks(schema_id);
"""

DROP_SQL = """
DROP TABLE IF EXISTS survey;
DROP TABLE IF EXISTS chat_logs;
DROP TABLE IF EXISTS submissions;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS users;
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Kontekstni upravitelj koji uvijek zatvara vezu."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Kreira shemu, po potrebi pokreće migraciju i ubacuje početne podatke."""
    conn = get_connection()
    cursor = conn.cursor()

    trenutna = cursor.execute("PRAGMA user_version").fetchone()[0]

    if trenutna and trenutna < SCHEMA_VERSION:
        # Razvojna migracija: stara shema se odbacuje i gradi iznova.
        print(
            f"[baza] Otkrivena starija shema (v{trenutna}). "
            f"Ponovna izgradnja na v{SCHEMA_VERSION}..."
        )
        cursor.executescript(DROP_SQL)
    elif trenutna == 0:
        # Baza je prazna ili potječe iz verzije prije uvođenja user_version.
        stara = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if stara:
            stupci = [
                r[1] for r in cursor.execute("PRAGMA table_info(tasks)").fetchall()
            ]
            if "solution_sql" not in stupci:
                print("[baza] Zatečena stara shema bez verzije. Ponovna izgradnja...")
                cursor.executescript(DROP_SQL)

    cursor.executescript(SCHEMA_SQL)
    cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()

    _seed(conn)
    conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """Ubacuje demo korisnike i početni skup zadataka ako je baza prazna."""
    from auth import hash_password  # lokalni import zbog kružne ovisnosti

    cursor = conn.cursor()

    broj_korisnika = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if broj_korisnika == 0:
        cursor.executemany(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            [
                ("nastavnik", hash_password(DEMO_LOZINKA_NASTAVNIK), "nastavnik"),
                ("student", hash_password(DEMO_LOZINKA_STUDENT), "student"),
            ],
        )
        print("[baza] Kreirani demo računi: nastavnik, student")
        if ZADANE_DEMO_LOZINKE:
            print(
                "[baza] UPOZORENJE: koriste se zadane demo lozinke iz README-a. "
                "Postavite DEMO_LOZINKA_NASTAVNIK i DEMO_LOZINKA_STUDENT u .env "
                "prije nego aplikaciju učinite dostupnom drugima."
            )

    broj_zadataka = cursor.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    if broj_zadataka == 0:
        cursor.executemany(
            """INSERT INTO tasks
               (schema_id, title, description, difficulty, topic, solution_sql, hint, ai_generated)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            POCETNI_ZADACI,
        )
        print(f"[baza] Ubačeno {len(POCETNI_ZADACI)} početnih zadataka")

    conn.commit()


# (schema_id, title, description, difficulty, topic, solution_sql, hint)
POCETNI_ZADACI = [
    # --- FAKULTET -----------------------------------------------------------
    (
        "fakultet",
        "Svi studenti",
        "Ispišite ime i prezime svih studenata, sortirano po prezimenu uzlazno.",
        "početnik",
        "SELECT, ORDER BY",
        "SELECT ime, prezime FROM studenti ORDER BY prezime",
        "Koristite ORDER BY na stupcu prezime.",
    ),
    (
        "fakultet",
        "Studenti stariji od 23 godine",
        "Ispišite ime, prezime i dob svih studenata koji imaju više od 23 godine, "
        "sortirano po dobi silazno.",
        "početnik",
        "WHERE, ORDER BY",
        "SELECT ime, prezime, dob FROM studenti WHERE dob > 23 ORDER BY dob DESC",
        "Uvjet se piše u WHERE dijelu upita.",
    ),
    (
        "fakultet",
        "Studenti iz Zagreba",
        "Ispišite ime i prezime studenata koji dolaze iz Zagreba.",
        "početnik",
        "WHERE",
        "SELECT ime, prezime FROM studenti WHERE grad = 'Zagreb'",
        "Tekstualne vrijednosti pišu se pod jednostrukim navodnicima.",
    ),
    (
        "fakultet",
        "Broj studenata po smjeru",
        "Za svaki smjer ispišite naziv smjera i broj studenata upisanih na taj smjer. "
        "Rezultat sortirajte po broju studenata silazno.",
        "srednji",
        "JOIN, GROUP BY",
        "SELECT s.naziv, COUNT(st.id) AS broj "
        "FROM smjerovi s JOIN studenti st ON st.smjer_id = s.id "
        "GROUP BY s.naziv ORDER BY broj DESC",
        "Spojite tablice s JOIN, zatim grupirajte po nazivu smjera.",
    ),
    (
        "fakultet",
        "Prosječna ocjena po kolegiju",
        "Za svaki kolegij ispišite naziv i prosječnu ocjenu zaokruženu na dvije "
        "decimale. Prikažite samo kolegije koji imaju barem dva upisa, sortirano "
        "po prosjeku silazno.",
        "srednji",
        "JOIN, GROUP BY, HAVING",
        "SELECT k.naziv, ROUND(AVG(u.ocjena), 2) AS prosjek "
        "FROM kolegiji k JOIN upisi u ON u.kolegij_id = k.id "
        "GROUP BY k.naziv HAVING COUNT(u.id) >= 2 ORDER BY prosjek DESC",
        "HAVING filtrira grupe nakon GROUP BY, za razliku od WHERE koji filtrira retke.",
    ),
    (
        "fakultet",
        "Studenti bez ijednog upisa",
        "Ispišite ime i prezime studenata koji nisu upisali nijedan kolegij.",
        "napredni",
        "LEFT JOIN, NULL",
        "SELECT s.ime, s.prezime FROM studenti s "
        "LEFT JOIN upisi u ON u.student_id = s.id "
        "WHERE u.id IS NULL",
        "LEFT JOIN zadržava sve studente; oni bez para imaju NULL u stupcima "
        "druge tablice.",
    ),
    # --- WEB TRGOVINA -------------------------------------------------------
    (
        "webshop",
        "Proizvodi kojih nema na stanju",
        "Ispišite naziv i cijenu svih proizvoda kojih nema na stanju.",
        "početnik",
        "WHERE",
        "SELECT naziv, cijena FROM proizvodi WHERE na_stanju = 0",
        "Tražite proizvode kod kojih je stanje jednako nuli.",
    ),
    (
        "webshop",
        "Najskuplji proizvod po kategoriji",
        "Za svaku kategoriju ispišite naziv kategorije i najvišu cijenu proizvoda "
        "u njoj, sortirano po nazivu kategorije.",
        "srednji",
        "JOIN, GROUP BY, MAX",
        "SELECT k.naziv, MAX(p.cijena) AS max_cijena "
        "FROM kategorije k JOIN proizvodi p ON p.kategorija_id = k.id "
        "GROUP BY k.naziv ORDER BY k.naziv",
        "Agregatna funkcija MAX radi nad grupama definiranim s GROUP BY.",
    ),
    (
        "webshop",
        "Ukupan broj naručenih komada po proizvodu",
        "Ispišite naziv proizvoda i ukupan broj naručenih komada, ali samo za "
        "narudžbe koje nisu otkazane. Sortirajte silazno po broju komada.",
        "napredni",
        "višestruki JOIN, SUM",
        "SELECT p.naziv, SUM(s.kolicina) AS ukupno "
        "FROM proizvodi p "
        "JOIN stavke s ON s.proizvod_id = p.id "
        "JOIN narudzbe n ON n.id = s.narudzba_id "
        "WHERE n.status <> 'otkazano' "
        "GROUP BY p.naziv ORDER BY ukupno DESC",
        "Trebate spojiti tri tablice i filtrirati status narudžbe prije grupiranja.",
    ),
    (
        "webshop",
        "Kupci s više od jedne narudžbe",
        "Ispišite ime i prezime kupaca koji imaju više od jedne narudžbe, "
        "zajedno s brojem njihovih narudžbi.",
        "srednji",
        "JOIN, GROUP BY, HAVING",
        "SELECT k.ime, k.prezime, COUNT(n.id) AS broj "
        "FROM kupci k JOIN narudzbe n ON n.kupac_id = k.id "
        "GROUP BY k.id, k.ime, k.prezime HAVING COUNT(n.id) > 1",
        "Grupirajte po kupcu i ograničite grupe s HAVING.",
    ),
    # --- KNJIŽNICA ----------------------------------------------------------
    (
        "knjiznica",
        "Knjige objavljene prije 1950.",
        "Ispišite naslov i godinu izdanja svih knjiga objavljenih prije 1950. "
        "godine, sortirano po godini uzlazno.",
        "početnik",
        "WHERE, ORDER BY",
        "SELECT naslov, godina FROM knjige WHERE godina < 1950 ORDER BY godina",
        "Usporedba brojeva ne traži navodnike.",
    ),
    (
        "knjiznica",
        "Nevraćene knjige",
        "Ispišite ime i prezime člana te naslov knjige za sve posudbe koje još "
        "nisu vraćene.",
        "srednji",
        "JOIN, NULL",
        "SELECT c.ime, c.prezime, k.naslov "
        "FROM posudbe p "
        "JOIN clanovi c ON c.id = p.clan_id "
        "JOIN knjige k ON k.id = p.knjiga_id "
        "WHERE p.datum_povrata IS NULL",
        "Nevraćena posudba prepoznaje se po NULL vrijednosti datuma povrata. "
        "Za usporedbu s NULL koristi se IS NULL, a ne = NULL.",
    ),
    (
        "knjiznica",
        "Broj knjiga po autoru",
        "Ispišite ime i prezime autora te broj njegovih knjiga. Uključite i autore "
        "koji nemaju nijednu knjigu. Sortirajte silazno po broju knjiga.",
        "napredni",
        "LEFT JOIN, GROUP BY",
        "SELECT a.ime, a.prezime, COUNT(k.id) AS broj_knjiga "
        "FROM autori a LEFT JOIN knjige k ON k.autor_id = a.id "
        "GROUP BY a.id, a.ime, a.prezime ORDER BY broj_knjiga DESC",
        "COUNT(stupac) ne broji NULL vrijednosti, za razliku od COUNT(*).",
    ),
    (
        "knjiznica",
        "Najposuđivanija knjiga",
        "Ispišite naslov knjige koja je najčešće posuđivana i broj posudbi.",
        "napredni",
        "JOIN, GROUP BY, LIMIT",
        "SELECT k.naslov, COUNT(p.id) AS broj "
        "FROM knjige k JOIN posudbe p ON p.knjiga_id = k.id "
        "GROUP BY k.id, k.naslov ORDER BY broj DESC LIMIT 1",
        "Sortirajte silazno i ograničite rezultat s LIMIT 1.",
    ),
]
