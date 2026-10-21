# Beaker Lab social report

Runs `Metrics/social_report.py` on GitHub Actions at about 7 AM and 2 PM ET (and on demand: Actions > Social Report > Run workflow),
encrypts the page with StatiCrypt (password in the REPORT_PASSWORD secret) and publishes it to GitHub Pages:
https://pocketlabgames.github.io/social-report/

Keys come from the KEYS_TGZ secret (never committed). The master copy of the script is in iCloud: Beaker Lab > Metrics.
