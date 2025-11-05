FROM python:3.11-slim

# Asenna tarvittavat paketit
RUN apt-get update && apt-get install -y \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Asenna Python-kirjastot
RUN pip install paramiko watchdog

# Luo työkansio
WORKDIR /app

# Kopioi sovellustiedostot
COPY frigate_sftp_upload.py .
COPY entrypoint.sh .

# Tee entrypoint-skriptistä suoritettava
RUN chmod +x entrypoint.sh

# Luo kansio Frigaten klippejä varten
RUN mkdir -p /media/frigate/clips

# Käyttäjä, jonka alla sovellus ajetaan
RUN useradd -m -u 1000 appuser
RUN chown -R appuser:appuser /app /media/frigate
USER appuser

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
