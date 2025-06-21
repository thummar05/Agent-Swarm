def validate_user_access(session_user_id: str, requested_user_id: str) -> bool:
    """Validate if the session user can access the requested user's data"""
    if not session_user_id:
        return False
    
    return session_user_id == requested_user_id