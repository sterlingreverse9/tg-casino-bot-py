import asyncio
import threading
import time
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

# Permanent background event loop dedicated to userbot operations
promo_loop = asyncio.new_event_loop()


def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


loop_thread = threading.Thread(target=start_loop, args=(promo_loop,), daemon=True)
loop_thread.start()


async def init_clients():
    global clients
    accounts = get_accounts()
    clients = []
    print(f"[INIT] Loading userbot accounts from DB... (Found: {len(accounts)})")
    
    for phone, api_id, api_hash, session_str in accounts:
        try:
            cli = Client(
                f"session_{phone}",
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_str,
            )
            await cli.start()
            clients.append(cli)
            print(f"  [+] Connected userbot: {phone}")
        except Exception as e:
            print(f"  [-] Failed to start account {phone}: {e}")


def get_active_client():
    global current_client_idx
    if not clients:
        return None
    cli = clients[current_client_idx % len(clients)]
    current_client_idx += 1
    return cli


async def sync_casino_members_loop():
    while True:
        try:
            cli = get_active_client()
            if cli:
                members = []
                async for member in cli.get_chat_members("thecassinogroup"):
                    members.append(member.user.id)
                update_casino_members(members)
                print(f"[SYNC] Updated casino members: {len(members)} found.")
        except Exception as e:
            print(f"[SYNC ERROR] Casino sync error: {e}")
        await asyncio.sleep(1800)  # 30 mins


async def process_message(client, message):
    status = get_setting("promo_status", "stop")
    if status != "start":
        print(f"[SKIP] Promo engine is currently {status.upper()}. Toggle status in DM.")
        return

    user = message.from_user
    if not user or user.is_bot or user.is_self:
        return

    user_id = user.id
    can_dm, reason = can_dm_user(user_id)

    if not can_dm:
        print(f"[SKIP] User {user_id} cannot be messaged. Reason: {reason}")
        return

    msg_to_send = ""
    is_reconfirm = False

    if reason == "new":
        msg_to_send = get_setting("promote_msg", "")
    elif reason == "reconfirm":
        msg_to_send = get_setting("reconfirm_msg", "")
        is_reconfirm = True

    if not msg_to_send:
        print(f"[SKIP] No promotion message configured for reason '{reason}'.")
        return

    print(f"[ACTION] Sending DM to target user {user_id}...")

    for _ in range(len(clients)):
        active_cli = get_active_client()
        if not active_cli:
            print("[ERROR] No active clients available.")
            break
        try:
            await active_cli.send_message(user_id, msg_to_send)
            record_dm(user_id, is_reconfirm)
            print(f"  [SUCCESS] DM delivered to user {user_id}")
            break
        except errors.FloodWait as e:
            print(f"  [LIMIT] Rate limited on account. Rotating... Wait: {e.value}s")
            await asyncio.sleep(1)
            continue
        except Exception as e:
            print(f"  [FAILED] Could not send DM to {user_id}: {e}")
            break


async def group_listener(cli, msg):
    raw_groups = get_groups()
    target_groups = [g.lower().strip("@") for g in raw_groups]

    # Handle chat identification safely
    chat_username = (msg.chat.username or "").lower()
    chat_id = str(msg.chat.id)

    print(f"[EVENT] New message captured in chat: '{msg.chat.title}' (@{chat_username} / {chat_id})")

    # Check if current chat matches target groups
    if chat_username in target_groups or chat_id in target_groups:
        print(f"  [MATCH] Target group detected!")
        await process_message(cli, msg)
    else:
        print(f"  [IGNORE] Group @{chat_username} is not in target list {target_groups}")


async def _start_promo_engine_async():
    await init_clients()
    if not clients:
        print("❌ No userbot accounts loaded! Add an account using /promote in DM first.")
        return

    target_groups = get_groups()
    print(f"[INIT] Loaded target groups: {target_groups}")

    for cli in clients:
        for grp in target_groups:
            try:
                await cli.join_chat(grp)
                print(f"  [+] Account joined target group: {grp}")
            except Exception as e:
                print(f"  [-] Could not join target group {grp}: {e}")

        # Bind group handler globally to capture messages
        cli.add_handler(
            handlers.MessageHandler(group_listener, filters.group)
        )

    promo_loop.create_task(sync_casino_members_loop())
    print("🔥 Promo MTProto Userbot Engine is Running and Listening...")


def start_promo_engine():
    asyncio.run_coroutine_threadsafe(_start_promo_engine_async(), promo_loop)


if __name__ == "__main__":
    start_promo_engine()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("Engine stopped.")
