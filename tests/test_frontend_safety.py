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


def test_save_handler_defines_payload_and_snapshot_before_request():
    script = (STATIC / "app.js").read_text()
    handler = script.split('bankForm.addEventListener("submit"', 1)[1].split('matchForm.addEventListener', 1)[0]
    request_index = handler.index('request("/experience-bank"')
    assert handler.index("const submitted = readBank();") < request_index
    assert handler.index("const snapshot = JSON.stringify(submitted);") < request_index
    assert "body: JSON.stringify(submitted)" in handler
    assert "if (bankSnapshot() === snapshot)" in handler
    assert "populateBank(saved);" in handler
    assert "bankBaseline = bankSnapshot();" in handler
    assert "bankBaseline = snapshot;" in handler


def test_save_handler_uses_declared_button_and_functions():
    script = (STATIC / "app.js").read_text()
    handler = script.split('bankForm.addEventListener("submit"', 1)[1].split('matchForm.addEventListener', 1)[0]
    assert 'const saveBankButton = document.querySelector("#save-bank-button");' in script
    assert not re.search(r"\bsaveButton\b", handler)
    for name in ["readBank", "request", "bankSnapshot", "populateBank", "updateBankSummary", "updateState"]:
        assert re.search(rf"\b{name}\(", handler)
        assert re.search(rf"\bfunction {name}\(", script)
    summary = script.split("function updateBankSummary(bank)", 1)[1].split("\n}", 1)[0]
    assert 'document.querySelector("#bank-summary").textContent' in summary


def test_save_handler_guards_and_restores_in_flight_state():
    script = (STATIC / "app.js").read_text()
    handler = script.split('bankForm.addEventListener("submit"', 1)[1].split('matchForm.addEventListener', 1)[0]
    request_index = handler.index('request("/experience-bank"')
    assert handler.index("if (saving || matching) return;") < request_index
    for statement in ["saving = true;", "bankForm.inert = true;", "saveBankButton.disabled = true;"]:
        assert handler.index(statement) < request_index
    cleanup = handler.split("finally {", 1)[1]
    for statement in ["saving = false;", "bankForm.inert = false;", "saveBankButton.disabled = false;"]:
        assert statement in cleanup
    assert "bankMessage.textContent = error.message;" in handler


def test_successful_load_initialises_summary_and_saved_state():
    script = (STATIC / "app.js").read_text()
    success = script.rsplit('request("/experience-bank")', 1)[1].split(".catch", 1)[0]
    assert success.index("populateBank(bank);") < success.index("bankBaseline = bankSnapshot();")
    assert success.index("bankBaseline = bankSnapshot();") < success.index("updateState();")
    assert success.index("bankLoading = false;") < success.index("updateState();")
    assert "updateBankSummary(bank);" in success
