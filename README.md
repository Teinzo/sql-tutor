# SQL Tutor

Web aplikacija za učenje SQL-a temeljena na umjetnoj inteligenciji.

Završni rad — *Razvoj i evaluacija web aplikacije za učenje SQL-a temeljene na
umjetnoj inteligenciji*.

---

## Pokretanje

```bash
# 1. Virtualno okruženje
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

# 2. Ovisnosti
pip install -r requirements.txt

# 3. Konfiguracija
copy .env.example .env         # Windows   (Linux/macOS: cp .env.example .env)
# u .env upišite svoj OPENAI_API_KEY

# 4. Provjera postavki (neobavezno, ali preporučeno)
python provjeri_postavke.py

# 5. Pokretanje
uvicorn main:app --reload
```

Aplikacija je zatim dostupna na <http://localhost:8000>.

### Demo računi

Pri prvom pokretanju prazne baze kreiraju se dva računa za lokalni prikaz:

| Korisničko ime | Lozinka        | Uloga     |
|----------------|----------------|-----------|
| `student`      | `student123`   | student   |
| `nastavnik`    | `nastavnik123` | nastavnik |

> **Ove lozinke su javne.** Namijenjene su isključivo lokalnom pokretanju.
> Ako aplikaciju činite dostupnom drugima, postavite `DEMO_LOZINKA_NASTAVNIK` i
> `DEMO_LOZINKA_STUDENT` u `.env` prije prvog pokretanja, ili obrišite račune
> nakon što napravite vlastiti. Aplikacija ispisuje upozorenje dok su zadane
> lozinke na snazi.

---

## Konfiguracija (`.env`)

| Varijabla                    | Opis                                     | Zadano                               |
|------------------------------|------------------------------------------|--------------------------------------|
| `OPENAI_API_KEY`             | API ključ s <https://platform.openai.com/api-keys> | —                          |
| `OPENAI_MODEL`               | Glavni jezični model                     | `gpt-5.6-luna`                       |
| `OPENAI_FALLBACK_MODEL`      | Pričuvni model                           | `gpt-4o-mini`                        |
| `SESSION_HOURS`              | Trajanje prijave u satima                | `12`                                 |
| `LLM_TIMEOUT`                | Vremensko ograničenje poziva modela (s)  | `60`                                 |
| `LLM_MAX_RETRIES`            | Broj ponovnih pokušaja kod grešaka       | `3`                                  |
| `DEMO_LOZINKA_NASTAVNIK`     | Lozinka demo nastavničkog računa         | `nastavnik123`                       |
| `DEMO_LOZINKA_STUDENT`       | Lozinka demo studentskog računa          | `student123`                         |

Model se mijenja isključivo u `.env`, bez diranja koda.

**Pričuvni model.** Ako glavni model vrati 404 (model povučen ili nedostupan
računu), aplikacija automatski nastavlja s pričuvnim modelom umjesto da ostane
bez AI funkcionalnosti. To je važno tijekom demonstracije sustava.

Potrošeni krediti prepoznaju se zasebno: OpenAI ih javlja statusom 429 s oznakom
`insufficient_quota`, isto kao i ograničenje broja zahtjeva. Aplikacija razlikuje
ta dva slučaja i kod potrošenih kredita odmah javlja jasnu poruku umjesto da
uzalud ponavlja poziv.

Izbor modela:

```
OPENAI_MODEL=gpt-5.6-luna     # najjeftinije, dovoljno za chat i zadatke
OPENAI_MODEL=gpt-5.6-terra    # bolja kvaliteta, ~10x skuplje
OPENAI_MODEL=gpt-4o-mini      # starije, ali provjereno i vrlo jeftino
```

Ako ključ nije postavljen, aplikacija se svejedno pokreće: zadaci, izvršavanje
upita i automatska provjera rješenja rade normalno, a AI funkcionalnosti javljaju
jasnu poruku.

---

## Struktura projekta

```
sql-tutor/
├── main.py                 Ulazna točka: FastAPI, rute stranica
├── config.py               Konfiguracija iz .env
├── database.py             Shema baze, migracija, početni podaci
├── schemas.py              Vježbovne sheme baza (fakultet, web trgovina, knjižnica)
├── auth.py                 PBKDF2 lozinke, sesije, kontrola pristupa
├── sql_runner.py           Sigurno izvršavanje i ocjenjivanje upita
├── ai_service.py           Poziv jezičnog modela (OpenAI)
├── routes_auth.py          API: registracija, prijava, odjava
├── routes_tasks.py         API: zadaci, izvršavanje upita, predaja rješenja
├── routes_ai.py            API: chatbot, generiranje zadataka
├── routes_stats.py         API: napredak, anketa
├── routes_admin.py         API: nastavnički panel
├── provjeri_postavke.py    Dijagnostika konfiguracije
├── templates/              Jinja2 predlošci
├── static/                 CSS i JavaScript
└── tests/                  Automatski testovi (pytest)
```

---

## Funkcionalnosti

### Za studenta

- **Zadaci** — filtriranje po shemi baze, razini težine i statusu rješenosti
- **SQL uređivač** — izvršavanje upita (`Ctrl` + `Enter`) i prikaz rezultata prije predaje
- **Automatska provjera** — usporedba rezultata s referentnim rješenjem
- **AI povratna informacija** — objašnjenje greške bez otkrivanja rješenja
- **AI tutor** — chatbot koji potpitanjima vodi prema rješenju
- **Generiranje zadataka** — nova vježba prema temi i razini težine
- **Napredak** — statistika po temama, razinama težine i shemama baza
- **Anketa** — evaluacija sustava u pet dimenzija

### Za nastavnika

- Pregled korištenja sustava i uspješnosti studenata
- Uspješnost po pojedinom zadatku (otkriva prezahtjevne ili nejasne zadatke)
- Zbirni rezultati ankete s komentarima
- Brisanje zadataka
- Uvid u referentna rješenja

---

## Kako radi ocjenjivanje

Ocjenjivanje je **dvoslojno**:

1. **Deterministički sloj** (`sql_runner.py`) — studentov upit i referentno
   rješenje izvršavaju se nad istom bazom u memoriji, a rezultati se uspoređuju.
   Ovaj sloj daje pouzdanu ocjenu točno/netočno i prepoznaje tipične greške
   (pogrešan broj stupaca, pogrešan redoslijed, pogrešan uvjet filtriranja).

2. **AI sloj** (`ai_service.py`) — jezičnom modelu prosljeđuje se **rezultat
   prvog sloja**, pa model ne mora pogađati je li upit točan nego objašnjava
   *zašto*. Time se izbjegava najčešći problem AI ocjenjivanja: model koji
   samouvjereno proglasi netočan upit točnim.

Ako AI sloj zakaže (nema ključa, model nedostupan), ocjena iz prvog sloja i
dalje vrijedi.

### Sigurnost izvršavanja upita

Studentov upit izvršava se nad **privremenom bazom u memoriji** koja se gradi
iznova pri svakom pozivu — glavna baza aplikacije nedostupna mu je. Dodatno se
prije izvršavanja provjerava da upit:

- počinje sa `SELECT` ili `WITH`,
- sadrži samo jedan izraz (nema `;` za nadovezivanje naredbi),
- ne sadrži naredbe koje mijenjaju podatke ili shemu (`DROP`, `DELETE`, `INSERT`,
  `UPDATE`, `ATTACH`, `PRAGMA`, …),
- ne pristupa internim tablicama SQLite-a (`sqlite_master`),
- ne traje dulje od 5 sekundi.

Komentari se uklanjaju prije provjere kako se zabranjene naredbe ne bi mogle
sakriti, a tekstualni literali se zanemaruju kako riječ poput `'delete'` u
podacima ne bi lažno okinula provjeru.

---

## Testiranje

```bash
pytest              # svi testovi
pytest -v           # s popisom pojedinačnih testova
```

Testovi koriste privremenu bazu i **ne troše AI kredite** — pozivi jezičnom
modelu zamijenjeni su lažnim odgovorima (`monkeypatch`).

| Datoteka                    | Što pokriva                                                    |
|-----------------------------|----------------------------------------------------------------|
| `tests/test_sql_runner.py`  | Sigurnosna provjera upita, izvršavanje, logika ocjenjivanja    |
| `tests/test_api.py`         | Autentikacija, kontrola pristupa, zadaci, predaja, statistika  |
| `tests/test_ai_service.py`  | Obrada odgovora modela, sastavljanje razgovora, otpornost      |

---

## Baza podataka

SQLite (`sql_tutor.db`), kreira se automatski pri prvom pokretanju.

| Tablica       | Sadržaj                                                    |
|---------------|------------------------------------------------------------|
| `users`       | Korisnici i uloge (`student`, `nastavnik`)                 |
| `sessions`    | Aktivne prijave (token, istek)                             |
| `tasks`       | Zadaci s referentnim rješenjem i uputom                    |
| `submissions` | Predana rješenja s ocjenom i povratnom informacijom        |
| `chat_logs`   | Razgovori s AI tutorom (za evaluaciju sustava)             |
| `survey`      | Odgovori na anketu                                         |

Shema je verzionirana pomoću `PRAGMA user_version`. Pri promjeni verzije stare
tablice se odbacuju i grade iznova — prikladno za razvoj, ne za produkciju.

### Vježbovne sheme

Zadaci se rješavaju nad jednom od tri neovisne sheme:

| Shema           | Tablice                                        | Pogodno za                          |
|-----------------|------------------------------------------------|-------------------------------------|
| **Fakultet**    | `smjerovi`, `studenti`, `kolegiji`, `upisi`    | osnovni upiti, `JOIN`, `GROUP BY`   |
| **Web trgovina**| `kategorije`, `kupci`, `proizvodi`, `narudzbe`, `stavke` | agregacije, `HAVING`, podupiti |
| **Knjižnica**   | `autori`, `knjige`, `clanovi`, `posudbe`       | `NULL`, `LEFT JOIN`, datumi         |

Nova shema dodaje se upisom u rječnik `SCHEMAS` u `schemas.py` — nije potrebna
nikakva promjena drugdje u kodu.

---

## Tehnologije

| Sloj        | Tehnologija                              |
|-------------|------------------------------------------|
| Poslužitelj | Python 3.10+, FastAPI, Uvicorn           |
| Baza        | SQLite                                   |
| Sučelje     | Jinja2, HTML, CSS, JavaScript (bez okvira)|
| AI          | OpenAI API (zamjenjiv model)             |
| Testiranje  | pytest, Starlette TestClient             |

---

## API

Interaktivna dokumentacija generira se automatski i dostupna je na
<http://localhost:8000/docs> dok aplikacija radi.
