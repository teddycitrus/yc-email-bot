# email-me

![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)

Python CLI that finds and verifies founder/contact email addresses for a company. Point it at either a **YC company page** (founders + domain scraped from YC's structured data) or **any company website/domain** — e.g. an a16z portfolio company — in which case it derives the domain and scrapes the company's own `/team` and `/about` pages for people. It then generates common professional email permutations and verifies them using DNS MX record lookups and SMTP-level handshake probing. When no individuals can be discovered, it falls back to common role inboxes (`founders@`, `hello@`, `info@`, `contact@`, `team@`). Results are emitted in table, JSON, or CSV format.

## Installation

```bash
pip install -e .
```

To install with dev/test dependencies:

```bash
pip install -e ".[dev]"
```

**Requirements:** Python ≥ 3.10

## Usage

```
email-me <target> <count> [options]
```

`<target>` is either a YC company URL (`https://www.ycombinator.com/companies/<slug>`) or a company website/domain (`acme.com`, `https://acme.com`). The mode is auto-detected.

### Examples

```bash
# YC mode: find 2 verified emails for Stripe founders, show progress
email-me https://www.ycombinator.com/companies/stripe 2 --verbose

# YC mode: 3 verified emails for Dropbox founders, output as JSON
email-me https://www.ycombinator.com/companies/dropbox 3 --format json --verbose

# Generic mode: any company (e.g. an a16z portfolio company) by domain
email-me databricks.com 3 --verbose

# Generic mode: full URL works too; role-inbox fallback if no team page
email-me https://www.somestartup.com 5 --format json

# Output 5 email permutations for Airbnb founders without SMTP verification, as CSV
email-me https://www.ycombinator.com/companies/airbnb 5 --no-smtp --format csv
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--format` | `table` | Output format: `table`, `json`, `csv` |
| `--timeout` | `10` | SMTP connection timeout in seconds |
| `--delay` | `1.0` | Delay between SMTP probes in seconds |
| `--no-catch-all` | off | Don't catch-all results in output and count |
| `--include-unknown` | off | Include unknown results in output |
| `--verbose` | off | Print progress to stderr |
| `--no-smtp` | off | Skip SMTP verification; output permutations only |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (at least 1 result found) |
| 1 | Scraping failed |
| 2 | No verified addresses found |
| 3 | Invalid arguments |

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP GET for YC pages |
| `beautifulsoup4` | HTML parsing |
| `lxml` | Fast HTML parser backend for BS4 |
| `dnspython` | DNS MX record resolution |

## Notes

- **Port 25 blocked:** Most residential ISPs and cloud providers block outbound port 25. The tool falls back to port 587 automatically.
- **Catch-all servers:** Some domains accept all RCPT TO addresses. These are flagged as `CATCH_ALL`.
- **Greylisting:** Large mail providers may temporarily defer connections from unknown IPs, producing `UNKNOWN` results for valid addresses.
- **Result of Port 25 blocked:** I catch all emails automatically rather than only spitting out verified ones
"# yc-email-bot" 
"# yc-email-bot" 
"# yc-email-bot" 
