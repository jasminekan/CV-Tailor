"""Static safety guards; these do not replace browser interaction tests."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_html_templates_do_not_interpolate_bank_values():
    script = (STATIC / "app.js").read_text()
    templates = re.findall(r"\.innerHTML\s*=\s*`([^`]*)`", script)
    assert len(templates) == 2
    assert all("${" not in template for template in templates)
    assert len(re.findall(r"\.innerHTML\s*=", script)) == len(templates)
    assert '.value = work[field] || ""' in script
    assert '.value = project[field] || ""' in script


def test_save_is_disabled_and_guarded_until_successful_load():
    html = (STATIC / "index.html").read_text()
    script = (STATIC / "app.js").read_text()
    assert re.search(r'<button[^>]*id="save-bank-button"[^>]*\bdisabled', html)
    assert "let bankLoaded = false;" in script
    save_handler = script.split('bankForm.addEventListener("submit"', 1)[1].split('matchForm.addEventListener', 1)[0]
    assert save_handler.index("if (!bankLoaded)") < save_handler.index('request("/experience-bank"')
    assert "return;" in save_handler.split("if (!bankLoaded)", 1)[1].split('bankMessage.textContent = "Saving..."', 1)[0]
    initial_load = script.rsplit('request("/experience-bank")', 1)[1]
    assert initial_load.index("populateBank(bank)") < initial_load.index("bankLoaded = true")
    assert "saveBankButton.disabled = false" in initial_load
    failure = initial_load.split(".catch", 1)[1]
    assert "bankLoaded = false" in failure
    assert "saveBankButton.disabled = true" in failure
