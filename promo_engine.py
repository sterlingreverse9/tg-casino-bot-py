import asyncio
import threading
from pyrogram import Client, filters, handlers, errors
from promo_db import (
    get_accounts,
    get_groups,
    get_setting,
    can_dm_user,
    record_dm,
    update_casino_members,
)

clients = []
current_client_idx = 0

# Permanent background loop thread for Pyrogram
promo_loop = asyncio.new_event_loop()


def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


loop_thread = threading.Thread(target=_start_loop, args=(promo_loop,), daemon=True)
loop_thread.start()


async def init_clients():
    global clients
    accounts = get_accounts()
    clients = []
    print(f"\n[PROMO ENGINE] Loading accounts... Found {len(accounts)}")

    for phone, api_id, api_hash, session_str in accounts:
        try:
            cli = Client(
                f"session_{phone.replace('+', '')}",
                api_id=int(api_id),
                api_hash=api_hash,
                session_string=session_str,
            )
            await cli.start()
            clients.append(cli)
            print(f"  [+] Active Userbot: {phone}")
        except Exception as e:
            print(f"  [-] Account {phone} failed to start: {e}")


def get_active_client():
    global current_client_idx
    if not clients:
        return None
    cli = clients[current_client_idx % len(clients)]
    current_client_idx += 1
    return cli


async def process_message(client, message):
    status = get_setting("promo_status", "stop")
    if status != "start":
        print(f"[ENGINE] Skipped message: Status is set to '{status.upper()}' (Enable in DM)")
        return

    user = message.from_user
    if not user or user.is_bot or user.is_self:
        return

    user_id = user.id
    can_dm, reason = can_dm_user(user_id)

    if not can_dm:
        print(f"[ENGINE] User {user_id} skipped. Reason: {reason}")
        return

    msg_to_send = ""
    is_reconfirm = False

    if reason == "new":
        msg_to_send = get_setting("promote_msg", "")
    elif reason == "reconfirm":
        msg_to_send = get_setting("reconfirm_msg", "")
        is_reconfirm = True

    if not msg_to_send:
        print(f"[ENGINE] Skipped: No message configured for '{reason}'.")
        return

    print(f"[ENGINE] Attempting DM to user {user_id}...")

    for _ in range(len(clients)):
        active_cli = get_active_client()
        if not active_cli:
            break
        try:
            await active_cli.send_message(user_id, msg_to_send)
            record_dm(user_id, is_reconfirm)
            print(f"  [SUCCESS] Message sent to {user_id}")
            break
        except errors.FloodWait as e:
            print(f"  [WAIT] FloodWait on account: {e.value}s. Rotating...")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"  [FAILED] Send failed for {user_id}: {e}")
            break


async def group_listener(cli, msg):
    raw_groups = get_groups()
    target_groups = [g.lower().strip("@") for g in raw_groups]

    chat_username = (msg.chat.username or "").lower()
    chat_id = str(msg.chat.id)

    print(f"\n[MSG CAPTURED] Chat: '{msg.chat.title}' (@{chat_username} | ID: {chat_id})")

    # Match username or channel ID against target list
    if chat_username in target_groups or chat_id in target_groups or chat_id.replace("-100", "") in target_groups:
        print("  --> Target group match! Processing promo pipeline...")
        await process_message(cli, msg)
    else:
        print(f"  --> Not in target list: {target_groups}")


async def _start_promo_engine_async():
    await init_clients()
    if not clients:
        print("[PROMO ENGINE] ❌ No userbot accounts found. Add one in Telegram DM using /promote.")
        return

    target_groups = get_groups()
    print(f"[PROMO ENGINE] Target Scraper Groups: {target_groups}")

    for cli in clients:
        for grp in target_groups:
            try:
                await cli.join_chat(grp)
                print(f"  [+] Joined target group: {grp}")
            except Exception:
                pass

        cli.add_handler(handlers.MessageHandler(group_listener, filters.group))

    print("🔥 PROMO ENGINE IS FULLY ONLINE & LISTENING 🔥\n")


def start_promo_engine():
    """Call this function inside main.py to fire up the engine."""
    asyncio.run_coroutine_threadsafe(_start_promo_engine_async(), promo_loop)
