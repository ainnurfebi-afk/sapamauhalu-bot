"""
main.py - Entry point Interactive Story Bot
"""

import logging
import sys

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
import admin as adm
import user as usr

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

# ─── Filter media atau teks biasa ─────────────────────────────────────────────
MEDIA_FILTER = (
    (filters.TEXT & ~filters.COMMAND)
    | filters.PHOTO
    | filters.ANIMATION
    | filters.VIDEO
    | filters.VOICE
    | filters.AUDIO
)

TEXT_ONLY = filters.TEXT & ~filters.COMMAND


def build_inputcerita_conv() -> ConversationHandler:
    """
    Conversation untuk:
    - /inputcerita — buat cerita baru
    - /inputpart   — tambah part ke cabang kosong
    - Tombol panel admin
    """
    return ConversationHandler(
        entry_points=[
            CommandHandler("inputcerita", adm.inputcerita_start),
            CommandHandler("inputpart",   adm.inputpart_start),
            CallbackQueryHandler(adm.admin_new_story_callback, pattern=r"^admin_new_story$"),
            CallbackQueryHandler(adm.admin_inputpart_callback, pattern=r"^admin_inputpart$"),
        ],
        states={
            # IC_WAIT_TITLE (0): terima judul cerita ATAU pilih cerita (inputpart)
            adm.IC_WAIT_TITLE: [
                CallbackQueryHandler(adm.inputpart_story_selected,  pattern=r"^ip_story_\d+$"),
                CallbackQueryHandler(adm.inputpart_choice_selected, pattern=r"^ip_choice_\d+$"),
                MessageHandler(TEXT_ONLY, adm.ic_receive_title),
            ],

            # IC_WAIT_TEXT (1): terima teks narasi
            adm.IC_WAIT_TEXT: [
                MessageHandler(TEXT_ONLY, adm.ic_receive_text),
            ],

            # IC_WAIT_MEDIA (2): terima media (bisa banyak)
            adm.IC_WAIT_MEDIA: [
                CommandHandler("skipmedia", adm.ic_skipmedia),
                CommandHandler("donemedia", adm.ic_donemedia),
                MessageHandler(MEDIA_FILTER, adm.ic_receive_media),
            ],

            # IC_WAIT_CHOICE (3): terima teks pilihan
            adm.IC_WAIT_CHOICE: [
                CommandHandler("lanjut",  adm.ic_lanjut),
                CommandHandler("selesai", adm.ic_selesai),
                MessageHandler(TEXT_ONLY, adm.ic_receive_choice),
            ],
        },
        fallbacks=[CommandHandler("cancel", adm.cancel_handler)],
        allow_reentry=True,
        per_message=False,
    )


def build_editpart_conv() -> ConversationHandler:
    """Conversation untuk /editpart."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("editpart", adm.editpart_start),
            CallbackQueryHandler(adm.admin_editpart_callback, pattern=r"^admin_editpart$"),
        ],
        states={
            adm.EP_WAIT_STORY: [
                CallbackQueryHandler(adm.ep_story_selected, pattern=r"^ep_story_\d+$"),
            ],
            adm.EP_WAIT_PART: [
                CallbackQueryHandler(adm.ep_part_selected, pattern=r"^ep_part_\d+$"),
            ],
            adm.EP_WAIT_FIELD: [
                CallbackQueryHandler(adm.ep_field_selected, pattern=r"^ep_field_"),
            ],
            adm.EP_WAIT_VALUE: [
                CommandHandler("donemedia", adm.ep_donemedia),
                MessageHandler(MEDIA_FILTER, adm.ep_receive_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", adm.cancel_handler)],
        allow_reentry=True,
        per_message=False,
    )


def main():
    from config import BOT_TOKEN
    logger.info("Memulai Interactive Story Bot...")

    db.init_db()
    logger.info("Database siap.")

    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandlers harus didaftarkan SEBELUM handler biasa
    app.add_handler(build_inputcerita_conv())
    app.add_handler(build_editpart_conv())

    # ── Admin commands ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("admin",      adm.admin_handler))
    app.add_handler(CommandHandler("addadmin",   adm.addadmin_handler))
    app.add_handler(CommandHandler("listcerita", adm.listcerita_handler))
    app.add_handler(CommandHandler("preview",    adm.preview_handler))

    # ── User commands ─────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",    usr.start_handler))
    app.add_handler(CommandHandler("reset",    usr.reset_handler))
    app.add_handler(CommandHandler("progress", usr.progress_handler))

    # ── Admin callbacks (non-conversation) ───────────────────────────────────
    app.add_handler(CallbackQueryHandler(
        adm.admin_panel_callback,
        pattern=r"^admin_(list|preview|delete)$"
    ))
    app.add_handler(CallbackQueryHandler(adm.preview_story_callback,  pattern=r"^preview_\d+$"))
    app.add_handler(CallbackQueryHandler(adm.confirm_delete_callback, pattern=r"^confirmdelete_\d+$"))
    app.add_handler(CallbackQueryHandler(adm.do_delete_callback,      pattern=r"^dodelete_\d+$"))

    # ── User callbacks ────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(usr.story_callback_handler,    pattern=r"^story_\d+$"))
    app.add_handler(CallbackQueryHandler(usr.continue_callback_handler, pattern=r"^continue_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(usr.newgame_callback_handler,  pattern=r"^newgame_\d+$"))
    app.add_handler(CallbackQueryHandler(usr.choice_callback_handler,   pattern=r"^choice_\d+$"))
    app.add_handler(CallbackQueryHandler(usr.reset_callback_handler,    pattern=r"^reset_\d+$"))
    app.add_handler(CallbackQueryHandler(usr.back_to_stories_callback,  pattern=r"^back_to_stories$"))

    logger.info("Bot berjalan. Tekan CTRL+C untuk berhenti.")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
