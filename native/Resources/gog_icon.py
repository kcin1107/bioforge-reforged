"""Makes the app icon from the GOG release's icon (goggame-*.ico, a glowing robotic hand in a silver ring; the 1995 DOS game has none).

    re/.venv/bin/python -I native/Resources/gog_icon.py GOGGAME.ico OUT.png

Called by build-app.sh when the game folder has the file, so GOG's artwork never goes into the repository; without it the app keeps
AppIcon.png. The 256 px picture loses the silver ring (macOS draws icons as rounded squares and would box a round one in grey), its
dark disc is enlarged to 1024 px (Lanczos) and blended into the same dark colour out to the corners."""
import sys

from PIL import Image, ImageDraw, ImageFilter

N = 1024
CENTRE, RADIUS = 128, 100                # the ring ends 19 px in from the edge; 100 keeps clear of its shading
EDGE = (6, 6, 5)                         # the disc's colour just inside the ring


def main(ico, out):
    im = Image.open(ico)
    im.size = max(im.info['sizes'])
    im = im.convert('RGB')
    disc = im.crop((CENTRE - RADIUS, CENTRE - RADIUS, CENTRE + RADIUS, CENTRE + RADIUS)).resize((N, N), Image.LANCZOS)
    mask = Image.new('L', (N, N), 0)
    ImageDraw.Draw(mask).ellipse([40, 40, N - 40, N - 40], fill=255)
    Image.composite(disc, Image.new('RGB', (N, N), EDGE), mask.filter(ImageFilter.GaussianBlur(40))).save(out)


if __name__ == '__main__':
    main(*sys.argv[1:3])
