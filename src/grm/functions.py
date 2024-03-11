from PIL import Image, ImageFilter
from io import BytesIO
import gzip

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile

def compress_image(image: InMemoryUploadedFile, target_size_mb: float = 1) -> InMemoryUploadedFile:
    # Open the image using Pillow
    img = Image.open(image)

    # width, height = img.size
    
    # # Perform compression or resizing operations as needed
    # # Example: Resize the image to a maximum width or height of 800 pixels
    # max_size = (width, height)
    # img.thumbnail(max_size)

    # # Save the compressed image to a BytesIO buffer
    # buffer = BytesIO()
    # img.save(buffer, format='JPEG')  # You can change the format as needed
    
    
    # Convert target size from MB to bytes
    target_size_bytes = target_size_mb * 1024 * 1024

    # Initial guess for dimensions (you may adjust these values based on your needs)
    width, height = img.size
    target_width = width
    target_height = height

    # Iteratively adjust dimensions to achieve target file size
    while True:
        # Resize the image to the current dimensions
        img_resized = img.resize((target_width, target_height), Image.LANCZOS)

        # Save the resized image to a BytesIO buffer
        buffer = BytesIO()
        img_resized.save(buffer, format='JPEG')  # You can change the format as needed

        # Check the size of the resized image
        current_size_bytes = buffer.tell()

        # If the current size is close to the target size, break the loop
        if abs(current_size_bytes - target_size_bytes) < 1024:  # Adjust the tolerance as needed
            break

        # Adjust dimensions based on the difference
        scale_factor = (target_size_bytes / current_size_bytes) ** 0.5
        target_width = int(target_width * scale_factor)
        target_height = int(target_height * scale_factor)
        

    # Create an InMemoryUploadedFile from the buffer
    image_file = InMemoryUploadedFile(
        buffer,
        None,
        image.name,  # Specify the file name
        'image/jpeg',  # Specify the content type
        buffer.tell,
        None
    )

    return image_file



def compress_file(file_content, target_size_mb: float=1):
    # # Compress the file content using gzip
    # compressed_content = gzip.compress(file_content)

    # # Create a ContentFile from the compressed content
    # compressed_file = ContentFile(compressed_content)

    # return compressed_file
    
    # Convert target size from MB to bytes
    target_size_bytes = target_size_mb * 1024 * 1024

    # Initial guess for compression quality (you may adjust this based on your needs)
    compression_quality = 9

    # Iteratively adjust compression quality to achieve target file size
    while True:
        print(compression_quality)
        # Compress the file content using gzip
        compressed_content = gzip.compress(file_content, compresslevel=compression_quality)

        # Create a ContentFile from the compressed content
        compressed_file = ContentFile(compressed_content)

        # Check the size of the compressed file
        current_size_bytes = len(compressed_content)

        # If the current size is close to the target size, break the loop
        if abs(current_size_bytes - target_size_bytes) < 1024 or compression_quality < 1 or compression_quality >= 9:  # Adjust the tolerance as needed
            break
        
        print(current_size_bytes, target_size_bytes)
        # Adjust compression quality based on the difference
        if current_size_bytes > target_size_bytes:
            compression_quality += 1
        else:
            break

    return compressed_file
