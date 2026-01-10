import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from db import cursor, conn
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd
import matplotlib
matplotlib.use("Agg")

USER_STATE = {}

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update.message)


async def show_main_menu(chat):       #send message after every task
    keyboard = [
        [InlineKeyboardButton("➕ Add Expense", callback_data="add")],
        [InlineKeyboardButton("📊 Show Expenses", callback_data="show")],
        [InlineKeyboardButton("📁 Get Excel File", callback_data="excel")],
        [InlineKeyboardButton("🗑️ Clear Expenses", callback_data="clear")],
        [InlineKeyboardButton("🧾 View Expenses", callback_data="view")]
    ]

    await chat.reply_text(
        "👉 What would you like to do next?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



# ---------- BUTTON HANDLER ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "add":
        keyboard = [
            [InlineKeyboardButton("🍔 Food", callback_data="cat_food")],
            [InlineKeyboardButton("🚕 Travel", callback_data="cat_travel")],
            [InlineKeyboardButton("🧴 Personal", callback_data="cat_personal")],
            [InlineKeyboardButton("📦 Other", callback_data="cat_other")]
        ]
        await query.message.reply_text(
            "Select expense category:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("cat_"):
        category = query.data.replace("cat_", "")
        USER_STATE[user_id] = {
        "category": category,
        "step": "amount"
        }

        await query.message.reply_text(f"Enter amount for {category.capitalize()}:")

    elif query.data == "show":
        current_month = int(datetime.now().strftime("%m"))
        year = datetime.now().strftime("%Y")

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        keyboard = []
        row = []

        for i in range(current_month):
            row.append(
                InlineKeyboardButton(
                    month_names[i],
                    callback_data=f"month_{i+1:02d}"
                )
            )
            if len(row) == 3:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        await query.message.reply_text(
            f"📅 Select month ({year}):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("month_"):
        month = query.data.split("_")[1]
        await show_monthly_expenses(query, month)

    elif query.data == "excel":
        await send_excel(query)
    

    elif query.data == "clear":
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, clear all", callback_data="clear_yes"),
                InlineKeyboardButton("❌ Cancel", callback_data="clear_no")
            ]
        ]

        await query.message.reply_text(
            "⚠️ Are you sure you want to delete ALL your expenses?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "clear_yes":
        cursor.execute(
            "DELETE FROM expenses WHERE user_id=?",
            (user_id,)
        )
        conn.commit()

        await query.message.reply_text("🗑️ All your expenses have been deleted.")
        await show_main_menu(query.message)


    elif query.data == "clear_no":
        await query.message.reply_text("❌ Deletion cancelled.")


    #Notes
    elif query.data == "note_enter":
        USER_STATE[user_id]["step"] = "note"
        await query.message.reply_text("✍️ Please enter your note:")

    elif query.data == "note_skip":
        state = USER_STATE[user_id]

        cursor.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                state["amount"],
                state["category"],
                datetime.now().strftime("%Y-%m-%d"),
                ""
            )
        )
        conn.commit()

        del USER_STATE[user_id]

        await query.message.reply_text("✅ Expense added successfully")
        await show_main_menu(query.message)

    #View Expenses Button
    elif query.data == "view":
        await list_expenses(query)


       


#Show Monthly Expense
async def show_monthly_expenses(query, month):
    user_id = query.from_user.id
    year = datetime.now().strftime("%Y")
    month_pattern = f"{year}-{month}%"

    # ---- MONTH TOTAL ----
    cursor.execute(
        "SELECT SUM(amount) FROM expenses WHERE user_id=? AND date LIKE ?",
        (user_id, month_pattern)
    )
    total = cursor.fetchone()[0] or 0

    await query.message.reply_text(
        f"📊 Expense Summary ({year}-{month})\n💰 Total: ₹{total}"
    )

    df = pd.read_sql_query(
        """
        SELECT date, category, SUM(amount) as total
        FROM expenses
        WHERE user_id=? AND date LIKE ?
        GROUP BY date, category
        ORDER BY date
        """,
        conn,
        params=(user_id, month_pattern)
    )

    if df.empty:
        await query.message.reply_text("No data for this month.")
        return

    df["date"] = pd.to_datetime(df["date"])
    pivot_df = (
        df.pivot(index="date", columns="category", values="total")
        .fillna(0)
        .sort_index()
    )

    plt.figure(figsize=(9, 4), dpi=90)

    colors = {
        "food": "green",
        "travel": "blue",
        "personal": "orange",
        "other": "red"
    }

    for cat, color in colors.items():
        if cat in pivot_df.columns:
            plt.plot(
                pivot_df.index,
                pivot_df[cat],
                label=cat.capitalize(),
                marker="o",
                color=color
            )

    plt.xlabel("Date")
    plt.ylabel("Amount")
    plt.title("Monthly Expense Trend")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()

    file_name = f"month_{user_id}_{month}.png"
    plt.savefig(file_name)
    plt.close()

    await query.message.reply_photo(photo=open(file_name, "rb"))
    
    await show_main_menu(query.message)



# ---------- ADD AMOUNT ----------
async def add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in USER_STATE:
        return

    state = USER_STATE[user_id]

    # ---- STEP 1: AMOUNT ----
    if state["step"] == "amount":
        try:
            amount = float(update.message.text)
            state["amount"] = amount
            state["step"] = "choose_note"

            keyboard = [
                [
                    InlineKeyboardButton("✍️ Enter Note", callback_data="note_enter"),
                    InlineKeyboardButton("⏭️ Skip", callback_data="note_skip")
                ]
            ]

            await update.message.reply_text(
                "🧾 Do you want to add a note?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except:
            await update.message.reply_text("❌ Please enter a valid number")

    # ---- STEP 2: NOTE TEXT ----
    elif state["step"] == "note":
        note = update.message.text

        cursor.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                state["amount"],
                state["category"],
                datetime.now().strftime("%Y-%m-%d"),
                note
            )
        )
        conn.commit()

        del USER_STATE[user_id]

        await update.message.reply_text("✅ Expense added successfully")
        await show_main_menu(update.message)



# ---------- SHOW GRAPH ----------
async def show_expenses_graph(query):
    user_id = query.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    # ----- TODAY EXPENSE -----
    cursor.execute(
        "SELECT SUM(amount) FROM expenses WHERE user_id=? AND date=?",
        (user_id, today)
    )
    today_total = cursor.fetchone()[0] or 0

    # ----- MONTHLY EXPENSE -----
    cursor.execute(
        "SELECT SUM(amount) FROM expenses WHERE user_id=? AND date LIKE ?",
        (user_id, f"{month}%")
    )
    month_total = cursor.fetchone()[0] or 0

    await query.message.reply_text(
        f"📅 **Expense Summary**\n\n"
        f"🟢 Today: ₹{today_total}\n"
        f"🔵 This Month: ₹{month_total}",
        parse_mode="Markdown"
    )

    # ----- CATEGORY-WISE DAILY DATA -----
    # ----- CATEGORY-WISE DAILY DATA -----
    df = pd.read_sql_query(
        """
        SELECT date, category, SUM(amount) as total
        FROM expenses
        WHERE user_id=?
        GROUP BY date, category
        ORDER BY date
        """,
        conn,
        params=(user_id,)
    )

    if df.empty:
        await query.message.reply_text("No data available for graph.")
        return

    # ----- DATA ALIGNMENT (CRITICAL PART) -----
    df["date"] = pd.to_datetime(df["date"])

    pivot_df = df.pivot_table(
        index="date",
        columns="category",
        values="total",
        fill_value=0
    )

    pivot_df = pivot_df.sort_index()

    # ----- LINE GRAPH -----
    plt.figure(figsize=(10, 5))

    colors = {
        "food": "green",
        "travel": "blue",
        "personal": "orange",
        "other": "red"
    }

    for cat in colors:
        if cat in pivot_df.columns:
            plt.plot(
                pivot_df.index,
                pivot_df[cat],
                label=cat.capitalize(),
                color=colors[cat],
                marker="o"
            )

    plt.xlabel("Date")
    plt.ylabel("Amount")
    plt.title("Category-wise Daily Expenses")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()

    plt.savefig("expense_line_graph.png")
    plt.close()

    await query.message.reply_photo(
        photo=open("expense_line_graph.png", "rb")
    )

# ---------- SEND CSV ----------
async def send_excel(query):
    user_id = query.from_user.id

    df = pd.read_sql_query(
        "SELECT date, category, amount FROM expenses WHERE user_id=?",
        conn,
        params=(user_id,)
    )

    if df.empty:
        await query.message.reply_text("No data to export.")
        return

    file_name = f"expenses_{user_id}.csv"
    df.to_csv(file_name, index=False)

    await query.message.reply_document(document=open(file_name, "rb"))

    await show_main_menu(query.message)

#View Notes
async def list_expenses(query):
    user_id = query.from_user.id

    cursor.execute(
        """
        SELECT id, date, category, amount, note
        FROM expenses
        WHERE user_id=?
        ORDER BY date DESC
        LIMIT 10
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    if not rows:
        await query.message.reply_text("No expenses found.")
        await show_main_menu(query.message)
        return

    msg = "🧾 *Your recent expenses:*\n\n"

    for eid, date, category, amount, note in rows:
        msg += f"🆔 {eid} | {date}\n"
        msg += f"{category.capitalize()} – ₹{amount}\n"
        if note:
            msg += f"📝 {note}\n"
        msg += "\n"

    await query.message.reply_text(msg, parse_mode="Markdown")
    await show_main_menu(query.message)



# ---------- BOT SETUP ----------
TOKEN = os.getenv("BOT_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_amount))

app.run_polling()
