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

# Permanent background event loop dedicated to Pyrogram calls
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


def get_next_client():
    """Gets the next account in round-robin sequence (loops back to 1st after last)."""
    global current_client_idx
    if not clients:
        return None
    
    # Simple modulo ensures infinite round-robin looping across all loaded accounts
    cli = clients[current_client_idx % len(clients)]
    current_client_idx = (current_client_idx + 1) % len(clients)
    return cli


async def ensure_group_joined(chat_identifier):
    """Ensures all active clients have joined the target group."""
    for cli in clients:
        try:
            await cli.join_chat(chat_identifier)
            print(f"  [AUTO-JOIN] Account successfully joined group: {chat_identifier}")
        except errors.UserAlreadyParticipant:
            pass
        except Exception as e:
            print(f"  [AUTO-JOIN FAIL] Could not join {chat_identifier}: {e}")


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

    # Fetch custom delay set by user (Default: 10 seconds)
    try:
        dm_delay = int(get_setting("dm_delay", "10"))
    except ValueError:
        dm_delay = 10

    print(f"[ENGINE] Attempting DM to user {user_id}...")

    # Iterate through available accounts. Round-robin guarantees looping back to 1st.
    attempts = 0
    total_accounts = len(clients)

    while attempts < total_accounts:
        active_cli = get_next_client()
        if not active_cli:
            print("[ENGINE] ❌ No active accounts available.")
            break

        attempts += 1
        try:
            await active_cli.send_message(user_id, msg_to_send)
            record_dm(user_id, is_reconfirm)
            print(f"  [SUCCESS] Message delivered to {user_id} using {active_cli.name}")
            
            # Apply configured delay between DM attempts to prevent account bans
            if dm_delay > 0:
                print(f"  [DELAY] Waiting {dm_delay}s before processing next DM...")
                await asyncio.sleep(dm_delay)
            break

        except errors.PeerFlood:
            print(f"  [PEER_FLOOD] {active_cli.name} is spam-restricted! Switching to next account...")
            # Continue loop -> gets next client in round-robin automatically
            continue

        except errors.FloodWait as e:
            print(f"  [FLOOD_WAIT] Limit hit on {active_cli.name}. Waiting {e.value}s... Switching account...")
            await asyncio.sleep(1)
            continue

        except Exception as e:
            print(f"  [FAILED] Could not send DM using {active_cli.name}: {e}")
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

    # Auto-join all added target groups across all connected userbots
    for grp in target_groups:
        await ensure_group_joined(grp)

    # Attach group handler
    for cli in clients:
        cli.add_handler(handlers.MessageHandler(group_listener, filters.group))

    print("🔥 PROMO ENGINE IS FULLY ONLINE & LISTENING 🔥\n")


def start_promo_engine():
    """Call this function inside main.py to fire up the engine."""
    asyncio.run_coroutine_threadsafe(_start_promo_engine_async(), promo_loop)
