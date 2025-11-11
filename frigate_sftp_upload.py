import os
import time
import paramiko
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
import logging
import json
import threading
from datetime import datetime, timedelta

# Konfiguraatio ympäristömuuttujista
FRIGATE_CLIPS_DIR = os.getenv('FRIGATE_CLIPS_DIR', '/media/frigate/clips')
SFTP_HOST = os.getenv('SFTP_HOST')
SFTP_PORT = int(os.getenv('SFTP_PORT', '22'))
SFTP_USERNAME = os.getenv('SFTP_USERNAME')
SFTP_PASSWORD = os.getenv('SFTP_PASSWORD')
SFTP_PRIVATE_KEY_PATH = os.getenv('SFTP_PRIVATE_KEY_PATH')
SFTP_REMOTE_DIR = os.getenv('SFTP_REMOTE_DIR', '/uploads')

# Tiedostotunnisteet, jotka lähetetään
UPLOAD_EXTENSIONS = json.loads(os.getenv('UPLOAD_EXTENSIONS', '["jpg", "jpeg", "png", "mp4", "avi", "mov"]'))

# Uudelleenyritysasetukset
RETRY_INTERVAL_MINUTES = int(os.getenv('RETRY_INTERVAL_MINUTES', '5'))
MAX_RETRY_ATTEMPTS = int(os.getenv('MAX_RETRY_ATTEMPTS', '10'))
FAILED_UPLOADS_FILE = os.getenv('FAILED_UPLOADS_FILE', '/app/failed_uploads.json')

# Lokituksen asetukset
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('frigate-sftp-upload')

class FrigateClipHandler(FileSystemEventHandler):
    def __init__(self):
        self.sftp_client = None
        self.connected = False
        self.processed_files = set()
        self.failed_uploads = {}
        self.successful_uploads = set()
        self.upload_lock = threading.Lock()
        self.load_failed_uploads()
        self.connect_sftp()
        
    def load_failed_uploads(self):
        """Lataa epäonnistuneiden siirtojen tiedot tiedostosta"""
        try:
            if os.path.exists(FAILED_UPLOADS_FILE):
                with open(FAILED_UPLOADS_FILE, 'r') as f:
                    data = json.load(f)
                    self.failed_uploads = data.get('failed', {})
                    self.successful_uploads = set(data.get('successful', []))
                    logger.info(f"Ladattu {len(self.failed_uploads)} epäonnistunutta siirtoa tiedostosta")
        except Exception as e:
            logger.error(f"Epäonnistuneiden siirtojen lataaminen epäonnistui: {e}")
            self.failed_uploads = {}
            self.successful_uploads = set()
    
    def save_failed_uploads(self):
        """Tallenna epäonnistuneiden siirtojen tiedot tiedostoon"""
        try:
            with self.upload_lock:
                data = {
                    'failed': self.failed_uploads,
                    'successful': list(self.successful_uploads)
                }
                # Varmista että kansio on olemassa
                dir_path = os.path.dirname(FAILED_UPLOADS_FILE)
                if dir_path:  # Only create if dirname is not empty
                    os.makedirs(dir_path, exist_ok=True)
                with open(FAILED_UPLOADS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Epäonnistuneiden siirtojen tallentaminen epäonnistui: {e}")
    
    def connect_sftp(self):
        """Yhdistä SFTP-palvelimeen"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Yritetään yhdistää SFTP-palvelimeen ({attempt + 1}/{max_retries})...")
                
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                if SFTP_PRIVATE_KEY_PATH and os.path.exists(SFTP_PRIVATE_KEY_PATH):
                    # Käytä SSH-avainta
                    private_key = paramiko.RSAKey.from_private_key_file(SFTP_PRIVATE_KEY_PATH)
                    self.ssh_client.connect(
                        SFTP_HOST, 
                        port=SFTP_PORT, 
                        username=SFTP_USERNAME, 
                        pkey=private_key,
                        timeout=30
                    )
                    auth_method = "SSH-avain"
                else:
                    # Käytä salasanaa
                    self.ssh_client.connect(
                        SFTP_HOST, 
                        port=SFTP_PORT, 
                        username=SFTP_USERNAME, 
                        password=SFTP_PASSWORD,
                        timeout=30
                    )
                    auth_method = "salasana"
                
                self.sftp_client = self.ssh_client.open_sftp()
                self.connected = True
                logger.info(f"SFTP-yhteys muodostettu onnistuneesti ({auth_method})")
                
                # Varmista, että etäkansio on olemassa
                try:
                    self.sftp_client.stat(SFTP_REMOTE_DIR)
                except FileNotFoundError:
                    logger.info(f"Luodaan etäkansio: {SFTP_REMOTE_DIR}")
                    self.sftp_client.mkdir(SFTP_REMOTE_DIR)
                    
                break
                
            except Exception as e:
                logger.error(f"SFTP-yhteyden muodostaminen epäonnistui (yritys {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    logger.error("Kaikki SFTP-yhteyden yritykset epäonnistuivat")
                    self.connected = False
    
    def upload_file(self, file_path, is_retry=False):
        """Lähetä tiedosto SFTP-palvelimelle"""
        if not self.connected:
            logger.warning("Ei aktiivista SFTP-yhteyttä, yritetään uudelleen...")
            self.connect_sftp()
            if not self.connected:
                self.record_failed_upload(file_path, "Ei SFTP-yhteyttä")
                return False
        
        try:
            file_name = os.path.basename(file_path)
            remote_path = f"{SFTP_REMOTE_DIR}/{file_name}"
            
            # Tarkista, onko tiedosto valmis (ei kirjoitettavana)
            if self.is_file_ready(file_path):
                file_size = os.path.getsize(file_path)
                retry_info = f" (uudelleenyritys)" if is_retry else ""
                logger.info(f"Lähetetään tiedosto{retry_info}: {file_name} ({file_size} bytes)")
                
                self.sftp_client.put(file_path, remote_path)
                
                logger.info(f"Tiedosto {file_name} lähetetty onnistuneesti")
                self.record_successful_upload(file_path)
                return True
            else:
                logger.warning(f"Tiedosto {file_name} ei ole valmis, ohitetaan")
                # Jos tiedosto ei ole valmis, ei kirjata epäonnistuneeksi (yritetään myöhemmin)
                return False
                
        except Exception as e:
            logger.error(f"Tiedoston {file_path} lähetys epäonnistui: {e}")
            self.record_failed_upload(file_path, str(e))
            # Yritä uudelleenyhdistää seuraavaa yritystä varten
            self.connected = False
            return False
    
    def record_successful_upload(self, file_path):
        """Kirjaa onnistunut siirto"""
        with self.upload_lock:
            self.processed_files.add(file_path)
            self.successful_uploads.add(file_path)
            # Poista epäonnistuneiden listasta jos siellä
            if file_path in self.failed_uploads:
                del self.failed_uploads[file_path]
        # Save outside the lock to avoid deadlock
        self.save_failed_uploads()
    
    def record_failed_upload(self, file_path, error_message):
        """Kirjaa epäonnistunut siirto"""
        with self.upload_lock:
            current_time = datetime.now().isoformat()
            
            if file_path not in self.failed_uploads:
                self.failed_uploads[file_path] = {
                    'attempt_count': 1,
                    'first_attempt': current_time,
                    'last_attempt': current_time,
                    'last_error': error_message
                }
                logger.warning(f"Tiedosto lisätty epäonnistuneiden listaan: {file_path}")
            else:
                self.failed_uploads[file_path]['attempt_count'] += 1
                self.failed_uploads[file_path]['last_attempt'] = current_time
                self.failed_uploads[file_path]['last_error'] = error_message
                logger.warning(f"Päivitetty epäonnistuneen siirron tiedot: {file_path} (yritys {self.failed_uploads[file_path]['attempt_count']})")
        
        # Save outside the lock to avoid deadlock
        self.save_failed_uploads()
    
    def is_file_ready(self, file_path):
        """Tarkista onko tiedosto valmis lukemista/lähetystä varten"""
        max_attempts = 5
        attempt_delay = 2
        
        for attempt in range(max_attempts):
            try:
                # Tarkista että tiedosto on olemassa ja ei ole tyhjä
                if not os.path.exists(file_path):
                    return False
                    
                if os.path.getsize(file_path) == 0:
                    time.sleep(attempt_delay)
                    continue
                
                # Yritä avata tiedosto lukutilassa
                with open(file_path, 'rb'):
                    return True
            except (IOError, OSError):
                if attempt < max_attempts - 1:
                    time.sleep(attempt_delay)
                else:
                    return False
        return False
    
    def on_created(self, event):
        """Käsittele uudet tiedostot"""
        if event.is_directory:
            return
            
        file_path = event.src_path
        file_ext = os.path.splitext(file_path)[1].lower().lstrip('.')
        
        # Tarkista onko tiedosto jo käsitelty onnistuneesti
        if file_path in self.successful_uploads:
            return
            
        # Lähetä vain sallitut tiedostotyypit
        if file_ext in UPLOAD_EXTENSIONS:
            logger.info(f"Uusi tiedosto havaittu: {file_path}")
            
            # Odota hetki, että tiedosto on täysin kirjoitettu
            time.sleep(3)
            
            # Yritä lähettää tiedosto
            self.upload_file(file_path)
    
    def retry_failed_uploads(self):
        """Yritä lähettää epäonnistuneet tiedostot uudelleen"""
        if not self.failed_uploads:
            return
        
        logger.info(f"Yritetään lähettää {len(self.failed_uploads)} epäonnistunutta tiedostoa uudelleen...")
        
        # Kopioi lista jotta voi muokata alkuperäistä iteroidessa
        failed_list = list(self.failed_uploads.keys())
        
        for file_path in failed_list:
            # Tarkista onko tiedosto vielä olemassa
            if not os.path.exists(file_path):
                logger.warning(f"Tiedosto ei enää ole olemassa, poistetaan listasta: {file_path}")
                with self.upload_lock:
                    if file_path in self.failed_uploads:
                        del self.failed_uploads[file_path]
                    self.save_failed_uploads()
                continue
            
            # Tarkista onko maksimimäärä yrityksiä ylitetty
            attempt_count = self.failed_uploads[file_path]['attempt_count']
            if attempt_count >= MAX_RETRY_ATTEMPTS:
                logger.error(f"Tiedosto {file_path} ylitti maksimimäärän yrityksiä ({MAX_RETRY_ATTEMPTS}), jätetään listaan")
                continue
            
            # Yritä lähettää
            logger.info(f"Yritetään lähettää tiedosto uudelleen ({attempt_count + 1}/{MAX_RETRY_ATTEMPTS}): {file_path}")
            self.upload_file(file_path, is_retry=True)
    
    def cleanup(self):
        """Siivoa resurssit"""
        if hasattr(self, 'sftp_client') and self.sftp_client:
            self.sftp_client.close()
            logger.info("SFTP-yhteys suljettu")
        if hasattr(self, 'ssh_client') and self.ssh_client:
            self.ssh_client.close()
            logger.info("SSH-yhteys suljettu")

def check_environment():
    """Tarkista pakolliset ympäristömuuttujat"""
    required_vars = ['SFTP_HOST', 'SFTP_USERNAME']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Puuttuvat pakolliset ympäristömuuttujat: {', '.join(missing_vars)}")
        return False
    
    # Tarkista että joko salasana tai SSH-avain on annettu
    if not os.getenv('SFTP_PASSWORD') and not os.getenv('SFTP_PRIVATE_KEY_PATH'):
        logger.error("Joko SFTP_PASSWORD tai SFTP_PRIVATE_KEY_PATH on annettava")
        return False
    
    if os.getenv('SFTP_PRIVATE_KEY_PATH') and not os.path.exists(os.getenv('SFTP_PRIVATE_KEY_PATH')):
        logger.error(f"SSH-avaintiedostoa ei löydy: {os.getenv('SFTP_PRIVATE_KEY_PATH')}")
        return False
    
    return True

def main():
    logger.info("Käynnistetään Frigate SFTP Uploader...")
    
    # Tarkista ympäristömuuttujat
    if not check_environment():
        logger.error("Ympäristömuuttujien tarkistus epäonnistui")
        return
    
    # Tarkista että Frigaten kansio on olemassa
    if not os.path.exists(FRIGATE_CLIPS_DIR):
        logger.error(f"Kansiota {FRIGATE_CLIPS_DIR} ei löydy!")
        return
    
    logger.info(f"Tarkkaillaan kansiota: {FRIGATE_CLIPS_DIR}")
    logger.info(f"Lähetetään tiedostotyypit: {UPLOAD_EXTENSIONS}")
    
    event_handler = FrigateClipHandler()
    observer = Observer()
    observer.schedule(event_handler, FRIGATE_CLIPS_DIR, recursive=True)
    
    try:
        observer.start()
        logger.info("Tiedostotarkkailu käynnistetty onnistuneesti")
        logger.info(f"Epäonnistuneita siirtoja yritetään uudelleen {RETRY_INTERVAL_MINUTES} minuutin välein")
        
        # Laske seuraava uudelleenyritysaika
        next_retry_time = datetime.now() + timedelta(minutes=RETRY_INTERVAL_MINUTES)
        
        # Pidä sovellus käynnissä
        while True:
            time.sleep(10)
            
            # Tarkista säännöllisesti SFTP-yhteys
            if not event_handler.connected:
                logger.warning("SFTP-yhteys katkaistu, yritetään uudelleen...")
                event_handler.connect_sftp()
            
            # Yritä epäonnistuneet siirrot uudelleen säännöllisesti
            if datetime.now() >= next_retry_time:
                event_handler.retry_failed_uploads()
                next_retry_time = datetime.now() + timedelta(minutes=RETRY_INTERVAL_MINUTES)
            
    except KeyboardInterrupt:
        logger.info("Sovellus suljetaan...")
        observer.stop()
    except Exception as e:
        logger.error(f"Odottamaton virhe: {e}")
        observer.stop()
    finally:
        event_handler.cleanup()
        observer.join()
        logger.info("Sovellus suljettu")

if __name__ == "__main__":
    main()
