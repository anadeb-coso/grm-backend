from PIL import Image
from io import BytesIO
from django.core.files import File

def reduce_image_size(profile_pic):
    print(profile_pic)
    img = Image.open(profile_pic)
    thumb_io = BytesIO()
    img.save(thumb_io, 'jpeg', quality=50)
    new_image = File(thumb_io, name=profile_pic.name)
    return new_image

