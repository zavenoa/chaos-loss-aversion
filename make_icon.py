from PIL import Image
from pathlib import Path
src=Path('Images/Chaos Orb.png')
im=Image.open(src).convert('RGBA')
im.save('Images/Chaos Orb.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('Created Images/Chaos Orb.ico')
