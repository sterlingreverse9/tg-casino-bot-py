from db import select, insert


def record_chat(chat_id, chat_type, title):
    existing = select("chats", filters={"chat_id": chat_id}, single=True)
    if existing is None:
        insert("chats", {"chat_id": chat_id, "chat_type": chat_type, "title": title})


def get_all_group_chat_ids():
    chats = select("chats")
    return [int(c["chat_id"]) for c in chats]


def get_all_chats():
    return select("chats")
