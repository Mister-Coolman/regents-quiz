from texify.inference import batch_inference
from texify.model.model import load_model
from texify.model.processor import load_processor
from PIL import Image
import os
IMG_FOLDER="extracted_images"
filename="lattest.png"
image_path = os.path.join(IMG_FOLDER, filename)
print(image_path)
# Load Pix2Tex model
model = load_model()
processor = load_processor()
img = Image.open(image_path) # Your image name here
results = batch_inference([img], model, processor)