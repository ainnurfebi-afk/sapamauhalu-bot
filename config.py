import os

# Wajib diset melalui environment variable atau file .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN tidak ditemukan!\n"
        "Set environment variable BOT_TOKEN=<token_dari_BotFather>\n"
        "Atau salin .env.example ke .env dan isi nilainya."
    )

# URL koneksi PostgreSQL (Neon.tech / Railway)
# Jika kosong, bot akan menggunakan SQLite lokal (untuk development)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ID admin awal — diambil dari environment variable ADMIN_IDS
# Format: angka dipisah koma, contoh: 815334629,8665703718
# Minimal 1 ID harus diisi agar ada admin yang bisa login pertama kali.
# Setelah bot berjalan, admin bisa menambah admin lain via /addadmin di Telegram.
_raw_ids = os.getenv("ADMIN_IDS", "")
INITIAL_ADMIN_IDS = [
    int(uid.strip()) for uid in _raw_ids.split(",") if uid.strip().isdigit()
]
if not INITIAL_ADMIN_IDS:
    raise RuntimeError(
        "ADMIN_IDS tidak ditemukan atau kosong!\n"
        "Set environment variable ADMIN_IDS=<user_id_1>,<user_id_2>\n"
        "Contoh: ADMIN_IDS=815334629,8665703718\n"
        "User ID bisa dicek via @userinfobot di Telegram."
    )

# Urutan tampil media: lebih kecil = tampil lebih dulu
# foto → gif → video → voice/audio → teks
MEDIA_ORDER = {"photo": 0, "animation": 1, "video": 2, "voice": 3, "audio": 4}
