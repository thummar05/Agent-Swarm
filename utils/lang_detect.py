from langdetect import detect


def detect_language(text: str) -> str:
    """Detect if the text is in Portuguese or English"""
    try:
        detected_lang = detect(text)
        return 'pt' if detected_lang == 'pt' else 'en'
    except:
        return 'en'