"""
admin.py - Handler admin untuk Interactive Story Bot

Commands:
  /admin        - Panel utama admin
  /inputcerita  - Buat cerita baru + part pertama
  /inputpart    - Tambah part ke cabang yang belum selesai
  /editpart     - Edit teks/media part yang ada
  /listcerita   - Daftar semua cerita
  /preview      - Lihat struktur pohon cerita
  /addadmin     - Tambahkan admin baru
  /cancel       - Batalkan sesi saat ini

Urutan input : teks dulu → media (foto/gif/video/voice)
Urutan tampil: foto → gif → video → voice → teks
"""

import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
)
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import MEDIA_ORDER

logger = logging.getLogger(__name__)

# ─── Conversation States ──────────────────────────────────────────────────────
(
    IC_WAIT_TITLE,       # 0 Menunggu judul cerita baru
    IC_WAIT_TEXT,        # 1 Menunggu teks narasi part
    IC_WAIT_MEDIA,       # 2 Menunggu media (bisa banyak); /skipmedia lewati; /donemedia lanjut
    IC_WAIT_CHOICE,      # 3 Menunggu teks pilihan; /selesai jika ending; /lanjut simpan pilihan
) = range(4)

(
    EP_WAIT_STORY,       # 10
    EP_WAIT_PART,        # 11
    EP_WAIT_FIELD,       # 12
    EP_WAIT_VALUE,       # 13
) = range(10, 14)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return db.is_admin(user_id)


def _admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_admin(update.effective_user.id):
            await update.effective_message.reply_text("❌ Kamu tidak memiliki akses admin.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


def _extract_media(msg: Message):
    """Kembalikan (file_id, media_type, text)."""
    if msg.photo:
        return msg.photo[-1].file_id, "photo", msg.caption or ""
    if msg.animation:
        return msg.animation.file_id, "animation", msg.caption or ""
    if msg.video:
        return msg.video.file_id, "video", msg.caption or ""
    if msg.voice:
        return msg.voice.file_id, "voice", msg.caption or ""
    if msg.audio:
        return msg.audio.file_id, "audio", msg.caption or ""
    if msg.text:
        return None, None, msg.text.strip()
    return None, None, ""


def _media_label(t: str) -> str:
    return {"photo": "📷 Foto", "animation": "🎞️ GIF", "video": "🎬 Video",
            "voice": "🎤 Voice Note", "audio": "🎵 Audio"}.get(t, "📎 Media")


def _part_num(part_id: int, story_id: int) -> str:
    parts = db.get_parts_by_story(story_id)
    for i, p in enumerate(parts, 1):
        if p['id'] == part_id:
            return str(i)
    return "?"


def _media_summary(pending: list) -> str:
    if not pending:
        return "_Belum ada media_"
    lines = [f"  • {_media_label(m['type'])}" for m in pending]
    return "\n".join(lines)


def _prompt_text(part_label: str = "part ini") -> str:
    return (
        f"📝 *Langkah 1 — Masukkan teks narasi* untuk {part_label}.\n\n"
        "Ketik teks cerita (boleh panjang), atau ketik `-` jika tidak ada teks.\n\n"
        "_/cancel untuk membatalkan._"
    )


def _prompt_media(pending: list) -> str:
    return (
        "🖼️ *Langkah 2 — Kirim media* (opsional).\n\n"
        f"Media saat ini:\n{_media_summary(pending)}\n\n"
        "Kirim foto, GIF, video, atau voice note.\n"
        "• /skipmedia — lewati (tidak ada media)\n"
        "• /donemedia — selesai tambah media, lanjut ke pilihan\n\n"
        "_/cancel untuk membatalkan._"
    )


def _prompt_choice(choices_so_far: list) -> str:
    lines = "\n".join(
        [f"  {i+1}. {c['text']}" for i, c in enumerate(choices_so_far)]
    ) if choices_so_far else "_Belum ada pilihan_"
    return (
        "🔀 *Langkah 3 — Buat pilihan* (tombol yang akan dilihat pembaca).\n\n"
        f"Pilihan sejauh ini:\n{lines}\n\n"
        "Ketik teks sebuah pilihan, lalu kirim.\n"
        "• /lanjut — simpan semua pilihan & selesaikan part ini\n"
        "• /selesai — part ini adalah *ENDING* (tanpa pilihan)\n\n"
        "_/cancel untuk membatalkan._"
    )


# ─── Admin Panel ──────────────────────────────────────────────────────────────

@_admin_only
async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admin - Panel utama."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Buat Cerita Baru",      callback_data="admin_new_story")],
        [InlineKeyboardButton("➕ Tambah Part (Cabang)",  callback_data="admin_inputpart")],
        [InlineKeyboardButton("✏️ Edit Part",             callback_data="admin_editpart")],
        [InlineKeyboardButton("📚 Daftar Cerita",         callback_data="admin_list")],
        [InlineKeyboardButton("👁️ Preview Cerita",        callback_data="admin_preview")],
        [InlineKeyboardButton("🗑️ Hapus Cerita",          callback_data="admin_delete")],
    ])
    await update.message.reply_text(
        "🛠️ *Panel Admin — Interactive Story Bot*\n\nPilih aksi:",
        parse_mode="Markdown", reply_markup=kb
    )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatcher callback non-conversation (list/preview/delete)."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return

    action = query.data
    if action == "admin_list":
        await _show_story_list(update, context, edit=True)
    elif action == "admin_preview":
        await _start_preview_flow(update, context)
    elif action == "admin_delete":
        await _start_delete_flow(update, context)


# ─── /addadmin ────────────────────────────────────────────────────────────────

@_admin_only
async def addadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addadmin <user_id> — Tambahkan admin baru."""
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "⚠️ *Cara penggunaan:* `/addadmin <user_id>`\n\n"
            "Contoh: `/addadmin 123456789`\n\n"
            "User ID bisa didapatkan dari bot seperti @userinfobot.",
            parse_mode="Markdown"
        )
        return

    new_id = int(args[0])
    adder_id = update.effective_user.id

    if db.is_admin(new_id):
        await update.message.reply_text(f"ℹ️ User `{new_id}` sudah menjadi admin.", parse_mode="Markdown")
        return

    db.add_admin(new_id, adder_id)
    await update.message.reply_text(
        f"✅ User `{new_id}` berhasil ditambahkan sebagai admin!\n\n"
        "Mereka bisa langsung menggunakan /admin.",
        parse_mode="Markdown"
    )


# ─── Helpers: Story/Delete/Preview Lists ─────────────────────────────────────

async def _show_story_list(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    stories = db.get_all_stories()
    if not stories:
        text = "📭 Belum ada cerita yang dibuat."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    lines = []
    for s in stories:
        parts = db.get_parts_by_story(s['id'])
        lines.append(f"• *{s['title']}* (ID: {s['id']}) — {len(parts)} part")

    text = "📚 *Daftar Cerita:*\n\n" + "\n".join(lines)
    if edit:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


async def _start_preview_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stories = db.get_all_stories()
    if not stories:
        await update.callback_query.edit_message_text("📭 Belum ada cerita.")
        return
    kb = [[InlineKeyboardButton(s['title'], callback_data=f"preview_{s['id']}")] for s in stories]
    await update.callback_query.edit_message_text(
        "👁️ *Preview Cerita*\nPilih cerita yang ingin dipreview:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def _start_delete_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stories = db.get_all_stories()
    if not stories:
        await update.callback_query.edit_message_text("📭 Belum ada cerita untuk dihapus.")
        return
    kb = [[InlineKeyboardButton(f"🗑️ {s['title']}", callback_data=f"confirmdelete_{s['id']}")] for s in stories]
    await update.callback_query.edit_message_text(
        "🗑️ *Hapus Cerita*\nPilih cerita yang ingin dihapus:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


@_admin_only
async def listcerita_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _show_story_list(update, context, edit=False)


@_admin_only
async def preview_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stories = db.get_all_stories()
    if not stories:
        await update.message.reply_text("📭 Belum ada cerita.")
        return
    kb = [[InlineKeyboardButton(s['title'], callback_data=f"preview_{s['id']}")] for s in stories]
    await update.message.reply_text(
        "👁️ *Preview Cerita*\nPilih cerita:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def preview_story_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    story_id = int(query.data.split("_")[1])
    story = db.get_story_by_id(story_id)
    if not story:
        await query.edit_message_text("❌ Cerita tidak ditemukan.")
        return

    parts = db.get_parts_by_story(story_id)
    lines = [f"📖 *{story['title']}*\n"]
    for i, part in enumerate(parts, 1):
        media_items = db.get_part_media(part['id'])
        media_str = ", ".join(_media_label(m['media_type']) for m in media_items) or "—"
        text_preview = (part['text'][:40] + "...") if len(part['text']) > 40 else part['text'] or "—"
        lines.append(f"*Part {i}* (ID:{part['id']})")
        lines.append(f"  Teks: _{text_preview}_")
        lines.append(f"  Media: {media_str}")
        choices = db.get_choices_by_part(part['id'])
        for c in choices:
            arrow = f"→ Part {_part_num(c['next_part_id'], story_id)}" if c['next_part_id'] else "→ _(belum diisi)_"
            lines.append(f"  🔀 \"{c['choice_text']}\" {arrow}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n...(terpotong)"
    await query.edit_message_text(text, parse_mode="Markdown")


async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return
    story_id = int(query.data.split("_")[1])
    story = db.get_story_by_id(story_id)
    if not story:
        await query.edit_message_text("❌ Cerita tidak ditemukan.")
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ya, Hapus", callback_data=f"dodelete_{story_id}"),
        InlineKeyboardButton("❌ Batal", callback_data="admin_list"),
    ]])
    await query.edit_message_text(
        f"🗑️ Yakin ingin menghapus cerita *\"{story['title']}\"*?\n\nSemua part dan pilihan akan ikut terhapus.",
        parse_mode="Markdown", reply_markup=kb
    )


async def do_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return
    story_id = int(query.data.split("_")[1])
    story = db.get_story_by_id(story_id)
    title = story['title'] if story else "?"
    db.delete_story(story_id)
    await query.edit_message_text(f"✅ Cerita *\"{title}\"* berhasil dihapus.", parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: INPUTCERITA — Buat cerita baru
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def inputcerita_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/inputcerita — Mulai buat cerita baru."""
    context.user_data.clear()
    context.user_data['mode'] = 'new_story'
    await update.message.reply_text(
        "📝 *Buat Cerita Baru*\n\n"
        "Langkah 1 dari 3: Masukkan *judul cerita*.\n\n"
        "_/cancel untuk membatalkan._",
        parse_mode="Markdown"
    )
    return IC_WAIT_TITLE


async def admin_new_story_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback tombol Buat Cerita Baru."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data['mode'] = 'new_story'
    await query.edit_message_text(
        "📝 *Buat Cerita Baru*\n\n"
        "Masukkan *judul cerita*:\n\n"
        "_/cancel untuk membatalkan._",
        parse_mode="Markdown"
    )
    return IC_WAIT_TITLE


async def ic_receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("❌ Judul tidak boleh kosong. Coba lagi:")
        return IC_WAIT_TITLE

    story_id = db.create_story(title)
    context.user_data.update({
        'story_id': story_id,
        'story_title': title,
        'current_part_id': None,
        'building_for_choice': None,
        'pending_choices': [],
        'pending_media': [],
    })

    await update.message.reply_text(
        f"✅ Judul *\"{title}\"* tersimpan!\n\n"
        + _prompt_text("Part 1"),
        parse_mode="Markdown"
    )
    return IC_WAIT_TEXT


# ─── State IC_WAIT_TEXT ───────────────────────────────────────────────────────

async def ic_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima teks narasi part, buat part di DB, lanjut ke input media."""
    raw = update.message.text.strip()
    text = "" if raw == "-" else raw

    story_id = context.user_data['story_id']
    part_id = db.create_part(story_id, text)
    context.user_data['current_part_id'] = part_id
    context.user_data['pending_media'] = []
    context.user_data['pending_choices'] = []

    building_for = context.user_data.get('building_for_choice')
    if building_for:
        db.update_choice_next_part(building_for, part_id)
        context.user_data['building_for_choice'] = None

    await update.message.reply_text(
        f"✅ Teks narasi tersimpan!\n\n" + _prompt_media([]),
        parse_mode="Markdown"
    )
    return IC_WAIT_MEDIA


# ─── State IC_WAIT_MEDIA ──────────────────────────────────────────────────────

async def ic_receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima satu item media, tambah ke pending_media."""
    msg = update.message
    file_id, media_type, _ = _extract_media(msg)

    if not file_id:
        await msg.reply_text(
            "❌ Kirim file media (foto, GIF, video, atau voice note).\n"
            "Gunakan /skipmedia jika tidak ada media, atau /donemedia jika sudah selesai.",
            parse_mode="Markdown"
        )
        return IC_WAIT_MEDIA

    pending = context.user_data.setdefault('pending_media', [])
    pending.append({'file_id': file_id, 'type': media_type})

    await msg.reply_text(
        f"✅ {_media_label(media_type)} ditambahkan!\n\n" + _prompt_media(pending),
        parse_mode="Markdown"
    )
    return IC_WAIT_MEDIA


async def ic_skipmedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/skipmedia — Lewati media, langsung ke input pilihan."""
    context.user_data['pending_media'] = []
    await _flush_media_and_go_choices(update, context)
    return IC_WAIT_CHOICE


async def ic_donemedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/donemedia — Selesai tambah media, lanjut ke input pilihan."""
    await _flush_media_and_go_choices(update, context)
    return IC_WAIT_CHOICE


async def _flush_media_and_go_choices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simpan semua pending_media ke DB, tampilkan prompt pilihan."""
    pending = context.user_data.get('pending_media', [])
    part_id = context.user_data['current_part_id']

    # Urutkan media sesuai MEDIA_ORDER sebelum simpan
    pending_sorted = sorted(pending, key=lambda m: MEDIA_ORDER.get(m['type'], 99))
    for i, m in enumerate(pending_sorted):
        db.add_part_media(part_id, m['file_id'], m['type'], i)

    await update.message.reply_text(
        _prompt_choice([]),
        parse_mode="Markdown"
    )


# ─── State IC_WAIT_CHOICE ─────────────────────────────────────────────────────

async def ic_receive_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima satu teks pilihan."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Teks pilihan tidak boleh kosong.")
        return IC_WAIT_CHOICE

    choices = context.user_data.setdefault('pending_choices', [])
    choices.append({'text': text})

    await update.message.reply_text(
        f"✅ Pilihan \"{text}\" ditambahkan!\n\n" + _prompt_choice(choices),
        parse_mode="Markdown"
    )
    return IC_WAIT_CHOICE


async def ic_lanjut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/lanjut — Simpan semua pilihan yang sudah dibuat, selesaikan part ini."""
    choices = context.user_data.get('pending_choices', [])
    part_id = context.user_data['current_part_id']
    story_id = context.user_data['story_id']

    if not choices:
        await update.message.reply_text(
            "⚠️ Belum ada pilihan. Tambahkan minimal 1 pilihan, atau gunakan /selesai jika ini ending."
        )
        return IC_WAIT_CHOICE

    # Simpan semua choices ke DB
    choice_ids = []
    for c in choices:
        cid = db.create_choice(part_id, c['text'])
        choice_ids.append(cid)

    # Ambil cabang yang belum selesai (next_part_id IS NULL)
    unfilled = db.get_unfilled_choices(story_id)
    if not unfilled:
        await update.message.reply_text(
            f"🎉 *Cerita selesai!*\n"
            f"Semua cabang sudah diisi. Cerita \"{context.user_data['story_title']}\" siap dibaca!\n\n"
            "Gunakan /preview untuk melihat struktur, atau /inputpart untuk menambah cabang.",
            parse_mode="Markdown"
        )
        context.user_data.clear()
        return ConversationHandler.END

    # Minta admin isi part untuk pilihan pertama yang masih kosong
    first_unfilled = unfilled[0]
    context.user_data['building_for_choice'] = first_unfilled['id']
    context.user_data['pending_choices'] = []
    context.user_data['pending_media'] = []

    part_num = _part_num(first_unfilled['part_id'], story_id)
    await update.message.reply_text(
        f"✅ {len(choices)} pilihan tersimpan!\n\n"
        f"Sekarang isi konten untuk cabang:\n"
        f"*Part {part_num} → \"{first_unfilled['choice_text']}\"*\n\n"
        + _prompt_text("part cabang ini"),
        parse_mode="Markdown"
    )
    return IC_WAIT_TEXT


async def ic_selesai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/selesai — Part ini adalah ending (tidak ada pilihan)."""
    story_id = context.user_data['story_id']
    title = context.user_data.get('story_title', '?')

    # Cek apakah masih ada cabang yang belum diisi
    unfilled = db.get_unfilled_choices(story_id)
    if unfilled:
        first = unfilled[0]
        context.user_data['building_for_choice'] = first['id']
        context.user_data['pending_choices'] = []
        context.user_data['pending_media'] = []
        part_num = _part_num(first['part_id'], story_id)
        await update.message.reply_text(
            f"✅ Part ini adalah ending.\n\n"
            f"Masih ada cabang yang belum selesai:\n"
            f"*Part {part_num} → \"{first['choice_text']}\"*\n\n"
            + _prompt_text("part cabang ini"),
            parse_mode="Markdown"
        )
        return IC_WAIT_TEXT

    await update.message.reply_text(
        f"🎉 *Cerita \"{title}\" selesai!*\n\n"
        "Semua cabang sudah diisi. Gunakan /preview untuk melihat struktur.",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: INPUTPART — Tambah part ke cabang yang belum selesai
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def inputpart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/inputpart — Mulai tambah part ke cabang yang kosong."""
    context.user_data.clear()
    return await _inputpart_show_stories(update, context, via_callback=False)


async def admin_inputpart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return ConversationHandler.END
    context.user_data.clear()
    return await _inputpart_show_stories(update, context, via_callback=True)


async def _inputpart_show_stories(update, context, via_callback=False):
    stories = db.get_all_stories()
    if not stories:
        text = "📭 Belum ada cerita. Buat dulu dengan /inputcerita."
        if via_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    kb = [[InlineKeyboardButton(s['title'], callback_data=f"ip_story_{s['id']}")] for s in stories]
    text = "➕ *Tambah Part ke Cabang Kosong*\n\nPilih cerita:"
    if via_callback:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return IC_WAIT_TITLE


async def inputpart_story_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    story_id = int(query.data.split("_")[2])
    story = db.get_story_by_id(story_id)
    if not story:
        await query.edit_message_text("❌ Cerita tidak ditemukan.")
        return ConversationHandler.END

    unfilled = db.get_unfilled_choices(story_id)
    if not unfilled:
        await query.edit_message_text(
            f"✅ Cerita *\"{story['title']}\"* sudah lengkap.\n"
            "Semua cabang sudah terisi.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    context.user_data.update({
        'story_id': story_id,
        'story_title': story['title'],
        'current_part_id': None,
        'building_for_choice': None,
        'pending_choices': [],
        'pending_media': [],
    })

    kb = []
    for c in unfilled:
        part_num = _part_num(c['part_id'], story_id)
        label = f"Part {part_num} → \"{c['choice_text']}\""
        kb.append([InlineKeyboardButton(label, callback_data=f"ip_choice_{c['id']}")])

    await query.edit_message_text(
        f"📖 *{story['title']}*\n\n"
        "Pilih cabang mana yang ingin diisi:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return IC_WAIT_PART_CONTENT if False else IC_WAIT_TITLE


async def inputpart_choice_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice_id = int(query.data.split("_")[2])

    from database import get_choice_by_id
    choice = get_choice_by_id(choice_id)
    if not choice:
        await query.edit_message_text("❌ Pilihan tidak ditemukan.")
        return ConversationHandler.END

    context.user_data['building_for_choice'] = choice_id
    context.user_data['pending_media'] = []
    context.user_data['pending_choices'] = []

    story_id = context.user_data['story_id']
    part_num = _part_num(choice['part_id'], story_id)

    await query.edit_message_text(
        f"✍️ Mengisi cabang: *Part {part_num} → \"{choice['choice_text']}\"*\n\n"
        + _prompt_text("part cabang ini"),
        parse_mode="Markdown"
    )
    return IC_WAIT_TEXT


# ─── State yang dipakai bersama inputcerita & inputpart ───────────────────────
# (ic_receive_text, ic_receive_media, ic_skipmedia, ic_donemedia,
#  ic_receive_choice, ic_lanjut, ic_selesai sudah didefinisikan di atas)

# Alias untuk ConversationHandler states yang shared
IC_WAIT_PART_CONTENT = IC_WAIT_TEXT  # backward compat label


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: EDITPART
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def editpart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/editpart — Mulai edit part yang sudah ada."""
    context.user_data.clear()
    return await _editpart_show_stories(update, context, via_callback=False)


async def admin_editpart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return ConversationHandler.END
    context.user_data.clear()
    return await _editpart_show_stories(update, context, via_callback=True)


async def _editpart_show_stories(update, context, via_callback=False):
    stories = db.get_all_stories()
    if not stories:
        text = "📭 Belum ada cerita."
        if via_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    kb = [[InlineKeyboardButton(s['title'], callback_data=f"ep_story_{s['id']}")] for s in stories]
    text = "✏️ *Edit Part*\n\nPilih cerita:"
    if via_callback:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return EP_WAIT_STORY


async def ep_story_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    story_id = int(query.data.split("_")[2])
    story = db.get_story_by_id(story_id)
    parts = db.get_parts_by_story(story_id)

    if not parts:
        await query.edit_message_text("❌ Cerita ini belum punya part.")
        return ConversationHandler.END

    context.user_data['story_id'] = story_id
    kb = []
    for i, p in enumerate(parts, 1):
        preview = (p['text'][:30] + "...") if len(p['text']) > 30 else p['text'] or "(tanpa teks)"
        kb.append([InlineKeyboardButton(f"Part {i}: {preview}", callback_data=f"ep_part_{p['id']}")])

    await query.edit_message_text(
        f"✏️ *Edit Part — {story['title']}*\n\nPilih part yang ingin diedit:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return EP_WAIT_PART


async def ep_part_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    part_id = int(query.data.split("_")[2])
    part = db.get_part_by_id(part_id)
    if not part:
        await query.edit_message_text("❌ Part tidak ditemukan.")
        return ConversationHandler.END

    context.user_data['edit_part_id'] = part_id
    media_items = db.get_part_media(part_id)
    media_str = ", ".join(_media_label(m['media_type']) for m in media_items) or "—"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Edit Teks", callback_data="ep_field_text")],
        [InlineKeyboardButton("🖼️ Ganti Media", callback_data="ep_field_media")],
        [InlineKeyboardButton("📝+🖼️ Edit Keduanya", callback_data="ep_field_both")],
        [InlineKeyboardButton("🗑️ Hapus Media", callback_data="ep_field_clearmedia")],
    ])

    text_preview = (part['text'][:60] + "...") if len(part['text']) > 60 else part['text'] or "—"
    await query.edit_message_text(
        f"✏️ *Part yang dipilih:*\n"
        f"Teks: _{text_preview}_\n"
        f"Media: {media_str}\n\n"
        "Pilih apa yang ingin diedit:",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return EP_WAIT_FIELD


async def ep_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("ep_field_", "")
    context.user_data['edit_field'] = field

    if field == "clearmedia":
        part_id = context.user_data['edit_part_id']
        db.clear_part_media(part_id)
        await query.edit_message_text("✅ Semua media part ini telah dihapus.")
        return ConversationHandler.END

    if field == "text":
        await query.edit_message_text(
            "📝 Kirim *teks baru* untuk part ini:\n_(ketik `-` untuk menghapus teks)_",
            parse_mode="Markdown"
        )
        return EP_WAIT_VALUE

    if field == "media":
        context.user_data['ep_pending_media'] = []
        part_id = context.user_data['edit_part_id']
        db.clear_part_media(part_id)
        await query.edit_message_text(
            "🖼️ Kirim media baru (foto, GIF, video, voice note).\n"
            "Bisa kirim lebih dari satu.\n"
            "• /donemedia — selesai\n\n"
            "_/cancel untuk membatalkan._",
            parse_mode="Markdown"
        )
        return EP_WAIT_VALUE

    if field == "both":
        await query.edit_message_text(
            "📝 Kirim *teks baru* dulu:\n_(ketik `-` untuk menghapus teks)_",
            parse_mode="Markdown"
        )
        return EP_WAIT_VALUE


async def ep_receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle input nilai baru untuk edit (teks, media, atau both-step)."""
    field = context.user_data.get('edit_field')
    part_id = context.user_data.get('edit_part_id')
    msg = update.message

    if field in ("text", "both"):
        if msg.text:
            new_text = "" if msg.text.strip() == "-" else msg.text.strip()
            db.update_part_text(part_id, new_text)
            if field == "both":
                context.user_data['ep_pending_media'] = []
                db.clear_part_media(part_id)
                context.user_data['edit_field'] = 'media'
                await msg.reply_text(
                    "✅ Teks tersimpan!\n\n"
                    "🖼️ Sekarang kirim media baru.\n"
                    "• /donemedia — selesai (tanpa ganti media)\n\n"
                    "_/cancel untuk membatalkan._",
                    parse_mode="Markdown"
                )
                return EP_WAIT_VALUE
            await msg.reply_text("✅ Teks part berhasil diperbarui!")
            return ConversationHandler.END
        else:
            await msg.reply_text("❌ Kirim teks. Gunakan `-` untuk menghapus teks.")
            return EP_WAIT_VALUE

    if field == "media":
        file_id, media_type, _ = _extract_media(msg)
        if not file_id:
            await msg.reply_text(
                "❌ Kirim file media. Atau /donemedia jika sudah selesai.",
                parse_mode="Markdown"
            )
            return EP_WAIT_VALUE

        pending = context.user_data.setdefault('ep_pending_media', [])
        pending.append({'file_id': file_id, 'type': media_type})
        await msg.reply_text(
            f"✅ {_media_label(media_type)} ditambahkan! Total: {len(pending)} media.\n"
            "Kirim lagi atau /donemedia untuk selesai."
        )
        return EP_WAIT_VALUE

    await msg.reply_text("❌ Terjadi kesalahan. Coba /cancel dan mulai ulang.")
    return ConversationHandler.END


async def ep_donemedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/donemedia saat edit media."""
    pending = context.user_data.get('ep_pending_media', [])
    part_id = context.user_data.get('edit_part_id')

    if part_id and pending:
        sorted_media = sorted(pending, key=lambda m: MEDIA_ORDER.get(m['type'], 99))
        for i, m in enumerate(sorted_media):
            db.add_part_media(part_id, m['file_id'], m['type'], i)
        await update.message.reply_text(f"✅ {len(pending)} media berhasil disimpan!")
    else:
        await update.message.reply_text("✅ Selesai (tidak ada media yang diubah).")

    return ConversationHandler.END


# ─── Cancel ───────────────────────────────────────────────────────────────────

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Sesi dibatalkan.\n\nGunakan /admin untuk kembali ke panel utama."
    )
    return ConversationHandler.END
