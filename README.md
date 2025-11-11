# Frigate SFTP Upload

Automaattinen tiedostojen siirtopalvelu Frigate-tallenteilta SFTP-palvelimelle. Tukee automaattista uudelleenyritystä epäonnistuneille siirroille.

## Ominaisuudet

- 📁 Tarkkailee Frigate-klippikansion muutoksia reaaliajassa
- 🔄 Automaattinen uudelleenyritys epäonnistuneille siirroille
- 💾 Pysyvä tallennustila epäonnistuneille siirroille (säilyy uudelleenkäynnistyksissä)
- 🔐 Tukee sekä salasana- että SSH-avain-autentikointia
- 📊 Kattava lokitus ja virheilmoitukset
- ⚙️ Konfiguroitavat asetukset ympäristömuuttujilla

## Ympäristömuuttujat

### Pakolliset asetukset

- `SFTP_HOST` - SFTP-palvelimen osoite
- `SFTP_USERNAME` - SFTP-käyttäjätunnus
- `SFTP_PASSWORD` tai `SFTP_PRIVATE_KEY_PATH` - Jompikumpi autentikointimenetelmistä

### Valinnaiset asetukset

- `SFTP_PORT` - SFTP-portti (oletus: 22)
- `SFTP_REMOTE_DIR` - Etäkansio palvelimella (oletus: /uploads)
- `FRIGATE_CLIPS_DIR` - Paikallinen Frigate-klippikansio (oletus: /media/frigate/clips)
- `UPLOAD_EXTENSIONS` - JSON-lista ladattavista tiedostotyypeistä (oletus: ["jpg","jpeg","png","mp4","avi","mov"])
- `LOG_LEVEL` - Lokitustaso (oletus: INFO)

### Uudelleenyritysasetukset

- `RETRY_INTERVAL_MINUTES` - Epäonnistuneiden siirtojen uudelleenyritysväli minuuteissa (oletus: 5)
- `MAX_RETRY_ATTEMPTS` - Maksimimäärä uudelleenyrityksiä ennen luovuttamista (oletus: 10)
- `FAILED_UPLOADS_FILE` - Polku epäonnistuneiden siirtojen tallennustiedostoon (oletus: /app/failed_uploads.json)

## Käyttö Docker Composella

```yaml
version: '3.8'

services:
  frigate-sftp-upload:
    build: .
    container_name: frigate-sftp-upload
    restart: unless-stopped
    volumes:
      - /path/to/frigate/media:/media/frigate:ro
    environment:
      - SFTP_HOST=192.168.0.116
      - SFTP_USERNAME=camera
      - SFTP_PASSWORD=password
      - RETRY_INTERVAL_MINUTES=5
      - MAX_RETRY_ATTEMPTS=10
```

## Uudelleenyritysmekanismi

Kun tiedoston siirto epäonnistuu (esim. verkkovirhe tai palvelin ei ole tavoitettavissa):

1. Tiedosto lisätään epäonnistuneiden siirtojen jonoon
2. Jono tallennetaan JSON-tiedostoon ja säilyy uudelleenkäynnistysten yli
3. Sovellus yrittää siirtää epäonnistuneet tiedostot uudelleen `RETRY_INTERVAL_MINUTES` välein
4. Jokainen uudelleenyritys kirjataan lokiin yrityskerran kera
5. Jos tiedosto siirretään onnistuneesti, se poistetaan epäonnistuneiden listasta
6. Jos `MAX_RETRY_ATTEMPTS` ylittyy, tiedosto jätetään jonoon mutta sitä ei enää yritetä

### Epäonnistuneiden siirtojen tietorakenne

Jokainen epäonnistunut siirto sisältää:
- `attempt_count` - Yritysten määrä
- `first_attempt` - Ensimmäisen yrityksen aikaleima
- `last_attempt` - Viimeisimmän yrityksen aikaleima
- `last_error` - Viimeisin virheviesti

## Lokitus

Sovellus kirjaa kaikki tapahtumat lokiin:
- Uusien tiedostojen havaitseminen
- Onnistuneet siirrot
- Epäonnistuneet siirrot
- Uudelleenyritykset
- SFTP-yhteysongelmien
