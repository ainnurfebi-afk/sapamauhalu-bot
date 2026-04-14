"""
admin.py - Handler admin Interactive Story Bot

Commands:
  /admin        - Panel utama admin
  /inputcerita  - Buat cerita baru
  /inputpart    - Tambah part ke cabang kosong
  /editpart     - Edit teks/media part yang ada
  /edittitle    - Edit judul cerita
  /export       - Export cerita ke file JSON
  /listcerita   - Daftar semua cerita
  /preview      - Lihat struktur pohon cerita
  /addadmin     - Tambahkan admin baru
  /cancel       - Batalkan sesi saat ini

Format teks  : admin bisa pakai bold/italic/underline via toolbar Telegram
Urutan input : teks dulu → media (foto/gif/video/voice)
Urutan tampil: foto → gif → video → voice → teks
"""

import io
import json
import html as html_module
import logging

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, InputFile
)
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import MEDIA_ORDER

logger = logging.getLogger(__name__)

# ─── Conversation States ──────────────────────────────────────────────────────

# inputcerita / inputpart
(
    IC_WAIT_TITLE,   # 0  judul cerita baru
    IC_WAIT_TEXT,    # 1  teks narasi part
    IC_WAIT_MEDIA,   # 2  media (bisa banyak)
    IC_WAIT_CHOICE,  # 3  teks pilihan
) = range(4)

# editpart
(
    EP_WAIT_STORY,   # 10
    EP_WAIT_PART,    # 11
    EP_WAIT_FIELD,   # 12
    EP_WAIT_VALUE,   # 13
) = range(10, 14)

# edittitle
(
    ET_WAIT_STORY,   # 20
    ET_WAIT_TITLE,   # 21
) = range(20, 22)

# alias (dipakai di main.py juga)
IC_WAIT_PART_CONTENT = IC_WAIT_TEXT


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


def _h(text: str) -> str:
    """Escape karakter HTML agar aman ditampilkan dalam pesan HTML."""
    return html_module.escape(str(text))


def _get_text_html(msg: Message) -> str:
    """
    Ambil teks dari pesan dengan mempertahankan formatting (bold/italic/underline).
    Gunakan message.text_html agar formatting yang diketik user di Telegram
    (via toolbar format) tersimpan dalam bentuk HTML.
    """
    return msg.text_html or msg.text or ""


def _extract_media(msg: Message):
    """Kembalikan (file_id, media_type)."""
    if msg.photo:
        return msg.photo[-1].file_id, "photo"
    if msg.animation:
        return msg.animation.file_id, "animation"
    if msg.video:
        return msg.video.file_id, "video"
    if msg.voice:
        return msg.voice.file_id, "voice"
    if msg.audio:
        return msg.audio.file_id, "audio"
    return None, None


def _media_label(t: str) -> str:
    return {
        "photo": "📷 Foto", "animation": "🎞️ GIF",
        "video": "🎬 Video", "voice": "🎤 Voice Note", "audio": "🎵 Audio"
    }.get(t, "📎 Media")


def _part_num(part_id: int, story_id: int) -> str:
    parts = db.get_parts_by_story(story_id)
    for i, p in enumerate(parts, 1):
        if p['id'] == part_id:
            return str(i)
    return "?"


def _media_summary(pending: list) -> str:
    if not pending:
        return "<i>Belum ada media</i>"
    return "\n".join(f"  • {_media_label(m['type'])}" for m in pending)


def _prompt_text(part_label: str = "part ini") -> str:
    return (
        f"📝 <b>Langkah 1 — Teks narasi</b> untuk {_h(part_label)}.\n\n"
        "Ketik teks cerita menggunakan toolbar format Telegram untuk "
        "<b>bold</b>, <i>italic</i>, <u>underline</u>.\n"
        "Ketik <code>-</code> jika tidak ada teks.\n\n"
        "<i>/cancel untuk membatalkan.</i>"
    )


def _prompt_media(pending: list) -> str:
    return (
        "🖼️ <b>Langkah 2 — Kirim media</b> (opsional).\n\n"
        f"Media saat ini:\n{_media_summary(pending)}\n\n"
        "Kirim foto, GIF, video, atau voice note. Bisa lebih dari satu.\n"
        "• /skipmedia — tidak ada media\n"
        "• /donemedia — selesai, lanjut ke pilihan\n\n"
        "<i>/cancel untuk membatalkan.</i>"
    )


def _prompt_choice(choices_so_far: list) -> str:
    if choices_so_far:
        lines = "\n".join(f"  {i+1}. {_h(c['text'])}" for i, c in enumerate(choices_so_far))
    else:
        lines = "<i>Belum ada pilihan</i>"
    return (
        "🔀 <b>Langkah 3 — Buat pilihan</b> (tombol untuk pembaca).\n\n"
        f"Pilihan sejauh ini:\n{lines}\n\n"
        "Ketik teks satu pilihan, lalu kirim.\n"
        "• /lanjut — simpan pilihan &amp; selesaikan part ini\n"
        "• /selesai — part ini adalah <b>ENDING</b> (tanpa pilihan)\n\n"
        "<i>/cancel untuk membatalkan.</i>"
    )


# ─── Admin Panel ──────────────────────────────────────────────────────────────

@_admin_only
async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admin - Panel utama."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Buat Cerita Baru",      callback_data="admin_new_story")],
        [InlineKeyboardButton("➕ Tambah Part (Cabang)",  callback_data="admin_inputpart")],
        [InlineKeyboardButton("✏️ Edit Part",             callback_data="admin_editpart")],
        [InlineKeyboardButton("🏷️ Edit Judul",            callback_data="admin_edittitle")],
        [InlineKeyboardButton("📚 Daftar Cerita",         callback_data="admin_list")],
        [InlineKeyboardButton("👁️ Preview Cerita",        callback_data="admin_preview")],
        [InlineKeyboardButton("📤 Export Cerita",         callback_data="admin_export")],
        [InlineKeyboardButton("🗑️ Hapus Cerita",          callback_data="admin_delete")],
    ])
    await update.message.reply_text(
        "🛠️ <b>Panel Admin — Interactive Story Bot</b>\n\nPilih aksi:",
        parse_mode="HTML", reply_markup=kb
    )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatcher callback non-conversation."""
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
    elif action == "admin_export":
        await _start_export_flow(update, context)


# ─── /addadmin ────────────────────────────────────────────────────────────────

@_admin_only
async def addadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addadmin <user_id> — Tambahkan admin baru."""
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "⚠️ <b>Cara penggunaan:</b> <code>/addadmin &lt;user_id&gt;</code>\n\n"
            "Contoh: <code>/addadmin 123456789</code>\n\n"
            "User ID bisa dicek via @userinfobot.",
            parse_mode="HTML"
        )
        return

    new_id = int(args[0])
    if db.is_admin(new_id):
        await update.message.reply_text(
            f"ℹ️ User <code>{new_id}</code> sudah menjadi admin.", parse_mode="HTML"
        )
        return

    db.add_admin(new_id, update.effective_user.id)
    await update.message.reply_text(
        f"✅ User <code>{new_id}</code> berhasil ditambahkan sebagai admin!\n\n"
        "Mereka bisa langsung menggunakan /admin.",
        parse_mode="HTML"
    )


# ─── Story List / Preview / Delete / Export Helpers ──────────────────────────

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
        lines.append(f"• <b>{_h(s['title'])}</b> (ID: {s['id']}) — {len(parts)} part")

    text = "📚 <b>Daftar Cerita:</b>\n\n" + "\n".join(lines)
    if edit:
        await update.callback_query.edit_message_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def _start_preview_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stories = db.get_all_stories()
    if not stories:
        await update.callback_query.edit_message_text("📭 Belum ada cerita.")
        return
    kb = [[InlineKeyboardButton(s['title'], callback_data=f"preview_{s['id']}")] for s in stories]
    await update.callback_query.edit_message_text(
        "👁️ <b>Preview Cerita</b>\nPilih cerita:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )


async def _start_delete_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stories = db.get_all_stories()
    if not stories:
        await update.callback_query.edit_message_text("📭 Belum ada cerita untuk dihapus.")
        return
    kb = [[InlineKeyboardButton(f"🗑️ {s['title']}", callback_data=f"confirmdelete_{s['id']}")] for s in stories]
    await update.callback_query.edit_message_text(
        "🗑️ <b>Hapus Cerita</b>\nPilih cerita yang ingin dihapus:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )


async def _start_export_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stories = db.get_all_stories()
    if not stories:
        await update.callback_query.edit_message_text("📭 Belum ada cerita untuk di-export.")
        return
    kb = [[InlineKeyboardButton(s['title'], callback_data=f"exportstory_{s['id']}")] for s in stories]
    await update.callback_query.edit_message_text(
        "📤 <b>Export Cerita ke JSON</b>\nPilih cerita:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
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
        "👁️ <b>Preview Cerita</b>\nPilih cerita:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
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
    lines = [f"📖 <b>{_h(story['title'])}</b>\n"]
    for i, part in enumerate(parts, 1):
        media_items = db.get_part_media(part['id'])
        media_str = ", ".join(_media_label(m['media_type']) for m in media_items) or "—"
        raw = part['text'] or ""
        # Strip HTML tags for preview display
        import re
        plain = re.sub(r'<[^>]+>', '', raw)
        text_preview = (plain[:40] + "...") if len(plain) > 40 else plain or "—"
        lines.append(f"<b>Part {i}</b> (ID:{part['id']})")
        lines.append(f"  Teks: <i>{_h(text_preview)}</i>")
        lines.append(f"  Media: {media_str}")
        choices = db.get_choices_by_part(part['id'])
        for c in choices:
            arrow = f"→ Part {_part_num(c['next_part_id'], story_id)}" if c['next_part_id'] else "→ <i>(belum diisi)</i>"
            lines.append(f"  🔀 \"{_h(c['choice_text'])}\" {arrow}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n...(terpotong)"
    await query.edit_message_text(text, parse_mode="HTML")


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
        f"🗑️ Yakin ingin menghapus cerita <b>\"{_h(story['title'])}\"</b>?\n\n"
        "Semua part dan pilihan akan ikut terhapus.",
        parse_mode="HTML", reply_markup=kb
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
    await query.edit_message_text(
        f"✅ Cerita <b>\"{_h(title)}\"</b> berhasil dihapus.", parse_mode="HTML"
    )


# ─── Export Cerita ────────────────────────────────────────────────────────────

@_admin_only
async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/export — Tampilkan daftar cerita untuk di-export."""
    stories = db.get_all_stories()
    if not stories:
        await update.message.reply_text("📭 Belum ada cerita.")
        return
    kb = [[InlineKeyboardButton(s['title'], callback_data=f"exportstory_{s['id']}")] for s in stories]
    await update.message.reply_text(
        "📤 <b>Export Cerita ke JSON</b>\nPilih cerita:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )


async def exportstory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate dan kirim file JSON struktur cerita."""
    query = update.callback_query
    await query.answer("Menyiapkan file...")
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return

    story_id = int(query.data.split("_")[1])
    story = db.get_story_by_id(story_id)
    if not story:
        await query.edit_message_text("❌ Cerita tidak ditemukan.")
        return

    parts = db.get_parts_by_story(story_id)
    data = {
        "title": story['title'],
        "created_at": str(story.get('created_at', '')),
        "parts": []
    }

    for part in parts:
        media_items = db.get_part_media(part['id'])
        choices = db.get_choices_by_part(part['id'])
        data["parts"].append({
            "id": part['id'],
            "text_html": part['text'],
            "media": [
                {"media_type": m['media_type'], "file_id": m['file_id']}
                for m in media_items
            ],
            "choices": [
                {"text": c['choice_text'], "next_part_id": c['next_part_id']}
                for c in choices
            ]
        })

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    buf = io.BytesIO(json_bytes)
    safe_title = "".join(c for c in story['title'] if c.isalnum() or c in " _-")[:40].strip()
    filename = f"{safe_title or 'cerita'}.json"

    await query.edit_message_text(
        f"📤 Mengirim file export <b>{_h(story['title'])}</b>...", parse_mode="HTML"
    )
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=buf,
        filename=filename,
        caption=(
            f"📤 <b>Export: {_h(story['title'])}</b>\n\n"
            f"• {len(parts)} part\n"
            "• Format: JSON\n"
            "• Field <code>text_html</code>: teks dengan tag HTML (bold/italic/dll)\n\n"
            "<i>File ini bisa dibuka/diedit dengan text editor atau database tool.</i>"
        ),
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: INPUTCERITA — Buat cerita baru
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def inputcerita_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📝 <b>Buat Cerita Baru</b>\n\n"
        "Masukkan <b>judul cerita</b>:\n\n"
        "<i>/cancel untuk membatalkan.</i>",
        parse_mode="HTML"
    )
    return IC_WAIT_TITLE


async def admin_new_story_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return ConversationHandler.END
    context.user_data.clear()
    await query.edit_message_text(
        "📝 <b>Buat Cerita Baru</b>\n\nMasukkan <b>judul cerita</b>:\n\n<i>/cancel untuk membatalkan.</i>",
        parse_mode="HTML"
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
        f"✅ Judul <b>\"{_h(title)}\"</b> tersimpan!\n\n" + _prompt_text("Part 1"),
        parse_mode="HTML"
    )
    return IC_WAIT_TEXT


# ─── IC_WAIT_TEXT ─────────────────────────────────────────────────────────────

async def ic_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima teks narasi — simpan dengan format HTML agar bold/italic/underline terjaga."""
    plain = update.message.text or ""
    text = "" if plain.strip() == "-" else _get_text_html(update.message)

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
        "✅ Teks narasi tersimpan!\n\n" + _prompt_media([]),
        parse_mode="HTML"
    )
    return IC_WAIT_MEDIA


# ─── IC_WAIT_MEDIA ────────────────────────────────────────────────────────────

async def ic_receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_id, media_type = _extract_media(msg)
    if not file_id:
        await msg.reply_text(
            "❌ Kirim file media (foto, GIF, video, atau voice note).\n"
            "Gunakan /skipmedia jika tidak ada, atau /donemedia jika sudah selesai.",
            parse_mode="HTML"
        )
        return IC_WAIT_MEDIA

    pending = context.user_data.setdefault('pending_media', [])
    pending.append({'file_id': file_id, 'type': media_type})
    await msg.reply_text(
        f"✅ {_media_label(media_type)} ditambahkan!\n\n" + _prompt_media(pending),
        parse_mode="HTML"
    )
    return IC_WAIT_MEDIA


async def ic_skipmedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['pending_media'] = []
    await _flush_media_and_go_choices(update, context)
    return IC_WAIT_CHOICE


async def ic_donemedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _flush_media_and_go_choices(update, context)
    return IC_WAIT_CHOICE


async def _flush_media_and_go_choices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = context.user_data.get('pending_media', [])
    part_id = context.user_data['current_part_id']
    for i, m in enumerate(sorted(pending, key=lambda x: MEDIA_ORDER.get(x['type'], 99))):
        db.add_part_media(part_id, m['file_id'], m['type'], i)
    await update.message.reply_text(_prompt_choice([]), parse_mode="HTML")


# ─── IC_WAIT_CHOICE ───────────────────────────────────────────────────────────

async def ic_receive_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Teks pilihan tidak boleh kosong.")
        return IC_WAIT_CHOICE
    choices = context.user_data.setdefault('pending_choices', [])
    choices.append({'text': text})
    await update.message.reply_text(
        f"✅ Pilihan \"{_h(text)}\" ditambahkan!\n\n" + _prompt_choice(choices),
        parse_mode="HTML"
    )
    return IC_WAIT_CHOICE


async def ic_lanjut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choices = context.user_data.get('pending_choices', [])
    part_id = context.user_data['current_part_id']
    story_id = context.user_data['story_id']

    if not choices:
        await update.message.reply_text(
            "⚠️ Belum ada pilihan. Tambahkan minimal 1, atau /selesai jika ini ending."
        )
        return IC_WAIT_CHOICE

    for c in choices:
        db.create_choice(part_id, c['text'])

    unfilled = db.get_unfilled_choices(story_id)
    if not unfilled:
        await update.message.reply_text(
            f"🎉 <b>Cerita selesai!</b>\n"
            f"Semua cabang sudah diisi. Cerita <b>\"{_h(context.user_data['story_title'])}\"</b> siap dibaca!\n\n"
            "Gunakan /preview untuk melihat struktur.",
            parse_mode="HTML"
        )
        context.user_data.clear()
        return ConversationHandler.END

    first = unfilled[0]
    context.user_data['building_for_choice'] = first['id']
    context.user_data['pending_choices'] = []
    context.user_data['pending_media'] = []
    part_num = _part_num(first['part_id'], story_id)

    await update.message.reply_text(
        f"✅ {len(choices)} pilihan tersimpan!\n\n"
        f"Sekarang isi konten untuk cabang:\n"
        f"<b>Part {part_num} → \"{_h(first['choice_text'])}\"</b>\n\n"
        + _prompt_text("part cabang ini"),
        parse_mode="HTML"
    )
    return IC_WAIT_TEXT


async def ic_selesai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    story_id = context.user_data['story_id']
    title = context.user_data.get('story_title', '?')

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
            f"<b>Part {part_num} → \"{_h(first['choice_text'])}\"</b>\n\n"
            + _prompt_text("part cabang ini"),
            parse_mode="HTML"
        )
        return IC_WAIT_TEXT

    await update.message.reply_text(
        f"🎉 <b>Cerita \"{_h(title)}\" selesai!</b>\n\n"
        "Semua cabang sudah diisi. Gunakan /preview untuk melihat struktur.",
        parse_mode="HTML"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: INPUTPART — Tambah part ke cabang kosong
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def inputpart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    text = "➕ <b>Tambah Part ke Cabang Kosong</b>\n\nPilih cerita:"
    if via_callback:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
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
            f"✅ Cerita <b>\"{_h(story['title'])}\"</b> sudah lengkap.\nSemua cabang sudah terisi.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    context.user_data.update({
        'story_id': story_id, 'story_title': story['title'],
        'current_part_id': None, 'building_for_choice': None,
        'pending_choices': [], 'pending_media': [],
    })

    kb = []
    for c in unfilled:
        part_num = _part_num(c['part_id'], story_id)
        kb.append([InlineKeyboardButton(
            f"Part {part_num} → \"{c['choice_text']}\"",
            callback_data=f"ip_choice_{c['id']}"
        )])

    await query.edit_message_text(
        f"📖 <b>{_h(story['title'])}</b>\n\nPilih cabang mana yang ingin diisi:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )
    return IC_WAIT_TITLE


async def inputpart_choice_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice_id = int(query.data.split("_")[2])
    choice = db.get_choice_by_id(choice_id)
    if not choice:
        await query.edit_message_text("❌ Pilihan tidak ditemukan.")
        return ConversationHandler.END

    context.user_data['building_for_choice'] = choice_id
    context.user_data['pending_media'] = []
    context.user_data['pending_choices'] = []

    story_id = context.user_data['story_id']
    part_num = _part_num(choice['part_id'], story_id)
    await query.edit_message_text(
        f"✍️ Mengisi cabang: <b>Part {part_num} → \"{_h(choice['choice_text'])}\"</b>\n\n"
        + _prompt_text("part cabang ini"),
        parse_mode="HTML"
    )
    return IC_WAIT_TEXT


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: EDITPART — Edit part yang sudah ada
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def editpart_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    text = "✏️ <b>Edit Part</b>\n\nPilih cerita:"
    if via_callback:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
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
        import re
        plain = re.sub(r'<[^>]+>', '', p['text'] or '')
        preview = (plain[:30] + "...") if len(plain) > 30 else plain or "(tanpa teks)"
        kb.append([InlineKeyboardButton(f"Part {i}: {preview}", callback_data=f"ep_part_{p['id']}")])

    await query.edit_message_text(
        f"✏️ <b>Edit Part — {_h(story['title'])}</b>\n\nPilih part yang ingin diedit:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
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
    story_id = context.user_data.get('story_id')
    part_num = _part_num(part_id, story_id) if story_id else "?"
    media_items = db.get_part_media(part_id)
    media_str = ", ".join(_media_label(m['media_type']) for m in media_items) or "—"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Edit Teks",          callback_data="ep_field_text")],
        [InlineKeyboardButton("🖼️ Ganti Media",         callback_data="ep_field_media")],
        [InlineKeyboardButton("📝+🖼️ Edit Keduanya",   callback_data="ep_field_both")],
        [InlineKeyboardButton("🗑️ Hapus Semua Media",  callback_data="ep_field_clearmedia")],
    ])

    # Edit pesan dengan pilihan field
    await query.edit_message_text(
        f"✏️ <b>Part {part_num}</b>\nMedia: {media_str}\n\nPilih apa yang ingin diedit:",
        parse_mode="HTML", reply_markup=kb
    )

    # Kirim teks saat ini sebagai pesan terpisah — mudah di-copy paste
    current_text = part['text'] or ""
    if current_text:
        import re
        plain_preview = re.sub(r'<[^>]+>', '', current_text)
        await query.message.reply_text(
            f"📋 <b>Isi teks Part {part_num} saat ini</b> (tampilan pembaca):\n\n"
            f"{current_text}\n\n"
            f"<code>── Teks mentah untuk copy-paste ──</code>\n"
            f"<pre>{_h(current_text)}</pre>",
            parse_mode="HTML"
        )
    else:
        await query.message.reply_text(
            f"📋 <b>Part {part_num}</b> belum memiliki teks narasi.",
            parse_mode="HTML"
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
            "📝 Kirim <b>teks baru</b> untuk part ini.\n\n"
            "Gunakan toolbar format Telegram untuk <b>bold</b>, <i>italic</i>, <u>underline</u>.\n"
            "Ketik <code>-</code> untuk menghapus teks.\n\n"
            "<i>/cancel untuk membatalkan.</i>",
            parse_mode="HTML"
        )
        return EP_WAIT_VALUE

    if field == "media":
        context.user_data['ep_pending_media'] = []
        db.clear_part_media(context.user_data['edit_part_id'])
        await query.edit_message_text(
            "🖼️ Kirim <b>media baru</b> (foto, GIF, video, voice note). Bisa lebih dari satu.\n"
            "• /donemedia — selesai\n\n"
            "<i>/cancel untuk membatalkan.</i>",
            parse_mode="HTML"
        )
        return EP_WAIT_VALUE

    if field == "both":
        await query.edit_message_text(
            "📝 Kirim <b>teks baru</b> dulu:\n\n"
            "Gunakan toolbar format Telegram untuk <b>bold</b>, <i>italic</i>, <u>underline</u>.\n"
            "Ketik <code>-</code> untuk menghapus teks.\n\n"
            "<i>/cancel untuk membatalkan.</i>",
            parse_mode="HTML"
        )
        return EP_WAIT_VALUE


async def ep_receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get('edit_field')
    part_id = context.user_data.get('edit_part_id')
    msg = update.message

    if field in ("text", "both"):
        if msg.text:
            plain = msg.text.strip()
            new_text = "" if plain == "-" else _get_text_html(msg)
            db.update_part_text(part_id, new_text)
            if field == "both":
                context.user_data['ep_pending_media'] = []
                db.clear_part_media(part_id)
                context.user_data['edit_field'] = 'media'
                await msg.reply_text(
                    "✅ Teks tersimpan!\n\n"
                    "🖼️ Sekarang kirim media baru (foto, GIF, video, voice note).\n"
                    "• /donemedia — selesai (lewati media)\n\n"
                    "<i>/cancel untuk membatalkan.</i>",
                    parse_mode="HTML"
                )
                return EP_WAIT_VALUE
            await msg.reply_text("✅ Teks part berhasil diperbarui!")
            return ConversationHandler.END
        else:
            await msg.reply_text("❌ Kirim teks. Gunakan <code>-</code> untuk menghapus teks.", parse_mode="HTML")
            return EP_WAIT_VALUE

    if field == "media":
        file_id, media_type = _extract_media(msg)
        if not file_id:
            await msg.reply_text(
                "❌ Kirim file media. Atau /donemedia jika sudah selesai.", parse_mode="HTML"
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
    pending = context.user_data.get('ep_pending_media', [])
    part_id = context.user_data.get('edit_part_id')
    if part_id and pending:
        for i, m in enumerate(sorted(pending, key=lambda x: MEDIA_ORDER.get(x['type'], 99))):
            db.add_part_media(part_id, m['file_id'], m['type'], i)
        await update.message.reply_text(f"✅ {len(pending)} media berhasil disimpan!")
    else:
        await update.message.reply_text("✅ Selesai (tidak ada media yang diubah).")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION: EDITTITLE — Edit judul cerita
# ═══════════════════════════════════════════════════════════════════════════════

@_admin_only
async def edittitle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/edittitle — Mulai edit judul cerita."""
    context.user_data.clear()
    return await _edittitle_show_stories(update, context, via_callback=False)


async def admin_edittitle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback tombol Edit Judul dari panel."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return ConversationHandler.END
    context.user_data.clear()
    return await _edittitle_show_stories(update, context, via_callback=True)


async def _edittitle_show_stories(update, context, via_callback=False):
    stories = db.get_all_stories()
    if not stories:
        text = "📭 Belum ada cerita."
        if via_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    kb = [[InlineKeyboardButton(s['title'], callback_data=f"et_story_{s['id']}")] for s in stories]
    text = "🏷️ <b>Edit Judul Cerita</b>\n\nPilih cerita yang judulnya ingin diubah:"
    if via_callback:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    return ET_WAIT_STORY


async def et_story_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    story_id = int(query.data.split("_")[2])
    story = db.get_story_by_id(story_id)
    if not story:
        await query.edit_message_text("❌ Cerita tidak ditemukan.")
        return ConversationHandler.END

    context.user_data['edit_story_id'] = story_id
    context.user_data['old_title'] = story['title']

    await query.edit_message_text(
        f"🏷️ Judul saat ini: <b>\"{_h(story['title'])}\"</b>\n\n"
        "Ketik <b>judul baru</b>:\n\n"
        "<i>/cancel untuk membatalkan.</i>",
        parse_mode="HTML"
    )
    return ET_WAIT_TITLE


async def et_receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_title = update.message.text.strip()
    if not new_title:
        await update.message.reply_text("❌ Judul tidak boleh kosong. Coba lagi:")
        return ET_WAIT_TITLE

    story_id = context.user_data['edit_story_id']
    old_title = context.user_data.get('old_title', '?')
    db.update_story_title(story_id, new_title)

    await update.message.reply_text(
        f"✅ Judul berhasil diubah!\n\n"
        f"<s>{_h(old_title)}</s>\n"
        f"→ <b>{_h(new_title)}</b>",
        parse_mode="HTML"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ─── Cancel ───────────────────────────────────────────────────────────────────

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Sesi dibatalkan.\n\nGunakan /admin untuk kembali ke panel utama."
    )
    return ConversationHandler.END
