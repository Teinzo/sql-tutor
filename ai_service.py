"""Sloj za komunikaciju s velikim jezičnim modelom (OpenAI API).

Objedinjuje tri AI funkcionalnosti sustava:
  1. chat_with_tutor    - sokratski chatbot tutor
  2. generate_sql_tasks - automatsko generiranje zadataka
  3. evaluate_query     - kvalitativna evaluacija studentovog rješenja
"""

import json
import random
import re
import secrets
import time
from typing import Any, Dict, List, Optional

import requests

from config import (
    LLM_API_KEY,
    LLM_FALLBACK_MODEL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_RETRY_BACKOFF,
    LLM_TIMEOUT,
    LLM_URL,
    is_llm_configured,
)
from schemas import schema_description


class AIError(Exception):
    """Greška u komunikaciji s jezičnim modelom."""


# ---------------------------------------------------------------------------
# Niska razina: poziv API-ja
# ---------------------------------------------------------------------------
def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }


def _poruka_greske(odgovor: "requests.Response") -> str:
    """Izvlači tekst greške iz odgovora API-ja, bez obzira na oblik."""
    try:
        return str(odgovor.json().get("error", {}).get("message", ""))
    except ValueError:
        return odgovor.text[:200]


# Jedna sesija za sve pozive: veza i TLS rukovanje se ponovno koriste, čime se
# svakom sljedećem pozivu ušteđuje nekoliko stotina milisekundi.
_sesija = requests.Session()


def call_llm(
    messages: List[Dict[str, str]],
    max_tokens: int = 700,
    temperature: float = 0.7,
    model: Optional[str] = None,
) -> str:
    """Šalje razgovor modelu i vraća tekst odgovora.

    Poziv se ponavlja kod privremenih grešaka (429, 5xx) uz eksponencijalno čekanje.
    """
    if not is_llm_configured():
        raise AIError("OPENAI_API_KEY nije postavljen. Dodajte ga u .env datoteku.")

    model_u_upotrebi = model or LLM_MODEL

    payload = {
        "model": model_u_upotrebi,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    zadnja_greska = ""
    pricuva_iskoristena = False

    def _prijedi_na_pricuvu(razlog: str) -> bool:
        """Prebacuje zahtjev na pričuvni model. Vraća False ako to nije moguće."""
        nonlocal model_u_upotrebi, pricuva_iskoristena
        if (
            pricuva_iskoristena
            or not LLM_FALLBACK_MODEL
            or LLM_FALLBACK_MODEL == model_u_upotrebi
        ):
            return False
        print(
            f"[AI] {razlog} Prelazim s '{model_u_upotrebi}' na pričuvni model "
            f"'{LLM_FALLBACK_MODEL}'."
        )
        model_u_upotrebi = LLM_FALLBACK_MODEL
        payload["model"] = model_u_upotrebi
        pricuva_iskoristena = True
        return True

    def _prilagodi_parametre(poruka: str) -> bool:
        """Usklađuje payload s onim što traži konkretna obitelj modela.

        Noviji OpenAI modeli traže 'max_completion_tokens' umjesto 'max_tokens'
        i ne dopuštaju proizvoljan 'temperature'. Umjesto da tvrdo kodiramo koji
        model što podržava, čitamo poruku greške i prilagodimo se jednom.
        Vraća True ako je nešto promijenjeno i vrijedi ponoviti poziv.
        """
        p = poruka.lower()
        promijenjeno = False

        if "max_completion_tokens" in p and "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
            promijenjeno = True

        if "temperature" in p and "temperature" in payload:
            payload.pop("temperature")
            promijenjeno = True

        return promijenjeno

    # While umjesto for jer prilagodba parametara (400) ne smije trošiti
    # pokušaj - ona nije greška poslužitelja nego usklađivanje zahtjeva.
    # Petlja je omeđena: _prilagodi_parametre može vratiti True najviše dvaput.
    pokusaj = 0
    while pokusaj < LLM_MAX_RETRIES:
        pokusaj += 1

        try:
            odgovor = _sesija.post(
                LLM_URL,
                headers=_headers(),
                json=payload,
                timeout=LLM_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            zadnja_greska = "Model nije odgovorio na vrijeme."
            if pokusaj == LLM_MAX_RETRIES:
                break
            time.sleep(LLM_RETRY_BACKOFF * pokusaj)
            continue
        except requests.exceptions.RequestException as exc:
            raise AIError(f"Mrežna greška: {exc}") from exc

        if odgovor.status_code == 400:
            # Najčešće neusklađen parametar između obitelji modela.
            poruka = _poruka_greske(odgovor)
            if _prilagodi_parametre(poruka):
                pokusaj -= 1
                continue
            raise AIError(f"Neispravan zahtjev (400): {poruka}")

        if odgovor.status_code == 401:
            raise AIError(
                "Neispravan API ključ (401). Provjerite OPENAI_API_KEY u .env datoteci."
            )

        if odgovor.status_code == 429:
            poruka = _poruka_greske(odgovor)
            # OpenAI koristi 429 i za rate limit i za potrošene kredite.
            # Pričuvni model kod potrošenih kredita ne pomaže jer se kvota
            # odnosi na cijeli račun, pa odmah javljamo jasnu poruku.
            if "quota" in poruka.lower():
                raise AIError(
                    "Potrošeni krediti na OpenAI računu. Dopunite ih na "
                    "platform.openai.com pod Settings -> Billing."
                )
            zadnja_greska = "Previše zahtjeva u kratkom vremenu (429)."
            if pokusaj == LLM_MAX_RETRIES:
                break
            time.sleep(LLM_RETRY_BACKOFF * pokusaj)
            continue

        if odgovor.status_code in (500, 502, 503, 504):
            zadnja_greska = f"Privremena greška poslužitelja ({odgovor.status_code})."
            if pokusaj == LLM_MAX_RETRIES:
                break
            # Linearno, a ne eksponencijalno čekanje - eksponencijalno odgađanje
            # nepotrebno produljuje čekanje korisnika.
            time.sleep(LLM_RETRY_BACKOFF * pokusaj)
            continue

        if odgovor.status_code == 404:
            # Model je povučen, naziv je pogrešan ili račun nema pristup.
            if _prijedi_na_pricuvu(f"Model '{model_u_upotrebi}' nije pronađen (404)."):
                continue
            raise AIError(
                f"Model '{model_u_upotrebi}' nije dostupan ovom računu (404). "
                "Provjerite OPENAI_MODEL u .env datoteci."
            )

        try:
            podaci = odgovor.json()
        except ValueError as exc:
            raise AIError(f"Odgovor nije valjani JSON: {odgovor.text[:200]}") from exc

        if odgovor.status_code != 200:
            poruka = podaci.get("error", {}).get("message", odgovor.text[:200])
            raise AIError(f"Greška API-ja ({odgovor.status_code}): {poruka}")

        if "choices" not in podaci or not podaci["choices"]:
            raise AIError(f"Neočekivan odgovor modela: {str(podaci)[:200]}")

        sadrzaj = _ocisti_odgovor(
            podaci["choices"][0].get("message", {}).get("content") or ""
        )

        if not sadrzaj:
            # Modeli koji interno zaključuju znaju potrošiti cijeli budžet na
            # razmišljanje i vratiti prazan sadržaj.
            razlog = podaci["choices"][0].get("finish_reason", "nepoznato")
            raise AIError(
                f"Model je vratio prazan odgovor (finish_reason: {razlog}). "
                "Najčešći uzrok je premalen max_tokens kod modela koji dio "
                "budžeta troši na interno zaključivanje."
            )

        return sadrzaj

    raise AIError(
        f"{LLM_PROVIDER} nije odgovorio nakon {LLM_MAX_RETRIES} pokušaja. "
        f"{zadnja_greska}"
    )


# Oznake kojima modeli s eksplicitnim zaključivanjem omeđuju tijek razmišljanja.
MISAONE_OZNAKE = ("think", "thinking", "reasoning", "scratchpad", "analysis")

# Uvodne fraze kojima takvi modeli započnu ispis razmišljanja umjesto odgovora.
MISAONI_UVOD = re.compile(
    r"^\s*(here'?s?\s+(is\s+)?(a\s+|my\s+)?(thinking|thought|reasoning)"
    r"|thinking process"
    r"|let me think|let'?s think"
    r"|okay,?\s+so\s+the user|first,?\s+i need to)",
    re.IGNORECASE,
)

# Oznake iza kojih model prelazi s razmišljanja na stvarni odgovor.
KRAJ_RAZMISLJANJA = re.compile(
    r"(?:let'?s\s+draft\s+(?:a\s+|my\s+)?(?:response|answer)"
    r"|here'?s?\s+(?:is\s+)?my\s+(?:response|answer|reply)"
    r"|(?:final|draft(?:ed)?)\s+(?:response|answer)"
    r"|my\s+response\s+(?:will\s+be|is)"
    r"|response\s+to\s+the\s+user)"
    r"\s*[:\-–]?\s*",
    re.IGNORECASE,
)

# Tragovi po kojima se prepoznaje da je odgovor zapravo tijek razmišljanja.
TRAGOVI_RAZMISLJANJA = (
    "thinking process",
    "rules review",
    "let's draft",
    "my previous action",
    "**user input**",
    "i need to respond",
)


def _ocisti_odgovor(text: str) -> str:
    """Uklanja tijek razmišljanja koji neki modeli ispisuju uz odgovor.

    Modeli s eksplicitnim zaključivanjem (npr. besplatne inačice Nemotrona)
    znaju u sadržaj odgovora ubaciti vlastito razmišljanje, najčešće na
    engleskom. Studentu se to ne smije prikazati, a kod generiranja zadataka
    takav uvod nepotrebno troši budžet izlaznih tokena.
    """
    if not text:
        return ""

    for oznaka in MISAONE_OZNAKE:
        # Zatvoreni blok: <think> ... </think>
        text = re.sub(
            rf"<{oznaka}>.*?</{oznaka}>", " ", text, flags=re.DOTALL | re.IGNORECASE
        )
        # Nezatvoreni blok na početku: sve do prve zatvarajuće oznake.
        text = re.sub(
            rf"^\s*<{oznaka}>.*?(</{oznaka}>|\Z)",
            " ",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    text = text.strip()

    if not izgleda_kao_razmisljanje(text):
        return text

    # 1. Model je često sam označi mjesto gdje prelazi na odgovor
    #    ("Let's draft a response:"). Uzima se sve iza zadnje takve oznake.
    oznake = list(KRAJ_RAZMISLJANJA.finditer(text))
    if oznake:
        kandidat = text[oznake[-1].end() :].strip().strip('"').strip("'").strip()
        if kandidat:
            return kandidat

    # 2. Kod generiranja zadataka stvarni sadržaj je JSON koji slijedi.
    for oznaka in ("```", "\n[", "\n{"):
        polozaj = text.find(oznaka)
        if polozaj > 0:
            return text[polozaj:].strip()

    # 3. Nacrt odgovora zna biti pod navodnicima na kraju razmišljanja.
    navodnici = [i for i, z in enumerate(text) if z == '"']
    if navodnici and len(text) - navodnici[-1] > 40:
        return text[navodnici[-1] + 1 :].strip().strip('"').strip()

    return text


def izgleda_kao_razmisljanje(text: str) -> bool:
    """Prepoznaje odgovor koji je zapravo tijek razmišljanja, a ne odgovor."""
    if not text:
        return False
    if MISAONI_UVOD.match(text):
        return True
    nisko = text[:1500].lower()
    return any(trag in nisko for trag in TRAGOVI_RAZMISLJANJA)


def _kandidati_pocetka(text: str) -> List[int]:
    """Položaji na kojima JSON vjerojatno počinje.

    Nije dovoljno uzeti prvu uglatu zagradu u tekstu: model zna u odgovoru
    citirati uputu (npr. 'Počni znakom [ i završi znakom ]'), pa bi se takva
    zagrada pogrešno protumačila kao početak podataka. Zato se prihvaća samo
    zagrada iza koje slijedi ono čime JSON stvarno može početi.
    """
    kandidati: List[int] = []

    for i, znak in enumerate(text):
        if znak not in "[{":
            continue
        sljedeci = text[i + 1 : i + 60].lstrip()[:1]
        if znak == "[" and sljedeci in ("{", '"', "[", "]"):
            kandidati.append(i)
        elif znak == "{" and sljedeci in ('"', "}"):
            kandidati.append(i)

    return kandidati


def _extract_json(text: str) -> Any:
    """Izvlači JSON iz odgovora modela, i kada je omotan tekstom ili markdownom."""
    text = (text or "").strip()
    if not text:
        raise AIError("Model je vratio prazan odgovor.")

    # Sadržaj markdown bloka ima prednost, ali se gleda i cijeli tekst.
    isjecci: List[str] = []
    blok = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if blok:
        isjecci.append(blok.group(1).strip())
    isjecci.append(text)

    for isjecak in isjecci:
        for pocetak in _kandidati_pocetka(isjecak):
            zavrsni = "]" if isjecak[pocetak] == "[" else "}"
            kraj = isjecak.rfind(zavrsni)

            # Odgovor može imati suvišan tekst iza JSON-a, pa se pokušava
            # sa svakim zatvarajućim znakom unatrag dok se ne dobije valjan JSON.
            while kraj > pocetak:
                try:
                    return json.loads(isjecak[pocetak : kraj + 1])
                except json.JSONDecodeError:
                    kraj = isjecak.rfind(zavrsni, pocetak, kraj)

    raise AIError(f"Model nije vratio valjan JSON. Odgovor: {text[:200]}")


def _salvage_json_objects(text: str) -> List[Any]:
    """Izvlači cjelovite JSON objekte iz nepotpunog odgovora.

    Modeli s niskim ograničenjem izlaznih tokena često prekinu odgovor usred
    zadnjeg objekta. Umjesto da se odbaci cijeli odgovor, ovdje se pronalaze
    svi objekti kojima je zagrada uredno zatvorena, a prekinuti se preskače.

    Brojanje zagrada zanemaruje one unutar tekstualnih literala, pa navodnik
    ili vitičasta zagrada u opisu zadatka ne pokvari rezultat.
    """
    objekti: List[Any] = []
    dubina = 0
    pocetak = -1
    u_nizu = False
    bijeg = False

    for i, znak in enumerate(text):
        if u_nizu:
            if bijeg:
                bijeg = False
            elif znak == "\\":
                bijeg = True
            elif znak == '"':
                u_nizu = False
            continue

        if znak == '"':
            u_nizu = True
        elif znak == "{":
            if dubina == 0:
                pocetak = i
            dubina += 1
        elif znak == "}":
            if dubina > 0:
                dubina -= 1
                if dubina == 0 and pocetak != -1:
                    try:
                        objekti.append(json.loads(text[pocetak : i + 1]))
                    except json.JSONDecodeError:
                        pass
                    pocetak = -1

    return objekti


# ---------------------------------------------------------------------------
# 1. Chatbot tutor
# ---------------------------------------------------------------------------
TUTOR_SYSTEM_PROMPT = """Ti si AI tutor za učenje SQL-a na hrvatskom jeziku.
Tvoja uloga je voditi studenta prema rješenju, a ne riješiti zadatak umjesto njega.

Pravila:
- NIKADA ne daj cjelovit SQL upit koji rješava studentov zadatak.
- Smiješ pokazati kratke isječke sintakse općenito (npr. "SELECT stupac FROM tablica WHERE uvjet").
- Postavljaj potpitanja koja navode studenta na sljedeći korak.
- Objasni koncept jednostavno, uz primjer kada to pomaže razumijevanju.
- Ako student pogriješi, reci što točno ne valja i zašto, ali ne ispravi upit umjesto njega.
- Budi kratak: najviše 5-6 rečenica po odgovoru.
- Budi strpljiv i ohrabrujuć.
- Odgovaraj isključivo na hrvatskom jeziku.
- NE ispisuj svoj tijek razmišljanja, analizu pitanja ni plan odgovora.
  Odmah počni odgovorom koji student treba pročitati."""


def chat_with_tutor(
    conversation_history: List[Dict[str, str]],
    user_message: str,
    schema_id: Optional[str] = None,
) -> str:
    """Vraća odgovor tutora na studentovo pitanje."""
    sustav = TUTOR_SYSTEM_PROMPT
    if schema_id:
        sustav += (
            "\n\nStudent trenutno vježba na sljedećoj shemi baze:\n"
            + schema_description(schema_id)
        )

    poruke: List[Dict[str, str]] = [{"role": "system", "content": sustav}]

    for poruka in conversation_history[-8:]:
        uloga = poruka.get("role")
        if uloga in ("user", "assistant") and poruka.get("content"):
            poruke.append({"role": uloga, "content": str(poruka["content"])})

    poruke.append({"role": "user", "content": user_message})

    # Budžet je namjerno veći od duljine odgovora jer modeli koji interno
    # zaključuju dio tokena potroše prije nego počnu pisati odgovor.
    odgovor = call_llm(poruke, max_tokens=1200, temperature=0.7)

    # Zaštita: ako je model ispisao razmišljanje umjesto odgovora i čišćenje ga
    # nije uspjelo izdvojiti, studentu se ne smije prikazati takav tekst.
    if izgleda_kao_razmisljanje(odgovor):
        raise AIError(
            "Model je umjesto odgovora ispisao svoj tijek razmišljanja. "
            "To se događa kod slabijih (besplatnih) modela. Pokušajte ponovno "
            "ili u .env datoteci odaberite kvalitetniji model."
        )

    return odgovor


# ---------------------------------------------------------------------------
# 2. Generiranje zadataka
# ---------------------------------------------------------------------------
# Naputci koji se nasumično biraju kako dva uzastopna generiranja s istim
# postavkama ne bi dala isti zadatak.
KUTOVI = (
    "Naglasak stavi na filtriranje po tekstualnom stupcu.",
    "Naglasak stavi na filtriranje po brojčanom stupcu ili datumu.",
    "Iskoristi tablicu koja se rjeđe koristi u ovoj shemi.",
    "Traži rezultat sortiran po izračunatoj vrijednosti.",
    "Uključi ograničenje broja redaka (LIMIT) u barem jedan zadatak.",
    "Formuliraj zadatak kao stvarno poslovno pitanje, ne kao vježbu.",
    "Traži da se rezultat grupira po stupcu koji nije očit izbor.",
    "Uključi uvjet koji isključuje neke retke, a ne samo uključuje.",
)


def _prompt_zadataka(
    difficulty: str,
    topic: str,
    schema_id: str,
    count: int,
    izbjegni: Optional[List[str]] = None,
) -> str:
    kut = random.choice(KUTOVI)
    nonce = secrets.token_hex(3)

    izbjegavanje = ""
    if izbjegni:
        popis = "\n".join(f"- {naslov}" for naslov in izbjegni[:25])
        izbjegavanje = (
            "\n\nOvi zadaci već postoje u sustavu. Generiraj BITNO DRUKČIJE "
            "zadatke — ne ponavljaj ista pitanja ni iste upite:\n" + popis
        )

    return f"""Generiraj {count} SQL zadatka na hrvatskom jeziku.

Razina težine: {difficulty}
Tema: {topic}

Zadaci se rješavaju nad ovom shemom baze (SQLite):
{schema_description(schema_id)}

Smjernica za raznolikost: {kut}
(Oznaka zahtjeva: {nonce} — služi samo za raznolikost, ne spominji je.)
{izbjegavanje}

Pravila:
- Koristi isključivo navedene tablice i stupce.
- Rješenje mora biti jedan SELECT upit koji se izvršava bez greške u SQLite-u.
- Opis zadatka mora nedvosmisleno odrediti koje stupce i kojim redoslijedom vratiti.
- Nemoj koristiti funkcije kojih nema u SQLite-u.
- Budi kratak: opis najviše jedna rečenica, uputa najviše deset riječi.
  Odgovor mora stati u zadani broj tokena.

Odgovori ISKLJUČIVO JSON poljem, bez teksta prije ili poslije:
[
  {{
    "title": "Kratak naziv zadatka",
    "description": "Jasan opis zadatka na hrvatskom",
    "difficulty": "{difficulty}",
    "solution_sql": "SELECT ...",
    "hint": "Kratka uputa koja ne otkriva rješenje"
  }}
]"""


def _minimalni_prompt(
    difficulty: str,
    topic: str,
    schema_id: str,
    izbjegni: Optional[List[str]] = None,
) -> str:
    """Kratak zahtjev za jedan zadatak, za modele koji zapnu na dugom naputku."""
    zabranjeno = ""
    if izbjegni:
        zabranjeno = "\nNe smije biti jedan od ovih: " + "; ".join(izbjegni[:10])

    return f"""Popuni ovaj JSON jednim SQL zadatkom ({difficulty}, {topic}).

Tablice: {schema_description(schema_id)}{zabranjeno}

Ispiši samo ovo, popunjeno:
[{{"title":"","description":"","difficulty":"{difficulty}","solution_sql":"","hint":""}}]"""


def generate_sql_tasks(
    difficulty: str,
    topic: str,
    schema_id: str = "fakultet",
    count: int = 3,
    izbjegni: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Generira zadatke pomoću jezičnog modela.

    Slabiji (osobito besplatni) modeli često umjesto čistog JSON-a vrate
    objašnjenje ili odgovor odrežu na pola. Zato se zahtjev po potrebi šalje
    dvaput, drugi put uz bitno kraći naputak, a svaki se odgovor čita na dva
    načina (cjelovito parsiranje i spašavanje pojedinačnih objekata).

    Parametar `izbjegni` prima naslove postojećih zadataka. Bez njega model na
    isti prompt vraća isti zadatak, pa uzastopna generiranja ne donose ništa novo.
    """
    sustav = (
        "Ti si generator SQL zadataka. Odgovaraš isključivo valjanim JSON "
        "poljem, bez dodatnog teksta, bez objašnjenja i bez markdown oznaka. "
        "NE ispisuj svoj tijek razmišljanja ni analizu zadatka. "
        "Prvi znak tvog odgovora mora biti '[', a zadnji ']'."
    )

    prompt = _prompt_zadataka(difficulty, topic, schema_id, count, izbjegni)
    zadnja_greska: Optional[AIError] = None
    odgovor = ""

    for pokusaj in (1, 2):
        if pokusaj == 2:
            # Drugi pokušaj NE nastavlja razgovor. Slanje modelova neuspjelog
            # odgovora natrag navodi ga da o njemu raspravlja umjesto da ga
            # ispravi, pa se šalje potpuno nov i bitno kraći zahtjev.
            prompt = _minimalni_prompt(difficulty, topic, schema_id, izbjegni)

        poruke = [
            {"role": "system", "content": sustav},
            {"role": "user", "content": prompt},
        ]

        odgovor = call_llm(
            poruke,
            max_tokens=1500,
            # Visoka temperatura kod prvog pokušaja daje raznolikost;
            # kod ponovnog pokušaja važnije je da format bude ispravan.
            temperature=0.3 if pokusaj == 2 else 1.0,
        )

        # Dva neovisna načina čitanja odgovora; uzima se onaj s više zadataka.
        # Kod odrezanog odgovora cjelovito parsiranje ne uspije ili uhvati samo
        # prvi objekt, dok spašavanje pokupi sve objekte sa zatvorenom zagradom.
        procitano: List[Any] = []
        try:
            razluceno = _extract_json(odgovor)
            if isinstance(razluceno, dict):
                procitano = [razluceno]
            elif isinstance(razluceno, list):
                procitano = razluceno
        except AIError as exc:
            zadnja_greska = exc

        spaseni = _salvage_json_objects(odgovor)
        if len(spaseni) > len(procitano):
            print(
                f"[generiranje] Odgovor modela je nepotpun; "
                f"spašeno {len(spaseni)} cjelovitih zadataka."
            )
            procitano = spaseni

        if procitano:
            podaci = procitano
            break
    else:
        raise AIError(
            "Model nije vratio valjan JSON ni nakon drugog pokušaja. "
            f"({zadnja_greska or 'prazan rezultat'}) "
            f"Odgovor modela: {odgovor[:300]}"
        )

    if isinstance(podaci, dict):
        podaci = [podaci]
    if not isinstance(podaci, list):
        raise AIError("Model nije vratio popis zadataka.")

    zadaci: List[Dict[str, str]] = []
    for stavka in podaci:
        if not isinstance(stavka, dict):
            continue
        rjesenje = str(
            stavka.get("solution_sql") or stavka.get("expected_result") or ""
        ).strip()
        naslov = str(stavka.get("title", "")).strip()
        opis = str(stavka.get("description", "")).strip()
        if not (rjesenje and naslov and opis):
            continue

        zadaci.append(
            {
                "title": naslov,
                "description": opis,
                "difficulty": str(stavka.get("difficulty", difficulty)).strip(),
                "topic": topic,
                "schema_id": schema_id,
                "solution_sql": rjesenje,
                "hint": str(stavka.get("hint", "")).strip(),
            }
        )

    if not zadaci:
        raise AIError("Model nije vratio nijedan upotrebljiv zadatak.")

    return zadaci


# ---------------------------------------------------------------------------
# 3. Evaluacija studentovog rješenja
# ---------------------------------------------------------------------------
def evaluate_query(
    task_description: str,
    solution_sql: str,
    student_sql: str,
    schema_id: str,
    tehnicki_ishod: str,
) -> str:
    """Vraća kratku pedagošku povratnu informaciju o studentovom upitu.

    Parametar `tehnicki_ishod` je rezultat determinističke provjere (točno /
    netočno / greška) koja se izvodi prije poziva modela, pa model ne mora
    pogađati je li upit točan nego se usredotočuje na objašnjenje.
    """
    prompt = f"""Student rješava SQL zadatak.

SHEMA BAZE:
{schema_description(schema_id)}

ZADATAK:
{task_description}

TOČNO RJEŠENJE (ne smiješ ga doslovno prepisati studentu):
{solution_sql}

STUDENTOV UPIT:
{student_sql}

REZULTAT AUTOMATSKE PROVJERE:
{tehnicki_ishod}

Napiši kratku povratnu informaciju na hrvatskom (najviše 4 rečenice):
- Ako je upit točan: pohvali i istakni jednu stvar koja je dobro napravljena te po
  potrebi predloži čitljiviji ili učinkovitiji način pisanja.
- Ako je netočan: objasni koji je koncept pogrešno primijenjen i navedi studenta
  pitanjem prema ispravku. NE daješ gotov ispravljeni upit.
- Ako je upit bacio grešku: objasni što ta greška znači običnim jezikom.

Piši izravno studentu, bez uvoda i bez naslova."""

    return call_llm(
        [
            {
                "role": "system",
                "content": "Ti si SQL tutor koji daje kratku, konkretnu i "
                           "ohrabrujuću povratnu informaciju na hrvatskom jeziku. "
                           "Nikada ne pišeš gotov ispravljeni upit umjesto studenta.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=900,
        temperature=0.4,
    )
