"""
Google Cloud Storage integration for HAI research data backup.
Automatically uploads user data folders when sessions end.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
from google.cloud import storage
from google.oauth2 import service_account

class GoogleCloudUploader:
    def __init__(self, credentials_json=None, bucket_name=None):
        """Initialize Google Cloud Storage client."""
        self.bucket_name = bucket_name or os.environ.get('GCS_BUCKET_NAME')
        self.client = None
        self.bucket = None
        
        try:
            if credentials_json:
                credentials_dict = json.loads(credentials_json)
                credentials = service_account.Credentials.from_service_account_info(credentials_dict)
                self.client = storage.Client(credentials=credentials)
            else:
                self.client = storage.Client()
            
            if self.bucket_name:
                self.bucket = self.client.bucket(self.bucket_name)
                print(f"Google Cloud Storage initialized with bucket: {self.bucket_name}")
            else:
                print("Warning: No bucket name provided for Google Cloud Storage")
                
        except Exception as e:
            print(f"Failed to initialize Google Cloud Storage: {str(e)}")
            self.client = None
            self.bucket = None
    
    def upload_folder(self, local_folder_path, cloud_folder_prefix=""):
        """Upload entire folder to Google Cloud Storage."""
        if not self.client or not self.bucket:
            print("Google Cloud Storage not initialized")
            return False, "Storage not initialized"
        
        if not os.path.exists(local_folder_path):
            print(f"Local folder does not exist: {local_folder_path}")
            return False, "Local folder not found"
        
        uploaded_files = []
        failed_files = []
        
        try:
            for root, dirs, files in os.walk(local_folder_path):
                for file in files:
                    local_file_path = os.path.join(root, file)
                    
                    relative_path = os.path.relpath(local_file_path, local_folder_path)
                    cloud_file_path = os.path.join(cloud_folder_prefix, relative_path).replace("\\", "/")
                    
                    success, message = self.upload_file(local_file_path, cloud_file_path)
                    
                    if success:
                        uploaded_files.append(cloud_file_path)
                        print(f"✅ Uploaded: {cloud_file_path}")
                    else:
                        failed_files.append(f"{local_file_path}: {message}")
                        print(f"❌ Failed: {local_file_path} - {message}")
            
            total_files = len(uploaded_files) + len(failed_files)
            success_rate = len(uploaded_files) / total_files if total_files > 0 else 0
            
            result_message = f"Upload completed: {len(uploaded_files)}/{total_files} files uploaded successfully"
            
            if failed_files:
                result_message += f". Failed files: {len(failed_files)}"
            
            return success_rate > 0.5, result_message  
            
        except Exception as e:
            error_msg = f"Error uploading folder: {str(e)}"
            print(error_msg)
            return False, error_msg
    
    def upload_file(self, local_file_path, cloud_file_path):
        """Upload a single file to Google Cloud Storage."""
        if not self.client or not self.bucket:
            return False, "Storage not initialized"
        
        try:
            blob = self.bucket.blob(cloud_file_path)
            
            with open(local_file_path, 'rb') as file:
                blob.upload_from_file(file)
            
            return True, "Upload successful"
            
        except Exception as e:
            return False, f"Upload failed: {str(e)}"
    
    def upload_text_content(self, text_content, cloud_file_path):
        """Upload text content directly to Google Cloud Storage."""
        if not self.client or not self.bucket:
            return False, "Storage not initialized"
        
        try:
            blob = self.bucket.blob(cloud_file_path)
            blob.upload_from_string(text_content, content_type='text/plain')
            return True, "Text upload successful"
            
        except Exception as e:
            return False, f"Text upload failed: {str(e)}"
    
    def list_files(self, prefix=""):
        """List files in the bucket with given prefix."""
        if not self.client or not self.bucket:
            return []
        
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
            return [blob.name for blob in blobs]
        except Exception as e:
            print(f"Error listing files: {str(e)}")
            return []

gcs_uploader = None

def get_cloud_uploader():
    """Get or create the global cloud uploader instance."""
    global gcs_uploader
    
    if gcs_uploader is None:
        credentials_json = os.environ.get('GOOGLE_CLOUD_CREDENTIALS')
        bucket_name = os.environ.get('GCS_BUCKET_NAME')
        
        if credentials_json and bucket_name:
            gcs_uploader = GoogleCloudUploader(credentials_json, bucket_name)
        else:
            print("Google Cloud Storage credentials or bucket name not configured")
            
    return gcs_uploader

def upload_user_data_to_cloud(participant_id, trial_type, user_audio_folder, version="V1", delay_seconds=5):
    """Upload user data to cloud storage after a delay (to ensure all files are written)."""
    def delayed_upload():
        try:
            time.sleep(delay_seconds)
            
            uploader = get_cloud_uploader()
            if not uploader:
                print("Cloud uploader not available")
                return
            
            participant_folder = os.path.join(user_audio_folder, str(participant_id))
            
            if not os.path.exists(participant_folder):
                print(f"Participant folder not found: {participant_folder}")
                return
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            cloud_prefix = f"hai_{version.lower()}_data/{participant_id}_{timestamp}"
            
            print(f"Starting upload of participant {participant_id} data to cloud...")
            
            success, message = uploader.upload_folder(participant_folder, cloud_prefix)
            
            if success:
                print(f"✅ Successfully uploaded data for participant {participant_id} to cloud")
            else:
                print(f"❌ Failed to upload data for participant {participant_id}: {message}")
                
        except Exception as e:
            print(f"Error in delayed cloud upload: {str(e)}")
    
    upload_thread = threading.Thread(target=delayed_upload, daemon=True)
    upload_thread.start()
