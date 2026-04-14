"""
user.py - Handler untuk user/pembaca Interactive Story Bot

Commands:
  /start    - Sambutan + daftar cerita
  /lanjut   - Lanjutkan membaca cerita yang sedang berjalan
  /reset    - Pilih cerita untuk diulang dari awal
  /progress - Lihat progress semua cerita

Urutan tampil per part: foto → gif → video → voice → teks
Cerita yang sudah selesai TIDAK dihapus otomatis (bisa dibaca ulang).
Untuk interaksi ulang dari awal, user gunakan /reset.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes

import database as db
from config import MEDIA_ORDER

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_story_keyboard(stories: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📖 {s['title']}", callback_data=f"story_{s['id']}")]
        for s in stories
    ])


def _build_choices_keyboard(choices: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(c['choice_text'], callback_data=f"choice_{c['id']}")]
        for c in choices
    ])


async def _delete_old_messages(bot: Bot, user_id: int, story_id: int):
    """Hapus pesan cerita lama dari chat (saat mulai ulang)."""
    messages = db.get_story_messages(user_id, story_id)
    for row in messages:
        try:
            await bot.delete_message(chat_id=row['chat_id'], message_id=row['message_id'])
        except Exception:
            pass
    db.clear_story_messages(user_id, story_id)


async def send_part(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    part_id: int,
    story_id: int,
    user_id: int,
):
    """
    Kirim konten sebuah part ke user.

    Urutan pengiriman:
      1. Foto
      2. GIF/animasi
      3. Video
      4. Voice note / audio
      5. Teks narasi (+ tombol pilihan)

    Saat ending: tampilkan pesan selesai + opsi mulai ulang.
    Pesan cerita TIDAK dihapus otomatis — user bisa scroll ke atas untuk membaca ulang.
    Gunakan /reset untuk interaksi ulang dari awal.
    """
    part = db.get_part_by_id(part_id)
    if not part:
        await update.effective_message.reply_text("❌ Part tidak ditemukan.")
        return

    # Simpan progress
    db.save_progress(user_id, story_id, part_id)

    # Nomor part
    all_parts = db.get_parts_by_story(story_id)
    part_num = next((i + 1 for i, p in enumerate(all_parts) if p['id'] == part_id), "?")

    choices = db.get_choices_by_part(part_id)
    is_ending = not bool(choices)

    # Ambil dan urutkan media: foto → gif → video → voice/audio
    media_items = db.get_part_media(part_id)
    media_sorted = sorted(media_items, key=lambda m: MEDIA_ORDER.get(m['media_type'], 99))

    chat_id = update.effective_chat.id
    sent_ids = []

    # ── Kirim media ────────────────────────────────────────────────────────────
    for media in media_sorted:
        mtype = media['media_type']
        fid = media['file_id']
        try:
            if mtype == "photo":
                msg = await update.effective_chat.send_photo(photo=fid)
            elif mtype == "animation":
                msg = await update.effective_chat.send_animation(animation=fid)
            elif mtype == "video":
                msg = await update.effective_chat.send_video(video=fid)
            elif mtype in ("voice", "audio"):
                msg = await update.effective_chat.send_voice(voice=fid)
            else:
                continue
            sent_ids.append(msg.message_id)
        except Exception as e:
            logger.warning(f"Gagal kirim media {mtype}: {e}")

    # ── Bangun teks narasi ────────────────────────────────────────────────────
    # Teks disimpan dalam format HTML (mendukung bold/italic/underline)
    part_text = part['text'] or ""
    header = f"📜 <b>Part {part_num}</b>"

    if is_ending:
        story = db.get_story_by_id(story_id)
        import html as html_module
        story_title = html_module.escape(story['title']) if story else "Cerita"
        body = f"{header}\n\n{part_text}" if part_text else header
        body += (
            "\n\n───────────────\n"
            f"🎉 <b>Tamat!</b> Kamu sudah menyelesaikan <i>{story_title}</i>.\n\n"
            "Pilih aksi:"
        )
        end_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Mulai Ulang", callback_data=f"newgame_{story_id}")],
            [InlineKeyboardButton("📚 Cerita Lain", callback_data="back_to_stories")],
        ])
        msg = await update.effective_chat.send_message(
            text=body, parse_mode="HTML", reply_markup=end_keyboard
        )
    else:
        body = f"{header}\n\n{part_text}" if part_text else header
        msg = await update.effective_chat.send_message(
            text=body,
            parse_mode="HTML",
            reply_markup=_build_choices_keyboard(choices)
        )

    sent_ids.append(msg.message_id)

    # Catat semua pesan untuk keperluan cleanup saat newgame
    for mid in sent_ids:
        db.add_story_message(user_id, story_id, chat_id, mid)


# ─── Command Handlers ─────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — Sambutan dan daftar cerita."""
    user = update.effective_user
    stories = db.get_all_stories()

    if not stories:
        await update.message.reply_text(
            f"Halo, *{user.first_name}*! 👋\n\n"
            "Belum ada cerita yang tersedia saat ini.\n"
            "Tunggu admin menambahkan cerita baru. 📝",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"Halo, *{user.first_name}*! 👋\n\n"
        "Selamat datang di *Interactive Story Bot*! 📚\n"
        "Setiap pilihanmu menentukan jalannya cerita.\n\n"
        "Pilih cerita yang ingin kamu baca:",
        parse_mode="Markdown",
        reply_markup=_build_story_keyboard(stories)
    )


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reset — Tampilkan daftar cerita untuk direset."""
    user_id = update.effective_user.id
    progress_list = db.get_all_user_progress(user_id)

    if not progress_list:
        await update.message.reply_text(
            "Kamu belum membaca cerita apa pun.\n"
            "Gunakan /start untuk memilih cerita. 📖"
        )
        return

    kb = [[InlineKeyboardButton(
        f"🔄 {p['title']}", callback_data=f"reset_{p['story_id']}"
    )] for p in progress_list]

    await update.message.reply_text(
        "🔄 *Reset Cerita*\n\nPilih cerita yang ingin diulang dari awal:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def progress_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/progress — Tampilkan progress semua cerita."""
    user_id = update.effective_user.id
    progress_list = db.get_all_user_progress(user_id)

    if not progress_list:
        await update.message.reply_text(
            "Kamu belum membaca cerita apa pun.\n"
            "Gunakan /start untuk memilih cerita. 📖"
        )
        return

    text = "📊 *Progress Membacamu:*\n\n"
    kb = []

    for prog in progress_list:
        all_parts = db.get_parts_by_story(prog['story_id'])
        part_num = next(
            (i + 1 for i, p in enumerate(all_parts) if p['id'] == prog['current_part_id']), "?"
        )
        total = len(all_parts)
        text += f"📖 *{prog['title']}*\n   ↳ Part {part_num} dari {total}\n\n"
        kb.append([InlineKeyboardButton(
            f"▶️ Lanjutkan: {prog['title']}",
            callback_data=f"continue_{prog['story_id']}_{prog['current_part_id']}"
        )])

    await update.message.reply_text(
        text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


# ─── Callback Handlers ────────────────────────────────────────────────────────

async def story_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User memilih cerita dari daftar."""
    query = update.callback_query
    await query.answer()

    story_id = int(query.data.split("_")[1])
    user_id = update.effective_user.id
    story = db.get_story_by_id(story_id)

    if not story:
        await query.edit_message_text("❌ Cerita tidak ditemukan.")
        return

    progress = db.get_progress(user_id, story_id)

    if progress:
        all_parts = db.get_parts_by_story(story_id)
        part_num = next(
            (i + 1 for i, p in enumerate(all_parts) if p['id'] == progress['current_part_id']), "?"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"▶️ Lanjutkan dari Part {part_num}",
                callback_data=f"continue_{story_id}_{progress['current_part_id']}"
            )],
            [InlineKeyboardButton("🔄 Mulai dari Awal", callback_data=f"newgame_{story_id}")],
        ])
        await query.edit_message_text(
            f"📖 *{story['title']}*\n\n"
            "Kamu sudah pernah membaca cerita ini!\n"
            "Ingin lanjutkan atau mulai dari awal?",
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        first_part = db.get_first_part(story_id)
        if not first_part:
            await query.edit_message_text(
                f"❌ Cerita *{story['title']}* belum memiliki konten.",
                parse_mode="Markdown"
            )
            return
        await query.edit_message_text(
            f"📖 Memulai: *{story['title']}*...", parse_mode="Markdown"
        )
        await send_part(update, context, first_part['id'], story_id, user_id)


async def continue_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lanjutkan dari progress tersimpan."""
    query = update.callback_query
    await query.answer()

    _, story_id, part_id = query.data.split("_")
    story_id, part_id = int(story_id), int(part_id)
    user_id = update.effective_user.id

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await send_part(update, context, part_id, story_id, user_id)


async def newgame_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mulai cerita dari awal — hapus pesan lama, reset progress."""
    query = update.callback_query
    await query.answer()

    story_id = int(query.data.split("_")[1])
    user_id = update.effective_user.id

    await _delete_old_messages(context.bot, user_id, story_id)
    db.reset_progress(user_id, story_id)

    first_part = db.get_first_part(story_id)
    if not first_part:
        await query.edit_message_text("❌ Cerita ini belum memiliki konten.")
        return

    story = db.get_story_by_id(story_id)
    await query.edit_message_text(
        f"🔄 Memulai ulang: *{story['title']}*...", parse_mode="Markdown"
    )
    await send_part(update, context, first_part['id'], story_id, user_id)


async def choice_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User memilih pilihan dalam cerita."""
    query = update.callback_query
    await query.answer()

    choice_id = int(query.data.split("_")[1])
    user_id = update.effective_user.id
    choice = db.get_choice_by_id(choice_id)

    if not choice:
        await query.answer("❌ Pilihan tidak valid.", show_alert=True)
        return

    if choice['next_part_id'] is None:
        await query.answer(
            "⚠️ Alur ini belum selesai dibuat. Tunggu admin ya!",
            show_alert=True
        )
        return

    # Tandai pilihan yang dipilih di pesan lama (hilangkan tombol)
    try:
        import html as html_module
        # Gunakan text_html agar formatting bold/italic yang sudah ada di pesan tetap terjaga
        old_html = query.message.text_html or query.message.text or ""
        await query.edit_message_text(
            old_html + f"\n\n<i>→ {html_module.escape(choice['choice_text'])}</i>",
            parse_mode="HTML",
            reply_markup=None
        )
    except Exception:
        pass

    current_part = db.get_part_by_id(choice['part_id'])
    if not current_part:
        return

    await send_part(update, context, choice['next_part_id'], current_part['story_id'], user_id)


async def reset_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Konfirmasi reset dari daftar /reset."""
    query = update.callback_query
    await query.answer()

    story_id = int(query.data.split("_")[1])
    user_id = update.effective_user.id

    await _delete_old_messages(context.bot, user_id, story_id)
    db.reset_progress(user_id, story_id)

    story = db.get_story_by_id(story_id)
    title = story['title'] if story else "cerita"
    first_part = db.get_first_part(story_id)

    if not first_part:
        await query.edit_message_text(f"❌ Cerita *{title}* belum punya konten.", parse_mode="Markdown")
        return

    await query.edit_message_text(
        f"🔄 Memulai ulang: *{title}*...", parse_mode="Markdown"
    )
    await send_part(update, context, first_part['id'], story_id, user_id)


async def back_to_stories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kembali ke daftar cerita."""
    query = update.callback_query
    await query.answer()
    stories = db.get_all_stories()
    if not stories:
        await query.edit_message_text("📭 Tidak ada cerita lain saat ini.")
        return
    await query.edit_message_text(
        "📚 Pilih cerita lain:",
        reply_markup=_build_story_keyboard(stories)
    )
