"""One-time login for the Firebase (Google Analytics 4) retention numbers.
Run on the Mac: it opens a Google login (use guydifa@gmail.com) and saves Private Keys/ga4-token.json (read-only)."""
import os, sys
from google_auth_oauthlib.flow import InstalledAppFlow
K = sys.argv[1]
flow = InstalledAppFlow.from_client_secrets_file(os.path.join(K, "youtube-oauth-client.json"), ["https://www.googleapis.com/auth/analytics.readonly"])
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
p = os.path.join(K, "ga4-token.json"); open(p, "w").write(creds.to_json()); os.chmod(p, 0o600)
print("SAVED ga4-token.json")
