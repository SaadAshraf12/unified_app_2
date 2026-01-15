# Railway Database Migration Guide

## Problem
The Railway PostgreSQL database doesn't have the new ATS Agent tables, causing this error:
```
psycopg2.errors.StringDataRightTruncation: value too long for type character varying(255)
```

## Solution

### Option 1: Run Migration Script (Recommended)

1. **Push your code to GitHub** (with the fixed `models.py`):
   ```bash
   cd "c:\Users\sashraf\Downloads\lead gen\Backup 31Dec2025\unified_app"
   git add .
   git commit -m "Fix source_file_id length and add migration script"
   git push origin main
   ```

2. **Railway will auto-deploy** your updated code

3. **Run the migration on Railway**:
   - Go to your Railway dashboard
   - Open your app's deployment
   - Go to the **"Deployments"** tab
   - Click on **"View Logs"** for the latest deployment
   - Once deployed, click **"..."** (three dots) → **"Run Command"**
   - Type: `python scripts/migrate_db.py`
   - Hit Enter

4. **Verify**:
   - The script will create all missing tables
   - You should see: "✅ Database migration completed successfully!"

### Option 2: Manual SQL (If Option 1 Doesn't Work)

1. **Connect to Railway PostgreSQL**:
   - In Railway dashboard, go to your PostgreSQL service
   - Click **"Data"** tab
   - Click **"Query"** to open SQL console

2. **Run this SQL**:

```sql
-- Create ATS Agent Config table
CREATE TABLE IF NOT EXISTS ats_agent_configs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    is_enabled BOOLEAN DEFAULT FALSE,
    job_title VARCHAR(255),
    job_description TEXT,
    required_skills TEXT DEFAULT '[]',
    allowed_locations TEXT DEFAULT '[]',
    min_experience INTEGER,
    max_experience INTEGER,
    must_have_skills TEXT DEFAULT '[]',
    weight_skills INTEGER DEFAULT 30,
    weight_title INTEGER DEFAULT 25,
    weight_experience INTEGER DEFAULT 20,
    weight_education INTEGER DEFAULT 15,
    weight_keywords INTEGER DEFAULT 10,
    top_n_candidates INTEGER DEFAULT 10,
    onedrive_enabled BOOLEAN DEFAULT FALSE,
    onedrive_folder_path VARCHAR(500),
    email_inbox_enabled BOOLEAN DEFAULT FALSE,
    email_folder_enabled BOOLEAN DEFAULT FALSE,
    email_folder_name VARCHAR(255),
    sharepoint_enabled BOOLEAN DEFAULT FALSE,
    sharepoint_site_url VARCHAR(500),
    sharepoint_library VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Create CV Candidates table
CREATE TABLE IF NOT EXISTS cv_candidates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    job_id INTEGER,
    full_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    location VARCHAR(100),
    linkedin_url VARCHAR(500),
    years_of_experience NUMERIC(4,1),
    skills TEXT DEFAULT '[]',
    education_level VARCHAR(50),
    current_job_title VARCHAR(255),
    cv_text TEXT,
    cv_file_path VARCHAR(500),
    cv_source VARCHAR(50),
    source_file_id VARCHAR(500),
    source_file_name VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    skills_score INTEGER,
    skills_reasoning TEXT,
    title_score INTEGER,
    title_reasoning TEXT,
    experience_score INTEGER,
    experience_reasoning TEXT,
    education_score INTEGER,
    education_reasoning TEXT,
    keywords_score INTEGER,
    keywords_reasoning TEXT,
    final_weighted_score NUMERIC(5,2),
    overall_assessment TEXT,
    red_flags TEXT DEFAULT '[]',
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT unique_user_cv UNIQUE (user_id, source_file_id)
);

-- Create ATS Scan History table
CREATE TABLE IF NOT EXISTS ats_scan_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    total_cvs_found INTEGER DEFAULT 0,
    cvs_processed INTEGER DEFAULT 0,
    cvs_filtered_out INTEGER DEFAULT 0,
    cvs_scored INTEGER DEFAULT 0,
    top_candidates_count INTEGER DEFAULT 0,
    scan_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scan_completed_at TIMESTAMP,
    status VARCHAR(50) DEFAULT 'running',
    error_message TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Update ActivityLog to include 'ats' agent type (if needed)
-- This might fail if the column doesn't have a constraint, which is fine
-- ALTER TABLE activity_logs ADD CONSTRAINT IF NOT EXISTS activity_logs_agent_type_check 
-- CHECK (agent_type IN ('email', 'meeting', 'ats'));
```

3. **Verify tables created**:
   ```sql
   SELECT table_name FROM information_schema.tables 
   WHERE table_schema = 'public' 
   AND table_name LIKE '%ats%';
   ```

### Option 3: Reset Railway Database (Nuclear Option - Use Only If Necessary)

⚠️ **WARNING**: This will delete ALL data!

1. In Railway dashboard → PostgreSQL service
2. Click **"Settings"**
3. Scroll to **"Danger Zone"**
4. Click **"Delete Service"**
5. Re-create a new PostgreSQL service
6. Your app will auto-recreate all tables on next deployment

## After Migration

1. **Test the ATS Agent**:
   - Go to your Railway app URL
   - Navigate to `/ats/config`
   - Configure your ATS settings
   - Try running a scan

2. **Check for errors**:
   - Monitor Railway logs
   - Verify CVs are being scanned and stored

## Summary of Changes Made

1. **Fixed `source_file_id` length**: Changed from `VARCHAR(255)` to `VARCHAR(500)` to handle long Microsoft Graph message IDs
2. **Created migration script**: `scripts/migrate_db.py` for easy database updates
3. **Provided manual SQL**: For direct database access if needed

---

**Recommended**: Use **Option 1** (migration script) - it's the safest and most professional approach.
