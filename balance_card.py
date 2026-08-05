import io
import requests
from PIL import Image, ImageDraw, ImageFont

def generate_balance_card(user_id, username, display_name, balance, casino_name="THE CASINO", avatar_url=None):
    # Dimensions & Minimalist Dark Background (#0F172A)
    width, height = 900, 450
    card = Image.new("RGBA", (width, height), (15, 23, 42))
    draw = ImageDraw.Draw(card)

    # Fonts
    try:
        font_casino = ImageFont.truetype("arialbd.ttf", 22)
        font_name = ImageFont.truetype("arialbd.ttf", 34)
        font_user = ImageFont.truetype("arial.ttf", 22)
        font_bal_label = ImageFont.truetype("arialbd.ttf", 20)
        font_bal_val = ImageFont.truetype("arialbd.ttf", 64)
    except IOError:
        font_casino = font_name = font_user = font_bal_label = font_bal_val = ImageFont.load_default()

    # --- 1. CASINO HEADER ---
    draw.text((50, 40), casino_name.upper(), font=font_casino, fill=(148, 163, 184))

    # Decorative Line
    draw.line([(50, 80), (850, 80)], fill=(30, 41, 59), width=2)

    # --- 2. USER AVATAR (Circular) ---
    avatar_x, avatar_y = 50, 110
    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=4)
            avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            avatar = avatar.resize((100, 100))
            
            mask = Image.new("L", (100, 100), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 100, 100), fill=255)
            
            card.paste(avatar, (avatar_x, avatar_y), mask)
            draw.ellipse((avatar_x-2, avatar_y-2, avatar_x+102, avatar_y+102), outline=(59, 130, 246), width=2)
        except Exception:
            pass

    # --- 3. USER NAME & HANDLE ---
    text_x = 170 if avatar_url else 50
    draw.text((text_x, 125), display_name, font=font_name, fill=(255, 255, 255))
    draw.text((text_x, 170), f"@{username}" if username else f"ID: {user_id}", font=font_user, fill=(100, 116, 139))

    # --- 4. BALANCE CARD SECTION ---
    # Minimalist Card Box Container
    draw.rounded_rectangle((50, 240, 850, 390), radius=15, fill=(30, 41, 59), outline=(51, 65, 85), width=1)

    draw.text((80, 260), "CURRENT WALLET BALANCE", font=font_bal_label, fill=(148, 163, 184))

    # Dynamic Color Check: Red if < ₹10 else Green
    balance_color = (239, 68, 68) if balance < 10.0 else (34, 197, 94)

    draw.text((80, 295), f"₹{balance:,.2f}", font=font_bal_val, fill=balance_color)

    # Output Image Bytes
    bio = io.BytesIO()
    card.save(bio, format="PNG")
    bio.seek(0)
    return bio
