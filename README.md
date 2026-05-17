# email-me

![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)

Python CLI that finds and verifies founder email addresses from YC pages. Given a YC company URL and a count, it scrapes founder names and the company domain, generates common professional email permutations, and verifies them using DNS MX record lookups and SMTP-level handshake probing. Results are emitted in table, JSON, or CSV format.

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
email-me <yc_url> <count> [options]
```

### Examples

```bash
# Find 2 verified emails for Stripe founders, show progress
email-me https://www.ycombinator.com/companies/stripe 2 --verbose

# Find 3 verified emails for Dropbox founders, output as JSON
email-me https://www.ycombinator.com/companies/dropbox 3 --format json --verbose

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
