import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from config import BOT_TOKEN, CASINO_NAME
from db import select, insert, update
from wallet import get_or_create_user, get_balance, adjust_balance, get_house_balance
from games.coinflip import play_coinflip
from games.dice import play_dice
from middleware.admin import is_admin

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def ensure_user(message: Message):
    get_or_create_user(message.from_user.id, message.from_user.username)


# ---------- Basic info commands ----------
@dp.message(Command("me", "profile"))
async def cmd_me(message: Message):
    await ensure_user(message)
    user = select("users", filters={"telegram_id": message.from_user.id}, single=True)
    await message.reply(
        f"👤 {message.from_user.username or message.from_user.first_name} — {CASINO_NAME}\n"
        f"💰 Balance: {user['balance']}\n"
        f"📊 Wagered: {user['total_wagered']}\n"
        f"✅ Won: {user['total_won']}\n"
        f"❌ Lost: {user['total_lost']}"
    )


@dp.message(Command("wallet"))
async def cmd_wallet(message: Message):
    await ensure_user(message)
    balance = get_balance(message.from_user.id)
    await message.reply(f"💰 Your balance: {balance} coins")


@dp.message(Command("depo", "withdraw"))
async def cmd_depo_withdraw(message: Message):
    await message.reply(
        f"⚠️ Deposits and withdrawals aren't available — {CASINO_NAME} runs on fun coins only, no real money."
    )


@dp.message(Command("rakeback"))
async def cmd_rakeback(message: Message):
    await ensure_user(message)
    user = select("users", filters={"telegram_id": message.from_user.id}, single=True)
    rakeback = round(float(user["total_lost"]) * 0.005, 2)
    if rakeback <= 0:
        await message.reply("No rakeback available yet — play a bit more first!")
        return
    new_balance = adjust_balance(message.from_user.id, rakeback)
    await message.reply(f"💸 Rakeback claimed: +{rakeback} coins\nBalance: {new_balance}")


@dp.message(Command("housebal", "house"))
async def cmd_housebal(message: Message):
    bal = get_house_balance()
    await message.reply(f"🏦 {CASINO_NAME} house balance: {bal} coins")


@dp.message(Command("history"))
async def cmd_history(message: Message):
    await ensure_user(message)
    bets = select(
        "bets",
        filters={"telegram_id": message.from_user.id},
        order="created_at",
        desc=True,
        limit=10,
    )
    if not bets:
        await message.reply("No bets yet.")
        return
    lines = [f"{'✅' if b['result'] == 'win' else '❌'} {b['game']} | bet {b['bet_amount']} | payout {b['payout']}" for b in bets]
    await message.reply("📜 Last 10 bets:\n" + "\n".join(lines))


@dp.message(Command("leaderboard", "ld"))
async def cmd_leaderboard(message: Message):
    top = select("users", order="total_won", desc=True, limit=10)
    lines = [f"{i+1}. {u['username'] or 'Anonymous'} — {u['total_won']} coins won" for i, u in enumerate(top)]
    await message.reply(f"🏆 {CASINO_NAME} Leaderboard:\n" + "\n".join(lines))


# ---------- Tip ----------
@dp.message(Command("tip"))
async def cmd_tip(message: Message):
    await ensure_user(message)

    if not message.reply_to_message:
        await message.reply("Reply to the user's message with /tip <amount> to send them coins.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.reply("Usage: reply to a user's message with /tip <amount>")
        return

    try:
        amount = float(parts[1])
    except ValueError:
        await message.reply("Amount must be a number.")
        return

    if amount <= 0:
        await message.reply("Amount must be positive.")
        return

    sender_id = message.from_user.id
    recipient = message.reply_to_message.from_user
    recipient_id = recipient.id

    if recipient_id == sender_id:
        await message.reply("You can't tip yourself.")
        return

    balance = get_balance(sender_id)
    if amount > balance:
        await message.reply(f"Not enough coins. Your balance: {balance}")
        return

    get_or_create_user(recipient_id, recipient.username)
    adjust_balance(sender_id, -amount)
    new_recipient_balance = adjust_balance(recipient_id, amount)

    await message.reply(
        f"🤝 {message.from_user.username or message.from_user.first_name} tipped "
        f"{recipient.username or recipient.first_name} {amount} coins!\n"
        f"Their new balance: {new_recipient_balance}"
    )


# ---------- Games ----------
@dp.message(Command("cf"))
async def cmd_cf(message: Message):
    await ensure_user(message)
    parts = message.text.split()
    if len(parts) != 3 or parts[2] not in ("heads", "tails"):
        await message.reply("Usage: /cf <amount> <heads|tails>")
        return
    try:
        bet_amount = float(parts[1])
    except ValueError:
        await message.reply("Amount must be a number.")
        return
    await play_coinflip(message, message.from_user.id, bet_amount, parts[2])


@dp.message(Command("dice", "dr"))
async def cmd_dice(message: Message):
    await ensure_user(message)
    parts = message.text.split()
    if len(parts) != 3:
        await message.reply("Usage: /dice <amount> <target 2-98>")
        return
    try:
        bet_amount = float(parts[1])
        target = float(parts[2])
    except ValueError:
        await message.reply("Amount and target must be numbers.")
        return
    await play_dice(message, message.from_user.id, bet_amount, target)


# ---------- Admin ----------
@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.reply("Usage: /add <telegram_id> <amount>")
        return
    target_id, amount = int(parts[1]), float(parts[2])
    get_or_create_user(target_id, None)
    new_balance = adjust_balance(target_id, amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "add", "target_id": target_id, "amount": amount})
    await message.reply(f"✅ Added {amount} coins to {target_id}. New balance: {new_balance}")


@dp.message(Command("deduct"))
async def cmd_deduct(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.reply("Usage: /deduct <telegram_id> <amount>")
        return
    target_id, amount = int(parts[1]), float(parts[2])
    new_balance = adjust_balance(target_id, -amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "deduct", "target_id": target_id, "amount": amount})
    await message.reply(f"✅ Deducted {amount} coins from {target_id}. New balance: {new_balance}")


@dp.message(Command("rain"))
async def cmd_rain(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.reply("Usage: /rain <amount>")
        return
    amount = float(parts[1])
    users = select("users")
    for u in users:
        adjust_balance(u["telegram_id"], amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "rain", "amount": amount})
    await message.reply(f"🌧️ Rained {amount} coins to {len(users)} users.")


@dp.message(Command("promote"))
async def cmd_promote(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.reply("Usage: /promote <telegram_id>")
        return
    target_id = int(parts[1])
    get_or_create_user(target_id, None)
    update("users", {"telegram_id": target_id}, {"is_admin": True})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "promote", "target_id": target_id})
    await message.reply(f"👑 {target_id} is now an admin.")


@dp.message(Command("updatehb"))
async def cmd_updatehb(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.reply("Usage: /updatehb <amount>")
        return
    amount = float(parts[1])
    update("house", {"id": 1}, {"balance": amount})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "updatehb", "amount": amount})
    await message.reply(f"🏦 House balance set to {amount}.")


async def main():
    print(f"{CASINO_NAME} bot running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
