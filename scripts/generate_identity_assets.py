"""Script to generate identity assets for DukaPulse:
- favicon.svg
- favicon.ico (16x16, 32x32, 48x48)
- apple-touch-icon.png (180x180)
- og-image.png (1200x630)
- github-social-preview.png (1280x640)
"""

import os

from PIL import Image, ImageDraw, ImageFont

STATIC_DIR = r"D:\MASTERY\DukaPulse\dukapulse\api\static\kiosk"
ASSETS_SRC_DIR = r"D:\MASTERY\DukaPulse\assets-src"

def draw_dukapulse_mark(size: int = 512, rounded_radius: int = 96) -> Image.Image:
    """Draw high-resolution DukaPulse icon using supersampling for ultra-smooth edges."""
    scale = 4
    w = size * scale
    r = rounded_radius * scale
    
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Background rounded rect (Slate 900 #0f172a)
    draw.rounded_rectangle([0, 0, w, w], radius=r, fill=(15, 23, 42, 255))
    
    # Scale from 32x32 to w
    s = w / 32.0
    
    # Roof: (5, 13) -> (16, 4) -> (27, 13)
    roof_pts = [(5 * s, 13 * s), (16 * s, 4 * s), (27 * s, 13 * s)]
    draw.line(roof_pts, fill=(248, 250, 252, 255), width=int(1.8 * s), joint="round")
    
    # Storefront walls: (8, 13) -> (8, 25) -> (24, 25) -> (24, 13)
    wall_pts = [(8 * s, 13 * s), (8 * s, 25 * s), (24 * s, 25 * s), (24 * s, 13 * s)]
    draw.line(wall_pts, fill=(248, 250, 252, 255), width=int(1.8 * s), joint="round")
    
    # Canopy line: (6, 15) -> (26, 15)
    draw.line([(6 * s, 15 * s), (26 * s, 15 * s)], fill=(148, 163, 184, 255), width=int(1.2 * s))
    
    # Telemetry pulse wave: (3, 20) -> (9, 20) -> (12.5, 13) -> (16, 26) -> (19.5, 16) -> (22.5, 20) -> (29, 20)
    pulse_pts = [
        (3.0 * s, 20.0 * s),
        (9.0 * s, 20.0 * s),
        (12.5 * s, 13.0 * s),
        (16.0 * s, 26.0 * s),
        (19.5 * s, 16.0 * s),
        (22.5 * s, 20.0 * s),
        (29.0 * s, 20.0 * s),
    ]
    draw.line(pulse_pts, fill=(16, 185, 129, 255), width=int(2.2 * s), joint="round")
    
    # Downsample with Lanczos filter for superior antialiasing
    return img.resize((size, size), Image.Resampling.LANCZOS)

def generate_favicons():
    # 1. 180x180 Apple Touch Icon
    apple_icon = draw_dukapulse_mark(180, rounded_radius=32)
    apple_path = os.path.join(STATIC_DIR, "apple-touch-icon.png")
    apple_icon.save(apple_path, format="PNG")
    print(f"Generated {apple_path} ({os.path.getsize(apple_path)/1024:.1f} KB)")
    
    # 2. Multi-size favicon.ico (16, 32, 48)
    ico_img = draw_dukapulse_mark(256, rounded_radius=40)
    ico_path = os.path.join(STATIC_DIR, "favicon.ico")
    ico_img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"Generated {ico_path} ({os.path.getsize(ico_path)/1024:.1f} KB)")

def generate_og_image():
    """Generate 1200x630 OpenGraph card featuring race panel and verified telemetry."""
    W, H = 1200, 630
    card = Image.new("RGB", (W, H), color=(15, 23, 42)) # Deep slate #0f172a
    draw = ImageDraw.Draw(card)
    
    # Subtle grid accent lines
    for x in range(0, W, 60):
        draw.line([(x, 0), (x, H)], fill=(30, 41, 59), width=1)
    for y in range(0, H, 60):
        draw.line([(0, y), (W, y)], fill=(30, 41, 59), width=1)
        
    # Top brand bar
    icon = draw_dukapulse_mark(56, rounded_radius=12)
    card.paste(icon, (50, 40), icon)
    
    try:
        font_brand = ImageFont.truetype("arialbd.ttf", 32)
        font_sub = ImageFont.truetype("arial.ttf", 16)
        font_badge = ImageFont.truetype("arialbd.ttf", 13)
        font_receipt = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font_brand = font_sub = font_badge = font_receipt = ImageFont.load_default()
        
    draw.text((120, 42), "DUKAPULSE", fill=(248, 250, 252), font=font_brand)
    draw.text((120, 78), "Micro-Retail POS & Concurrency Guard for African Neighborhood Dukas", fill=(148, 163, 184), font=font_sub)
    
    # Badges on top right
    badges = ["Tiger Data Hypertables", "FastEmbed ONNX", "PostgreSQL Row-Locks"]
    badge_x = W - 50
    for b in reversed(badges):
        bbox = draw.textbbox((0, 0), b, font=font_badge)
        bw = bbox[2] - bbox[0] + 24
        bh = 32
        bx = badge_x - bw
        draw.rounded_rectangle([bx, 50, bx + bw, 50 + bh], radius=6, fill=(30, 41, 59), outline=(51, 65, 85), width=1)
        draw.text((bx + 12, 58), b, fill=(226, 232, 240), font=font_badge)
        badge_x = bx - 12
        
    # Divider line
    draw.line([(50, 115), (W - 50, 115)], fill=(51, 65, 85), width=1)
    
    # Main hero image: crop and embed the concurrency race capture
    race_path = os.path.join(ASSETS_SRC_DIR, "03_concurrency_race_panel.png")
    if os.path.exists(race_path):
        race_img = Image.open(race_path)
        # Crop to the active race panel region
        # 1440x900 -> panel is centered from ~180 to ~1240 horizontally, ~250 to ~650 vertically
        cropped = race_img.crop((160, 240, 1280, 680))
        # Scale to fit nicely: width 1100, height 400
        target_w = 1100
        target_h = int(cropped.height * (target_w / cropped.width))
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        # Border around embed
        embed_x = (W - target_w) // 2
        embed_y = 135
        draw.rounded_rectangle([embed_x - 2, embed_y - 2, embed_x + target_w + 2, embed_y + target_h + 2], radius=8, outline=(71, 85, 105), width=1)
        card.paste(resized, (embed_x, embed_y))
        
    # Footer receipt bar
    footer_y = H - 55
    draw.line([(50, footer_y - 12), (W - 50, footer_y - 12)], fill=(51, 65, 85), width=1)
    draw.text((50, footer_y), "Stress Tested in CI: 16 threads race 10,000 purchase attempts for 1 stock unit -> exactly 1 success, 9,999 blocked, zero oversell.", fill=(52, 211, 153), font=font_receipt)
    draw.text((W - 350, footer_y), "https://dukapulse-kiosk.onrender.com", fill=(148, 163, 184), font=font_receipt)
    
    # Save OG image (target <= 500 KB)
    og_path = os.path.join(STATIC_DIR, "og-image.png")
    card.save(og_path, format="PNG", optimize=True)
    size_kb = os.path.getsize(og_path) / 1024
    print(f"Generated {og_path} ({size_kb:.1f} KB - target <= 500 KB)")
    
    # Also save to assets-src for portfolio and GitHub preview
    social_preview = card.resize((1280, 640), Image.Resampling.LANCZOS)
    gh_path = os.path.join(ASSETS_SRC_DIR, "github-social-preview.png")
    social_preview.save(gh_path, format="PNG", optimize=True)
    print(f"Generated {gh_path} ({os.path.getsize(gh_path)/1024:.1f} KB)")

if __name__ == "__main__":
    generate_favicons()
    generate_og_image()
