"""
Nyhetsbrief – daglig morgenbrief for Norge → Skandinavia → Norden → Europa.
RSS → SQLite → regelbasert forhåndsutvalg → GitHub Models (gratis) → statisk HTML/PWA i docs/
Hvis AI-kallet feiler, lages briefen med reglene alene, så den kommer alltid.

Rangering:
  * Saker om samme hendelse fra flere kilder slås sammen. Flere kilder = viktigere.
  * Ord knyttet til politikk, økonomi, sikkerhet og energi gir pluss. Sport og kjendis gir minus.
  * Høyt oppe i kildens egen toppliste og nylig publisert gir litt pluss.
  * En sak havner på det høyeste nivået der den er omtalt, og gjentas ikke lenger ned.
"""
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser

ROT = Path(__file__).parent
DB_FIL = ROT / "data" / "nyheter.db"
DOCS = ROT / "docs"
KALENDER_FIL = ROT / "kalender.json"
TZ = ZoneInfo("Europe/Oslo")

# Rekkefølgen på nivåene er prioriteringen.
FEEDS = {
    "Norge": {
        "NRK": "https://www.nrk.no/toppsaker.rss",
        "NRK Norge": "https://www.nrk.no/norge/toppsaker.rss",
    },
    "Skandinavia": {
        "SVT": "https://www.svt.se/nyheter/rss.xml",
        "DR": "https://www.dr.dk/nyheder/service/feeds/senestenyt",
    },
    "Norden": {
        "Yle News": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_NEWS",
        "RÚV English": "https://www.ruv.is/rss/english",
    },
    "Europa": {
        "BBC": "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
        "DW": "https://rss.dw.com/rdf/rss-en-eu",
        "France 24": "https://www.france24.com/en/europe/rss",
    },
}
NIVAER = list(FEEDS)
# Maks antall saker per nivå. Med korte AI-oppsummeringer gir dette ca. 4–5 minutters lesetid.
ANTALL_PER_NIVA = {"Norge": 5, "Skandinavia": 3, "Norden": 3, "Europa": 3}
MAKS_FOLG_MED = 4
MIN_POENG = 2

# GitHub Models: gratis, bruker GITHUB_TOKEN i Actions. Små forespørsler holder oss under gratisgrensene.
AI_URL = "https://models.github.ai/inference/chat/completions"
# Prøves i rekkefølge. Bytt eller legg til modeller med AI_MODELLER="a,b,c" i workflow-filen.
AI_MODELLER = [m.strip() for m in os.environ.get(
    "AI_MODELLER", "openai/gpt-4.1-mini,openai/gpt-4o-mini,openai/gpt-4.1").split(",") if m.strip()]
KANDIDATER_PER_NIVA = {"Norge": 10, "Skandinavia": 6, "Norden": 5, "Europa": 6}
DAGER_I_KALENDER = 7
BEHOLD_DAGER = 60
INGRESS_MAKS = 220

# --------------------------------------------------------------- ordlister
# Ordstammer på norsk, svensk, dansk og engelsk. Treffer starten av ord.
VIKTIG = {
    3: ["styringsrente", "rentemøte", "renten", "renta", "interest rate", "inflasjon", "inflation",
        "statsbudsjett", "budsjett", "budget", "nato", "krig", "war", "invasjon", "invasion",
        "valg", "valget", "election", "folkeavstemning", "referendum"],
    2: ["regjering", "regering", "government", "stortinget", "riksdag", "folketing", "parlament",
        "statsminist", "prime minister", "president", "minister", "eu-", "eus ", "european union",
        "kommisjon", "commission", "høyesterett", "högsta domstol", "højesteret", "supreme court",
        "domstol", "court", "dom ", "strøm", "strømpris", "elpris", "energi", "energy", "gass", "gas ",
        "olje", "oil", "ukrain", "russland", "ryssland", "rusland", "russia", "forsvar", "försvar",
        "defen", "sikkerhet", "säkerhet", "sikkerhed", "security", "sanksjon", "sanktion", "sanction"],
    1: ["arbeidsledig", "arbetslös", "ledighed", "unemploy", "bnp", "gdp", "kpi", "økonomi",
        "ekonomi", "economy", "streik", "strejk", "strike", "toll", "tariff", "handel", "trade",
        "klima", "climate", "flom", "flood", "brann", "wildfire", "migrasjon", "migration", "asyl"],
}
UVIKTIG = ["fotball", "fotboll", "fodbold", "football", "eliteserien", "allsvenskan", "superliga",
           "champions league", "premier league", "håndball", "handboll", "håndbold", "langrenn",
           "skiskyting", "alpint", "tennis", "golf", "formel 1", "sport", "kjendis", "kändis",
           "kendis", "celebrity", "influencer", "reality", "melodi grand prix", "eurovision",
           "oppskrift", "recept", "opskrift"]

# Kategorier for «Følg med i dag» når hendelsen kommer fra nyhetssakene
KATEGORI_ORD = {
    "Rentemøte": ["styringsrente", "rentemøte", "rentebeslut", "räntebesked", "interest rate",
                  "norges bank", "riksbanken", "nationalbanken", "ecb"],
    "Statsbudsjett": ["statsbudsjett", "budsjett", "budget"],
    "NATO": ["nato"],
    "EU": ["eu-", "eus ", "toppmøte", "summit", "european council", "kommisjon", "commission"],
    "Valg": ["valg", "valet", "election", "folkeavstemning", "referendum"],
    "Økonomiske tall": ["kpi", "inflasjon", "inflation", "bnp", "gdp", "arbeidsledig",
                        "arbetslös", "unemploy", "ssb"],
    "Rettsavgjørelse": ["dom ", "dommen", "domen", "verdict", "ruling", "høyesterett",
                        "court", "rettssak", "rättegång", "retssag", "trial"],
    "Energimarked": ["strøm", "elpris", "energi", "energy", "gass", "olje", "oil", "opec"],
}
I_DAG = re.compile(r"\b(i dag|idag|today|tänään)\b", re.I)

UKEDAGER = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MANEDER = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
           "august", "september", "oktober", "november", "desember"]
STOPPORD = set("""og i på til for med som det den de er at av en et fra har ikke om var
och på för med som det den är att av ett från har inte om var
og på for med som det den er at af en et fra har ikke om var
the and for with that from this have has are was were will into after over about""".split())


def norsk_dato(d: date) -> str:
    return f"{UKEDAGER[d.weekday()].capitalize()} {d.day}. {MANEDER[d.month - 1]}"


def ordmonster(ord_liste) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(re.escape(o) for o in ord_liste) + ")", re.I)


VIKTIG_RE = {vekt: ordmonster(liste) for vekt, liste in VIKTIG.items()}
UVIKTIG_RE = ordmonster(UVIKTIG)
KATEGORI_RE = {k: ordmonster(v) for k, v in KATEGORI_ORD.items()}


# ---------------------------------------------------------------- database
def koble_til() -> sqlite3.Connection:
    DB_FIL.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_FIL)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS artikler (
            id INTEGER PRIMARY KEY,
            lenke TEXT UNIQUE, tittel TEXT, nokkel TEXT,
            niva TEXT, kilde TEXT, ingress TEXT, posisjon INTEGER,
            publisert TEXT, forst_sett TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_nokkel ON artikler(nokkel);
        CREATE INDEX IF NOT EXISTS ix_sett ON artikler(forst_sett);
        CREATE TABLE IF NOT EXISTS briefer (dato TEXT PRIMARY KEY, innhold TEXT, laget TEXT);
    """)
    return con


def rens(tekst: str, maks: int) -> str:
    tekst = re.sub(r"<[^>]+>", " ", tekst or "")
    tekst = re.sub(r"\s+", " ", html.unescape(tekst)).strip()
    if len(tekst) > maks:
        tekst = tekst[:maks].rsplit(" ", 1)[0] + " …"
    return tekst


def nokkel(tittel: str) -> str:
    return re.sub(r"[^a-z0-9æøåäöü]", "", tittel.lower())[:120]


def ord_i(tekst: str) -> set[str]:
    return {o for o in re.findall(r"[a-zæøåäöüé0-9]{4,}", tekst.lower()) if o not in STOPPORD}


# ---------------------------------------------------------------- RSS
def hent_rss(con) -> None:
    na = datetime.now(timezone.utc)
    grense = na - timedelta(hours=36)
    for niva, kilder in FEEDS.items():
        for kilde, url in kilder.items():
            try:
                feed = feedparser.parse(url, agent="Nyhetsbrief/1.0")
                if not feed.entries:
                    raise ValueError(feed.get("bozo_exception", "tom feed"))
            except Exception as e:
                print(f"[feilet] {kilde}: {e}", file=sys.stderr)
                continue
            nye = 0
            for pos, e in enumerate(feed.entries[:30]):
                t = e.get("published_parsed") or e.get("updated_parsed")
                pub = datetime.fromtimestamp(time.mktime(t), timezone.utc) if t else na
                tittel, lenke = rens(e.get("title", ""), 200), e.get("link", "")
                if pub < grense or not tittel or not lenke:
                    continue
                n = nokkel(tittel)
                if con.execute("SELECT 1 FROM artikler WHERE nokkel=?", (n,)).fetchone():
                    continue
                cur = con.execute(
                    "INSERT OR IGNORE INTO artikler(lenke,tittel,nokkel,niva,kilde,ingress,posisjon,publisert,forst_sett)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (lenke, tittel, n, niva, kilde, rens(e.get("summary", ""), INGRESS_MAKS),
                     pos, pub.isoformat(), na.isoformat()))
                nye += cur.rowcount
            print(f"[ok] {kilde}: {nye} nye", file=sys.stderr)
    con.execute("DELETE FROM artikler WHERE forst_sett < ?",
                ((na - timedelta(days=BEHOLD_DAGER)).isoformat(),))
    con.commit()


def ferske_saker(con) -> list[dict]:
    grense = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    kol = ["id", "niva", "kilde", "tittel", "ingress", "lenke", "posisjon", "publisert"]
    rader = con.execute(f"SELECT {','.join(kol)} FROM artikler WHERE forst_sett>=?", (grense,))
    return [dict(zip(kol, r)) for r in rader]


# ---------------------------------------------------------------- rangering
def artikkelpoeng(a: dict) -> float:
    tekst = f"{a['tittel']} {a['ingress']}"
    p = 0.0
    for vekt, monster in VIKTIG_RE.items():
        p += vekt * min(len(set(m.lower() for m in monster.findall(tekst))), 2)
    if UVIKTIG_RE.search(tekst):
        p -= 6
    p += max(0.0, 3 - a["posisjon"] / 5)  # høyt i kildens toppliste
    timer = (datetime.now(timezone.utc) - datetime.fromisoformat(a["publisert"])).total_seconds() / 3600
    p += max(0.0, 2 - timer / 12)          # fersk
    return p


def grupper(saker: list[dict]) -> list[dict]:
    """Slår sammen saker om samme hendelse basert på felles ord i tittelen."""
    for a in saker:
        a["ord"] = ord_i(a["tittel"])
        a["poeng"] = artikkelpoeng(a)
    grupper_ = []
    for a in sorted(saker, key=lambda x: -x["poeng"]):
        beste, beste_likhet = None, 0.0
        for g in grupper_:
            felles = len(a["ord"] & g["ord"])
            likhet = felles / max(1, min(len(a["ord"]), len(g["ord"])))
            if felles >= 2 and likhet >= 0.4 and likhet > beste_likhet:
                beste, beste_likhet = g, likhet
        if beste:
            beste["saker"].append(a)
            beste["ord"] |= a["ord"]
        else:
            grupper_.append({"saker": [a], "ord": set(a["ord"])})

    for g in grupper_:
        kilder = {a["kilde"] for a in g["saker"]}
        g["antall_kilder"] = len(kilder)
        g["poeng"] = max(a["poeng"] for a in g["saker"]) + 3 * (len(kilder) - 1)
        g["niva"] = min((a["niva"] for a in g["saker"]), key=NIVAER.index)
        # Hovedsak: den beste fra det høyeste nivået
        g["hoved"] = max((a for a in g["saker"] if a["niva"] == g["niva"]), key=lambda a: a["poeng"])
    return sorted(grupper_, key=lambda g: -g["poeng"])


def velg_saker(grupper_: list[dict]) -> dict:
    ut = {n: [] for n in NIVAER}
    for g in grupper_:
        if g["poeng"] < MIN_POENG or len(ut[g["niva"]]) >= ANTALL_PER_NIVA[g["niva"]]:
            continue
        h = g["hoved"]
        sett, kilder = set(), []
        for a in sorted(g["saker"], key=lambda a: NIVAER.index(a["niva"])):
            if a["kilde"] not in sett:
                sett.add(a["kilde"])
                kilder.append({"navn": a["kilde"], "lenke": a["lenke"]})
        ut[g["niva"]].append({"tittel": h["tittel"], "tekst": h["ingress"],
                              "kilder": kilder, "antall_kilder": g["antall_kilder"]})
    return ut


# ---------------------------------------------------------------- kalender
def les_ics(url: str) -> list[dict]:
    """Enkel ICS-leser: henter DTSTART, SUMMARY og URL fra hver VEVENT."""
    req = urllib.request.Request(url, headers={"User-Agent": "Nyhetsbrief/1.0"})
    tekst = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    tekst = re.sub(r"\r?\n[ \t]", "", tekst)  # foldede linjer
    ut = []
    for blokk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", tekst, re.S):
        felt = {}
        for linje in blokk.splitlines():
            if ":" in linje:
                navn, verdi = linje.split(":", 1)
                felt[navn.split(";")[0].upper()] = (navn, verdi.strip())
        if "DTSTART" not in felt or "SUMMARY" not in felt:
            continue
        param, v = felt["DTSTART"]
        try:
            if len(v) == 8:
                d, tid = datetime.strptime(v, "%Y%m%d").date(), ""
            else:
                dt = datetime.strptime(v.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
                m = re.search(r"TZID=([^;:]+)", param)
                if v.endswith("Z"):
                    dt = dt.replace(tzinfo=timezone.utc).astimezone(TZ)
                elif m:
                    dt = dt.replace(tzinfo=ZoneInfo(m.group(1))).astimezone(TZ)
                d, tid = dt.date(), dt.strftime("%H:%M")
        except (ValueError, KeyError):
            continue
        ut.append({"dato": d.isoformat(), "tid": tid,
                   "hendelse": felt["SUMMARY"][1].replace("\\,", ",").replace("\\;", ";"),
                   "kilde": felt.get("URL", ("", ""))[1]})
    return ut


def les_kalender(idag: date) -> list[dict]:
    if not KALENDER_FIL.exists():
        return []
    data = json.loads(KALENDER_FIL.read_text(encoding="utf-8"))
    hendelser = [h for h in data.get("hendelser", []) if not h.get("eksempel")]
    for k in (k for k in data.get("ics", []) if not k.get("eksempel")):
        try:
            for h in les_ics(k["url"]):
                h.setdefault("kategori", k.get("kategori", "Annet"))
                h["kildenavn"] = k.get("navn", "Kalender")
                h["kilde"] = h["kilde"] or k.get("lenke", "")
                hendelser.append(h)
            print(f"[ok] kalender {k.get('navn')}", file=sys.stderr)
        except Exception as e:
            print(f"[feilet] kalender {k.get('navn')}: {e}", file=sys.stderr)
    slutt = idag + timedelta(days=DAGER_I_KALENDER)
    ut = []
    for h in hendelser:
        try:
            if idag <= date.fromisoformat(h["dato"]) <= slutt:
                ut.append(h)
        except (KeyError, ValueError):
            continue
    return sorted(ut, key=lambda h: (h["dato"], h.get("tid") or "99"))


def folg_med(kalender: list[dict], saker: list[dict], idag: date) -> list[dict]:
    ut = []
    for h in kalender:
        if h["dato"] == idag.isoformat():
            ut.append({"tid": h.get("tid", ""), "kategori": h.get("kategori", "Annet"),
                       "hendelse": h["hendelse"], "hvorfor": h.get("beskrivelse", ""),
                       "kilder": [{"navn": h.get("kildenavn", "Kalender"), "lenke": h.get("kilde", "")}]})
    # Fra nyhetene: saker som sier «i dag» og treffer en kategori
    fra_nyheter = []
    for a in saker:
        tekst = f"{a['tittel']} {a['ingress']}"
        if not I_DAG.search(tekst) or UVIKTIG_RE.search(tekst):
            continue
        kategori = next((k for k, m in KATEGORI_RE.items() if m.search(tekst)), None)
        if kategori:
            fra_nyheter.append((a["poeng"], {
                "tid": "", "kategori": f"{kategori}, fra nyhetene", "hendelse": a["tittel"],
                "hvorfor": a["ingress"], "kilder": [{"navn": a["kilde"], "lenke": a["lenke"]}]}))
    fra_nyheter.sort(key=lambda x: -x[0])
    ut = ut[:MAKS_FOLG_MED]
    ut += [f for _, f in fra_nyheter[:MAKS_FOLG_MED - len(ut)]]
    return sorted(ut, key=lambda f: f["tid"] or "99")


# ---------------------------------------------------------------- kilder for en gruppe
def kilder_for_gruppe(g) -> list[dict]:
    sett, ut = set(), []
    for a in sorted(g["saker"], key=lambda a: NIVAER.index(a["niva"])):
        if a["kilde"] not in sett:
            sett.add(a["kilde"])
            ut.append({"navn": a["kilde"], "lenke": a["lenke"]})
    return ut


def kort_fortalt_regler(grupper_) -> list[dict]:
    topp = [g for g in grupper_ if g["poeng"] >= MIN_POENG][:3]
    return [{"tekst": g["hoved"]["tittel"], "kilder": kilder_for_gruppe(g)[:1]} for g in topp]


# ---------------------------------------------------------------- AI (GitHub Models)
def kandidater(grupper_) -> dict[str, dict]:
    ut, teller = {}, {n: 0 for n in NIVAER}
    for g in grupper_:
        n = g["niva"]
        if g["poeng"] >= MIN_POENG and teller[n] < KANDIDATER_PER_NIVA[n]:
            teller[n] += 1
            ut[f"G{len(ut) + 1}"] = g
    return ut


def spor_ai(instruks: str, modell: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN mangler")
    kropp = json.dumps({
        "model": modell,
        "temperature": 0.2,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Du er en nøktern, partipolitisk nøytral nyhetsredaktør. Du svarer kun med gyldig JSON."},
            {"role": "user", "content": instruks},
        ],
    }).encode()
    for forsok in range(2):
        req = urllib.request.Request(AI_URL, data=kropp, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as svar:
                ra = svar.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and forsok == 0:
                print("[ai] rate limit, prøver igjen om 30 s", file=sys.stderr)
                time.sleep(30)
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}")
        try:
            data = json.loads(ra)
        except json.JSONDecodeError:
            raise RuntimeError(f"svaret var ikke JSON: {ra[:300]!r}")
        if "choices" not in data or not data["choices"]:
            raise RuntimeError(f"uventet svar: {ra[:300]!r}")
        valg = data["choices"][0]
        innhold = (valg.get("message") or {}).get("content") or ""
        if not innhold.strip():
            raise RuntimeError(f"tomt svar (finish_reason={valg.get('finish_reason')})")
        return innhold
    raise RuntimeError("ingen svar etter nytt forsøk")


def ai_brief(grupper_, kalender_i_dag, nyhets_folg, idag: date) -> dict:
    kand = kandidater(grupper_)
    kal = {f"K{i}": h for i, h in enumerate(kalender_i_dag, 1)}

    linjer = "\n".join(
        f"{gid} | {g['niva']} | {g['antall_kilder']} kilder | {g['hoved']['tittel']} | {g['hoved']['ingress']}"
        for gid, g in kand.items())
    kal_linjer = "\n".join(
        f"{k} | {h.get('tid', '')} | {h.get('kategori', '')} | {h['hendelse']} | {h.get('beskrivelse', '')}"
        for k, h in kal.items()) or "(ingen)"
    antall = ", ".join(f"{n}: opptil {a}" for n, a in ANTALL_PER_NIVA.items())

    instruks = f"""Lag en KORT morgenbrief på norsk bokmål for {norsk_dato(idag)} {idag.year}.
Hele briefen skal kunne leses på under 5 minutter. Kvalitet foran antall.

1. "kort_fortalt": nøyaktig 3 korte setninger (maks 20 ord hver) om de viktigste sakene samlet.
2. "saker": velg saker per nivå, prioritert i rekkefølgen Norge, Skandinavia, Norden, Europa ({antall}).
   Ta bare med saker som faktisk er viktige. Det er helt greit å velge færre.
   Skriv en kort norsk tittel og 1–2 setninger (maks 40 ord) per sak. Oversett svenske, danske og engelske saker.
3. "folg_med": maks {MAKS_FOLG_MED} hendelser som skjer I DAG, hentet fra kalenderen eller fra saker som tydelig
   sier at noe skjer i dag (rentemøter, budsjetter, EU, NATO, valg, økonomiske tall, rettsavgjørelser, energi).
   Én setning om hva som skjer eller avgjøres. Ikke spå utfall, ikke vurder, ikke anbefal. Ikke finn på klokkeslett.

Bruk bare informasjonen under. Ingen meninger eller spekulasjon.

Svar med JSON:
{{"kort_fortalt": [{{"tekst": "...", "ref": "G1"}}],
 "saker": {{"Norge": [{{"ref": "G1", "tittel": "...", "tekst": "..."}}], "Skandinavia": [], "Norden": [], "Europa": []}},
 "folg_med": [{{"ref": "K1", "tid": "10:00", "kategori": "Rentemøte", "hendelse": "...", "hvorfor": "..."}}]}}
"ref" må være en id fra listene (G-nummer for saker, K-nummer for kalender).

KALENDER I DAG:
{kal_linjer}

SAKER (id | nivå | antall kilder | tittel | ingress):
{linjer}"""

    ra, modell, feil = None, None, []
    for m in AI_MODELLER:
        try:
            tekst = spor_ai(instruks, m)
            start, slutt = tekst.find("{"), tekst.rfind("}")
            if start < 0 or slutt < start:
                raise RuntimeError(f"fant ikke JSON i svaret: {tekst[:200]!r}")
            ra, modell = json.loads(tekst[start:slutt + 1]), m
            break
        except Exception as e:
            print(f"[ai] {m} feilet: {e}", file=sys.stderr)
            feil.append(m)
    if ra is None:
        raise RuntimeError(f"alle modeller feilet ({', '.join(feil)})")

    def kilder(ref):
        ref = str(ref).strip().upper()
        if ref in kand:
            return kilder_for_gruppe(kand[ref])
        if ref in kal:
            h = kal[ref]
            return [{"navn": h.get("kildenavn", "Kalender"), "lenke": h.get("kilde", "")}]
        return None

    ut = {"kort_fortalt": [], "saker": {n: [] for n in NIVAER}, "folg_med": []}
    for k in ra.get("kort_fortalt", [])[:3]:
        if (kk := kilder(k.get("ref"))) and k.get("tekst"):
            ut["kort_fortalt"].append({"tekst": k["tekst"], "kilder": kk[:1]})
    brukt = set()
    for niva in NIVAER:
        for sak in ra.get("saker", {}).get(niva, [])[:ANTALL_PER_NIVA[niva]]:
            ref = str(sak.get("ref", "")).upper()
            if ref in kand and ref not in brukt and sak.get("tittel"):
                brukt.add(ref)
                ut["saker"][niva].append({"tittel": sak["tittel"], "tekst": sak.get("tekst", ""),
                                          "kilder": kilder_for_gruppe(kand[ref]),
                                          "antall_kilder": kand[ref]["antall_kilder"]})
    for f in ra.get("folg_med", [])[:MAKS_FOLG_MED]:
        if (kk := kilder(f.get("ref"))) and f.get("hendelse"):
            ut["folg_med"].append({"tid": f.get("tid", "") if str(f.get("ref", "")).upper() in kal else "",
                                   "kategori": f.get("kategori", "Annet"), "hendelse": f["hendelse"],
                                   "hvorfor": f.get("hvorfor", ""), "kilder": kk})
    ut["folg_med"].sort(key=lambda f: f["tid"] or "99")
    if not any(ut["saker"].values()):
        raise RuntimeError("AI-svaret inneholdt ingen gyldige saker")
    ut["modell"] = modell
    return ut


# ---------------------------------------------------------------- HTML
def e(t) -> str:
    return html.escape(str(t or ""))


def lenker(kilder) -> str:
    return " ".join(f'<a href="{e(k["lenke"])}" rel="noopener">{e(k["navn"])}</a>' if k["lenke"]
                    else e(k["navn"]) for k in kilder)


def side(tittel: str, innhold: str, rot: str) -> str:
    return f"""<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(tittel)}</title>
<meta name="theme-color" content="#16324a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Nyhetsbrief">
<link rel="manifest" href="{rot}manifest.webmanifest">
<link rel="apple-touch-icon" href="{rot}icon-180.png">
<link rel="icon" href="{rot}icon-192.png">
<link rel="stylesheet" href="{rot}stil.css">
</head>
<body>
<main>
{innhold}
</main>
<script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("{rot}sw.js");</script>
</body>
</html>"""


def lesetid(b: dict) -> int:
    tekst = " ".join([k["tekst"] for k in b["kort_fortalt"]]
                     + [f"{f['hendelse']} {f['hvorfor']}" for f in b["folg_med"]]
                     + [f"{s['tittel']} {s['tekst']}" for l in b["saker"].values() for s in l])
    return max(1, round(len(tekst.split()) / 200))


def bygg_brief_html(b: dict, idag: date, laget: datetime, rot: str) -> str:
    kort = "".join(f'<li>{e(k["tekst"])}</li>' for k in b["kort_fortalt"])
    deler = [f"""<header class="topp">
  <p class="ar">{idag.year}</p>
  <h1>{e(norsk_dato(idag))}</h1>
  <p class="oppdatert">Lesetid ca. {lesetid(b)} min. Oppdatert kl. {laget:%H.%M}.</p>
  {f'<ul class="kort">{kort}</ul>' if kort else ""}
</header>"""]

    if b["folg_med"]:
        punkter = "".join(f"""<li>
  <span class="tid">{e(f["tid"]) or "I dag"}</span>
  <div>
    <p class="kat">{e(f["kategori"])}</p>
    <h3>{e(f["hendelse"])}</h3>
    {f'<p>{e(f["hvorfor"])}</p>' if f["hvorfor"] else ""}
    <p class="kilder">{lenker(f["kilder"])}</p>
  </div>
</li>""" for f in b["folg_med"])
        deler.append(f'<section class="folg"><h2>Følg med i dag</h2><ol class="tidslinje">{punkter}</ol></section>')

    for niva, liste in b["saker"].items():
        if not liste:
            continue
        artikler = "".join(f"""<article>
  <h3>{e(s["tittel"])}</h3>
  {f'<p>{e(s["tekst"])}</p>' if s["tekst"] else ""}
  <p class="kilder">{lenker(s["kilder"])}</p>
</article>""" for s in liste)
        deler.append(f'<section class="niva"><h2>{e(niva)}</h2>{artikler}</section>')

    if b["senere"]:
        rader = "".join(f'<li><span>{e(norsk_dato(date.fromisoformat(h["dato"])))}'
                        f'{" kl. " + e(h["tid"]) if h.get("tid") else ""}</span>{e(h["hendelse"])}</li>'
                        for h in b["senere"])
        deler.append(f'<details class="senere"><summary>Senere denne uken ({len(b["senere"])})</summary><ul>{rader}</ul></details>')

    merknad = (f"Oppsummert med AI ({e(b['modell'])}) fra offentlige RSS-kilder. Sjekk originalsaken før du siterer eller handler på noe."
               if b["modus"] == "ai" else
               "Utvalgt etter faste regler. Titler og ingresser er hentet uendret fra kildenes RSS-feeder og tilhører dem.")
    deler.append(f"""<footer>
  <p><a href="{rot}arkiv/">Tidligere briefer</a></p>
  <p>{merknad}</p>
</footer>""")
    return side(f"Nyhetsbrief {idag.isoformat()}", "\n".join(deler), rot)


def bygg_arkiv(con) -> str:
    datoer = [r[0] for r in con.execute("SELECT dato FROM briefer ORDER BY dato DESC")]
    rader = "".join(f'<li><a href="{d}.html">{e(norsk_dato(date.fromisoformat(d)))} {d[:4]}</a></li>'
                    for d in datoer)
    return side("Nyhetsbrief – arkiv",
                f'<header class="topp"><h1>Arkiv</h1></header><section class="arkiv"><ul>{rader}</ul></section>'
                '<footer><p><a href="../">Til dagens brief</a></p></footer>', "../")


# ---------------------------------------------------------------- main
def main() -> None:
    laget = datetime.now(TZ)
    idag = laget.date()
    con = koble_til()

    hent_rss(con)
    saker = ferske_saker(con)
    print(f"{len(saker)} ferske saker", file=sys.stderr)
    if not saker:
        sys.exit("Fant ingen saker – sjekk feedene i loggen.")

    grupper_ = grupper(saker)
    kalender = les_kalender(idag)
    i_dag = [h for h in kalender if h["dato"] == idag.isoformat()]
    regel_folg = folg_med(kalender, saker, idag)

    try:
        innhold = ai_brief(grupper_, i_dag, regel_folg, idag)
        modus = "ai"
        brukt_modell = innhold.pop("modell")
        print(f"[ai] brief laget med {brukt_modell}", file=sys.stderr)
    except Exception as feil:
        print(f"[ai] ikke tilgjengelig ({feil}) – bruker regelbasert brief", file=sys.stderr)
        innhold = {"kort_fortalt": kort_fortalt_regler(grupper_),
                   "saker": velg_saker(grupper_), "folg_med": regel_folg}
        modus = "regler"
        brukt_modell = ""

    brief = {**innhold,
             "senere": [h for h in kalender if h["dato"] > idag.isoformat()],
             "modus": modus, "modell": brukt_modell}

    con.execute("INSERT OR REPLACE INTO briefer VALUES (?,?,?)",
                (idag.isoformat(), json.dumps(brief, ensure_ascii=False), laget.isoformat()))
    con.commit()

    (DOCS / "arkiv").mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(bygg_brief_html(brief, idag, laget, ""), encoding="utf-8")
    (DOCS / "arkiv" / f"{idag.isoformat()}.html").write_text(
        bygg_brief_html(brief, idag, laget, "../"), encoding="utf-8")
    (DOCS / "arkiv" / "index.html").write_text(bygg_arkiv(con), encoding="utf-8")
    (DOCS / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ferdig: docs/index.html (lesetid ca. {lesetid(brief)} min)", file=sys.stderr)


if __name__ == "__main__":
    main()
