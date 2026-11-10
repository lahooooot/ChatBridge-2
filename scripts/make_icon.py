"""Create the source-controlled ChatBridge application symbol."""
from pathlib import Path
from PIL import Image, ImageDraw
root = Path(__file__).resolve().parents[1]
image = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((4, 4, 252, 252), radius=58, fill='#141b27')
draw.rounded_rectangle((45, 64, 165, 150), radius=24, outline='#70e0c3', width=13)
draw.polygon([(62,145),(62,175),(95,148)], fill='#70e0c3')
draw.rounded_rectangle((93, 107, 213, 193), radius=24, outline='#a29cff', width=13)
draw.polygon([(166,188),(193,215),(193,187)], fill='#a29cff')
image.save(root/'icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
image.save(root/'docs/icon.png')
print(root/'icon.ico')
