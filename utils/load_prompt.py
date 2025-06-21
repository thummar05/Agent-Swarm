import os

def load_prompt_template(prompt_name: str, language: str = "en") -> str:
    """
    Loads a prompt template from the 'prompts' directory.

    Args:
        prompt_name (str): The base name of the prompt (e.g., 'customer_support', 'router').
        language (str): The language of the prompt ('en' for English, 'pt' for Portuguese).

    Returns:
        str: The content of the prompt file, or an empty string if not found/error.
    """

    current_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(current_dir, ".."))
    
    prompts_folder = os.path.join(project_root, "prompts")
    
    # Construct the full file path
    file_name = f"{prompt_name}_{language}.txt"
    file_path = os.path.join(prompts_folder, file_name)

    try:
        if not os.path.exists(file_path):
            print(f"Warning: Prompt file not found: {file_path}")
            return ""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Failed to load prompt template from {file_path}: {e}")
        return ""