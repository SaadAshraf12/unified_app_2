"""
AI-Powered Scoring Module - OpenAI integration for CV evaluation
"""
import json
import openai
from typing import Dict, Optional


def get_openai_client(api_key: str):
    """Get OpenAI client with API key."""
    return openai.OpenAI(api_key=api_key)


def score_cv_with_openai(cv_data: Dict, job_config: Dict, api_key: str) -> Optional[Dict]:
    """
    Score a CV against job description using OpenAI.
    Returns scoring results with component scores and reasoning.
    """
    try:
        client = get_openai_client(api_key)
        
        # Prepare the prompt
        prompt_data = {
            "job_title": job_config.get('job_title', ''),
            "job_description": job_config.get('job_description', ''),
            "required_skills": job_config.get('required_skills', []),
            "cv_text": cv_data.get('cv_text', '')[:8000],  # Limit token usage
            "task": "Evaluate this CV against the job requirements and provide detailed scoring."
        }
        
        system_prompt = """You are an expert HR recruiter and ATS (Applicant Tracking System) evaluator.
Your task is to score CVs against job descriptions across multiple dimensions.
Be objective, consistent, and provide clear reasoning for your scores.

Scoring criteria (0-100 for each):
1. Skills Match: Technical and soft skills alignment with job requirements
2. Job Title Match: Career titles and progression alignment  
3. Experience Relevance: Depth and relevance of work experience
4. Education: Educational background fit for the role
5. Keywords: JD keyword matching and industry terminology

Provide scores and detailed reasoning for each dimension."""

        user_prompt = f"""
Job Title: {prompt_data['job_title']}

Job Description:
{prompt_data['job_description']}

Required Skills: {', '.join(prompt_data['required_skills'])}

Candidate CV:
{prompt_data['cv_text']}

Please evaluate this candidate and provide:
1. Score for each dimension (0-100)
2. Detailed reasoning for each score
3. Overall assessment
4. Any red flags you notice

Respond in JSON format with this structure:
{{
  "skills_score": <0-100>,
  "skills_reasoning": "<detailed explanation>",
  "title_score": <0-100>,
  "title_reasoning": "<detailed explanation>",
  "experience_score": <0-100>,
  "experience_reasoning": "<detailed explanation>",
  "education_score": <0-100>,
  "education_reasoning": "<detailed explanation>",
  "keywords_score": <0-100>,
  "keywords_reasoning": "<detailed explanation>",
  "overall_assessment": "<summary>",
  "red_flags": ["<flag1>", "<flag2>"],
  "years_of_experience": <number>,
  "location": "<city/location from CV>",
  "current_title": "<current job title>",
  "extracted_skills": ["<skill1>", "<skill2>"]
}}
"""
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000
        )
        
        # Parse response
        result = json.loads(response.choices[0].message.content)
        return result
        
    except Exception as e:
        print(f"Error scoring CV with OpenAI: {e}")
        return None


def calculate_weighted_score(component_scores: Dict, weights: Dict) -> float:
    """
    Calculate final weighted score from component scores.
    
    component_scores: Dict with keys like 'skills_score', 'title_score', etc.
    weights: Dict with keys like 'weight_skills', 'weight_title', etc.
    """
    final_score = (
        component_scores.get('skills_score', 0) * float(weights.get('weight_skills', 0.4)) +
        component_scores.get('title_score', 0) * float(weights.get('weight_title', 0.2)) +
        component_scores.get('experience_score', 0) * float(weights.get('weight_experience', 0.2)) +
        component_scores.get('education_score', 0) * float(weights.get('weight_education', 0.1)) +
        component_scores.get('keywords_score', 0) * float(weights.get('weight_keywords', 0.1))
    )
    return round(final_score, 2)
