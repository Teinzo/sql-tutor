"""Testovi API sučelja: autentikacija, zadaci, predaja, statistika i panel.

AI rute nisu pokrivene jer zahtijevaju vanjski poziv jezičnom modelu; njihova
logika obrade odgovora testira se zasebno u test_ai_service.py.
"""

import uuid


# ---------------------------------------------------------------------------
# Autentikacija
# ---------------------------------------------------------------------------
def test_registracija_i_prijava(klijent):
    ime = f"test_{uuid.uuid4().hex[:8]}"

    r = klijent.post("/api/register", json={"username": ime, "password": "tajna123"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "student"

    klijent.post("/api/logout")

    r = klijent.post("/api/login", json={"username": ime, "password": "tajna123"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == ime


def test_dupli_korisnik_je_odbijen(klijent):
    ime = f"test_{uuid.uuid4().hex[:8]}"
    klijent.post("/api/register", json={"username": ime, "password": "tajna123"})
    klijent.post("/api/logout")

    r = klijent.post("/api/register", json={"username": ime, "password": "tajna123"})
    assert r.status_code == 400
    assert "postoji" in r.json()["detail"]


def test_pogresna_lozinka_vraca_401(klijent):
    r = klijent.post("/api/login", json={"username": "student", "password": "krivo"})
    assert r.status_code == 401


def test_prekratko_korisnicko_ime_je_odbijeno(klijent):
    r = klijent.post("/api/register", json={"username": "ab", "password": "tajna123"})
    assert r.status_code == 422


def test_nedopusteni_znakovi_u_imenu(klijent):
    r = klijent.post(
        "/api/register", json={"username": "ime s razmakom", "password": "tajna123"}
    )
    assert r.status_code == 400


def test_neprijavljen_korisnik_ne_moze_do_zadataka(klijent):
    assert klijent.get("/api/tasks").status_code == 401
    assert klijent.get("/api/progress").status_code == 401
    assert klijent.post("/api/submit", json={"task_id": 1, "query": "x"}).status_code == 401


def test_lozinka_se_ne_pohranjuje_u_citljivom_obliku():
    from auth import hash_password, verify_password

    sazetak = hash_password("mojaLozinka")
    assert "mojaLozinka" not in sazetak
    assert sazetak.startswith("pbkdf2_sha256$")
    assert verify_password("mojaLozinka", sazetak)
    assert not verify_password("drugaLozinka", sazetak)


def test_ista_lozinka_daje_razlicite_sazetke():
    """Nasumična sol znači da dva korisnika s istom lozinkom imaju različit zapis."""
    from auth import hash_password

    assert hash_password("ista") != hash_password("ista")


# ---------------------------------------------------------------------------
# Zadaci
# ---------------------------------------------------------------------------
def test_popis_zadataka(student):
    r = student.get("/api/tasks")
    assert r.status_code == 200
    zadaci = r.json()["tasks"]
    assert len(zadaci) > 0
    assert "solution_sql" not in zadaci[0], "Rješenje ne smije biti vidljivo studentu"


def test_filtriranje_po_shemi(student):
    r = student.get("/api/tasks?schema_id=knjiznica")
    assert r.status_code == 200
    assert all(z["schema_id"] == "knjiznica" for z in r.json()["tasks"])


def test_detalji_zadatka_bez_rjesenja_za_studenta(student):
    r = student.get("/api/tasks/1")
    assert r.status_code == 200
    podaci = r.json()
    assert "solution_sql" not in podaci["task"]
    assert "tablice" in podaci["schema"]


def test_nastavnik_vidi_referentno_rjesenje(nastavnik):
    r = nastavnik.get("/api/tasks/1")
    assert r.status_code == 200
    assert "solution_sql" in r.json()["task"]


def test_nepostojeci_zadatak_vraca_404(student):
    assert student.get("/api/tasks/999999").status_code == 404


def test_izvrsavanje_upita(student):
    r = student.post(
        "/api/run", json={"schema_id": "fakultet", "query": "SELECT * FROM studenti"}
    )
    assert r.status_code == 200
    podaci = r.json()
    assert podaci["uspjeh"] is True
    assert podaci["broj_redaka"] == 10


def test_izvrsavanje_zabranjenog_upita(student):
    r = student.post(
        "/api/run", json={"schema_id": "fakultet", "query": "DROP TABLE studenti"}
    )
    assert r.status_code == 200
    assert r.json()["uspjeh"] is False


def test_pregled_sheme(student):
    r = student.get("/api/schema-preview/webshop")
    assert r.status_code == 200
    assert "proizvodi" in r.json()["tablice"]


def test_nepoznata_shema_vraca_404(student):
    assert student.get("/api/schema-preview/nepostojeca").status_code == 404


# ---------------------------------------------------------------------------
# Predaja rješenja
# ---------------------------------------------------------------------------
def test_tocna_predaja(student):
    r = student.post(
        "/api/submit",
        json={
            "task_id": 1,
            "query": "SELECT ime, prezime FROM studenti ORDER BY prezime",
            "trazi_ai_povratnu": False,
        },
    )
    assert r.status_code == 200
    podaci = r.json()
    assert podaci["is_correct"] is True
    assert podaci["status"] == "tocno"


def test_netocna_predaja(student):
    r = student.post(
        "/api/submit",
        json={
            "task_id": 1,
            "query": "SELECT ime FROM studenti",
            "trazi_ai_povratnu": False,
        },
    )
    assert r.status_code == 200
    assert r.json()["is_correct"] is False


def test_predaja_se_biljezi_u_povijesti(student):
    student.post(
        "/api/submit",
        json={
            "task_id": 2,
            "query": "SELECT ime, prezime, dob FROM studenti WHERE dob > 23 ORDER BY dob DESC",
            "trazi_ai_povratnu": False,
        },
    )
    r = student.get("/api/tasks/2")
    assert len(r.json()["attempts"]) > 0


def test_predaja_na_nepostojeci_zadatak(student):
    r = student.post(
        "/api/submit",
        json={"task_id": 999999, "query": "SELECT 1", "trazi_ai_povratnu": False},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Napredak i anketa
# ---------------------------------------------------------------------------
def test_statistika_napretka(student):
    student.post(
        "/api/submit",
        json={
            "task_id": 1,
            "query": "SELECT ime, prezime FROM studenti ORDER BY prezime",
            "trazi_ai_povratnu": False,
        },
    )

    r = student.get("/api/progress")
    assert r.status_code == 200
    podaci = r.json()
    assert podaci["sazetak"]["ukupno_predaja"] > 0
    assert podaci["sazetak"]["rijeseno_zadataka"] >= 1
    assert 0 <= podaci["sazetak"]["postotak_tocnosti"] <= 100
    assert isinstance(podaci["po_tezini"], list)


def test_slanje_ankete(student):
    r = student.post(
        "/api/survey",
        json={
            "korisnost": 5,
            "jasnoca": 4,
            "kvaliteta_ai": 5,
            "sucelje": 4,
            "preporuka": 5,
            "komentar": "Testni komentar.",
        },
    )
    assert r.status_code == 200
    assert student.get("/api/survey/mine").json()["ispunjena"] is True


def test_ponovna_anketa_azurira_umjesto_da_dupla(student):
    """Jedan ispitanik smije imati tocno jedan odgovor.

    Bez toga bi isti student mogao visestruko utjecati na prosjeke, cime bi
    rezultati evaluacije sustava postali neupotrebljivi.
    """
    import database

    odgovor = {
        "korisnost": 3,
        "jasnoca": 3,
        "kvaliteta_ai": 3,
        "sucelje": 3,
        "preporuka": 3,
        "komentar": "Prvi odgovor.",
    }
    assert student.post("/api/survey", json=odgovor).status_code == 200

    odgovor["korisnost"] = 5
    odgovor["komentar"] = "Ispravljeni odgovor."
    assert student.post("/api/survey", json=odgovor).status_code == 200

    conn = database.get_connection()
    try:
        red = conn.execute(
            """SELECT COUNT(*) AS broj,
                      MAX(korisnost) AS korisnost,
                      MAX(komentar)  AS komentar
               FROM survey
               WHERE user_id = (SELECT id FROM users WHERE username = 'student')"""
        ).fetchone()
    finally:
        conn.close()

    assert red["broj"] == 1
    assert red["korisnost"] == 5
    assert red["komentar"] == "Ispravljeni odgovor."


def test_ocjena_izvan_raspona_je_odbijena(student):
    r = student.post(
        "/api/survey",
        json={
            "korisnost": 9,
            "jasnoca": 4,
            "kvaliteta_ai": 5,
            "sucelje": 4,
            "preporuka": 5,
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Nastavnički panel
# ---------------------------------------------------------------------------
def test_student_nema_pristup_panelu(student):
    assert student.get("/api/admin/overview").status_code == 403
    assert student.get("/api/admin/students").status_code == 403


def test_nastavnik_ima_pristup_panelu(nastavnik):
    r = nastavnik.get("/api/admin/overview")
    assert r.status_code == 200
    assert "studenata" in r.json()

    assert nastavnik.get("/api/admin/students").status_code == 200
    assert nastavnik.get("/api/admin/task-stats").status_code == 200
    assert nastavnik.get("/api/admin/survey-results").status_code == 200


def test_student_ne_moze_brisati_zadatke(student):
    assert student.delete("/api/tasks/1").status_code == 403


# ---------------------------------------------------------------------------
# Stranice
# ---------------------------------------------------------------------------
def test_javne_stranice_se_ucitavaju(klijent):
    for putanja in ["/", "/login", "/register"]:
        assert klijent.get(putanja).status_code == 200


def test_zasticene_stranice_preusmjeravaju_na_prijavu(klijent):
    for putanja in ["/dashboard", "/tasks", "/chat", "/progress", "/admin"]:
        r = klijent.get(putanja, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"


def test_prijavljen_student_vidi_stranice(student):
    for putanja in ["/dashboard", "/tasks", "/tasks/1", "/chat",
                    "/generate", "/progress", "/survey"]:
        assert student.get(putanja).status_code == 200, putanja


def test_student_ne_vidi_nastavnicku_stranicu(student):
    r = student.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_provjera_zdravlja(klijent):
    r = klijent.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_popis_shema(klijent):
    r = klijent.get("/api/schemas")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["schemas"]]
    assert {"fakultet", "webshop", "knjiznica"}.issubset(set(ids))
