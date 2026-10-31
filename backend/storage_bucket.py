# import os
# from google.cloud import storage
# from dotenv import load_dotenv,find_dotenv

# load_dotenv(find_dotenv())

# project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
# bucket_name = os.getenv("GCS_BUCKET_NAME")

# if not project_id:
#     raise ValueError("GOOGLE_CLOUD_PROJECT is missing")

# if not bucket_name:
#     raise ValueError("GCS_BUCKET_NAME is missing")

# client = storage.Client(project=project_id)
# bucket = client.bucket(bucket_name)

# try:
#     bucket.reload()

#     print("✅ Bucket access works")
#     print("Bucket:", bucket.name)
#     print("Project:", project_id)
#     print("Location:", bucket.location)

# except Exception as error:
#     print(type(error).__name__)
#     print(error) 

import os
from google.cloud import storage
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
bucket_name = os.getenv("GCS_BUCKET_NAME")

if not project_id:
    raise ValueError("GOOGLE_CLOUD_PROJECT is missing")

if not bucket_name:
    raise ValueError("GCS_BUCKET_NAME is missing")

client = storage.Client(project=project_id)
bucket = client.bucket(bucket_name)

try:
    bucket.reload()

    print("✅ Bucket access works")
    print("Bucket:", bucket.name)
    print("Project:", project_id)  # Fixed attribute error
    print("Location:", bucket.location)

    # --- Test Writing a File ---
    blob = bucket.blob("test.txt")
    blob.upload_from_string("Hello from Sanat's backend script! Storage is working.")
    print("✅ Successfully wrote 'test.txt' to the bucket!")

except Exception as error:
    print(type(error).__name__)
    print(error)