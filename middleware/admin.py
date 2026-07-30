# admin permission check
from db import supabase


def is_admin(telegram_id: int) -> bool:
    result = supabase.table("users").select("is_admin").eq("telegram_id", telegram_id).execute()
    return bool(result.data and result.data[0]["is_admin"])