"""
CV Scanner Module - Collect CVs from multiple sources
"""
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta


def scan_outlook_folder(access_token: str, folder_name: str = "Recruitment") -> List[Dict]:
    """
    Scan Outlook folder for CV attachments using Microsoft Graph API.
    Returns list of file data dictionaries.
    """
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Get folder ID
        folders_url = 'https://graph.microsoft.com/v1.0/me/mailFolders'
        response = requests.get(folders_url, headers=headers)
        response.raise_for_status()
        folders = response.json().get('value', [])
        
        folder_id = None
        for folder in folders:
            if folder.get('displayName', '').lower() == folder_name.lower():
                folder_id = folder['id']
                break
        
        if not folder_id:
            print(f"Folder '{folder_name}' not found")
            return []
        
        # Get newest messages first (no filter to avoid API error, check hasAttachments in code)
        messages_url = f'https://graph.microsoft.com/v1.0/me/mailFolders/{folder_id}/messages?$orderby=receivedDateTime desc&$top=100&$select=id,hasAttachments,receivedDateTime'
        response = requests.get(messages_url, headers=headers)
        response.raise_for_status()
        messages = response.json().get('value', [])
        
        cv_files = []
        emails_processed = 0
        
        for message in messages:
            # Skip messages without attachments
            if not message.get('hasAttachments'):
                continue
            
            emails_processed += 1
            if emails_processed > 50:
                break
            
            # Get attachments
            attachments_url = f"https://graph.microsoft.com/v1.0/me/messages/{message['id']}/attachments"
            att_response = requests.get(attachments_url, headers=headers)
            att_response.raise_for_status()
            attachments = att_response.json().get('value', [])
            
            for att in attachments:
                filename = att.get('name', '')
                if filename.lower().endswith(('.pdf', '.docx', '.doc')):
                    cv_files.append({
                        'filename': filename,
                        'content': att.get('contentBytes'),  # Base64 encoded
                        'source': 'outlook',
                        'source_id': f"{message['id']}_{att['id']}"
                    })
        
        print(f"Found {len(cv_files)} CV files from {emails_processed} emails")
        return cv_files
        
    except Exception as e:
        print(f"Error scanning Outlook folder: {e}")
        return []


def scan_sharepoint_library(access_token: str, site_url: str, library_name: str) -> List[Dict]:
    """
    Scan SharePoint document library for CVs.
    Returns list of file data dictionaries.
    """
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Get site ID
        site_api_url = f"https://graph.microsoft.com/v1.0/sites/{site_url}"
        response = requests.get(site_api_url, headers=headers)
        response.raise_for_status()
        site_id = response.json()['id']
        
        # Get drive (library)
        drives_url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drives'
        response = requests.get(drives_url, headers=headers)
        response.raise_for_status()
        drives = response.json().get('value', [])
        
        drive_id = None
        for drive in drives:
            if library_name.lower() in drive.get('name', '').lower():
                drive_id = drive['id']
                break
        
        if not drive_id:
            print(f"Library '{library_name}' not found")
            return []
        
        # Get files
        files_url = f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children'
        response = requests.get(files_url, headers=headers)
        response.raise_for_status()
        items = response.json().get('value', [])
        
        cv_files = []
        for item in items:
            if item.get('file'):  # Is a file, not folder
                filename = item.get('name', '')
                if filename.lower().endswith(('.pdf', '.docx', '.doc')):
                    cv_files.append({
                        'filename': filename,
                        'download_url': item.get('@microsoft.graph.downloadUrl'),
                        'source': 'sharepoint',
                        'source_id': item['id']
                    })
        
        return cv_files
        
    except Exception as e:
        print(f"Error scanning SharePoint: {e}")
        return []


def scan_onedrive_folder(access_token: str, folder_path: str = "CVs") -> List[Dict]:
    """
    Scan OneDrive folder for CV files.
    Returns list of file data dictionaries.
    """
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Get the folder (or root if not specified)
        if folder_path and folder_path != "/":
            folder_url = f'https://graph.microsoft.com/v1.0/me/drive/root:/{folder_path}:/children'
        else:
            folder_url = 'https://graph.microsoft.com/v1.0/me/drive/root/children'
        
        response = requests.get(folder_url, headers=headers)
        response.raise_for_status()
        items = response.json().get('value', [])
        
        cv_files = []
        for item in items:
            if item.get('file'):  # Is a file, not folder
                filename = item.get('name', '')
                if filename.lower().endswith(('.pdf', '.docx', '.doc')):
                    cv_files.append({
                        'filename': filename,
                        'download_url': item.get('@microsoft.graph.downloadUrl'),
                        'source': 'onedrive',
                        'source_id': item['id']
                    })
        
        return cv_files
        
    except Exception as e:
        print(f"Error scanning OneDrive: {e}")
        return []


def scan_email_attachments(access_token: str, folder_name: Optional[str] = None, max_emails: int = 50) -> List[Dict]:
    """
    Scan email attachments for CVs.
    If folder_name is provided, scans that folder. Otherwise scans inbox.
    Returns list of file data dictionaries.
    """
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        if folder_name:
            # Get specific folder
            folders_url = 'https://graph.microsoft.com/v1.0/me/mailFolders'
            response = requests.get(folders_url, headers=headers)
            response.raise_for_status()
            folders = response.json().get('value', [])
            
            folder_id = None
            available_folders = []
            
            # First check top-level folders
            for folder in folders:
                folder_display = folder.get('displayName', '')
                available_folders.append(folder_display)
                if folder_display.lower() == folder_name.lower():
                    folder_id = folder['id']
                    break
            
            # If not found, check subfolders (child folders of Inbox and other main folders)
            if not folder_id:
                for folder in folders:
                    parent_id = folder['id']
                    child_url = f'https://graph.microsoft.com/v1.0/me/mailFolders/{parent_id}/childFolders'
                    try:
                        child_resp = requests.get(child_url, headers=headers)
                        if child_resp.status_code == 200:
                            child_folders = child_resp.json().get('value', [])
                            for child in child_folders:
                                child_display = child.get('displayName', '')
                                available_folders.append(f"  → {folder.get('displayName')}/{child_display}")
                                if child_display.lower() == folder_name.lower():
                                    folder_id = child['id']
                                    print(f"Found folder '{folder_name}' as subfolder of '{folder.get('displayName')}'")
                                    break
                    except:
                        pass
                    if folder_id:
                        break
            
            if not folder_id:
                print(f"Folder '{folder_name}' not found. Available folders: {available_folders}")
                return []
            
            # Get newest emails first (fetch more to account for those without attachments)
            messages_url = f'https://graph.microsoft.com/v1.0/me/mailFolders/{folder_id}/messages?$orderby=receivedDateTime desc&$top=100&$select=id,hasAttachments,receivedDateTime'
        else:
            # Scan inbox - get newest emails first
            messages_url = f'https://graph.microsoft.com/v1.0/me/messages?$orderby=receivedDateTime desc&$top=100&$select=id,hasAttachments,receivedDateTime'
        
        response = requests.get(messages_url, headers=headers)
        response.raise_for_status()
        messages = response.json().get('value', [])
        
        cv_files = []
        emails_with_attachments = 0
        
        for message in messages:
            # Skip messages without attachments
            if not message.get('hasAttachments'):
                continue
            
            emails_with_attachments += 1
            if emails_with_attachments > max_emails:
                break
            
            # Get attachments
            attachments_url = f"https://graph.microsoft.com/v1.0/me/messages/{message['id']}/attachments"
            att_response = requests.get(attachments_url, headers=headers)
            att_response.raise_for_status()
            attachments = att_response.json().get('value', [])
            
            for att in attachments:
                filename = att.get('name', '')
                if filename.lower().endswith(('.pdf', '.docx', '.doc')):
                    source_type = 'email_folder' if folder_name else 'email_inbox'
                    cv_files.append({
                        'filename': filename,
                        'content': att.get('contentBytes'),  # Base64 encoded
                        'source': source_type,
                        'source_id': f"{message['id']}_{att['id']}"
                    })
        
        print(f"Found {len(cv_files)} CV files from {emails_with_attachments} emails with attachments")
        return cv_files
        
    except Exception as e:
        print(f"Error scanning emails: {e}")
        return []


def download_file(url: str, save_path: str, access_token: Optional[str] = None) -> bool:
    """Download file from URL to local path."""
    try:
        headers = {}
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
        
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return True
    except Exception as e:
        print(f"Error downloading file: {e}")
        return False


def save_base64_file(base64_content: str, save_path: str) -> bool:
    """Save base64-encoded file content to disk."""
    try:
        import base64
        file_data = base64.b64decode(base64_content)
        with open(save_path, 'wb') as f:
            f.write(file_data)
        return True
    except Exception as e:
        print(f"Error saving base64 file: {e}")
        return False
