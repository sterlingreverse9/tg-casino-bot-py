from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import adjust_balance
from game_status import is_game_enabled, set_game_enabled
from middleware.admin import is_admin
from helpers import ensure_user
from referral import (
    get_or_create_referral_code, get_referral_stats, claim_referral_balance,
    get_referral_history, get_referred_deposit_totals, get_referred_loss_totals,
)
from settings import (
    get_referral_deposit_pct, get_referral_deposit_count, get_referral_loss_pct,
    set_referral_deposit_pct, set_referral_deposit_count, set_referral_loss_pct,
)


def build_referral_text(telegram_id: int) -> str:
    code = get_or_create_referral_code(telegram_id)
    bot_username = bot.get_me().username
    stats = get_referral_stats(telegram_id)
    dep_pct, dep_count, loss_pct = get_referral_deposit_pct(), get_referral_deposit_count(), get_referral_loss_pct()

    return (
        "ℹ️ Earn balance(₹) from invited users\n\n"
        f"🔗 Referral link: t.me/{bot_username}?start=ref-{code}\n"
        f"🔥 Current system: {dep_pct}% of first {dep_count} deposits, and {loss_pct}% of every loss of your referrals\n"
        f"📈 Users invited: {stats['invited_count']}\n"
        f"💵 Total earned: {stats['total_earned']} rupess\n\n"
        f"💸 Referral balance: {stats['referral_balance']} rupess"
    )


def build_referral_keyboard(telegram_id: int):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("♎ Claim Balance", callback_data=f"refclaim:{telegram_id}"),
        InlineKeyboardButton("📜 Referral History", callback_data=f"refhist:{telegram_id}"),
    )
    markup.add(InlineKeyboardButton("🏆 Referral Leaderboard", callback_data=f"reflb:{telegram_id}:deposits"))
    return markup


@bot.message_handler(commands=["refer", "inv", "invite", "referral"])
def cmd_refer(message):
    ensure_user(message)
    if not is_game_enabled("referral"):
        bot.reply_to(message, "The referral system is currently disabled.")
        return
    telegram_id = message.from_user.id
    bot.reply_to(message, build_referral_text(telegram_id), reply_markup=build_referral_keyboard(telegram_id))


@bot.callback_query_handler(func=lambda call: call.data.startswith("refclaim:"))
def handle_ref_claim(call):
    telegram_id = int(call.data.split(":")[1])
    if call.from_user.id != telegram_id:
        bot.answer_callback_query(call.id, "Not your referral panel.")
        return
    amount, error = claim_referral_balance(telegram_id)
    if error:
        bot.answer_callback_query(call.id, error, show_alert=True)
        return
    new_balance = adjust_balance(telegram_id, amount)
    bot.answer_callback_query(call.id, f"Claimed {amount} coins!")
    bot.send_message(call.message.chat.id, f"✅ Claimed {amount} referral rupees!\nBalance: {new_balance}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("refhist:"))
def handle_ref_history(call):
    telegram_id = int(call.data.split(":")[1])
    if call.from_user.id != telegram_id:
        bot.answer_callback_query(call.id, "Not your referral panel.")
        return
    bot.answer_callback_query(call.id)
    history = get_referral_history(telegram_id)
    if not history:
        bot.send_message(call.message.chat.id, "No referrals yet.")
        return
    lines = [f"👤 {h.get('referred_username') or h['referred_id']} — joined {h['joined_at']}" for h in history]
    bot.send_message(call.message.chat.id, "📜 Referral History:\n" + "\n".join(lines))


@bot.callback_query_handler(func=lambda call: call.data.startswith("reflb:"))
def handle_ref_leaderboard(call):
    _, tid_str, mode = call.data.split(":")
    telegram_id = int(tid_str)
    if call.from_user.id != telegram_id:
        bot.answer_callback_query(call.id, "Not your referral panel.")
        return
    bot.answer_callback_query(call.id)

    if mode == "deposits":
        data = get_referred_deposit_totals(telegram_id)
        title = "🏆 Top depositors among your referrals:"
        next_mode, next_label = "losses", "🔻 See top losses"
    else:
        data = get_referred_loss_totals(telegram_id)
        title = "🏆 Top losses among your referrals:"
        next_mode, next_label = "deposits", "💰 See top depositors"

    if not data:
        text = title + "\nNo referrals yet."
    else:
        lines = [f"{i + 1}. {name} — {amt} coins" for i, (name, amt) in enumerate(data[:10])]
        text = title + "\n" + "\n".join(lines)

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(next_label, callback_data=f"reflb:{telegram_id}:{next_mode}"))
    bot.send_message(call.message.chat.id, text, reply_markup=markup)


# ---------- Admin: referral settings ----------
@bot.message_handler(commands=["stopreferral", "stopinvite"])
def cmd_stop_referral(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    set_game_enabled("referral", False)
    bot.reply_to(message, "⏸️ Referral system paused.")


@bot.message_handler(commands=["startreferral", "startinvite"])
def cmd_start_referral(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    set_game_enabled("referral", True)
    bot.reply_to(message, "▶️ Referral system resumed.")


@bot.message_handler(commands=["updateinviterewards"])
def cmd_update_invite_rewards(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 4:
        bot.reply_to(message, "Usage: /updateinviterewards <%deposit> <for how many deposits> <%losses>\nExample: /updateinviterewards 5 3 1")
        return
    try:
        dep_pct, dep_count, loss_pct = float(parts[1]), int(parts[2]), float(parts[3])
    except ValueError:
        bot.reply_to(message, "All three values must be numbers.")
        return
    set_referral_deposit_pct(dep_pct)
    set_referral_deposit_count(dep_count)
    set_referral_loss_pct(loss_pct)
    bot.reply_to(
        message,
        f"✅ Referral rewards updated: {dep_pct}% of first {dep_count} deposits + {loss_pct}% of every loss.",
    )
