"""
ATS Agent Celery Tasks
"""
from celery_worker import celery
from models import db, ATSAgentConfig, CVCandidate, ATSScanHistory, UserSettings
from agents.ats_agent.scanner import scan_onedrive_folder, scan_email_attachments, scan_sharepoint_library, download_file, save_base64_file
from agents.ats_agent.parser import extract_text_from_cv, parse_cv_basic_info
from agents.ats_agent.filters import apply_hard_filters
from agents.ats_agent.scorer import score_cv_with_openai, calculate_weighted_score
from datetime import datetime
from werkzeug.utils import secure_filename
import os


UPLOAD_FOLDER = 'static/uploads/cvs'


@celery.task(name='ats_agent.scheduled_scan')
def scheduled_ats_scan():
    """
    Scheduled task to scan for CVs from all configured sources and process them.
    Runs for all users who have ATS agent enabled.
    """
    from app import create_app
    app = create_app()
    
    with app.app_context():
        # Get all users with ATS enabled
        configs = ATSAgentConfig.query.filter_by(is_enabled=True).all()
        
        for config in configs:
            try:
                process_ats_scan(config.user_id)
            except Exception as e:
                print(f"Error processing ATS scan for user {config.user_id}: {e}")


@celery.task(name='ats_agent.process_scan')
def process_ats_scan(user_id):
    """Process ATS scan for a specific user (Celery background task)."""
    from app import create_app
    app = create_app('production')
    
    with app.app_context():
        config = ATSAgentConfig.query.filter_by(user_id=user_id).first()
        if not config or not config.is_enabled:
            return
        
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        if not settings or not settings.openai_api_key:
            return
        
        # Get valid access token (refresh if needed)
        access_token = None
        if settings.ms_access_token:
            from utils.ms_auth import get_valid_access_token
            access_token = get_valid_access_token(settings, db)
            if not access_token:
                print(f"Failed to get valid access token for user {user_id}")
                return

        
        # Create scan history record
        scan = ATSScanHistory(user_id=user_id, status='running')
        db.session.add(scan)
        db.session.commit()
        
        try:
            cv_files = []
            
            # Scan OneDrive
            if config.onedrive_enabled and access_token:
                onedrive_cvs = scan_onedrive_folder(access_token, config.onedrive_folder_path)
                cv_files.extend(onedrive_cvs)
            
            # Scan Email Inbox
            if config.email_inbox_enabled and access_token:
                inbox_cvs = scan_email_attachments(access_token, folder_name=None)
                cv_files.extend(inbox_cvs)
            
            # Scan Email Folder
            if config.email_folder_enabled and access_token:
                folder_cvs = scan_email_attachments(access_token, config.email_folder_name)
                cv_files.extend(folder_cvs)
            
            # Scan SharePoint
            if config.sharepoint_enabled and config.sharepoint_site_url and access_token:
                sp_cvs = scan_sharepoint_library(
                    access_token,
                    config.sharepoint_site_url,
                    config.sharepoint_library
                )
                cv_files.extend(sp_cvs)
            
            scan.total_cvs_found = len(cv_files)
            
            processed = 0
            scored = 0
            filtered = 0
            
            # Process each CV
            for cv_file in cv_files:
                # Skip if already processed
                existing = CVCandidate.query.filter_by(
                    user_id=user_id,
                    source_file_id=cv_file['source_id']
                ).first()
                if existing:
                    continue
                
                # Download/save file
                filename = secure_filename(cv_file['filename'])
                filepath = os.path.join(UPLOAD_FOLDER, f"{user_id}_{datetime.now().timestamp()}_{filename}")
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                
                if cv_file.get('download_url'):
                    download_file(cv_file['download_url'], filepath, access_token)
                elif cv_file.get('content'):
                    save_base64_file(cv_file['content'], filepath)
                
                # Parse CV
                cv_text = extract_text_from_cv(filepath)
                if not cv_text:
                    continue
                
                # Sanitize CV text - remove NUL bytes that PostgreSQL doesn't accept
                cv_text = cv_text.replace('\x00', '').replace('\0', '')
                
                basic_info = parse_cv_basic_info(cv_text)
                
                # Skip if candidate with same email already exists (deduplication)
                candidate_email = basic_info.get('email')
                if candidate_email:
                    existing_by_email = CVCandidate.query.filter_by(
                        user_id=user_id,
                        email=candidate_email
                    ).first()
                    if existing_by_email:
                        print(f"Skipping duplicate candidate: {candidate_email}")
                        continue

                
                # Create candidate record
                candidate = CVCandidate(
                    user_id=user_id,
                    cv_text=cv_text,
                    cv_file_path=filepath,
                    cv_source=cv_file['source'],
                    source_file_id=cv_file['source_id'],
                    source_file_name=cv_file['filename'],
                    full_name=basic_info.get('name'),
                    email=basic_info.get('email'),
                    phone=basic_info.get('phone'),
                    linkedin_url=basic_info.get('linkedin_url')
                )
                
                # Apply hard filters
                filter_config = {
                    'allowed_locations': config.allowed_locations,
                    'min_experience': config.min_experience,
                    'max_experience': config.max_experience,
                    'must_have_skills': config.must_have_skills
                }
                
                passed, reasons = apply_hard_filters({'cv_text': cv_text}, filter_config)
                
                if not passed:
                    candidate.status = 'filtered_out'
                    filtered += 1
                else:
                    # Score with OpenAI
                    job_config = {
                        'job_title': config.job_title,
                        'job_description': config.job_description,
                        'required_skills': config.required_skills
                    }
                    
                    score_result = score_cv_with_openai(
                        {'cv_text': cv_text},
                        job_config,
                        settings.openai_api_key
                    )
                    
                    if score_result:
                        # Update candidate with scores
                        candidate.skills_score = score_result.get('skills_score')
                        candidate.skills_reasoning = score_result.get('skills_reasoning')
                        candidate.title_score = score_result.get('title_score')
                        candidate.title_reasoning = score_result.get('title_reasoning')
                        candidate.experience_score = score_result.get('experience_score')
                        candidate.experience_reasoning = score_result.get('experience_reasoning')
                        candidate.education_score = score_result.get('education_score')
                        candidate.education_reasoning = score_result.get('education_reasoning')
                        candidate.keywords_score = score_result.get('keywords_score')
                        candidate.keywords_reasoning = score_result.get('keywords_reasoning')
                        candidate.overall_assessment = score_result.get('overall_assessment')
                        candidate.red_flags = score_result.get('red_flags', [])
                        
                        # Calculate weighted score
                        weights = {
                            'weight_skills': config.weight_skills,
                            'weight_title': config.weight_title,
                            'weight_experience': config.weight_experience,
                            'weight_education': config.weight_education,
                            'weight_keywords': config.weight_keywords
                        }
                        candidate.final_weighted_score = calculate_weighted_score(score_result, weights)
                        
                        # Update extracted data - sanitize numeric fields
                        yoe = score_result.get('years_of_experience')
                        if isinstance(yoe, (int, float)):
                            candidate.years_of_experience = yoe
                        elif isinstance(yoe, str):
                            # Try to extract number from string
                            import re
                            numbers = re.findall(r'[\d.]+', yoe)
                            candidate.years_of_experience = float(numbers[0]) if numbers else None
                        else:
                            candidate.years_of_experience = None
                        
                        candidate.location = score_result.get('location')
                        candidate.current_job_title = score_result.get('current_title')
                        candidate.skills = score_result.get('extracted_skills', [])
                        
                        candidate.status = 'scored'
                        candidate.processed_at = datetime.utcnow()
                        scored += 1
                
                db.session.add(candidate)
                processed += 1
            
            # Update scan history
            scan.cvs_processed = processed
            scan.cvs_scored = scored
            scan.cvs_filtered_out = filtered
            scan.status = 'completed'
            scan.scan_completed_at = datetime.utcnow()
            
            db.session.commit()
            print(f"ATS scan completed for user {user_id}: {scored} scored, {filtered} filtered")
            
        except Exception as e:
            # Rollback any pending transaction first
            db.session.rollback()
            
            # Now update the scan status
            try:
                scan.status = 'failed'
                scan.error_message = str(e)[:500]  # Limit error message length
                db.session.commit()
            except:
                db.session.rollback()
            
            print(f"ATS scan failed for user {user_id}: {e}")
