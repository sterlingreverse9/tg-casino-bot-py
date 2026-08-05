import io
import os
import requests
from PIL import Image, ImageDraw, ImageFont

# Helper function to auto-download stylish Google Font (Montserrat)
FONT_FILE = "Montserrat-Bold.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf"

def get_stylish_font(size):
    if not os.path.exists(FONT_FILE):
        try:
            r = requests.get(FONT_URL, timeout=10)
            if r.status_code == 200:
                with open(FONT_FILE, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            print(f"Font download error: {e}")

    if os.path.exists(FONT_FILE):
        try:
            return ImageFont.truetype(FONT_FILE, size)
        except Exception:
            pass

    # Fallback to system fonts if download fails
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except IOError:
        return ImageFont.load_default()


def generate_balance_card(user_id, username, display_name, balance, casino_name="THE CASINO", avatar_url=None):
    width, height = 800, 500
    card = Image.new("RGBA", (width, height), (15, 23, 42))
    draw = ImageDraw.Draw(card)

    # Load Stylish Montserrat Fonts
    font_casino = get_stylish_font(28)
    font_name = get_stylish_font(32)
    font_user = get_stylish_font(20)
    font_bal_label = get_stylish_font(20)
    font_bal_val = get_stylish_font(90)

    # --- 1. CASINO HEADER ---
    draw.text((40, 30), casino_name.upper(), font=font_casino, fill=(148, 163, 184))
    draw.line([(40, 75), (760, 75)], fill=(30, 41, 59), width=2)

    # --- 2. USER PROFILE & NAME ---
    avatar_x, avatar_y = 40, 95
    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=4)
            avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            avatar = avatar.resize((90, 90))
            
            mask = Image.new("L", (90, 90), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 90, 90), fill=255)
            
            card.paste(avatar, (avatar_x, avatar_y), mask)
            draw.ellipse((avatar_x-2, avatar_y-2, avatar_x+92, avatar_y+92), outline=(59, 130, 246), width=3)
        except Exception:
            pass

    text_x = 150 if avatar_url else 40
    clean_name = display_name.encode('ascii', 'ignore').decode('ascii').strip() or "Player"
    draw.text((text_x, 105), clean_name, font=font_name, fill=(255, 255, 255))
    draw.text((text_x, 150), f"@{username}" if username else f"ID: {user_id}", font=font_user, fill=(100, 116, 139))

    # --- 3. HUGE BALANCE SECTION ---
    draw.rounded_rectangle((40, 210, 760, 450), radius=20, fill=(30, 41, 59), outline=(51, 65, 85), width=2)

    draw.text((70, 235), "MAIN WALLET BALANCE", font=font_bal_label, fill=(148, 163, 184))

    # Dynamic Color Check: Red if < ₹10.00 else Green
    balance_color = (239, 68, 68) if balance < 10.0 else (34, 197, 94)

    formatted_bal = f"RS. {balance:,.2f}"
    draw.text((70, 280), formatted_bal, font=font_bal_val, fill=balance_color)

    # Output Image Bytes
    bio = io.BytesIO()
    card.save(bio, format="PNG")
    bio.seek(0)
    return bio
