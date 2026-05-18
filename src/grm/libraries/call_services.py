# import aiohttp
# from io import BytesIO
# from django.core.files.uploadedfile import InMemoryUploadedFile
# from django.http import Http404

# def convert_InMemoryUploadedFile_to_BytesIO(file):
#     if isinstance(file, InMemoryUploadedFile):
#         bytes_io = BytesIO()
#         bytes_io.write(file.read())
#         return bytes_io
#     return file

# async def upload_image(file):
#     try:
#         url = "https://dcc.coso-togo.com/attachments/upload-to-issue/"
#         headers = {"Authorization": "Bearer your_token_here"}

#         async with aiohttp.ClientSession() as session:
#             # async with session.post(url, headers=headers, data=open(file_path, 'rb')) as response:
#             async with session.post(url, headers=headers, data=convert_InMemoryUploadedFile_to_BytesIO(file)) as response:
#                 if response.status == 200:
#                     print("Image uploaded successfully")
#                 else:
#                     print(f"Error uploading image: {response.status}")
#                 return response
#     except Exception as exc:
#         return Http404

# loop = asyncio.new_event_loop()
# asyncio.set_event_loop(loop)
# loop = asyncio.get_event_loop()
# print(loop.run_until_complete(call_services.upload_image(file)))