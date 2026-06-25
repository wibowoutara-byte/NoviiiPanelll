"""
IVAS Telegram Bot
Commands:
  /start      — Menu utama
  /status     — Status login & cookie
  /setcookie  — Tambah/update cookie (paste JSON)
  /clearcookie — Hapus semua cookie tersimpan
  /setapikey  — Ganti ScraperAPI key
  /refresh    — Force re-login
  /numbers    — Daftar nomor aktif
  /received   — Statistik SMS received
  /live       — Live SMS hari ini
  /otps       — OTP terbaru
  /cekapi     — Cek semua endpoint
  /help       — Bantuan
"""
import os, json, logging, asyncio
import httpx
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '') or os.environ.get('BOT_TOKEN', '')
ADMIN_IDS   = [int(x.strip()) for x in os.environ.get('ADMIN_ID', '').split(',') if x.strip().isdigit()]
BOT_API_KEY = os.environ.get('BOT_API_KEY', 'changeme-secret-key')
FLASK_URL   = os.environ.get('FLASK_URL', 'http://localhost:5000')

WAITING_COOKIE = 1
WAITING_APIKEY = 2

CANCEL_KB     = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="cancel_cookie")]])
CANCEL_KEY_KB = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="cancel_apikey")]])


def is_admin(uid: int) -> bool:
    return not ADMIN_IDS or uid in ADMIN_IDS


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Status",        callback_data="status"),
         InlineKeyboardButton("🍪 Set Cookie",    callback_data="setcookie")],
        [InlineKeyboardButton("🗑️ Hapus Cookie",  callback_data="clearcookie"),
         InlineKeyboardButton("🔄 Refresh Login", callback_data="refresh")],
        [InlineKeyboardButton("📱 Numbers",       callback_data="numbers"),
         InlineKeyboardButton("📨 Received SMS",  callback_data="received")],
        [InlineKeyboardButton("⚡ Live SMS",      callback_data="live"),
         InlineKeyboardButton("🔑 OTPs",          callback_data="otps")],
        [InlineKeyboardButton("📡 Cek Semua API", callback_data="cekapi"),
         InlineKeyboardButton("🔑 ScraperAPI Key",callback_data="setapikey")],
        [InlineKeyboardButton("❓ Bantuan",        callback_data="help")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")]])


async def _flask(method: str, path: str, timeout: int = 90, **kwargs):
    async with httpx.AsyncClient(timeout=timeout) as c:
        return await getattr(c, method)(f"{FLASK_URL}{path}", **kwargs)


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(f"Halo {user.first_name}! Bot ini khusus admin IVAS.")
        return
    await update.message.reply_text(
        f"👋 Halo *{user.first_name}!*\n\n"
        "🤖 *IVAS Dashboard Bot*\n"
        "Monitor & kelola ivasms.com langsung dari Telegram.\n\n"
        "Pilih menu:",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard(),
    )


# ─── Status ──────────────────────────────────────────────────────────────────

async def show_status(message, edit=False):
    try:
        resp = await _flask('get', '/api/cookies/status')
        d    = resp.json()
        names = ', '.join(f'`{n}`' for n in d.get('cookie_names', [])) or '—'
        proxy = '✅ ScraperAPI' if d.get('using_proxy') else '⚠️ Direct'
        logged = d.get('logged_in', False)
        text = (
            "📊 *Status IVAS Dashboard*\n\n"
            f"🔐 Login:   {'✅ Aktif' if logged else '❌ Gagal'}\n"
            f"🍪 Cookie:  {'✅ Ada (' + str(len(d.get('cookie_names',[]))) + ' item)' if d.get('has_cookies') else '❌ Kosong'}\n"
            f"🌐 Proxy:   {proxy}\n"
            f"📋 Keys:    {names}\n\n"
            + ("✅ Dashboard berjalan normal." if logged
               else "⚠️ Cookie invalid/kosong.\nGunakan *Set Cookie* untuk update, atau *Refresh* untuk coba credentials.")
        )
    except Exception as e:
        text = f"❌ Tidak bisa menghubungi dashboard:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Set Cookie",    callback_data="setcookie"),
         InlineKeyboardButton("🗑️ Hapus Cookie", callback_data="clearcookie")],
        [InlineKeyboardButton("🔄 Refresh",       callback_data="refresh"),
         InlineKeyboardButton("📡 Cek API",       callback_data="cekapi")],
        [InlineKeyboardButton("🔙 Menu Utama",    callback_data="main_menu")],
    ])
    if edit:
        await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = await update.message.reply_text("⏳ Mengecek status…")
    await show_status(msg, edit=True)


# ─── Refresh ─────────────────────────────────────────────────────────────────

async def do_refresh(message, edit=False):
    try:
        resp = await _flask('post', '/api/refresh')
        ok   = resp.json().get('success', False)
        text = (
            "✅ *Login berhasil di-refresh!*" if ok
            else "❌ *Refresh gagal.* Cookie expired — update dengan /setcookie atau cek credentials."
        )
    except Exception as e:
        text = f"❌ Tidak bisa menghubungi dashboard:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Set Cookie",  callback_data="setcookie"),
         InlineKeyboardButton("📊 Status",      callback_data="status")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    if edit:
        await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = await update.message.reply_text("⏳ Force refresh login…")
    await do_refresh(msg, edit=True)


# ─── Cek Semua API ───────────────────────────────────────────────────────────

async def show_cekapi(message, edit=False):
    loading = "⏳ Mengecek semua endpoint API IVAS…\n(mungkin 30–60 detik)"
    if edit:
        await message.edit_text(loading)
    else:
        message = await message.reply_text(loading)
        edit = True

    endpoints = [
        ('/api/cookies/status', 'Status/Cookie'),
        ('/api/numbers',        'Numbers'),
        ('/api/received',       'Received SMS'),
        ('/api/live',           'Live SMS'),
    ]
    lines = [f"📡 *Hasil Cek API IVAS*\n`{datetime.now().strftime('%H:%M:%S %d/%m/%Y')}`\n"]

    for path, label in endpoints:
        try:
            resp = await _flask('get', path, timeout=120)
            if resp.status_code == 200:
                d = resp.json()
                if 'numbers' in path:
                    detail = f"{d.get('count', '?')} nomor"
                elif 'received' in path:
                    detail = f"{d.get('count_sms','?')} SMS | ${d.get('revenue','?')}"
                elif 'live' in path:
                    s = d.get('stats', {})
                    detail = f"total {s.get('total','?')} | ${s.get('revenue','?')}"
                elif 'status' in path:
                    detail = '✅ login' if d.get('logged_in') else '❌ tidak login'
                else:
                    detail = 'OK'
                lines.append(f"✅ *{label}*: {detail}")
            else:
                lines.append(f"⚠️ *{label}*: HTTP {resp.status_code}")
        except Exception as e:
            lines.append(f"❌ *{label}*: `{str(e)[:60]}`")

    text = '\n'.join(lines)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Numbers",    callback_data="numbers"),
         InlineKeyboardButton("📨 Received",  callback_data="received")],
        [InlineKeyboardButton("⚡ Live SMS",  callback_data="live"),
         InlineKeyboardButton("🔑 OTPs",      callback_data="otps")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_cekapi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await show_cekapi(update.message, edit=False)


# ─── Numbers ─────────────────────────────────────────────────────────────────

async def show_numbers(message, edit=False):
    if not edit:
        message = await message.reply_text("⏳ Mengambil daftar nomor…")
        edit = True
    else:
        await message.edit_text("⏳ Mengambil daftar nomor…")

    try:
        resp = await _flask('get', '/api/numbers', timeout=120)
        if resp.status_code != 200:
            text = f"❌ Error HTTP {resp.status_code}:\n`{resp.text[:200]}`"
        else:
            d    = resp.json()
            nums = d.get('numbers', [])
            if not nums:
                text = "📱 *Daftar Nomor*\n\n_Tidak ada nomor ditemukan._"
            else:
                lines = [f"📱 *Daftar Nomor IVAS* ({d.get('count', len(nums))} total)\n"]
                for i, n in enumerate(nums[:20], 1):
                    rate  = f" | rate: {n['rate']}"       if n.get('rate')       else ''
                    limit = f" | limit: {n['limit']}"     if n.get('limit')      else ''
                    rng   = f" ({n['range_name']})"       if n.get('range_name') else ''
                    lines.append(f"{i}. `{n['number']}`{rng}{rate}{limit}")
                if len(nums) > 20:
                    lines.append(f"\n_… dan {len(nums)-20} nomor lainnya_")
                text = '\n'.join(lines)
    except Exception as e:
        text = f"❌ Gagal:\n`{e}`"

    await message.edit_text(text, parse_mode='Markdown', reply_markup=back_kb())


async def cmd_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await show_numbers(update.message, edit=False)


# ─── Received Stats ───────────────────────────────────────────────────────────

async def show_received(message, edit=False):
    if not edit:
        message = await message.reply_text("⏳ Mengambil statistik SMS received…")
        edit = True
    else:
        await message.edit_text("⏳ Mengambil statistik SMS received…")

    try:
        resp = await _flask('get', '/api/received', timeout=120)
        if resp.status_code != 200:
            text = f"❌ Error HTTP {resp.status_code}"
        else:
            d       = resp.json()
            details = d.get('sms_details', [])
            lines   = [
                "📨 *Statistik SMS Received*\n",
                f"📊 Total SMS : `{d.get('count_sms','0')}`",
                f"✅ Paid      : `{d.get('paid_sms','0')}`",
                f"❌ Unpaid    : `{d.get('unpaid_sms','0')}`",
                f"💰 Revenue   : `${d.get('revenue','0')}`",
            ]
            if details:
                lines.append(f"\n📋 *Per Range* ({len(details)} range):")
                for det in details[:10]:
                    lines.append(
                        f"• `{det.get('range','?')}` — "
                        f"{det.get('count','0')} SMS "
                        f"(paid: {det.get('paid','0')}, unpaid: {det.get('unpaid','0')})"
                    )
                if len(details) > 10:
                    lines.append(f"_… +{len(details)-10} range lainnya_")
            text = '\n'.join(lines)
    except Exception as e:
        text = f"❌ Gagal:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 OTPs",        callback_data="otps"),
         InlineKeyboardButton("⚡ Live SMS",    callback_data="live")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await show_received(update.message, edit=False)


# ─── Live SMS ────────────────────────────────────────────────────────────────

async def show_live(message, edit=False):
    if not edit:
        message = await message.reply_text("⏳ Mengambil data live SMS…")
        edit = True
    else:
        await message.edit_text("⏳ Mengambil data live SMS…")

    try:
        resp = await _flask('get', '/api/live', timeout=120)
        if resp.status_code != 200:
            text = f"❌ Error HTTP {resp.status_code}"
        else:
            d    = resp.json()
            s    = d.get('stats', {})
            nums = d.get('numbers', [])
            rows = d.get('sid_rows', [])
            lines = [
                "⚡ *Live SMS Hari Ini*\n",
                f"📊 Total SMS : `{s.get('total','0')}`",
                f"✅ Paid      : `{s.get('paid','0')}`",
                f"❌ Unpaid    : `{s.get('unpaid','0')}`",
                f"💰 Revenue   : `${s.get('revenue','0')}`",
            ]
            if nums:
                lines.append(f"\n📱 *Nomor Aktif* ({len(nums)}):")
                for n in nums[:10]:
                    lines.append(f"  `{n}`")
                if len(nums) > 10:
                    lines.append(f"  _… +{len(nums)-10} lainnya_")
            text = '\n'.join(lines)
    except Exception as e:
        text = f"❌ Gagal:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 Received", callback_data="received"),
         InlineKeyboardButton("🔑 OTPs",    callback_data="otps")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await show_live(update.message, edit=False)


# ─── OTPs ────────────────────────────────────────────────────────────────────

async def show_otps(message, edit=False):
    if not edit:
        message = await message.reply_text("⏳ Mengambil OTP terbaru (bisa 1–2 menit)…")
        edit = True
    else:
        await message.edit_text("⏳ Mengambil OTP terbaru…")

    try:
        resp = await _flask('get', '/api/received', timeout=180)
        if resp.status_code != 200:
            text = f"❌ Error HTTP {resp.status_code}"
        else:
            d       = resp.json()
            details = d.get('sms_details', [])
            lines   = [f"🔑 *OTP / Received SMS*\n",
                       f"📊 Total: `{d.get('count_sms','?')}` | Revenue: `${d.get('revenue','?')}`\n"]
            if not details:
                lines.append("_Tidak ada data._")
            else:
                for det in details[:15]:
                    lines.append(
                        f"• `{det.get('range','?')}` — {det.get('count','0')} SMS | paid: {det.get('paid','0')}"
                    )
            text = '\n'.join(lines)
    except Exception as e:
        text = f"❌ Gagal:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh",      callback_data="otps"),
         InlineKeyboardButton("📨 Received",    callback_data="received")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_otps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await show_otps(update.message, edit=False)


# ─── Set Cookie (conversation) ───────────────────────────────────────────────

SET_COOKIE_PROMPT = (
    "🍪 *Tambah / Update Cookie IVAS*\n\n"
    "Paste cookie dalam format JSON dari browser.\n\n"
    "*Format array (Cookie-Editor extension):*\n"
    "```\n"
    '[\n  {"name":"ivas_sms_session","value":"eyJ..."},\n'
    '  {"name":"XSRF-TOKEN","value":"eyJ..."}\n]\n'
    "```\n\n"
    "*Format object:*\n"
    "```\n"
    '{"ivas_sms_session":"eyJ...","XSRF-TOKEN":"eyJ..."}\n'
    "```\n\n"
    "💡 Cara: Login ivasms.com → install *Cookie-Editor* → Export → Copy JSON → paste di sini.\n\n"
    "Kirim JSON cookie:"
)


async def cmd_setcookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    # Works for both /setcookie command and inline button
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            SET_COOKIE_PROMPT, parse_mode='Markdown', reply_markup=CANCEL_KB,
        )
    else:
        await update.message.reply_text(SET_COOKIE_PROMPT, parse_mode='Markdown', reply_markup=CANCEL_KB)
    return WAITING_COOKIE


async def receive_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    raw = update.message.text.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        await update.message.reply_text(
            f"❌ *JSON tidak valid!*\n\n`{e}`\n\nCoba paste ulang.",
            parse_mode='Markdown', reply_markup=CANCEL_KB,
        )
        return WAITING_COOKIE

    if isinstance(parsed, list):
        if not all(isinstance(c, dict) and 'name' in c and 'value' in c for c in parsed):
            await update.message.reply_text(
                "⚠️ Array tidak valid — setiap item harus punya `name` dan `value`.",
                parse_mode='Markdown', reply_markup=CANCEL_KB,
            )
            return WAITING_COOKIE
        count = len(parsed)
        names = [c['name'] for c in parsed]
    elif isinstance(parsed, dict):
        count = len(parsed)
        names = list(parsed.keys())
    else:
        await update.message.reply_text("❌ Format tidak dikenali. Gunakan [] atau {}.")
        return WAITING_COOKIE

    msg = await update.message.reply_text(f"⏳ Menyimpan {count} cookie dan login ulang…")

    try:
        resp = await _flask('post', '/api/cookies',
                            json={'api_key': BOT_API_KEY, 'cookies': parsed})
        d    = resp.json()
        if resp.status_code == 200:
            names_str = ', '.join(f'`{n}`' for n in names[:5])
            if len(names) > 5:
                names_str += f' … +{len(names)-5} lagi'
            login_ok = d.get('login_ok', False)
            text = (
                "✅ *Cookie berhasil disimpan!*\n\n"
                f"🍪 Tersimpan: {count} cookie\n"
                f"📋 Keys: {names_str}\n"
                f"🔐 Login: {'✅ Berhasil!' if login_ok else '❌ Gagal — cookie mungkin expired'}\n\n"
                + ("Dashboard aktif!" if login_ok else "Coba export cookie yang lebih baru.")
            )
        else:
            text = f"❌ *Gagal!*\n\n`{d.get('error', resp.text)}`"
    except Exception as e:
        text = f"❌ Tidak bisa menghubungi dashboard:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Status",      callback_data="status"),
         InlineKeyboardButton("📡 Cek API",    callback_data="cekapi")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    await msg.edit_text(text, parse_mode='Markdown', reply_markup=kb)
    return ConversationHandler.END


# ─── Clear Cookie ─────────────────────────────────────────────────────────────

async def do_clearcookie(message, edit=False):
    try:
        resp = await _flask('post', '/api/cookies/clear', json={'api_key': BOT_API_KEY})
        d    = resp.json()
        if resp.status_code == 200:
            login_ok = d.get('login_ok', False)
            text = (
                "🗑️ *Cookie berhasil dihapus!*\n\n"
                f"🔐 Login ulang via credentials: {'✅ Berhasil' if login_ok else '❌ Gagal'}\n\n"
                + ("Sekarang login via credentials (email/password)." if login_ok
                   else "Login gagal — pastikan credentials (IVAS_EMAIL/PASSWORD) dikonfigurasi di Railway env.")
            )
        else:
            text = f"❌ Gagal:\n`{d.get('error','unknown error')}`"
    except Exception as e:
        text = f"❌ Tidak bisa menghubungi dashboard:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Set Cookie Baru", callback_data="setcookie"),
         InlineKeyboardButton("📊 Status",         callback_data="status")],
        [InlineKeyboardButton("🔙 Menu Utama",     callback_data="main_menu")],
    ])
    if edit:
        await message.edit_text(text, parse_mode='Markdown', reply_markup=kb)
    else:
        await message.reply_text(text, parse_mode='Markdown', reply_markup=kb)


async def cmd_clearcookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = await update.message.reply_text("⏳ Menghapus cookies…")
    await do_clearcookie(msg, edit=True)


# ─── Set ScraperAPI Key (conversation) ───────────────────────────────────────

async def cmd_setapikey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = (
        "🔑 *Ganti ScraperAPI Key*\n\n"
        "Dapatkan key di https://www.scraperapi.com → Dashboard.\n\n"
        "Kirim API key baru:"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode='Markdown', reply_markup=CANCEL_KEY_KB)
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=CANCEL_KEY_KB)
    return WAITING_APIKEY


async def receive_apikey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    new_key = update.message.text.strip()
    if len(new_key) < 10 or ' ' in new_key:
        await update.message.reply_text(
            "❌ Key tidak valid. Coba lagi:", reply_markup=CANCEL_KEY_KB,
        )
        return WAITING_APIKEY

    msg = await update.message.reply_text("⏳ Menyimpan key baru dan re-login…")
    try:
        resp = await _flask('post', '/api/scraperkey',
                            json={'api_key': BOT_API_KEY, 'scraper_key': new_key},
                            timeout=90)
        d = resp.json()
        if resp.status_code == 200:
            hint     = d.get('key_hint', f"{new_key[:6]}…{new_key[-4:]}")
            login_ok = d.get('login_ok', False)
            text = (
                "✅ *ScraperAPI Key diupdate!*\n\n"
                f"🔑 Key: `{hint}`\n"
                f"🔐 Login ulang: {'✅ Berhasil' if login_ok else '❌ Gagal — cek key di scraperapi.com'}"
            )
        else:
            text = f"❌ Gagal:\n`{d.get('error','unknown error')}`"
    except Exception as e:
        text = f"❌ Tidak bisa menghubungi dashboard:\n`{e}`"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Status",      callback_data="status"),
         InlineKeyboardButton("📡 Cek API",    callback_data="cekapi")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")],
    ])
    await msg.edit_text(text, parse_mode='Markdown', reply_markup=kb)
    return ConversationHandler.END


# ─── Cancel handlers ─────────────────────────────────────────────────────────

async def cancel_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ Dibatalkan.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")]]),
    )
    return ConversationHandler.END


async def cancel_apikey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ Dibatalkan.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")]]),
    )
    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Dibatalkan.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ─── Help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *Bantuan IVAS Bot*\n\n"
        "`/start`        — Menu utama\n"
        "`/status`       — Cek status login & cookie\n"
        "`/setcookie`    — Tambah/update cookie dari browser\n"
        "`/clearcookie`  — Hapus semua cookie tersimpan\n"
        "`/setapikey`    — Ganti ScraperAPI key\n"
        "`/refresh`      — Force re-login\n"
        "`/numbers`      — Daftar nomor aktif\n"
        "`/received`     — Statistik SMS received\n"
        "`/live`         — Live SMS hari ini\n"
        "`/otps`         — OTP terbaru\n"
        "`/cekapi`       — Cek semua endpoint API\n"
        "`/help`         — Bantuan ini\n\n"
        "🍪 *Cara update cookie:*\n"
        "1. Login di browser → ivasms.com\n"
        "2. Install *Cookie-Editor* extension\n"
        "3. Klik icon → Export → Copy JSON\n"
        "4. /setcookie → paste JSON\n\n"
        "🗑️ *Hapus cookie:* /clearcookie\n"
        "→ Session akan coba login via credentials (email/password)"
    )
    msg = update.effective_message
    if hasattr(msg, 'reply_text'):
        await msg.reply_text(text, parse_mode='Markdown', reply_markup=back_kb())
    else:
        await msg.edit_text(text, parse_mode='Markdown', reply_markup=back_kb())


# ─── Button handler ──────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'main_menu':
        await query.edit_message_text(
            "🤖 *IVAS Dashboard Bot*\n\nPilih menu:",
            parse_mode='Markdown', reply_markup=main_menu_keyboard(),
        )
    elif data == 'status':
        await show_status(query.message, edit=True)
    elif data == 'refresh':
        await query.edit_message_text("⏳ Force refresh login…")
        await do_refresh(query.message, edit=True)
    elif data == 'clearcookie':
        await query.edit_message_text("⏳ Menghapus cookies…")
        await do_clearcookie(query.message, edit=True)
    elif data == 'cekapi':
        await show_cekapi(query.message, edit=True)
    elif data == 'numbers':
        await show_numbers(query.message, edit=True)
    elif data == 'received':
        await show_received(query.message, edit=True)
    elif data == 'live':
        await show_live(query.message, edit=True)
    elif data == 'otps':
        await show_otps(query.message, edit=True)
    elif data == 'help':
        await cmd_help(update, context)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation: set cookie
    cookie_conv = ConversationHandler(
        entry_points=[
            CommandHandler('setcookie', cmd_setcookie),
            CallbackQueryHandler(cmd_setcookie, pattern='^setcookie$'),
        ],
        states={
            WAITING_COOKIE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cookie),
                CallbackQueryHandler(cancel_cookie, pattern='^cancel_cookie$'),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_cmd),
            CallbackQueryHandler(cancel_cookie, pattern='^cancel_cookie$'),
        ],
    )

    # Conversation: set apikey
    apikey_conv = ConversationHandler(
        entry_points=[
            CommandHandler('setapikey', cmd_setapikey),
            CallbackQueryHandler(cmd_setapikey, pattern='^setapikey$'),
        ],
        states={
            WAITING_APIKEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_apikey),
                CallbackQueryHandler(cancel_apikey, pattern='^cancel_apikey$'),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_cmd),
            CallbackQueryHandler(cancel_apikey, pattern='^cancel_apikey$'),
        ],
    )

    app.add_handler(cookie_conv)
    app.add_handler(apikey_conv)
    app.add_handler(CommandHandler('start',       cmd_start))
    app.add_handler(CommandHandler('status',      cmd_status))
    app.add_handler(CommandHandler('refresh',     cmd_refresh))
    app.add_handler(CommandHandler('clearcookie', cmd_clearcookie))
    app.add_handler(CommandHandler('numbers',     cmd_numbers))
    app.add_handler(CommandHandler('received',    cmd_received))
    app.add_handler(CommandHandler('live',        cmd_live))
    app.add_handler(CommandHandler('otps',        cmd_otps))
    app.add_handler(CommandHandler('cekapi',      cmd_cekapi))
    app.add_handler(CommandHandler('help',        cmd_help))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Telegram bot started (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
