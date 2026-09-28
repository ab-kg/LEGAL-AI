"""One-off: route every API call in app.js through apiFetch so the JWT header
is attached and 401s are handled centrally."""
import pathlib
import re

APP_JS = pathlib.Path(r"C:\Users\harsh\Desktop\AB-KG\PROJECTS\LEGAL-AI\frontend\js\app.js")

HELPER = '''const API_BASE_URL = `${window.location.origin}/api`;
let sessionId = null;
let trendChart = null;

// Every API call goes through here so the bearer token is attached
// consistently and an expired session redirects to login in one place.
async function apiFetch(url, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    const token = sessionStorage.getItem('sc_token');
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(url, Object.assign({}, options, { headers }));

    if (res.status === 401) {
        sessionStorage.removeItem('sc_token');
        sessionStorage.removeItem('sc_user');
        if (!window.location.pathname.endsWith('login.html')) {
            window.location.href = '/login.html?expired=1';
        }
    }
    return res;
}
'''

OLD_HEADER = """const API_BASE_URL = `${window.location.origin}/api`;
let sessionId = null;
let trendChart = null;
"""

text = APP_JS.read_text(encoding="utf-8")

if "async function apiFetch" not in text:
    assert OLD_HEADER in text, "could not find the header block to replace"
    text = text.replace(OLD_HEADER, HELPER, 1)
    print("inserted apiFetch helper")

before = len(re.findall(r"await fetch\(`\$\{API_BASE_URL\}", text))
text = re.sub(r"await fetch\(`\$\{API_BASE_URL\}", "await apiFetch(`${API_BASE_URL}", text)
after = len(re.findall(r"await apiFetch\(`\$\{API_BASE_URL\}", text))

APP_JS.write_text(text, encoding="utf-8")

leftover = len(re.findall(r"await fetch\(", text))
print(f"rewritten: {before} -> apiFetch calls {after}")
print(f"remaining bare 'await fetch(': {leftover}")
