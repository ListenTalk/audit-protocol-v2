"""
Smart Invoice Bot – PDF Invoice Generator
Free: 3 invoices/month. Pro: unlimited (manual activation by admin OR via Telegram Stars).
"""
import logging
import os
import uuid
import sqlite3
from datetime import datetime, timedelta
from io import BytesIO

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove, LabeledPrice
)
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, Filters,
    CallbackContext, PreCheckoutQueryHandler
)
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

load_dotenv()
BOT_TOKEN      = os.getenv("BOT_TOKEN")
ADMIN_ID       = int(os.getenv("ADMIN_ID", "0"))
FREE_LIMIT     = 3
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
PROXY_URL      = os.getenv("PROXY_URL", "")

# ── Цена Pro в Telegram Stars ─────────────────────────────────────────────────
# 1 Star ≈ $0.013 | 200 Stars ≈ $2.6 | настрой под себя
STARS_PRICE = 200

if not BOT_TOKEN:
    exit("ERROR: BOT_TOKEN not found in .env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── States ────────────────────────────────────────────────────────────────────
(
    SETUP_NAME, SETUP_EMAIL, SETUP_PHONE, SETUP_ADDRESS, SETUP_LOGO,
    INV_CLIENT, INV_ITEMS, INV_ADD_MORE, INV_CONFIRM, UPLOAD_LOGO
) = range(10)

DB_PATH = "smart_invoice.db"


# ── Database ──────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id          INTEGER PRIMARY KEY,
                company          TEXT,
                email            TEXT,
                phone            TEXT,
                address          TEXT,
                plan             TEXT DEFAULT 'free',
                plan_until       TEXT,
                logo_file_id     TEXT,
                logo_uploaded_at TEXT,
                created_at       TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS invoices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                inv_number  TEXT,
                client_name TEXT,
                total       REAL,
                created_at  TEXT DEFAULT (datetime('now'))
            );
        """)


def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def save_user(user_id: int, data: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, company, email, phone, address)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                company = excluded.company,
                email   = excluded.email,
                phone   = excluded.phone,
                address = excluded.address
        """, (user_id, data["company"], data["email"], data["phone"], data["address"]))


def save_logo(user_id: int, file_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET logo_file_id = ?, logo_uploaded_at = datetime('now') WHERE user_id = ?",
            (file_id, user_id)
        )


def count_invoices_this_month(user_id: int) -> int:
    month = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE user_id = ? AND created_at LIKE ?",
            (user_id, f"{month}%")
        ).fetchone()
    return row[0] if row else 0


def save_invoice(user_id: int, inv_number: str, client: str, total: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO invoices (user_id, inv_number, client_name, total) VALUES (?, ?, ?, ?)",
            (user_id, inv_number, client, total)
        )


def set_pro(user_id: int, days: int = 30):
    until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET plan = 'pro', plan_until = ? WHERE user_id = ?",
            (until, user_id)
        )


def is_pro(user_id: int) -> bool:
    u = get_user(user_id)
    if not u or u["plan"] != "pro":
        return False
    if u["plan_until"] and u["plan_until"] < datetime.now().strftime("%Y-%m-%d"):
        return False
    return True


# ── PDF Generator ─────────────────────────────────────────────────────────────
def make_pdf(company: dict, inv_data: dict, inv_number: str, logo_img=None):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch
    )
    styles = getSampleStyleSheet()
    normal = styles["Normal"]

    title_style = ParagraphStyle(
        "InvTitle", parent=styles["Heading1"],
        fontSize=28, textColor=colors.HexColor("#1E2761"),
        spaceAfter=4, alignment=2
    )

    story = []

    left_cell = logo_img if logo_img else Paragraph(f"<b>{company['company']}</b>", normal)
    header = Table(
        [[left_cell, Paragraph("INVOICE", title_style)]],
        colWidths=[4 * inch, 3 * inch]
    )
    header.setStyle(TableStyle([
        ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1,  0), 0.5, colors.HexColor("#E2E8F0")),
    ]))
    story.append(header)
    story.append(Spacer(1, 16))

    meta_data = [
        [Paragraph("<b>FROM</b>", normal), "",
         Paragraph("<b>INVOICE #</b>", normal), Paragraph("<b>DATE</b>", normal)],
        [Paragraph(company.get("company", ""), normal), "",
         Paragraph(inv_number, normal),
         Paragraph(datetime.now().strftime("%B %d, %Y"), normal)],
        [Paragraph(company.get("email",   ""), normal), "", "", ""],
        [Paragraph(company.get("phone",   ""), normal), "", "", ""],
        [Paragraph(company.get("address", ""), normal), "", "", ""],
    ]
    meta = Table(meta_data, colWidths=[2.8 * inch, 0.5 * inch, 2 * inch, 1.7 * inch])
    meta.setStyle(TableStyle([
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta)
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>BILL TO</b>", normal))
    story.append(Paragraph(f"<b>{inv_data['client']}</b>", normal))
    story.append(Spacer(1, 16))

    rows = [["Description", "Qty", "Unit Price", "Total"]]
    grand = 0.0
    for it in inv_data["items"]:
        sub = it["qty"] * it["price"]
        grand += sub
        qty_str = str(int(it["qty"])) if float(it["qty"]).is_integer() else str(it["qty"])
        rows.append([it["desc"], qty_str, f"${it['price']:.2f}", f"${sub:.2f}"])
    rows.append(["", "", "TOTAL", f"${grand:.2f}"])

    tbl = Table(rows, colWidths=[3.5 * inch, 0.8 * inch, 1.4 * inch, 1.3 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,  0), (-1,  0), colors.HexColor("#1E2761")),
        ("TEXTCOLOR",     (0,  0), (-1,  0), colors.white),
        ("FONTNAME",      (0,  0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,  0), (-1,  0), 10),
        ("ROWBACKGROUNDS",(0,  1), (-1, -2), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#E8F1FE")),
        ("FONTNAME",      (2, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN",         (1,  0), (-1, -1), "RIGHT"),
        ("GRID",          (0,  0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
        ("TOPPADDING",    (0,  0), (-1, -1), 6),
        ("BOTTOMPADDING", (0,  0), (-1, -1), 6),
        ("LEFTPADDING",   (0,  0), (-1, -1), 8),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 24))
    story.append(Paragraph("Thank you for your business!", normal))
    story.append(Paragraph("Generated by Smart Invoice Bot", normal))

    doc.build(story)
    buf.seek(0)
    return buf, grand


def format_items_summary(items: list) -> str:
    lines = []
    total = 0.0
    for i, it in enumerate(items, 1):
        sub = it["qty"] * it["price"]
        total += sub
        lines.append(f"{i}. {it['desc']} × {it['qty']} = ${sub:.2f}")
    lines.append(f"\n💰 *Total: ${total:.2f}*")
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────
def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 New Invoice", callback_data="new_invoice")],
        [InlineKeyboardButton("⚙️ My Profile", callback_data="profile"),
         InlineKeyboardButton("📊 History",    callback_data="history")],
        [InlineKeyboardButton("⭐ Upgrade to Pro", callback_data="upgrade")],
    ])


def send_main_menu(message, uid: int):
    user = get_user(uid)
    if user:
        plan_label = "⭐ Pro" if is_pro(uid) else "Free"
        used = count_invoices_this_month(uid)
        message.reply_text(
            f"👋 Welcome back, *{user['company']}*!\n\n"
            f"Plan: {plan_label}  |  This month: {used} invoice(s)\n\n"
            "What would you like to do?",
            parse_mode="Markdown",
            reply_markup=main_menu_markup()
        )
    else:
        message.reply_text(
            "Use /start to set up your account.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Set up my account", callback_data="setup")]
            ])
        )


# ── /start ────────────────────────────────────────────────────────────────────
def start(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    user = get_user(uid)
    if user:
        plan_label = "⭐ Pro" if is_pro(uid) else "Free"
        used = count_invoices_this_month(uid)
        update.message.reply_text(
            f"👋 Welcome back, *{user['company']}*!\n\n"
            f"Plan: {plan_label}  |  This month: {used} invoice(s)\n\n"
            "What would you like to do?",
            parse_mode="Markdown",
            reply_markup=main_menu_markup()
        )
    else:
        update.message.reply_text(
            "👋 Welcome to *Smart Invoice Bot*!\n\n"
            "Generate professional PDF invoices in seconds — right from Telegram.\n\n"
            "✅ Free: 3 invoices/month\n"
            f"⭐ Pro: unlimited invoices — {STARS_PRICE} Telegram Stars/month\n\n"
            "Let's set up your account first:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Set up my account", callback_data="setup")],
                [InlineKeyboardButton("⭐ Upgrade to Pro",    callback_data="upgrade")]
            ])
        )


# ── /add_pro (admin) ──────────────────────────────────────────────────────────
def add_pro_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        update.message.reply_text("Usage: /add_pro <user_id>")
        return
    uid = int(args[0])
    if not get_user(uid):
        update.message.reply_text(f"⚠️ User {uid} not found in database.")
        return
    set_pro(uid)
    update.message.reply_text(f"✅ User {uid} is now Pro for 30 days.")
    try:
        context.bot.send_message(
            uid,
            "🎉 *Your Pro plan is now active for 30 days!*\n\nUse /start to continue.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning("Could not notify user %d: %s", uid, e)


# ── Upgrade callback ──────────────────────────────────────────────────────────
def upgrade_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    q.message.reply_text(
        "⭐ *Upgrade to Pro*\n\n"
        "✅ Unlimited invoices\n"
        "✅ Priority support\n\n"
        f"💫 Price: *{STARS_PRICE} Telegram Stars* (30 days)\n\n"
        "Choose a payment method:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💫 Оплатить {STARS_PRICE} Stars", callback_data="buy_stars")],
            [InlineKeyboardButton(f"💬 Написать @{ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
        ])
    )


# ── Stars payment: отправка инвойса ──────────────────────────────────────────
def buy_stars_cb(update: Update, context: CallbackContext):
    """Отправляем инвойс для оплаты через Telegram Stars."""
    q = update.callback_query
    q.answer()
    uid = update.effective_user.id

    if is_pro(uid):
        q.message.reply_text("✅ You already have Pro! Enjoy unlimited invoices.")
        return

    context.bot.send_invoice(
        chat_id=uid,
        title="Smart Invoice Bot — Pro",
        description="30 days Pro: unlimited PDF invoices + priority support",
        payload=f"pro_upgrade_{uid}",
        provider_token="",            # Must be empty for Telegram Stars
        currency="XTR",               # XTR = Telegram Stars
        prices=[LabeledPrice("Pro — 30 days", STARS_PRICE)],
    )


# ── Stars payment: подтверждение (обязательный шаг!) ─────────────────────────
def pre_checkout_cb(update: Update, context: CallbackContext):
    """Telegram требует обязательно ответить на pre_checkout_query в течение 10 сек."""
    query = update.pre_checkout_query

    if not query.invoice_payload.startswith("pro_upgrade_"):
        query.answer(ok=False, error_message="Invalid payment. Please try again.")
        return

    query.answer(ok=True)


# ── Stars payment: успешная оплата ────────────────────────────────────────────
def successful_payment_handler(update: Update, context: CallbackContext):
    """Вызывается когда Stars успешно списаны — активируем Pro."""
    uid     = update.effective_user.id
    payment = update.message.successful_payment
    stars   = payment.total_amount

    set_pro(uid, days=30)

    update.message.reply_text(
        f"🎉 *Payment of {stars} Stars successful!*\n\n"
        "✅ Pro is now active for 30 days.\n"
        "You now have unlimited invoices!\n\n"
        "Create your first invoice right now 👇",
        parse_mode="Markdown",
        reply_markup=main_menu_markup()
    )

    # Notify admin
    try:
        context.bot.send_message(
            ADMIN_ID,
            f"💫 *New Stars payment!*\n\n"
            f"User ID: `{uid}`\n"
            f"Stars: {stars}\n"
            f"Payload: `{payment.invoice_payload}`\n"
            f"Charge ID: `{payment.telegram_payment_charge_id}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning("Could not notify admin: %s", e)


# ── Setup conversation ────────────────────────────────────────────────────────
def setup_start(update: Update, context: CallbackContext):
    q = update.callback_query
    if q:
        q.answer()
        q.message.reply_text("🏢 Enter your company name:")
    else:
        update.message.reply_text("🏢 Enter your company name:")
    return SETUP_NAME


def setup_name(update: Update, context: CallbackContext):
    context.user_data["company"] = update.message.text.strip()
    update.message.reply_text("📧 Enter your email:")
    return SETUP_EMAIL


def setup_email(update: Update, context: CallbackContext):
    context.user_data["email"] = update.message.text.strip()
    update.message.reply_text("📱 Enter your phone:")
    return SETUP_PHONE


def setup_phone(update: Update, context: CallbackContext):
    context.user_data["phone"] = update.message.text.strip()
    update.message.reply_text("📍 Enter your address:")
    return SETUP_ADDRESS


def setup_address(update: Update, context: CallbackContext):
    context.user_data["address"] = update.message.text.strip()
    update.message.reply_text(
        "🖼 Do you want to upload a company logo?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Upload Logo", callback_data="upload_logo"),
             InlineKeyboardButton("⏭ Skip",        callback_data="skip_logo")]
        ])
    )
    return SETUP_LOGO


def upload_logo_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    q.message.reply_text("📷 Send your logo image now:")
    return UPLOAD_LOGO


def handle_logo(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    _finish_save(uid, context)
    file_id = update.message.photo[-1].file_id
    save_logo(uid, file_id)
    update.message.reply_text(
        "✅ Logo saved! Account is ready.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Create first invoice →", callback_data="new_invoice")]
        ])
    )
    context.user_data.clear()
    return ConversationHandler.END


def skip_logo_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid = update.effective_user.id
    _finish_save(uid, context)
    q.message.reply_text(
        "✅ Account ready!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Create first invoice →", callback_data="new_invoice")]
        ])
    )
    context.user_data.clear()
    return ConversationHandler.END


def _finish_save(uid: int, context: CallbackContext):
    data = {
        "company": context.user_data.get("company", ""),
        "email":   context.user_data.get("email",   ""),
        "phone":   context.user_data.get("phone",   ""),
        "address": context.user_data.get("address", ""),
    }
    save_user(uid, data)


# ── Invoice conversation ──────────────────────────────────────────────────────
def new_invoice(update: Update, context: CallbackContext):
    q = update.callback_query
    if q:
        q.answer()
    uid = update.effective_user.id

    if not get_user(uid):
        update.effective_message.reply_text(
            "⚠️ Please run /start first to set up your account."
        )
        return ConversationHandler.END

    if not is_pro(uid) and count_invoices_this_month(uid) >= FREE_LIMIT:
        update.effective_message.reply_text(
            f"⚠️ You've used all {FREE_LIMIT} free invoices this month.\n\n"
            f"Upgrade to Pro for just {STARS_PRICE} Telegram Stars:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Upgrade to Pro", callback_data="upgrade")]
            ])
        )
        return ConversationHandler.END

    context.user_data["items"] = []
    update.effective_message.reply_text("👤 Enter client name:")
    return INV_CLIENT


def inv_client(update: Update, context: CallbackContext):
    context.user_data["client"] = update.message.text.strip()
    update.message.reply_text(
        "📝 Add an item in this format:\n`Description, Qty, Price`\n\nExample: `Web design, 1, 500`",
        parse_mode="Markdown"
    )
    return INV_ITEMS


def inv_items(update: Update, context: CallbackContext):
    parts = [p.strip() for p in update.message.text.split(",")]
    if len(parts) != 3:
        update.message.reply_text(
            "❌ Wrong format. Use: `Description, Qty, Price`\nExample: `Logo design, 2, 150`",
            parse_mode="Markdown"
        )
        return INV_ITEMS
    try:
        desc  = parts[0]
        qty   = float(parts[1])
        price = float(parts[2].replace("$", "").replace(" ", ""))
        if qty <= 0 or price < 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("❌ Qty and price must be positive numbers. Try again.")
        return INV_ITEMS

    context.user_data["items"].append({"desc": desc, "qty": qty, "price": price})
    update.message.reply_text(
        format_items_summary(context.user_data["items"]),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add more item", callback_data="add"),
             InlineKeyboardButton("✅ Generate PDF",  callback_data="gen")]
        ])
    )
    return INV_ADD_MORE


def add_more_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "add":
        q.message.reply_text(
            "📝 Add next item: `Description, Qty, Price`",
            parse_mode="Markdown"
        )
        return INV_ITEMS
    return create_invoice(update, context)


def create_invoice(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid    = update.effective_user.id
    user   = get_user(uid)
    items  = context.user_data.get("items", [])
    client = context.user_data.get("client", "Client")

    if not items:
        q.message.reply_text("⚠️ No items added. Cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

    inv_num = f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    logo_img = None
    if user.get("logo_file_id"):
        try:
            tg_file = context.bot.get_file(user["logo_file_id"])
            logo_buf = BytesIO()
            tg_file.download(out=logo_buf)
            logo_buf.seek(0)
            logo_img = Image(logo_buf, width=1.5 * inch, height=0.75 * inch, kind="proportional")
        except Exception as e:
            logger.warning("Logo download failed: %s", e)

    pdf, total = make_pdf(user, {"client": client, "items": items}, inv_num, logo_img)
    save_invoice(uid, inv_num, client, total)

    used      = count_invoices_this_month(uid)
    remaining = "∞" if is_pro(uid) else max(0, FREE_LIMIT - used)

    q.message.reply_document(
        document=pdf,
        filename=f"Invoice_{inv_num}.pdf",
        caption=(
            f"📄 *{inv_num}*\n"
            f"👤 {client}\n"
            f"💰 ${total:,.2f}\n"
            f"📋 Remaining this month: {remaining}"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 New Invoice", callback_data="new_invoice")],
            [InlineKeyboardButton("🏠 Main Menu",   callback_data="back_to_menu")],
        ])
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Profile callback ──────────────────────────────────────────────────────────
def profile_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid = update.effective_user.id
    u   = get_user(uid)
    if not u:
        q.message.reply_text("No profile found. Use /start.")
        return

    used = count_invoices_this_month(uid)
    plan = "⭐ Pro" if is_pro(uid) else f"Free ({used}/{FREE_LIMIT})"

    with get_conn() as conn:
        total_inv = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE user_id = ?", (uid,)
        ).fetchone()[0]

    logo_status = "✅ Uploaded" if u.get("logo_file_id") else "❌ None"

    q.message.reply_text(
        f"*Your Profile*\n\n"
        f"🏢 {u['company']}\n"
        f"📧 {u['email']}\n"
        f"📱 {u['phone']}\n"
        f"📍 {u['address']}\n"
        f"🖼 Logo: {logo_status}\n\n"
        f"Plan: {plan}\n"
        f"Total invoices: {total_inv}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Update Profile", callback_data="setup")],
            [InlineKeyboardButton("🔙 Back",           callback_data="back_to_menu")]
        ])
    )


# ── History callback ──────────────────────────────────────────────────────────
def history_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    uid = update.effective_user.id

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT inv_number, client_name, total, created_at
               FROM invoices WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 10""",
            (uid,)
        ).fetchall()

    if not rows:
        q.message.reply_text("📭 No invoices yet.")
        return

    lines = ["*Recent Invoices (last 10):*\n"]
    for row in rows:
        lines.append(
            f"📄 `{row['inv_number']}`\n"
            f"   👤 {row['client_name']} — 💰 ${row['total']:,.2f} — 📅 {str(row['created_at'])[:10]}\n"
        )
    q.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Back to menu ──────────────────────────────────────────────────────────────
def back_to_menu_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    context.user_data.clear()
    try:
        q.answer()
    except Exception:
        pass
    send_main_menu(q.message, update.effective_user.id)
    return ConversationHandler.END


# ── /cancel ───────────────────────────────────────────────────────────────────
def cancel(update: Update, context: CallbackContext):
    context.user_data.clear()
    update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    init_db()

    request_kwargs = {}
    if PROXY_URL:
        request_kwargs["proxy_url"] = PROXY_URL
        logger.info("🔌 Using proxy: %s", PROXY_URL)
    else:
        logger.info("🌐 Using system connection (VPN/direct)")

    updater = Updater(BOT_TOKEN, request_kwargs=request_kwargs)
    dp = updater.dispatcher

    # Global commands
    dp.add_handler(CommandHandler("start",   start))
    dp.add_handler(CommandHandler("add_pro", add_pro_cmd))

    # Simple callbacks (outside conversations)
    dp.add_handler(CallbackQueryHandler(upgrade_cb,      pattern="^upgrade$"))
    dp.add_handler(CallbackQueryHandler(buy_stars_cb,    pattern="^buy_stars$"))   # ← Stars инвойс
    dp.add_handler(CallbackQueryHandler(profile_cb,      pattern="^profile$"))
    dp.add_handler(CallbackQueryHandler(history_cb,      pattern="^history$"))
    dp.add_handler(CallbackQueryHandler(back_to_menu_cb, pattern="^back_to_menu$"))

    # ── Telegram Stars: ОБЯЗАТЕЛЬНЫЕ обработчики ──────────────────────────────
    dp.add_handler(PreCheckoutQueryHandler(pre_checkout_cb))           # шаг 1: подтверждение
    dp.add_handler(MessageHandler(                                     # шаг 2: успех
        Filters.successful_payment, successful_payment_handler
    ))

    # Setup conversation
    setup_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(setup_start, pattern="^setup$"),
            CommandHandler("setup", setup_start),
        ],
        states={
            SETUP_NAME:    [MessageHandler(Filters.text & ~Filters.command, setup_name)],
            SETUP_EMAIL:   [MessageHandler(Filters.text & ~Filters.command, setup_email)],
            SETUP_PHONE:   [MessageHandler(Filters.text & ~Filters.command, setup_phone)],
            SETUP_ADDRESS: [MessageHandler(Filters.text & ~Filters.command, setup_address)],
            SETUP_LOGO: [
                CallbackQueryHandler(upload_logo_cb, pattern="^upload_logo$"),
                CallbackQueryHandler(skip_logo_cb,   pattern="^skip_logo$"),
            ],
            UPLOAD_LOGO: [MessageHandler(Filters.photo, handle_logo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(setup_conv)

    # Invoice conversation
    invoice_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(new_invoice, pattern="^new_invoice$"),
        ],
        states={
            INV_CLIENT:   [MessageHandler(Filters.text & ~Filters.command, inv_client)],
            INV_ITEMS:    [MessageHandler(Filters.text & ~Filters.command, inv_items)],
            INV_ADD_MORE: [CallbackQueryHandler(add_more_cb, pattern="^(add|gen)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(invoice_conv)

    logger.info("🚀 Smart Invoice Bot is running!")
    updater.start_polling(
        drop_pending_updates=True,
        read_latency=5,
        timeout=30,
    )
    updater.idle()


if __name__ == "__main__":
    main()
