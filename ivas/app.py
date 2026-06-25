"""
IVAS SMS Dashboard
- curl_cffi with Chrome TLS fingerprint (bypasses Cloudflare)
- ScraperAPI as HTTP proxy (optional but recommended)
- Cookie login + credential login fallback
"""
import os, re, json, time, logging
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from curl_cffi import requests as cffi_requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_URL      = "https://www.ivasms.com"
IVAS_EMAIL    = os.environ.get('IVAS_EMAIL', '')
IVAS_PASSWORD = os.environ.get('IVAS_PASSWORD', '')
BOT_API_KEY   = os.environ.get('BOT_API_KEY', 'changeme-secret-key')
DATA_DIR      = Path(__file__).parent / 'data'
COOKIES_FILE  = DATA_DIR / 'cookies.json'
CONFIG_FILE   = DATA_DIR / 'config.json'


# ─── Config ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> bool:
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"save_config: {e}")
        return False


def get_scraper_key() -> str:
    cfg = load_config()
    return cfg.get('scraper_api_key', '') or os.environ.get('SCRAPER_API_KEY', '')


def set_scraper_key(new_key: str) -> bool:
    cfg = load_config()
    cfg['scraper_api_key'] = new_key.strip()
    return save_config(cfg)


# ─── Cookies ──────────────────────────────────────────────────────────────────

def load_cookies_from_file() -> dict:
    raw = os.environ.get('COOKIES_JSON', '').strip()
    if not raw and COOKIES_FILE.exists():
        try:
            raw = COOKIES_FILE.read_text(encoding='utf-8').strip()
        except Exception as e:
            logger.error(f"Cannot read cookies file: {e}")
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        if isinstance(d, list):
            return {c['name']: c['value'] for c in d if 'name' in c and 'value' in c}
        if isinstance(d, dict):
            return d
    except Exception as e:
        logger.error(f"Cookie JSON parse error: {e}")
    return {}


def save_cookies_to_file(cookies_data) -> bool:
    try:
        COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        parsed = json.loads(cookies_data) if isinstance(cookies_data, str) else cookies_data
        COOKIES_FILE.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding='utf-8')
        logger.info(f"Cookies saved to {COOKIES_FILE}")
        return True
    except Exception as e:
        logger.error(f"save_cookies_to_file: {e}")
        return False


def clear_cookies_file() -> bool:
    try:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        logger.info("Cookies file cleared")
        return True
    except Exception as e:
        logger.error(f"clear_cookies_file: {e}")
        return False


# ─── IVAS Client ──────────────────────────────────────────────────────────────

class IVASClient:
    def __init__(self):
        self.session    = cffi_requests.Session(impersonate="chrome120")
        self.logged_in  = False
        self.csrf_token = None
        self._setup_headers()

    def _setup_headers(self):
        self.session.headers.update({
            'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection':      'keep-alive',
            'Sec-Fetch-Dest':  'document',
            'Sec-Fetch-Mode':  'navigate',
            'Sec-Fetch-Site':  'none',
            'Sec-Fetch-User':  '?1',
        })

    def _scraper_url(self, target_url: str) -> str:
        key = get_scraper_key()
        if not key:
            return target_url
        return f"http://api.scraperapi.com?api_key={key}&url={target_url}"

    def _req(self, method: str, url: str, retries: int = 3, **kwargs):
        kwargs.setdefault('timeout', 45)
        final_url = self._scraper_url(url)
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.request(method, final_url, **kwargs)
                logger.info(f"[{attempt}] {method.upper()} {url} → {resp.status_code}")
                return resp
            except Exception as e:
                logger.warning(f"[{attempt}/{retries}] {url}: {e}")
                if attempt < retries:
                    time.sleep(2 * attempt)
                else:
                    raise
        return None

    def _ajax_headers(self, referer: str) -> dict:
        return {
            'Accept':           'text/html, */*; q=0.01',
            'Content-Type':     'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin':           BASE_URL,
            'Referer':          referer,
        }

    def login(self) -> bool:
        self.logged_in  = False
        self.csrf_token = None
        self.session    = cffi_requests.Session(impersonate="chrome120")
        self._setup_headers()

        cookies = load_cookies_from_file()
        if cookies:
            for name, value in cookies.items():
                self.session.cookies.set(name, value, domain='www.ivasms.com')
            logger.info(f"Injected {len(cookies)} cookies — verifying…")
            if self._verify():
                return True
            logger.warning("Cookies invalid — trying credentials")

        if IVAS_EMAIL and IVAS_PASSWORD:
            return self._cred_login()

        logger.error("No valid cookies and no credentials set")
        return False

    def _verify(self) -> bool:
        try:
            resp = self._req('GET', f"{BASE_URL}/portal/numbers")
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                el   = soup.find('input', {'name': '_token'})
                if el:
                    self.csrf_token = el['value']
                    self.logged_in  = True
                    logger.info(f"Session valid. CSRF={self.csrf_token[:16]}…")
                    return True
                # Also check for logout link (still logged in)
                if soup.find('a', href=re.compile('/logout')):
                    self.logged_in = True
                    logger.info("Session valid (logout link found, no token)")
                    return True
                logger.warning(f"No _token found. Snippet: {resp.text[:300]}")
        except Exception as e:
            logger.error(f"_verify: {e}")
        return False

    def _cred_login(self) -> bool:
        key = get_scraper_key()
        logger.info(f"Credential login via {'ScraperAPI' if key else 'direct curl_cffi'}…")
        try:
            r1 = self._req('GET', f"{BASE_URL}/login")
            if not r1 or r1.status_code != 200:
                return False
            soup = BeautifulSoup(r1.text, 'html.parser')
            el   = soup.find('input', {'name': '_token'})
            if not el:
                logger.error("No CSRF token on login page")
                return False

            post_url = (
                f"http://api.scraperapi.com?api_key={key}&url={BASE_URL}/login"
                if key else f"{BASE_URL}/login"
            )
            r2 = self.session.request(
                'POST', post_url,
                data={'_token': el['value'], 'email': IVAS_EMAIL,
                      'password': IVAS_PASSWORD, 'remember': '1'},
                allow_redirects=True, timeout=45,
                headers={
                    'Content-Type':   'application/x-www-form-urlencoded',
                    'Origin':         BASE_URL,
                    'Referer':        f"{BASE_URL}/login",
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Dest': 'document',
                },
            )
            logger.info(f"POST /login → {r2.status_code if r2 else 'no response'}")
            if r2 and r2.status_code == 200:
                return self._verify()
        except Exception as e:
            logger.error(f"_cred_login: {e}")
        return False

    def ensure_login(self) -> bool:
        if self.logged_in and self.csrf_token:
            return True
        return self.login()

    def fetch_numbers(self):
        if not self.ensure_login():
            return None
        try:
            resp = self._req('GET', f"{BASE_URL}/portal/numbers")
            if not resp or resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, 'html.parser')
            out  = []
            for row in soup.select('table tbody tr'):
                cells = [c.get_text(strip=True) for c in row.find_all('td')]
                if cells and re.match(r'^\+?\d{7,}$', cells[0].replace(' ', '')):
                    out.append({
                        'number':     cells[0],
                        'range_name': cells[1] if len(cells) > 1 else '',
                        'rate':       cells[2] if len(cells) > 2 else '',
                        'limit':      cells[3] if len(cells) > 3 else '',
                    })
            if not out:
                seen = set()
                for m in re.finditer(r'\b(\d{10,})\b', resp.text):
                    n = m.group(1)
                    if n not in seen:
                        seen.add(n)
                        out.append({'number': n, 'range_name': '', 'rate': '', 'limit': ''})
            logger.info(f"Numbers: {len(out)}")
            return out
        except Exception as e:
            logger.error(f"fetch_numbers: {e}")
            return None

    def fetch_received_stats(self, from_date='', to_date=''):
        if not self.ensure_login():
            return None
        try:
            resp = self._req(
                'POST', f"{BASE_URL}/portal/sms/received/getsms",
                data={'from': from_date, 'to': to_date, '_token': self.csrf_token},
                headers=self._ajax_headers(f"{BASE_URL}/portal/sms/received"),
            )
            if not resp or resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, 'html.parser')

            def _t(sel):
                el = soup.select_one(sel)
                return el.get_text(strip=True).replace(' USD', '') if el else '0'

            details = []
            for item in soup.select('div.item'):
                rng  = item.select_one('.col-sm-4')
                cols = item.select('.col-3')
                if not rng:
                    continue
                def _p(el):
                    if not el: return '0'
                    p = el.select_one('p')
                    return p.get_text(strip=True) if p else el.get_text(strip=True)
                rev_el = (
                    item.select_one('.col-3:nth-child(5) p span.currency_cdr') or
                    item.select_one('.col-3:last-child p span')
                )
                details.append({
                    'range':   rng.get_text(strip=True),
                    'count':   _p(cols[0]) if cols else '0',
                    'paid':    _p(cols[1]) if len(cols) > 1 else '0',
                    'unpaid':  _p(cols[2]) if len(cols) > 2 else '0',
                    'revenue': rev_el.get_text(strip=True) if rev_el else '0',
                })

            result = {
                'count_sms':   _t('#CountSMS'),
                'paid_sms':    _t('#PaidSMS'),
                'unpaid_sms':  _t('#UnpaidSMS'),
                'revenue':     _t('#RevenueSMS'),
                'sms_details': details,
            }
            logger.info(f"Received: {result['count_sms']} SMS, {len(details)} ranges")
            return result
        except Exception as e:
            logger.error(f"fetch_received_stats: {e}")
            return None

    def fetch_live_sms(self):
        if not self.ensure_login():
            return None
        try:
            resp = self._req('GET', f"{BASE_URL}/portal/live/my_sms")
            if not resp or resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, 'html.parser')

            def _t(sid):
                el = soup.find(id=sid)
                return el.get_text(strip=True).replace(' USD', '').replace(',', '') if el else '0'

            stats    = {'total': _t('CountSMS'), 'paid': _t('PaidSMS'),
                        'unpaid': _t('UnpaidSMS'), 'revenue': _t('RevenueSMS')}
            nums_list = []
            seen      = set()
            for m in re.finditer(r'\b(\d{10,})\b', resp.text):
                n = m.group(1)
                if n not in seen:
                    seen.add(n)
                    nums_list.append(n)
            sid_rows = []
            for row in soup.select('table tbody tr'):
                cells = [c.get_text(strip=True) for c in row.find_all('td')]
                if len(cells) >= 2:
                    sid_rows.append({'sid': cells[0], 'paid': cells[1] if len(cells) > 1 else '',
                                     'limit': cells[2] if len(cells) > 2 else '',
                                     'message': cells[3] if len(cells) > 3 else ''})
            logger.info(f"Live: {stats}, {len(nums_list)} nums, {len(sid_rows)} rows")
            return {'stats': stats, 'sms_today': stats['total'],
                    'numbers': nums_list[:200], 'sid_rows': sid_rows}
        except Exception as e:
            logger.error(f"fetch_live_sms: {e}")
            return None


# ─── App bootstrap ─────────────────────────────────────────────────────────────

app    = Flask(__name__)
client = IVASClient()

logger.info("Boot login…")
if client.login():
    logger.info("Logged in OK")
else:
    logger.error(
        "Login FAILED — set SCRAPER_API_KEY + IVAS_EMAIL + IVAS_PASSWORD or update cookies via Telegram bot"
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({'status': 'IVAS Dashboard running', 'ts': datetime.utcnow().isoformat()})


@app.route('/api/healthz')
def healthz():
    return jsonify({'ok': True})


@app.route('/api/status')
def api_status():
    key = get_scraper_key()
    return jsonify({
        'logged_in':   client.logged_in,
        'has_cookies': bool(load_cookies_from_file()),
        'has_creds':   bool(IVAS_EMAIL and IVAS_PASSWORD),
        'using_proxy': bool(key),
        'scraper_key': f"{key[:6]}…{key[-4:]}" if len(key) > 10 else ('set' if key else 'not set'),
        'ts':          datetime.utcnow().isoformat(),
    })


@app.route('/api/numbers')
def api_numbers():
    d = client.fetch_numbers()
    if d is None:
        return jsonify({'error': 'fetch failed'}), 500
    return jsonify({'numbers': d, 'count': len(d)})


@app.route('/api/received')
def api_received():
    d = client.fetch_received_stats(request.args.get('from', ''), request.args.get('to', ''))
    if d is None:
        return jsonify({'error': 'fetch failed'}), 500
    return jsonify(d)


@app.route('/api/live')
def api_live():
    d = client.fetch_live_sms()
    if d is None:
        return jsonify({'error': 'fetch failed'}), 500
    return jsonify(d)


@app.route('/api/all')
def api_all():
    today    = datetime.now().strftime('%Y-%m-%d')
    numbers  = client.fetch_numbers()
    received = client.fetch_received_stats(today, today)
    live     = client.fetch_live_sms()
    errors   = [k for k, v in [('numbers', numbers), ('received', received), ('live', live)] if v is None]
    if errors:
        return jsonify({'error': f"Failed: {', '.join(errors)}"}), 500
    return jsonify({'numbers': numbers, 'received': received, 'live': live,
                    'ts': datetime.utcnow().isoformat()})


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    client.logged_in  = False
    client.csrf_token = None
    success = client.login()
    return jsonify({'success': success, 'ts': datetime.utcnow().isoformat()})


@app.route('/api/cookies', methods=['POST'])
def api_update_cookies():
    data = request.get_json(silent=True) or {}
    if data.get('api_key') != BOT_API_KEY:
        return jsonify({'error': 'unauthorized'}), 401
    cookies_payload = data.get('cookies')
    if not cookies_payload:
        return jsonify({'error': 'no cookies provided'}), 400
    ok = save_cookies_to_file(cookies_payload)
    if not ok:
        return jsonify({'error': 'failed to save cookies'}), 500
    client.logged_in  = False
    client.csrf_token = None
    login_ok = client.login()
    return jsonify({'saved': True, 'login_ok': login_ok, 'ts': datetime.utcnow().isoformat()})


@app.route('/api/cookies/clear', methods=['POST'])
def api_clear_cookies():
    data = request.get_json(silent=True) or {}
    if data.get('api_key') != BOT_API_KEY:
        return jsonify({'error': 'unauthorized'}), 401
    ok = clear_cookies_file()
    if not ok:
        return jsonify({'error': 'failed to clear cookies'}), 500
    client.logged_in  = False
    client.csrf_token = None
    # Try credential login after clearing cookies
    login_ok = client.login()
    return jsonify({'cleared': True, 'login_ok': login_ok, 'ts': datetime.utcnow().isoformat()})


@app.route('/api/cookies/status')
def api_cookie_status():
    cookies = load_cookies_from_file()
    key     = get_scraper_key()
    return jsonify({
        'has_cookies':  bool(cookies),
        'cookie_names': list(cookies.keys()),
        'logged_in':    client.logged_in,
        'using_proxy':  bool(key),
        'scraper_key':  f"{key[:6]}…{key[-4:]}" if len(key) > 10 else ('set' if key else 'not set'),
    })


@app.route('/api/scraperkey', methods=['POST'])
def api_set_scraper_key():
    data = request.get_json(silent=True) or {}
    if data.get('api_key') != BOT_API_KEY:
        return jsonify({'error': 'unauthorized'}), 401
    new_key = (data.get('scraper_key') or '').strip()
    if not new_key:
        return jsonify({'error': 'scraper_key required'}), 400
    ok = set_scraper_key(new_key)
    if not ok:
        return jsonify({'error': 'failed to save key'}), 500
    client.logged_in  = False
    client.csrf_token = None
    login_ok = client.login()
    return jsonify({
        'saved':    True,
        'login_ok': login_ok,
        'key_hint': f"{new_key[:6]}…{new_key[-4:]}",
        'ts':       datetime.utcnow().isoformat(),
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
