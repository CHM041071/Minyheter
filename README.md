# Nyhetsbrief

En kort daglig morgenbrief, med **lesetid på 4–5 minutter**, som prioriterer
**Norge → Skandinavia → Norden → Europa**, med en egen seksjon **«Følg med i dag»**.
Alt er gratis. Det eneste du trenger, er en gratis API-nøkkel fra Google AI Studio.

```
RSS-feeder ───┐                                  ┌─> Google Gemini (gratis)  ─┐
kalender.json ┼─> agent.py ─> SQLite ─> regler ──┤                              ├─> docs/ (HTML + PWA)
.ics-kalendere┘                                  └─> (reserve: bare regler) ────┘
```

## Hva du får hver morgen

- **Kort fortalt:** tre setninger som gir hele bildet
- **Følg med i dag:** maks fire hendelser som skjer i dag
- **Nyheter:** opptil 5 fra Norge og 3 hver fra Skandinavia, Norden og Europa,
  med 1–2 setninger hver, oversatt til norsk. AI-en velger gjerne færre hvis dagen er rolig.
- **Senere denne uken:** sammenfoldet nederst

## Hvordan AI brukes

1. Reglene grupperer og rangerer alle sakene og sender bare de ~27 beste kandidatene videre.
2. Google Gemini velger ut, oversetter og skriver kort. Modellene prøves i denne rekkefølgen:
   `gemini-3.8-flash` (best, ca. 20 gratis kall per dag), deretter `gemini-3.5-flash-lite`
   (ca. 500 per dag) og til slutt `gemini-flash-latest`.
3. AI-en kan bare vise til saker og kalenderhendelser via ID. Lenker og kilder hentes alltid
   fra databasen. Punkter med ukjente ID-er fjernes, og klokkeslett godtas bare fra kalenderen.
4. **Hvis alle AI-kall feiler**, lages briefen med reglene alene. Nederst på siden står
   hvilken metode som ble brukt.

Du kan bytte modeller med `AI_MODELLER` i workflow-filen. Google endrer modellnavn og
gratiskvoter jevnlig. Se ai.google.dev/gemini-api/docs/models.

## Oppsett

1. **Lag et offentlig GitHub-repo** og last opp alle filene, inkludert mappene
   `.github/workflows`, `docs` og `data`. Merk at opplasting i nettleseren hopper over
   `.github`. Den må lages med Add file → Create new file.
2. **Gemini-nøkkel:** lag en gratis nøkkel på aistudio.google.com (Get API key). Legg den inn
   under Settings → Secrets and variables → Actions → New repository secret, med navnet
   `GEMINI_API_KEY`.
3. **Første kjøring:** Actions → Nyhetsbrief → *Run workflow*. Se i loggen hvilke
   feeder som svarte (`[ok]`) og hvilke som feilet (`[feilet]`).
4. **Slå på GitHub Pages:** Settings → Pages → *Deploy from a branch* → `main`, mappen `/docs`.
   Etter et par minutter ligger siden på `https://BRUKERNAVN.github.io/REPONAVN/`.
5. **Legg den på iPhone:** åpne adressen i Safari → Del → *Legg til på Hjem-skjerm*.

## Slik rangerer reglene

Reglene gjør forhåndsutvalget, og de lager hele briefen hvis AI ikke er tilgjengelig:

| Regel | Effekt |
|---|---|
| Samme hendelse omtalt av flere kilder | Slås sammen. +3 poeng per ekstra kilde |
| Ord om renter, budsjett, valg, krig, NATO | +3 |
| Ord om regjering, parlament, EU, domstoler, energi, sikkerhet | +2 |
| Ord om arbeidsledighet, BNP, handel, klima, streik | +1 |
| Sport, kjendis, underholdning | −6 |
| Høyt i kildens egen toppliste | opptil +3 |
| Publisert siste timene | opptil +2 |

En sak havner på det **høyeste nivået** der den er omtalt. Hvis for eksempel både NRK og
BBC skriver om Norges Bank, havner saken under Norge med begge kildene, og gjentas ikke
under Europa.

I reservemodus vises titler og ingresser uendret fra kildene, altså på originalspråket.

Ordlistene ligger øverst i `agent.py` (`VIKTIG`, `UVIKTIG`, `KATEGORI_ORD`) og kan justeres fritt.

## «Følg med i dag»

Denne seksjonen hentes fra tre steder:

1. **Hendelser i `kalender.json`** som du legger inn selv.
2. **Kalenderabonnementer (.ics)** som du legger inn under `"ics"` i `kalender.json`.
   Disse hentes automatisk hver dag. Mange institusjoner tilbyr slike lenker på sine
   kalendersider. Se etter «Abonner», «iCal» eller «Legg til i kalender».
3. **Nyhetssaker** som sier «i dag» og handler om en av kategoriene. Disse merkes
   *«fra nyhetene»*, så du ser at de er funnet automatisk.

Hendelser de neste sju dagene vises under «Senere denne uken».

Her finner du datoer:

| Kategori | Kilde |
|---|---|
| Rentemøter | Norges Bank, ECB, Riksbanken, Nationalbanken |
| Statsbudsjett | regjeringen.no |
| Økonomiske tall | SSBs publiseringskalender, Eurostats release calendar |
| EU-møter | consilium.europa.eu |
| NATO | nato.int |
| Valg | valg.no og tilsvarende for andre land |
| Rettsavgjørelser | domstol.no, curia.europa.eu |
| Energimarked | Nord Pool, OPEC, IEA |

## Kostnad

Ingen. GitHub Actions og Pages er gratis for offentlige repoer, og én Gemini-forespørsel om
dagen ligger godt innenfor gratisnivået. Google kan bruke innhold sendt på gratisnivået til
å forbedre tjenestene sine. Her er det bare offentlige nyhetssaker.

## Viktig om offentlig repo

Alt i repoet er synlig for alle: nettsiden, arkivet og databasen. Innholdet består av
overskrifter og korte ingresser fra kildene, alltid med lenke tilbake.

## Tilpasning

| Hva | Hvor |
|---|---|
| Kilder | `FEEDS` i `agent.py` |
| Antall saker per nivå | `ANTALL_PER_NIVA` (hold den lav, så briefen forblir kort) |
| Maks punkter i «Følg med» | `MAKS_FOLG_MED` |
| AI-modeller | `AI_MODELLER` i workflow-filen |
| Hva som regnes som viktig | `VIKTIG` og `UVIKTIG` |
| Kategorier i «Følg med» | `KATEGORI_ORD` |
| Farger og typografi | `docs/stil.css` |
| Tidspunkt | `cron` i `.github/workflows/nyhetsbrief.yml` (i UTC) |

## Kjøre lokalt

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...   # valgfritt, uten nøkkel brukes reglene
python agent.py
python -m http.server -d docs     # åpne http://localhost:8000
```
