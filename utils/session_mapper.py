def map_sessions_to_classes(sessions, classes):
    """
    Maps attendance sessions to their corresponding classes.

    Args:
        sessions (list): A list of session objects.
        classes (list): A list of class objects.

    Returns:
        dict: A dictionary mapping session IDs to class names.
    """
    session_class_map = {}
    for session in sessions:
        class_name = next((cls.name for cls in classes if cls.id == session.class_id), None)
        if class_name:
            session_class_map[session.id] = class_name
    return session_class_map


def get_classes_for_session(session_id, sessions, classes):
    """
    Retrieves the classes associated with a specific session.

    Args:
        session_id (int): The ID of the session.
        sessions (list): A list of session objects.
        classes (list): A list of class objects.

    Returns:
        list: A list of class names associated with the session.
    """
    session = next((s for s in sessions if s.id == session_id), None)
    if session:
        return [cls.name for cls in classes if cls.id == session.class_id]
    return []