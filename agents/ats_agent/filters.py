"""
Hard Filtering Module - Apply pre-scoring filters to CVs
"""
from typing import Dict, List, Optional


def check_location_filter(cv_text: str, location: Optional[str], allowed_locations: List[str]) -> tuple[bool, str]:
    """
    Check if candidate's location matches allowed locations.
    Returns (passed, reason)
    """
    if not allowed_locations:
        return True, "No location filter applied"
    
    if not location:
        # Try to find location in CV text
        cv_lower = cv_text.lower()
        for allowed_loc in allowed_locations:
            if allowed_loc.lower() in cv_lower:
                return True, f"Location matched: {allowed_loc}"
        return False, f"Location not in allowed list: {allowed_locations}"
    
    # Check if candidate's location is in allowed list
    for allowed_loc in allowed_locations:
        if allowed_loc.lower() in location.lower():
            return True, f"Location matched: {allowed_loc}"
    
    return False, f"Location '{location}' not in allowed list"


def check_experience_filter(years_of_experience: Optional[float], 
                            min_exp: int, 
                            max_exp: int) -> tuple[bool, str]:
    """
    Check if candidate's experience is within required range.
    Returns (passed, reason)
    """
    if years_of_experience is None:
        return True, "Experience not extracted, allowing to proceed"
    
    if years_of_experience < min_exp:
        return False, f"Experience {years_of_experience} years < minimum {min_exp} years"
    
    if years_of_experience > max_exp:
        return False, f"Experience {years_of_experience} years > maximum {max_exp} years"
    
    return True, f"Experience {years_of_experience} years within range"


def check_must_have_skills(cv_text: str, must_have_skills: List[str]) -> tuple[bool, str]:
    """
    Check if CV contains all must-have skills.
    Returns (passed, reason)
    """
    if not must_have_skills:
        return True, "No must-have skills required"
    
    cv_lower = cv_text.lower()
    missing_skills = []
    
    for skill in must_have_skills:
        if skill.lower() not in cv_lower:
            missing_skills.append(skill)
    
    if missing_skills:
        return False, f"Missing required skills: {', '.join(missing_skills)}"
    
    return True, "All required skills present"


def apply_hard_filters(cv_data: Dict, config: Dict) -> tuple[bool, List[str]]:
    """
    Apply all hard filters to a CV.
    Returns (passed, rejection_reasons)
    """
    reasons = []
    
    # Location filter
    if config.get('allowed_locations'):
        passed, reason = check_location_filter(
            cv_data.get('cv_text', ''),
            cv_data.get('location'),
            config['allowed_locations']
        )
        if not passed:
            reasons.append(reason)
    
    # Experience filter
    min_exp = config.get('min_experience', 0)
    max_exp = config.get('max_experience', 99)
    if min_exp > 0 or max_exp < 99:
        passed, reason = check_experience_filter(
            cv_data.get('years_of_experience'),
            min_exp,
            max_exp
        )
        if not passed:
            reasons.append(reason)
    
    # Must-have skills filter
    if config.get('must_have_skills'):
        passed, reason = check_must_have_skills(
            cv_data.get('cv_text', ''),
            config['must_have_skills']
        )
        if not passed:
            reasons.append(reason)
    
    return (len(reasons) == 0, reasons)
