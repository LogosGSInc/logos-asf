import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from abigail.model_router.sensitivity import classify_sensitivity


def test_public():
    level, _ = classify_sensitivity("Help me write a poem about autumn.")
    assert level == "public"


def test_user_private_journal():
    level, sig = classify_sensitivity("Summarize my private recovery journal.")
    assert level == "user_private"
    assert sig != ""


def test_user_private_personal():
    level, _ = classify_sensitivity("Review my personal notes from therapy.")
    assert level == "user_private"


def test_confidential_nda():
    level, sig = classify_sensitivity("Here is our internal NDA with the investor.")
    assert level == "confidential"
    assert sig != ""


def test_sacred_doctrinal_scripture():
    level, _ = classify_sensitivity("Build a doctrine card from Scripture.")
    assert level == "sacred_doctrinal"


def test_sacred_doctrinal_art_of_war():
    level, _ = classify_sensitivity("Combine The Art of War with our covenant.")
    assert level == "sacred_doctrinal"


def test_regulated_hipaa():
    level, sig = classify_sensitivity("Summarize this HIPAA-covered medical record.")
    assert level == "regulated"
    assert sig != ""


def test_regulated_gdpr():
    level, _ = classify_sensitivity("How do we handle GDPR compliance for EU users?")
    assert level == "regulated"


def test_precedence_regulated_beats_confidential():
    # HIPAA should win over "confidential" label
    level, _ = classify_sensitivity("Our confidential HIPAA medical records.")
    assert level == "regulated"
