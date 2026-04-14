"""Debug script to test Google Drive folder listing."""
from app.services.google_drive import parse_drive_folder_url, list_images_in_folder, get_folder_name, _get_drive_service

url = "https://drive.google.com/drive/folders/1IB0PcePizHyGO0o_fWATwva1Sn6kLFr4?usp=drive_link"
parsed = parse_drive_folder_url(url)
folder_id = parsed["folder_id"]
print(f"Folder ID: {folder_id}")

service = _get_drive_service()

# Get folder name
try:
    folder_name = get_folder_name(folder_id)
    print(f"Folder name: {folder_name}")
except Exception as e:
    print(f"ERROR getting folder name: {e}")

# List ALL files without MIME filter
print("\n--- ALL files (no MIME filter) ---")
try:
    query = f"'{folder_id}' in parents and trashed = false"
    response = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size)",
        pageSize=50,
    ).execute()
    files = response.get("files", [])
    print(f"Total files: {len(files)}")
    for f in files:
        print(f"  - {f['name']} | MIME: {f.get('mimeType', '?')} | Size: {f.get('size', '?')}")
except Exception as e:
    print(f"ERROR listing all files: {e}")

# List with image MIME filter
print("\n--- Image files (with MIME filter) ---")
try:
    images = list_images_in_folder(folder_id)
    print(f"Image files: {len(images)}")
    for f in images:
        print(f"  - {f['name']} | MIME: {f.get('mimeType', '?')}")
except Exception as e:
    print(f"ERROR listing images: {e}")
