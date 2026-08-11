import asyncio
import threading
from bot_instance import bot
from promo_db import (
    add_account,
    add_group,
    get_accounts,
    get_groups,
    get_setting,
    remove_account,
    remove_group,
    set_setting,
)
from pyrogram import Client
from telebot import types

AUTHORIZED_USER = "mrpuppyx"
USER_STATES = {}
ACTIVE_CLIENTS = {}  # Retains active connected Pyrogram client instances

# Permanent background event loop for Pyrogram operations
PYROGRAM_LOOP = asyncio.new_event_loop()


def _start_asyncio_thread():
    asyncio.set_event_loop(PYROGRAM_LOOP)
    PYROGRAM_LOOP.run_forever()


threading.Thread(target=_start_asyncio_thread, daemon=True).start()


def run_in_pyrogram_loop(coro):
    """Executes a coroutine safely on the dedicated Pyrogram loop thread."""
    future = asyncio.run_coroutine_threadsafe(coro, PYROGRAM_LOOP)
    return future.result()


async def _async_send_otp(chat_id, api_id, api_hash, phone):
    cli = Client(
        f"temp_{phone}", api_id=api_id, api_hash=api_hash, in_memory=True
    )
    await cli.connect()
    sent_code = await cli.send_code(phone)
    ACTIVE_CLIENTS[chat_id] = cli  # Keep connected instance alive
    return sent_code.phone_code_hash


async def _async_sign_in(chat_id, phone, phone_code_hash, otp):
    cli = ACTIVE_CLIENTS.get(chat_id)
    if not cli:
        raise Exception("Login session lost. Please restart the process.")

    try:
        await cli.sign_in(phone, phone_code_hash, str(otp).strip())
        session_str = await cli.export_session_string()
        return session_str
    finally:
        await cli.disconnect()
        ACTIVE_CLIENTS.pop(chat_id, None)


def is_authorized(user):
    return (user.username or "").lower() == AUTHORIZED_USER.lower()


def build_promote_dashboard():
    status = get_setting("promo_status", "stop")
    default_bal = get_setting("default_balance", "100")
    status_str = "🟢 STARTED" if status == "start" else "🔴 STOPPED"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "➕ Add New Account", callback_data="promo:add_acc"
        ),
        types.InlineKeyboardButton(
            "❌ Remove Account", callback_data="promo:rem_acc"
        ),
        types.InlineKeyboardButton(
            "📝 Set Promote Msg", callback_data="promo:set_msg"
        ),
        types.InlineKeyboardButton(
            "👥 Add or Remove Group", callback_data="promo:manage_grp"
        ),
        types.InlineKeyboardButton(
            "🔄 Set/Del Reconfirm Msg", callback_data="promo:reconfirm_menu"
        ),
        types.InlineKeyboardButton(
            f"💰 Set Default Balance (Curr: ₹{default_bal})",
            callback_data="promo:set_def_bal",
        ),
        types.InlineKeyboardButton(
            f"⚙️ Status: {status_str} (Toggle)",
            callback_data="promo:toggle_status",
        ),
    )
    return markup, status_str


@bot.message_handler(commands=["promote", "Promote"])
def cmd_promote(message):
    if message.chat.type != "private":
        bot.reply_to(message, "❌ This command can only be used in DM.")
        return
    if not is_authorized(message.from_user):
        bot.reply_to(message, "❌ Unauthorized.")
        return

    markup, status_str = build_promote_dashboard()
    bot.send_message(
        message.chat.id,
        f"📣 <b>PROMOTION ENGINE DASHBOARD</b>\n\n"
        f"<b>Engine Status:</b> {status_str}\n"
        f"Select an option below to manage slave accounts, target groups, default balances, and automated messaging.",
        parse_mode="HTML",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("promo:"))
def handle_promote_callbacks(call):
    if not is_authorized(call.from_user):
        bot.answer_callback_query(call.id, "Unauthorized", show_alert=True)
        return

    action = call.data.split(":")[1]
    chat_id = call.message.chat.id

    if action == "add_acc":
        USER_STATES[chat_id] = {"step": "API_ID"}
        bot.send_message(
            chat_id, "📥 Please enter your <b>API ID</b>:", parse_mode="HTML"
        )

    elif action == "rem_acc":
        accs = get_accounts()
        if not accs:
            bot.answer_callback_query(
                call.id, "No accounts found.", show_alert=True
            )
            return
        markup = types.InlineKeyboardMarkup()
        for phone, _, _, _ in accs:
            markup.add(
                types.InlineKeyboardButton(
                    f"🗑️ {phone}", callback_data=f"promo_delacc:{phone}"
                )
            )
        bot.send_message(
            chat_id, "Select an account to remove:", reply_markup=markup
        )

    elif action == "set_msg":
        curr = get_setting("promote_msg", "None")
        USER_STATES[chat_id] = {"step": "SET_PROMOTE_MSG"}
        bot.send_message(
            chat_id,
            f"<b>Current Promo Message:</b>\n\n{curr}\n\n👇 Send your new promotion message below:",
            parse_mode="HTML",
        )

    elif action == "manage_grp":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(
                "➕ Add Group", callback_data="promo:add_grp_input"
            ),
            types.InlineKeyboardButton(
                "➖ Remove Group", callback_data="promo:rem_grp_list"
            ),
        )
        bot.send_message(
            chat_id, "Manage Target Scraper Groups:", reply_markup=markup
        )

    elif action == "add_grp_input":
        USER_STATES[chat_id] = {"step": "ADD_GROUP"}
        bot.send_message(
            chat_id,
            "📥 Send group username (e.g. <code>@groupusername</code>):",
            parse_mode="HTML",
        )

    elif action == "rem_grp_list":
        grps = get_groups()
        if not grps:
            bot.answer_callback_query(
                call.id, "No target groups added.", show_alert=True
            )
            return
        markup = types.InlineKeyboardMarkup()
        for g in grps:
            markup.add(
                types.InlineKeyboardButton(
                    f"🗑️ @{g}", callback_data=f"promo_delgrp:{g}"
                )
            )
        bot.send_message(
            chat_id, "Select group to remove:", reply_markup=markup
        )

    elif action == "reconfirm_menu":
        curr = get_setting("reconfirm_msg", "None")
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "✍️ Set Message", callback_data="promo:set_reconfirm_msg"
            ),
            types.InlineKeyboardButton(
                "🗑️ Delete Message", callback_data="promo:del_reconfirm_msg"
            ),
        )
        bot.send_message(
            chat_id,
            f"<b>Current Reconfirm Msg:</b>\n\n{curr}",
            parse_mode="HTML",
            reply_markup=markup,
        )

    elif action == "set_reconfirm_msg":
        USER_STATES[chat_id] = {"step": "SET_RECONFIRM_MSG"}
        bot.send_message(
            chat_id, "👇 Send the 24-hour follow-up reconfirm message:"
        )

    elif action == "del_reconfirm_msg":
        set_setting("reconfirm_msg", "")
        bot.answer_callback_query(
            call.id, "Reconfirm message cleared!", show_alert=True
        )

    elif action == "set_def_bal":
        USER_STATES[chat_id] = {"step": "SET_DEFAULT_BAL"}
        bot.send_message(
            chat_id,
            "💰 Enter new default joining balance amount (e.g. <code>0</code> or <code>100</code>):",
            parse_mode="HTML",
        )

    elif action == "toggle_status":
        curr = get_setting("promo_status", "stop")
        new_status = "start" if curr == "stop" else "stop"
        set_setting("promo_status", new_status)
        markup, status_str = build_promote_dashboard()
        bot.edit_message_text(
            f"📣 <b>PROMOTION ENGINE DASHBOARD</b>\n\n<b>Engine Status:</b> {status_str}",
            chat_id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith("promo_delacc:"))
def handle_del_acc(call):
    phone = call.data.split(":")[1]
    remove_account(phone)
    bot.answer_callback_query(call.id, f"Removed {phone}", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("promo_delgrp:"))
def handle_del_grp(call):
    grp = call.data.split(":")[1]
    remove_group(grp)
    bot.answer_callback_query(call.id, f"Removed @{grp}", show_alert=True)


@bot.message_handler(
    func=lambda m: m.chat.id in USER_STATES and is_authorized(m.from_user)
)
def process_promote_inputs(message):
    chat_id = message.chat.id
    state = USER_STATES[chat_id]
    step = state.get("step")

    if step == "API_ID":
        try:
            state["api_id"] = int(message.text.strip())
            state["step"] = "API_HASH"
            bot.send_message(
                chat_id, "🔑 Now send your <b>API Hash</b>:", parse_mode="HTML"
            )
        except ValueError:
            bot.send_message(
                chat_id, "❌ Invalid API ID. Please send a valid number."
            )

    elif step == "API_HASH":
        state["api_hash"] = message.text.strip()
        state["step"] = "PHONE"
        bot.send_message(
            chat_id,
            "📱 Enter mobile number (without international code, e.g., <code>9876543210</code>):",
            parse_mode="HTML",
        )

    elif step == "PHONE":
        raw_phone = message.text.strip().replace("+", "")
        phone = (
            f"+91{raw_phone}"
            if len(raw_phone) == 10 and raw_phone.isdigit()
            else f"+{raw_phone}"
        )
        state["phone"] = phone

        try:
            phone_code_hash = run_in_pyrogram_loop(
                _async_send_otp(chat_id, state["api_id"], state["api_hash"], phone)
            )
            state["phone_code_hash"] = phone_code_hash
            state["step"] = "OTP"
            bot.send_message(
                chat_id,
                f"📩 OTP sent to <code>{phone}</code>. Enter code:",
                parse_mode="HTML",
            )
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed to send OTP: {e}")
            del USER_STATES[chat_id]

    elif step == "OTP":
        otp = message.text.strip()
        try:
            session_str = run_in_pyrogram_loop(
                _async_sign_in(
                    chat_id,
                    state["phone"],
                    state["phone_code_hash"],
                    otp,
                )
            )
            add_account(
                state["phone"], state["api_id"], state["api_hash"], session_str
            )
            bot.send_message(
                chat_id,
                f"✅ Account <code>{state['phone']}</code> logged in and saved successfully!",
                parse_mode="HTML",
            )
        except Exception as e:
            bot.send_message(chat_id, f"❌ Login failed: {e}")
        finally:
            if chat_id in USER_STATES:
                del USER_STATES[chat_id]

    elif step == "SET_PROMOTE_MSG":
        set_setting("promote_msg", message.text)
        bot.send_message(chat_id, "✅ Promo message saved!")
        del USER_STATES[chat_id]

    elif step == "SET_RECONFIRM_MSG":
        set_setting("reconfirm_msg", message.text)
        bot.send_message(chat_id, "✅ Reconfirm message saved!")
        del USER_STATES[chat_id]

    elif step == "SET_DEFAULT_BAL":
        if message.text.strip().isdigit():
            val = message.text.strip()
            set_setting("default_balance", val)
            bot.send_message(
                chat_id,
                f"✅ Default joining balance updated to <b>₹{val}</b>!",
                parse_mode="HTML",
            )
        else:
            bot.send_message(
                chat_id, "❌ Invalid number. Please send numbers only."
            )
        del USER_STATES[chat_id]

    elif step == "ADD_GROUP":
        grp = message.text.strip().replace("@", "")
        add_group(grp)
        bot.send_message(
            chat_id,
            f"✅ Group <code>@{grp}</code> added to scraper list!",
            parse_mode="HTML",
        )
        del USER_STATES[chat_id]
