"""Vježbovne sheme baza podataka.

Svaka shema opisuje jednu malu, samostalnu bazu koja se pri svakom izvršavanju
upita iznova kreira u memoriji (SQLite ":memory:"). Time je studentov upit
potpuno izoliran od glavne baze aplikacije.
"""

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# 1. FAKULTET - osnovni SELECT, WHERE, ORDER BY, JOIN, GROUP BY
# ---------------------------------------------------------------------------
FAKULTET_DDL = """
CREATE TABLE smjerovi (
    id       INTEGER PRIMARY KEY,
    naziv    TEXT NOT NULL,
    trajanje INTEGER NOT NULL
);

CREATE TABLE studenti (
    id       INTEGER PRIMARY KEY,
    ime      TEXT NOT NULL,
    prezime  TEXT NOT NULL,
    dob      INTEGER,
    smjer_id INTEGER,
    godina   INTEGER,
    grad     TEXT,
    FOREIGN KEY (smjer_id) REFERENCES smjerovi(id)
);

CREATE TABLE kolegiji (
    id       INTEGER PRIMARY KEY,
    naziv    TEXT NOT NULL,
    ects     INTEGER NOT NULL,
    smjer_id INTEGER,
    FOREIGN KEY (smjer_id) REFERENCES smjerovi(id)
);

CREATE TABLE upisi (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER,
    kolegij_id INTEGER,
    ocjena     INTEGER,
    datum      TEXT,
    FOREIGN KEY (student_id) REFERENCES studenti(id),
    FOREIGN KEY (kolegij_id) REFERENCES kolegiji(id)
);

INSERT INTO smjerovi (id, naziv, trajanje) VALUES
    (1, 'Informatika', 3),
    (2, 'Matematika', 3),
    (3, 'Fizika', 3),
    (4, 'Ekonomija', 4);

INSERT INTO studenti (id, ime, prezime, dob, smjer_id, godina, grad) VALUES
    (1,  'Ana',      'Horvat',  22, 1, 3, 'Zagreb'),
    (2,  'Ivan',     'Kovač',   28, 2, 2, 'Split'),
    (3,  'Maja',     'Perić',   24, 1, 2, 'Rijeka'),
    (4,  'Luka',     'Novak',   26, 3, 1, 'Osijek'),
    (5,  'Sara',     'Jurić',   21, 1, 1, 'Zagreb'),
    (6,  'Marko',    'Babić',   23, 4, 3, 'Zadar'),
    (7,  'Petra',    'Vuković', 25, 2, 3, 'Zagreb'),
    (8,  'Nikola',   'Marić',   20, 1, 1, 'Split'),
    (9,  'Iva',      'Radić',   27, 4, 4, 'Rijeka'),
    (10, 'Tomislav', 'Kralj',   22, 3, 2, 'Varaždin');

INSERT INTO kolegiji (id, naziv, ects, smjer_id) VALUES
    (1, 'Baze podataka',         6, 1),
    (2, 'Programiranje',         7, 1),
    (3, 'Matematička analiza',   8, 2),
    (4, 'Linearna algebra',      6, 2),
    (5, 'Kvantna mehanika',      7, 3),
    (6, 'Mikroekonomija',        5, 4),
    (7, 'Umjetna inteligencija', 6, 1);

INSERT INTO upisi (id, student_id, kolegij_id, ocjena, datum) VALUES
    (1,  1,  1, 5, '2025-02-10'),
    (2,  1,  2, 4, '2025-02-12'),
    (3,  1,  7, 5, '2025-06-01'),
    (4,  3,  1, 3, '2025-02-10'),
    (5,  3,  2, 4, '2025-02-12'),
    (6,  5,  1, 2, '2025-02-10'),
    (7,  5,  7, 3, '2025-06-01'),
    (8,  8,  2, 5, '2025-02-12'),
    (9,  2,  3, 4, '2025-02-15'),
    (10, 2,  4, 3, '2025-02-16'),
    (11, 7,  3, 5, '2025-02-15'),
    (12, 4,  5, 4, '2025-03-01'),
    (13, 10, 5, 2, '2025-03-01'),
    (14, 6,  6, 5, '2025-02-20'),
    (15, 9,  6, 4, '2025-02-20');
"""

# ---------------------------------------------------------------------------
# 2. WEB TRGOVINA - agregacije, višestruki JOIN, HAVING, podupiti
# ---------------------------------------------------------------------------
WEBSHOP_DDL = """
CREATE TABLE kategorije (
    id    INTEGER PRIMARY KEY,
    naziv TEXT NOT NULL
);

CREATE TABLE kupci (
    id          INTEGER PRIMARY KEY,
    ime         TEXT NOT NULL,
    prezime     TEXT NOT NULL,
    email       TEXT,
    grad        TEXT,
    registriran TEXT
);

CREATE TABLE proizvodi (
    id            INTEGER PRIMARY KEY,
    naziv         TEXT NOT NULL,
    cijena        REAL NOT NULL,
    kategorija_id INTEGER,
    na_stanju     INTEGER,
    FOREIGN KEY (kategorija_id) REFERENCES kategorije(id)
);

CREATE TABLE narudzbe (
    id       INTEGER PRIMARY KEY,
    kupac_id INTEGER,
    datum    TEXT,
    status   TEXT,
    FOREIGN KEY (kupac_id) REFERENCES kupci(id)
);

CREATE TABLE stavke (
    id          INTEGER PRIMARY KEY,
    narudzba_id INTEGER,
    proizvod_id INTEGER,
    kolicina    INTEGER,
    FOREIGN KEY (narudzba_id) REFERENCES narudzbe(id),
    FOREIGN KEY (proizvod_id) REFERENCES proizvodi(id)
);

INSERT INTO kategorije (id, naziv) VALUES
    (1, 'Elektronika'), (2, 'Knjige'), (3, 'Odjeća'), (4, 'Sport');

INSERT INTO kupci (id, ime, prezime, email, grad, registriran) VALUES
    (1, 'Ana',   'Horvat', 'ana@mail.hr',   'Zagreb', '2024-01-15'),
    (2, 'Ivan',  'Kovač',  'ivan@mail.hr',  'Split',  '2024-03-02'),
    (3, 'Maja',  'Perić',  'maja@mail.hr',  'Rijeka', '2024-05-20'),
    (4, 'Luka',  'Novak',  'luka@mail.hr',  'Zagreb', '2025-01-08'),
    (5, 'Sara',  'Jurić',  'sara@mail.hr',  'Osijek', '2025-02-11'),
    (6, 'Marko', 'Babić',  'marko@mail.hr', 'Zagreb', '2025-04-30');

INSERT INTO proizvodi (id, naziv, cijena, kategorija_id, na_stanju) VALUES
    (1, 'Laptop Lenovo',           799.99, 1, 12),
    (2, 'Bežične slušalice',        59.90, 1, 40),
    (3, 'Pametni sat',             149.00, 1,  0),
    (4, 'Roman Zlatarovo zlato',    12.50, 2, 25),
    (5, 'Udžbenik SQL',             34.00, 2, 18),
    (6, 'Majica pamučna',           19.99, 3, 60),
    (7, 'Zimska jakna',            129.00, 3,  7),
    (8, 'Nogometna lopta',          29.90, 4, 15),
    (9, 'Tenisice za trčanje',      89.90, 4,  3);

INSERT INTO narudzbe (id, kupac_id, datum, status) VALUES
    (1, 1, '2025-03-01', 'isporučeno'),
    (2, 1, '2025-04-12', 'isporučeno'),
    (3, 2, '2025-04-15', 'otkazano'),
    (4, 3, '2025-05-02', 'isporučeno'),
    (5, 4, '2025-05-18', 'u obradi'),
    (6, 1, '2025-06-01', 'u obradi'),
    (7, 5, '2025-06-09', 'isporučeno');

INSERT INTO stavke (id, narudzba_id, proizvod_id, kolicina) VALUES
    (1,  1, 1, 1),
    (2,  1, 2, 2),
    (3,  2, 5, 1),
    (4,  2, 4, 3),
    (5,  3, 3, 1),
    (6,  4, 6, 4),
    (7,  4, 8, 1),
    (8,  5, 9, 2),
    (9,  6, 2, 1),
    (10, 6, 7, 1),
    (11, 7, 5, 2);
"""

# ---------------------------------------------------------------------------
# 3. KNJIŽNICA - rad s NULL vrijednostima, LEFT JOIN, datumi
# ---------------------------------------------------------------------------
KNJIZNICA_DDL = """
CREATE TABLE autori (
    id      INTEGER PRIMARY KEY,
    ime     TEXT NOT NULL,
    prezime TEXT NOT NULL,
    drzava  TEXT
);

CREATE TABLE knjige (
    id        INTEGER PRIMARY KEY,
    naslov    TEXT NOT NULL,
    autor_id  INTEGER,
    godina    INTEGER,
    zanr      TEXT,
    primjerci INTEGER,
    FOREIGN KEY (autor_id) REFERENCES autori(id)
);

CREATE TABLE clanovi (
    id       INTEGER PRIMARY KEY,
    ime      TEXT NOT NULL,
    prezime  TEXT NOT NULL,
    uclanjen TEXT,
    aktivan  INTEGER
);

CREATE TABLE posudbe (
    id            INTEGER PRIMARY KEY,
    clan_id       INTEGER,
    knjiga_id     INTEGER,
    datum_posudbe TEXT,
    datum_povrata TEXT,
    FOREIGN KEY (clan_id) REFERENCES clanovi(id),
    FOREIGN KEY (knjiga_id) REFERENCES knjige(id)
);

INSERT INTO autori (id, ime, prezime, drzava) VALUES
    (1, 'August',   'Šenoa',  'Hrvatska'),
    (2, 'Miroslav', 'Krleža', 'Hrvatska'),
    (3, 'George',   'Orwell', 'Velika Britanija'),
    (4, 'Jane',     'Austen', 'Velika Britanija'),
    (5, 'Ivo',      'Andrić', 'Bosna i Hercegovina');

INSERT INTO knjige (id, naslov, autor_id, godina, zanr, primjerci) VALUES
    (1, 'Zlatarovo zlato',               1, 1871, 'Povijesni roman', 4),
    (2, 'Seljačka buna',                 1, 1877, 'Povijesni roman', 2),
    (3, 'Povratak Filipa Latinovicza',   2, 1932, 'Roman',           3),
    (4, 'Gospoda Glembajevi',            2, 1928, 'Drama',           5),
    (5, '1984',                          3, 1949, 'Distopija',       6),
    (6, 'Životinjska farma',             3, 1945, 'Satira',          4),
    (7, 'Ponos i predrasude',            4, 1813, 'Roman',           3),
    (8, 'Na Drini ćuprija',              5, 1945, 'Roman',           2),
    (9, 'Anonimni zbornik',           NULL, 1990, 'Zbornik',         1);

INSERT INTO clanovi (id, ime, prezime, uclanjen, aktivan) VALUES
    (1, 'Ana',  'Horvat', '2023-09-01', 1),
    (2, 'Ivan', 'Kovač',  '2024-01-20', 1),
    (3, 'Maja', 'Perić',  '2024-06-15', 0),
    (4, 'Luka', 'Novak',  '2025-02-01', 1),
    (5, 'Sara', 'Jurić',  '2025-03-11', 1);

INSERT INTO posudbe (id, clan_id, knjiga_id, datum_posudbe, datum_povrata) VALUES
    (1, 1, 5, '2025-03-01', '2025-03-20'),
    (2, 1, 1, '2025-04-05', NULL),
    (3, 2, 5, '2025-04-10', '2025-04-25'),
    (4, 2, 6, '2025-05-01', NULL),
    (5, 3, 7, '2025-01-15', '2025-02-01'),
    (6, 4, 3, '2025-05-20', NULL),
    (7, 5, 5, '2025-06-01', '2025-06-15'),
    (8, 1, 8, '2025-06-10', NULL);
"""

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "fakultet": {
        "id": "fakultet",
        "naziv": "Fakultet",
        "opis": "Studenti, smjerovi, kolegiji i upisi s ocjenama. "
                "Pogodno za osnovne upite, filtriranje i spajanje tablica.",
        "ikona": "🎓",
        "ddl": FAKULTET_DDL,
        "tablice": {
            "smjerovi": ["id", "naziv", "trajanje"],
            "studenti": ["id", "ime", "prezime", "dob", "smjer_id", "godina", "grad"],
            "kolegiji": ["id", "naziv", "ects", "smjer_id"],
            "upisi": ["id", "student_id", "kolegij_id", "ocjena", "datum"],
        },
    },
    "webshop": {
        "id": "webshop",
        "naziv": "Web trgovina",
        "opis": "Kupci, proizvodi, narudžbe i stavke narudžbi. "
                "Pogodno za agregacije, GROUP BY, HAVING i višestruka spajanja.",
        "ikona": "🛒",
        "ddl": WEBSHOP_DDL,
        "tablice": {
            "kategorije": ["id", "naziv"],
            "kupci": ["id", "ime", "prezime", "email", "grad", "registriran"],
            "proizvodi": ["id", "naziv", "cijena", "kategorija_id", "na_stanju"],
            "narudzbe": ["id", "kupac_id", "datum", "status"],
            "stavke": ["id", "narudzba_id", "proizvod_id", "kolicina"],
        },
    },
    "knjiznica": {
        "id": "knjiznica",
        "naziv": "Knjižnica",
        "opis": "Autori, knjige, članovi i posudbe. "
                "Pogodno za rad s NULL vrijednostima, LEFT JOIN-om i datumima.",
        "ikona": "📚",
        "ddl": KNJIZNICA_DDL,
        "tablice": {
            "autori": ["id", "ime", "prezime", "drzava"],
            "knjige": ["id", "naslov", "autor_id", "godina", "zanr", "primjerci"],
            "clanovi": ["id", "ime", "prezime", "uclanjen", "aktivan"],
            "posudbe": ["id", "clan_id", "knjiga_id", "datum_posudbe", "datum_povrata"],
        },
    },
}

DEFAULT_SCHEMA = "fakultet"


def get_schema(schema_id: str) -> Dict[str, Any]:
    """Vraća definiciju sheme; ako ne postoji, vraća zadanu shemu."""
    return SCHEMAS.get(schema_id, SCHEMAS[DEFAULT_SCHEMA])


def get_ddl(schema_id: str) -> str:
    return get_schema(schema_id)["ddl"]


def schema_description(schema_id: str) -> str:
    """Tekstualni opis strukture sheme koji se šalje jezičnom modelu."""
    schema = get_schema(schema_id)
    redovi: List[str] = []
    for tablica, stupci in schema["tablice"].items():
        redovi.append(f"- {tablica}({', '.join(stupci)})")
    return "\n".join(redovi)


def list_schemas() -> List[Dict[str, Any]]:
    """Popis shema bez DDL-a (za prikaz u sučelju)."""
    return [
        {
            "id": s["id"],
            "naziv": s["naziv"],
            "opis": s["opis"],
            "ikona": s["ikona"],
            "tablice": s["tablice"],
        }
        for s in SCHEMAS.values()
    ]
