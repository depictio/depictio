import sys
from PIL import Image, ImageSequence
import os
import os.path
import glob
# input_dir = sys.argv[1]
input_dir = "/Users/tweber/Gits/depictio/dev/graph-globe/assets/images/TIF"
files = glob.glob(input_dir + "/*.tif")

for file in files:
    filename_ext = os.path.basename(file)
    filename = os.path.splitext(filename_ext)[0]
    try:
        im = Image.open(file)
        for i, page in enumerate(ImageSequence.Iterator(im)):
            path = input_dir.replace("TIF", "PNG") + filename + "-"+str(i+1)+".png"        
            if not os.path.isfile(path):
                try:
                    page.save(path)
                except:
                    print(filename_ext)        
    except:
        print(filename_ext)
