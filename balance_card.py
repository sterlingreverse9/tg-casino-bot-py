import io
import urllib.request
from PIL import Image, ImageDraw, ImageFont


def get_font(size):
    """Attempt to load a clean TTF font available on Android/Termux, falling back to default."""
    font_paths = [
        "/system/fonts/Roboto-Bold.ttf",
        "/system/fonts/Roboto-Regular.ttf",
        "/system/fonts/DroidSans.ttf",
        "arial.ttf"
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_balance_card(user_id, username, display_name, balance, casino_name="THE CASINO", avatar_url=None):
    width, height = 900, 500
    
    # Background - Sleek Dark Navy/Slate
    card = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw = ImageDraw.Draw(card)

    # Outer Card Border & Glow Frame
    draw.rounded_rectangle([15, 15, width - 15, height - 15], radius=24, outline=(59, 130, 246), width=3)
    draw.rounded_rectangle([25, 25, width - 25, height - 25], radius=20, fill=(30, 41, 59))

    # Fonts
    font_header = get_font(22)
    font_title = get_font(34)
    font_sub = get_font(22)
    font_label = get_font(20)
    font_bal = get_font(52)

    # Top Bar - Casino Branding
    brand_text = f"🎰 {casino_name.upper()}"
    draw.text((50, 45), brand_text, fill=(148, 163, 184), font=font_header)

    # Avatar Handling
    avatar_size = 110
    avatar_x, avatar_y = 50, 95
    
    avatar_loaded = False
    if avatar_url:
        try:
            req = urllib.request.Request(avatar_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3) as response:
                avatar_data = response.read()
            avatar_img = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
            avatar_img = avatar_img.resize((avatar_size, avatar_size))
            
            # Mask for rounded avatar
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            
            card.paste(avatar_img, (avatar_x, avatar_y), mask)
            avatar_loaded = True
        except Exception as err:
            print(f"⚠️ Avatar download skipped: {err}")

    if not avatar_loaded:
        # Placeholder Circular Avatar
        draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(51, 65, 85), outline=(94, 234, 212), width=2)
        initial = (display_name or "P")[0].upper()
        draw.text((avatar_x + 40, avatar_y + 30), initial, fill=(255, 255, 255), font=font_title)

    # User Info Block
    name_str = (display_name[:18] + '...') if len(display_name or '') > 18 else (display_name or "Player")
    user_str = f"@{username}" if username else f"ID: {user_id}"

    draw.text((185, 105), name_str, fill=(255, 255, 255), font=font_title)
    draw.text((185, 155), user_str, fill=(148, 163, 184), font=font_sub)

    # Balance Display Inner Container
    box_top, box_bottom = 230, 440
    draw.rounded_rectangle([50, box_top, width - 50, box_bottom], radius=16, fill=(15, 23, 42), outline=(71, 85, 105), width=2)

    # Balance Labels
    draw.text((80, box_top + 30), "MAIN WALLET BALANCE", fill=(148, 163, 184), font=font_label)
    
    # Large Emerald Green Balance Text
    formatted_bal = f"₹ {balance:,.2f}"
    draw.text((80, box_top + 80), formatted_bal, fill=(34, 197, 94), font=font_bal)

    # Output to JPEG/PNG bytes
    output = io.BytesIO()
    card.convert("RGB").save(output, format="PNG", quality=95)
    output.seek(0)
    return output.getvalue()
