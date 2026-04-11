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

# ID admin awal (akan dimasukkan ke tabel admins saat init_db)
INITIAL_ADMIN_IDS = [815334629, 6532811092]

# Urutan tampil media: lebih kecil = tampil lebih dulu
# foto → gif → video → voice/audio → teks
MEDIA_ORDER = {"photo": 0, "animation": 1, "video": 2, "voice": 3, "audio": 4}
