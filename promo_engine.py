import asyncio

# Fix Python 3.14 missing event loop error on Pyrogram import
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import time
from pyrogram import Client, filters, errors
from promo_db import get_accounts, get_groups, get_setting, can_dm_user, record_dm, update_casino_members

clients = []
current_client_idx = 0

async def init_clients():
    global clients
    accounts = get_accounts()
    clients = []
    for phone, api_id, api_hash, session_str in accounts:
        try:
            cli = Client(f"session_{phone}", api_id=api_id, api_hash=api_hash, session_string=session_str)
            await cli.start()
            clients.append(cli)
        except Exception as e:
            print(f"Failed to start account {phone}: {e}")

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
        except Exception as e:
            print(f"Casino sync error: {e}")
        await asyncio.sleep(1800) # 30 mins

async def process_message(client, message):
    if get_setting("promo_status", "stop") != "start":
        return

    user = message.from_user
    if not user or user.is_bot or user.is_self:
        return

    user_id = user.id
    can_dm, reason = can_dm_user(user_id)

    if not can_dm:
        return

    msg_to_send = ""
    is_reconfirm = False

    if reason == "new":
        msg_to_send = get_setting("promote_msg", "")
    elif reason == "reconfirm":
        msg_to_send = get_setting("reconfirm_msg", "")
        is_reconfirm = True

    if not msg_to_send:
        return

    for _ in range(len(clients)):
        active_cli = get_active_client()
        if not active_cli:
            break
        try:
            await active_cli.send_message(user_id, msg_to_send)
            record_dm(user_id, is_reconfirm)
            break
        except errors.FloodWait as e:
            print(f"Rate limited. Rotating account... Waiting {e.value}s on this instance.")
            await asyncio.sleep(1)
            continue
        except Exception as e:
            print(f"Failed to DM {user_id}: {e}")
            break

async def start_promo_engine():
    await init_clients()
    if not clients:
        print("No userbot accounts loaded. Add an account using /promote in DM first.")
        return

    asyncio.create_task(sync_casino_members_loop())

    target_groups = get_groups()
    for cli in clients:
        for grp in target_groups:
            try:
                await cli.join_chat(grp)
            except Exception:
                pass

    @Client.on_message(filters.group)
    async def group_listener(cli, msg):
        target_groups = get_groups()
        if msg.chat.username and msg.chat.username.lower() in target_groups:
            await process_message(cli, msg)

    print("🔥 Promo MTProto Userbot Engine is Running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_promo_engine())
